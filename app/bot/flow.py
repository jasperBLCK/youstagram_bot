"""Сценарий «ссылка → (ОП) → файл», общий для личных сообщений и колбэков."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberRestricted
from arq.connections import ArqRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards
from app.bot.texts import t
from app.config import get_settings
from app.db.models import DownloadStatus, Sponsor, SponsorKind, SponsorSubscription, SubStatus, User
from app.services import delivery, gate, stats
from app.services.links import MediaLink
from app.services.state import Pending, State, link_to_dict

log = logging.getLogger(__name__)

MEMBER_STATUSES = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


@dataclass(slots=True)
class Ctx:
    bot: Bot
    session: AsyncSession
    state: State
    arq: ArqRedis
    cfg: dict[str, Any]
    is_admin: bool = False


async def is_member(bot: Bot, chat_id: int, user_id: int) -> bool | None:
    """True/False — статус подписки, None — проверить не удалось (бот не админ и т.п.)."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError as exc:
        log.warning("get_chat_member(%s, %s) failed: %s", chat_id, user_id, exc)
        return None
    if isinstance(member, ChatMemberRestricted):
        return member.is_member
    return member.status in MEMBER_STATUSES


async def resolve_gate(ctx: Ctx, user: User, now: datetime) -> list[Sponsor]:
    limit = max(int(ctx.cfg["gate_max_sponsors"]), 1)
    chosen: list[Sponsor] = []
    for s in await gate.candidate_sponsors(ctx.session, user, ctx.cfg, now):
        if len(chosen) >= limit:
            break
        if gate.is_verifiable(s) and s.chat_id is not None and await is_member(ctx.bot, s.chat_id, user.id):
            await gate.record_subscription(ctx.session, s, user.id, SubStatus.JOINED, via_bot=False, now=now)
            continue
        chosen.append(s)
    return chosen


def gate_text(n: int, lang: str) -> str:
    return t("gate", lang, count=t("gate_count_1" if n == 1 else "gate_count_n", lang))


async def request(ctx: Ctx, user: User, chat_id: int, token: str, link: MediaLink, fmt: str) -> None:
    """Точка входа после выбора формата: либо показываем ОП, либо сразу отдаём файл."""
    now = datetime.now(UTC)
    if gate.needs_gate(user, ctx.cfg, now, is_admin=ctx.is_admin):
        sponsors = await resolve_gate(ctx, user, now)
        if sponsors:
            for s in sponsors:
                s.shows += 1
            await stats.incr(ctx.session, "gate_shown")
            await ctx.session.commit()
            msg = await ctx.bot.send_message(
                chat_id,
                gate_text(len(sponsors), user.lang),
                reply_markup=keyboards.gate(
                    sponsors, user.id, user.lang, premium=bool(ctx.cfg["premium_enabled"])
                ),
                disable_web_page_preview=True,
            )
            await ctx.state.set_pending(
                user.id, Pending(token, fmt, [s.id for s in sponsors], msg.message_id)
            )
            return
        # инвентаря нет — пропускаем без ОП и не сбрасываем «окно свободы» зря
        await gate.mark_gate_passed(ctx.session, user, now)
        await ctx.session.commit()
    await deliver(ctx, user.id, user.lang, chat_id, link, fmt, extras=True, source="share")


async def check_gate(ctx: Ctx, user: User, pending: Pending) -> tuple[bool, set[int], list[Sponsor]]:
    now = datetime.now(UTC)
    sponsors = await gate.sponsors_by_ids(ctx.session, pending.sponsor_ids)
    done: set[int] = set()
    for s in sponsors:
        ok: bool | None
        if s.kind == SponsorKind.CHANNEL and s.chat_id is not None:
            ok = await is_member(ctx.bot, s.chat_id, user.id)
            if not ok and s.join_request:
                ok = await _has_request(ctx.session, s.id, user.id) or ok
            if ok is None:
                ok = True  # не наказываем пользователя за ошибку настройки канала
        elif s.kind == SponsorKind.LINK and delivery_tracking_enabled():
            ok = await ctx.state.has_click(s.id, user.id)
        else:
            ok = True
        if ok:
            done.add(s.id)
            await gate.record_subscription(ctx.session, s, user.id, SubStatus.JOINED, via_bot=True, now=now)
    passed = len(done) == len(sponsors)
    if passed:
        await gate.mark_gate_passed(ctx.session, user, now)
        await stats.incr(ctx.session, "gate_passed")
    await ctx.session.commit()
    return passed, done, sponsors


def delivery_tracking_enabled() -> bool:
    return bool(get_settings().public_base_url)


async def _has_request(session: AsyncSession, sponsor_id: int, user_id: int) -> bool:
    status = await session.scalar(
        select(SponsorSubscription.status).where(
            SponsorSubscription.sponsor_id == sponsor_id, SponsorSubscription.user_id == user_id
        )
    )
    return status in (SubStatus.REQUESTED, SubStatus.JOINED)


async def deliver(
    ctx: Ctx,
    user_id: int,
    lang: str,
    chat_id: int,
    link: MediaLink,
    fmt: str,
    *,
    extras: bool,
    source: str,
    reply_to: int | None = None,
) -> None:
    key = link.cache_key(fmt)
    cached = await delivery.get_cache(ctx.session, key)
    if cached is not None:
        caption = await delivery.build_caption(
            ctx.bot, cached.title, lang, branding=bool(ctx.cfg["caption_branding"]), source=source
        )
        try:
            await delivery.send_cached(ctx.bot, chat_id, cached.items, caption, reply_to=reply_to)
        except TelegramAPIError as exc:
            log.warning("cached send failed for %s: %s — re-downloading", key, exc)
            await ctx.session.delete(cached)
            await ctx.session.commit()
        else:
            cached.hits += 1
            await delivery.log_download(ctx.session, user_id, link, fmt, DownloadStatus.CACHED)
            await ctx.session.commit()
            if extras:
                await delivery.after_delivery(ctx.bot, ctx.session, user_id, ctx.cfg)
            return

    if not await ctx.state.acquire_lock(user_id):
        await ctx.bot.send_message(chat_id, t("queued_busy", lang), reply_to_message_id=reply_to)
        return
    status = await ctx.bot.send_message(chat_id, t("downloading", lang), reply_to_message_id=reply_to)
    await ctx.arq.enqueue_job(
        "download_job",
        user_id=user_id,
        lang=lang,
        chat_id=chat_id,
        link=link_to_dict(link),
        fmt=fmt,
        status_message_id=status.message_id,
        reply_to=reply_to,
        source=source,
        extras=extras,
    )

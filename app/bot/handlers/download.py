import contextlib
from typing import Any

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from arq.connections import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import flow, keyboards
from app.bot.texts import t
from app.db.models import User
from app.services.downloader import Fmt
from app.services.links import Platform, find_link
from app.services.state import State
from app.services.users import detect_lang

router = Router(name="download")


def _ctx(
    bot: Bot, session: AsyncSession, store: State, arq: ArqRedis, cfg: dict[str, Any], is_admin: bool
) -> flow.Ctx:
    return flow.Ctx(bot=bot, session=session, state=store, arq=arq, cfg=cfg, is_admin=is_admin)


@router.message(F.chat.type == ChatType.PRIVATE, F.text | F.caption)
async def on_private_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    store: State,
    arq: ArqRedis,
    cfg: dict[str, Any],
    user: User,
    is_admin: bool,
) -> None:
    lang = user.lang
    if cfg["maintenance"] and not is_admin:
        await message.answer(t("maintenance", lang))
        return
    link = find_link(message.text or message.caption)
    if link is None:
        await message.answer(t("no_link", lang))
        return
    if await store.hit_rate_limit(user.id, int(cfg["rate_limit_per_min"])) and not is_admin:
        await message.answer(t("rate_limited", lang))
        return
    token = await store.save_request(user.id, link)
    if link.platform == Platform.YOUTUBE:
        await message.answer(t("choose_format", lang), reply_markup=keyboards.formats(token, lang))
        return
    await flow.request(
        _ctx(bot, session, store, arq, cfg, is_admin), user, message.chat.id, token, link, Fmt.VIDEO
    )


@router.callback_query(F.data.startswith("fmt:"))
async def on_format(
    call: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    store: State,
    arq: ArqRedis,
    cfg: dict[str, Any],
    user: User,
    is_admin: bool,
) -> None:
    _, token, fmt = (call.data or "::").split(":", 2)
    link = await store.load_request(token, user.id)
    if link is None or fmt not in (Fmt.VIDEO, Fmt.AUDIO):
        await call.answer(t("expired", user.lang), show_alert=True)
        return
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.delete()
    await flow.request(_ctx(bot, session, store, arq, cfg, is_admin), user, user.id, token, link, fmt)


@router.callback_query(F.data == "gate:check")
async def on_gate_check(
    call: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    store: State,
    arq: ArqRedis,
    cfg: dict[str, Any],
    user: User,
    is_admin: bool,
) -> None:
    pending = await store.get_pending(user.id)
    link = await store.load_request(pending.token, user.id) if pending else None
    if pending is None or link is None:
        await call.answer(t("expired", user.lang), show_alert=True)
        return
    ctx = _ctx(bot, session, store, arq, cfg, is_admin)
    passed, done, sponsors = await flow.check_gate(ctx, user, pending)
    if not passed:
        names = ", ".join(s.title for s in sponsors if s.id not in done)
        await call.answer(t("gate_not_done", user.lang, names=names)[:200], show_alert=True)
        if isinstance(call.message, Message):
            kb = keyboards.gate(sponsors, user.id, user.lang, done=done, premium=bool(cfg["premium_enabled"]))
            with contextlib.suppress(TelegramBadRequest):
                await call.message.edit_reply_markup(reply_markup=kb)
        return
    await store.clear_pending(user.id)
    await call.answer(t("gate_ok", user.lang))
    if isinstance(call.message, Message):
        await call.message.delete()
    await flow.deliver(ctx, user.id, user.lang, user.id, link, pending.fmt, extras=True, source="share")


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text | F.caption)
async def on_group_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    store: State,
    arq: ArqRedis,
    cfg: dict[str, Any],
) -> None:
    if not cfg["group_mode"] or cfg["maintenance"] or message.from_user is None:
        return
    link = find_link(message.text or message.caption)
    if link is None:
        return
    uid = message.from_user.id
    if await store.hit_rate_limit(uid, int(cfg["rate_limit_per_min"])):
        return
    lang = detect_lang(message.from_user.language_code)
    ctx = _ctx(bot, session, store, arq, cfg, False)
    await flow.deliver(
        ctx,
        uid,
        lang,
        message.chat.id,
        link,
        Fmt.VIDEO,
        extras=False,
        source="group",
        reply_to=message.message_id,
    )

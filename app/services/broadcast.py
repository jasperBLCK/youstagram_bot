"""Рассылки: отправка одного сообщения и итерация по аудитории с соблюдением лимитов Telegram."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Broadcast, BroadcastStatus, User
from app.services.tracking import tracked_url

log = logging.getLogger(__name__)

SEND_DELAY = 1 / 25  # ~25 сообщений в секунду — безопасно ниже глобального лимита Telegram (30/с)
BATCH = 500


def keyboard(b: Broadcast) -> InlineKeyboardMarkup | None:
    rows = []
    for i, btn in enumerate(b.buttons or []):
        text, url = (btn.get("text") or "").strip(), (btn.get("url") or "").strip()
        if text and url:
            rows.append([InlineKeyboardButton(text=text, url=tracked_url("b", b.id, url, i=i))])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_one(bot: Bot, chat_id: int, b: Broadcast) -> Message:
    kb = keyboard(b)
    media: str | FSInputFile | None = b.media_file_id or (FSInputFile(b.media_path) if b.media_path else None)
    if b.media_type and media is not None:
        caption = b.text[:1024]
        if b.media_type == "photo":
            return await bot.send_photo(chat_id, media, caption=caption, reply_markup=kb)
        if b.media_type == "video":
            return await bot.send_video(chat_id, media, caption=caption, reply_markup=kb)
        if b.media_type == "animation":
            return await bot.send_animation(chat_id, media, caption=caption, reply_markup=kb)
    return await bot.send_message(
        chat_id, b.text, reply_markup=kb, disable_web_page_preview=b.disable_preview
    )


def extract_file_id(msg: Message) -> str | None:
    if msg.photo:
        return msg.photo[-1].file_id
    if msg.video:
        return msg.video.file_id
    if msg.animation:
        return msg.animation.file_id
    return None


def audience_query(b: Broadcast, now: datetime) -> Select[tuple[int]]:
    q = select(User.id).where(User.is_blocked.is_(False), User.is_banned.is_(False))
    if b.target_lang != "all":
        q = q.where(User.lang == b.target_lang)
    if b.target_active_days:
        q = q.where(User.last_seen_at >= now - timedelta(days=b.target_active_days))
    return q


async def count_audience(session: AsyncSession, b: Broadcast, now: datetime) -> int:
    sub = audience_query(b, now).subquery()
    return int(await session.scalar(select(func.count()).select_from(sub)) or 0)


async def _send_with_retry(bot: Bot, user_id: int, b: Broadcast) -> Message | None:
    for _ in range(3):
        try:
            return await send_one(bot, user_id, b)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
    return None


async def run_broadcast(
    bot: Bot,
    sessions: async_sessionmaker[AsyncSession],
    broadcast_id: int,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    now = datetime.now(UTC)
    async with sessions() as session:
        b = await session.get(Broadcast, broadcast_id)
        if b is None or b.status in (BroadcastStatus.DONE, BroadcastStatus.CANCELLED):
            return
        if b.status != BroadcastStatus.RUNNING:
            b.status = BroadcastStatus.RUNNING
            b.started_at = now
            b.total = await count_audience(session, b, now)
        await session.commit()

    while True:
        async with sessions() as session:
            b = await session.get(Broadcast, broadcast_id)
            if b is None or b.status != BroadcastStatus.RUNNING:
                return
            ids = list(
                (
                    await session.execute(
                        audience_query(b, b.started_at or now)
                        .where(User.id > b.last_user_id)
                        .order_by(User.id)
                        .limit(BATCH)
                    )
                ).scalars()
            )
            if not ids:
                b.status = BroadcastStatus.DONE
                b.finished_at = datetime.now(UTC)
                await session.commit()
                log.info("broadcast %s done: sent=%s failed=%s", b.id, b.sent, b.failed)
                return

            sent = failed = 0
            blocked: list[int] = []
            for uid in ids:
                try:
                    msg = await _send_with_retry(bot, uid, b)
                    if msg is None:
                        failed += 1
                    else:
                        sent += 1
                        if b.media_type and not b.media_file_id:
                            b.media_file_id = extract_file_id(msg)
                except TelegramForbiddenError:
                    failed += 1
                    blocked.append(uid)
                except TelegramBadRequest as exc:
                    failed += 1
                    if "chat not found" in str(exc).lower():
                        blocked.append(uid)
                except Exception:
                    failed += 1
                    log.exception("broadcast %s send to %s failed", broadcast_id, uid)
                await sleep(SEND_DELAY)

            if blocked:
                await session.execute(update(User).where(User.id.in_(blocked)).values(is_blocked=True))
            await session.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id)
                .values(
                    sent=Broadcast.sent + sent,
                    failed=Broadcast.failed + failed,
                    last_user_id=ids[-1],
                    media_file_id=b.media_file_id,
                )
            )
            await session.commit()

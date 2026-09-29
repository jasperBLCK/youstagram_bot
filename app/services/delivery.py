"""Выдача файла пользователю + всё, что происходит после неё (счётчики, реклама, рефералка)."""

import contextlib
import html
import logging
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.texts import t
from app.db.models import Ad, Download, DownloadStatus, MediaCache, User
from app.services import ads as ads_service
from app.services import stats
from app.services.downloader import MediaFile
from app.services.gate import is_premium
from app.services.links import MediaLink
from app.services.premium import extend_premium
from app.services.tracking import tracked_url

log = logging.getLogger(__name__)

_bot_username: str | None = None


async def bot_username(bot: Bot) -> str:
    global _bot_username
    if _bot_username is None:
        me = await bot.me()
        _bot_username = me.username or ""
    return _bot_username


async def build_caption(bot: Bot, title: str | None, lang: str, *, branding: bool, source: str) -> str:
    parts: list[str] = []
    if title:
        parts.append(html.escape(title[:200]))
    if branding:
        uname = await bot_username(bot)
        if uname:
            link = f'<a href="https://t.me/{uname}?start=src_{source}">@{uname}</a>'
            parts.append(t("caption_brand", lang, bot=link))
    return "\n\n".join(parts)[:1024]


def _file_id(msg: Message) -> tuple[str, str] | None:
    if msg.video:
        return "video", msg.video.file_id
    if msg.audio:
        return "audio", msg.audio.file_id
    if msg.photo:
        return "photo", msg.photo[-1].file_id
    if msg.document:
        return "document", msg.document.file_id
    return None


async def send_files(
    bot: Bot,
    chat_id: int,
    files: list[MediaFile],
    caption: str,
    *,
    title: str | None = None,
    performer: str | None = None,
    reply_to: int | None = None,
) -> list[dict[str, Any]]:
    """Отправляет скачанные файлы, возвращает [{type, file_id}] для кэша."""
    if len(files) == 1:
        f = files[0]
        src = FSInputFile(f.path)
        if f.kind == "video":
            msg = await bot.send_video(
                chat_id,
                src,
                caption=caption,
                width=f.width,
                height=f.height,
                duration=f.duration,
                supports_streaming=True,
                reply_to_message_id=reply_to,
            )
        elif f.kind == "audio":
            msg = await bot.send_audio(
                chat_id,
                src,
                caption=caption,
                title=(title or None) and title[:64],
                performer=performer,
                duration=f.duration,
                reply_to_message_id=reply_to,
            )
        else:
            msg = await bot.send_photo(chat_id, src, caption=caption, reply_to_message_id=reply_to)
        fid = _file_id(msg)
        return [{"type": fid[0], "file_id": fid[1]}] if fid else []

    media: list[InputMediaVideo | InputMediaPhoto] = []
    for i, f in enumerate(files):
        cap = caption if i == 0 else None
        if f.kind == "video":
            media.append(InputMediaVideo(media=FSInputFile(f.path), caption=cap, supports_streaming=True))
        elif f.kind == "photo":
            media.append(InputMediaPhoto(media=FSInputFile(f.path), caption=cap))
    msgs = await bot.send_media_group(chat_id, media=media, reply_to_message_id=reply_to)  # type: ignore[arg-type]
    return [{"type": fid[0], "file_id": fid[1]} for m in msgs if (fid := _file_id(m))]


async def send_cached(
    bot: Bot, chat_id: int, items: list[dict[str, Any]], caption: str, *, reply_to: int | None = None
) -> None:
    if len(items) == 1:
        it = items[0]
        kind, fid = it["type"], it["file_id"]
        if kind == "video":
            await bot.send_video(
                chat_id, fid, caption=caption, supports_streaming=True, reply_to_message_id=reply_to
            )
        elif kind == "audio":
            await bot.send_audio(chat_id, fid, caption=caption, reply_to_message_id=reply_to)
        elif kind == "photo":
            await bot.send_photo(chat_id, fid, caption=caption, reply_to_message_id=reply_to)
        else:
            await bot.send_document(chat_id, fid, caption=caption, reply_to_message_id=reply_to)
        return
    media: list[InputMediaVideo | InputMediaPhoto] = []
    for i, it in enumerate(items):
        cap = caption if i == 0 else None
        if it["type"] == "video":
            media.append(InputMediaVideo(media=it["file_id"], caption=cap))
        else:
            media.append(InputMediaPhoto(media=it["file_id"], caption=cap))
    await bot.send_media_group(chat_id, media=media, reply_to_message_id=reply_to)  # type: ignore[arg-type]


async def get_cache(session: AsyncSession, key: str) -> MediaCache | None:
    return await session.get(MediaCache, key)


async def save_cache(session: AsyncSession, key: str, items: list[dict[str, Any]], title: str | None) -> None:
    if not items:
        return
    existing = await session.get(MediaCache, key)
    if existing is None:
        session.add(MediaCache(key=key, items=items, title=title))
    else:
        existing.items, existing.title = items, title


async def log_download(
    session: AsyncSession,
    user_id: int,
    link: MediaLink,
    fmt: str,
    status: DownloadStatus,
    *,
    size: int = 0,
    error: str | None = None,
) -> None:
    session.add(
        Download(
            user_id=user_id,
            platform=str(link.platform),
            url=link.url[:1024],
            fmt=fmt,
            status=status,
            file_size=size,
            error=error,
        )
    )
    if status in (DownloadStatus.DONE, DownloadStatus.CACHED):
        await stats.incr(session, "downloads")
        await stats.incr(session, f"downloads:{link.platform}")
        if status == DownloadStatus.CACHED:
            await stats.incr(session, "downloads_cached")
    else:
        await stats.incr(session, "downloads_failed")


def ad_keyboard(ad_id: int, button_text: str | None, url: str | None) -> InlineKeyboardMarkup | None:
    if not (button_text and url):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=button_text, url=tracked_url("a", ad_id, url))]]
    )


async def after_delivery(bot: Bot, session: AsyncSession, user_id: int, cfg: dict[str, Any]) -> None:
    """Счётчики пользователя, награда рефереру, рекламный блок / мягкий апселл."""
    now = datetime.now(UTC)
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(downloads_count=User.downloads_count + 1, downloads_since_gate=User.downloads_since_gate + 1)
    )
    user = await session.scalar(
        select(User).where(User.id == user_id).execution_options(populate_existing=True)
    )
    if user is None:
        await session.commit()
        return

    referrer_to_notify: User | None = None
    if cfg["referral_enabled"] and user.referrer_id and not user.referral_rewarded:
        user.referral_rewarded = True
        referrer = await session.get(User, user.referrer_id)
        if referrer:
            extend_premium(referrer, now, hours=float(cfg["referral_bonus_hours"]))
            await stats.incr(session, "referrals")
            referrer_to_notify = referrer

    ad = None
    n = user.downloads_count
    every = max(int(cfg["ads_every_n"]), 1)
    if cfg["ads_enabled"] and not is_premium(user, now) and n % every == 0:
        ad = await ads_service.pick_ad(session, user.lang, now)
        if ad:
            await ads_service.register_impression(session, ad.id)
            await stats.incr(session, "ad_impressions")
    await session.commit()

    lang = user.lang
    if referrer_to_notify:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                referrer_to_notify.id,
                t("ref_reward", referrer_to_notify.lang, hours=cfg["referral_bonus_hours"]),
            )

    try:
        if ad:
            text = f"{ad.text}\n\n<i>{t('ad_label', lang)}</i>"
            kb = ad_keyboard(ad.id, ad.button_text, ad.url)
            if ad.photo_file_id:
                await bot.send_photo(user_id, ad.photo_file_id, caption=text[:1024], reply_markup=kb)
            elif ad.photo_path:
                msg = await bot.send_photo(
                    user_id, FSInputFile(ad.photo_path), caption=text[:1024], reply_markup=kb
                )
                if msg.photo:
                    await session.execute(
                        update(Ad).where(Ad.id == ad.id).values(photo_file_id=msg.photo[-1].file_id)
                    )
                    await session.commit()
            else:
                await bot.send_message(user_id, text, reply_markup=kb, disable_web_page_preview=True)
        elif (
            cfg["referral_enabled"]
            and int(cfg["upsell_every_n"]) > 0
            and n % int(cfg["upsell_every_n"]) == 0
            and not is_premium(user, now)
        ):
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text=t("btn_invite", lang), callback_data="menu:ref"),
                        InlineKeyboardButton(text=t("btn_premium", lang), callback_data="menu:premium"),
                    ]
                ]
            )
            await bot.send_message(
                user_id, t("upsell_ref", lang, hours=cfg["referral_bonus_hours"]), reply_markup=kb
            )
    except TelegramAPIError as exc:
        log.warning("post-delivery message failed: %s", exc)

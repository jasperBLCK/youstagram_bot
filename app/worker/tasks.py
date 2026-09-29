import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from arq import cron, func
from arq.connections import RedisSettings
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.factory import create_bot
from app.bot.texts import t
from app.config import get_settings
from app.db.models import Broadcast, BroadcastStatus, DownloadStatus
from app.db.session import dispose_engine, session_factory
from app.services import ads, delivery, gate, settings_store
from app.services.broadcast import run_broadcast
from app.services.downloader import Downloader, DownloadError, ErrorCode, Fmt
from app.services.state import State, link_from_dict

log = logging.getLogger("worker")


def _error_text(code: ErrorCode, lang: str, cfg: dict[str, Any]) -> str:
    if code == ErrorCode.TOO_LONG:
        return t("err_too_long", lang, minutes=cfg["max_duration_min"])
    return t(f"err_{code}", lang)


async def download_job(
    ctx: dict[str, Any],
    *,
    user_id: int,
    lang: str,
    chat_id: int,
    link: dict[str, Any],
    fmt: str,
    status_message_id: int,
    reply_to: int | None,
    source: str,
    extras: bool,
) -> str:
    bot: Bot = ctx["bot"]
    sessions: async_sessionmaker[AsyncSession] = ctx["sessions"]
    downloader: Downloader = ctx["downloader"]
    state: State = ctx["state"]
    media_link = link_from_dict(link)
    key = media_link.cache_key(fmt)
    try:
        async with sessions() as session:
            cfg = await settings_store.load_all(session)
            cached = await delivery.get_cache(session, key)
            branding = bool(cfg["caption_branding"])
            if cached is not None:
                caption = await delivery.build_caption(
                    bot, cached.title, lang, branding=branding, source=source
                )
                await delivery.send_cached(bot, chat_id, cached.items, caption, reply_to=reply_to)
                cached.hits += 1
                await delivery.log_download(session, user_id, media_link, fmt, DownloadStatus.CACHED)
                await session.commit()
                await _safe_delete(bot, chat_id, status_message_id)
                if extras:
                    await delivery.after_delivery(bot, session, user_id, cfg)
                return "cached"

        max_sec = int(cfg["max_duration_min"]) * 60
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(downloader.download, media_link, Fmt(fmt), max_duration_sec=max_sec),
                timeout=get_settings().download_timeout_sec,
            )
        except (DownloadError, TimeoutError) as exc:
            code = exc.code if isinstance(exc, DownloadError) else ErrorCode.FAILED
            log.info("download failed %s: %s", media_link.url, exc)
            await _safe_edit(bot, chat_id, status_message_id, _error_text(code, lang, cfg))
            async with sessions() as session:
                await delivery.log_download(
                    session, user_id, media_link, fmt, DownloadStatus.FAILED, error=str(exc)[:1000]
                )
                await session.commit()
            return f"failed:{code}"

        try:
            action = ChatAction.UPLOAD_VOICE if fmt == Fmt.AUDIO else ChatAction.UPLOAD_VIDEO
            await bot.send_chat_action(chat_id, action)
            caption = await delivery.build_caption(bot, result.title, lang, branding=branding, source=source)
            items = await delivery.send_files(
                bot,
                chat_id,
                result.files,
                caption,
                title=result.title,
                performer=result.uploader,
                reply_to=reply_to,
            )
            size = sum(f.path.stat().st_size for f in result.files)
        except TelegramAPIError as exc:
            log.warning("send failed %s: %s", media_link.url, exc)
            await _safe_edit(bot, chat_id, status_message_id, t("err_failed", lang))
            return "send_failed"
        finally:
            result.cleanup()

        async with sessions() as session:
            await delivery.save_cache(session, key, items, result.title)
            await delivery.log_download(session, user_id, media_link, fmt, DownloadStatus.DONE, size=size)
            await session.commit()
            await _safe_delete(bot, chat_id, status_message_id)
            if extras:
                await delivery.after_delivery(bot, session, user_id, cfg)
        return "done"
    finally:
        await state.release_lock(user_id)


async def _safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    with contextlib.suppress(TelegramAPIError):
        await bot.delete_message(chat_id, message_id)


async def _safe_edit(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except TelegramAPIError:
        await bot.send_message(chat_id, text)


async def broadcast_job(ctx: dict[str, Any], broadcast_id: int) -> None:
    await run_broadcast(ctx["bot"], ctx["sessions"], broadcast_id)


async def tick(ctx: dict[str, Any]) -> None:
    """Раз в минуту: истёкшие спонсоры/реклама, запуск отложенных рассылок."""
    sessions: async_sessionmaker[AsyncSession] = ctx["sessions"]
    now = datetime.now(UTC)
    async with sessions() as session:
        await gate.expire_sponsors(session, now)
        await ads.expire_ads(session, now)
        due = (
            (
                await session.execute(
                    select(Broadcast.id).where(
                        Broadcast.status == BroadcastStatus.SCHEDULED, Broadcast.scheduled_at <= now
                    )
                )
            )
            .scalars()
            .all()
        )
        await session.commit()
    for bid in due:
        await ctx["redis"].enqueue_job("broadcast_job", bid, _job_id=f"broadcast:{bid}")


async def startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set")
    ctx["bot"] = create_bot()
    ctx["sessions"] = session_factory()
    ctx["state"] = State(Redis.from_url(settings.redis_url))
    ctx["downloader"] = Downloader(
        base_dir=settings.download_dir,
        limit_bytes=settings.upload_limit_bytes,
        proxy=settings.ytdlp_proxy,
        cookies_file=settings.ytdlp_cookies_file,
        timeout=settings.download_timeout_sec,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    if bot := ctx.get("bot"):
        await bot.session.close()
    if state := ctx.get("state"):
        await state.r.aclose()
    await dispose_engine()


class WorkerSettings:
    functions: ClassVar = [
        func(download_job, max_tries=1, timeout=get_settings().download_timeout_sec + 180),
        func(broadcast_job, max_tries=5, timeout=12 * 3600),
    ]
    cron_jobs: ClassVar = [cron(tick, second=0, run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().worker_max_jobs
    keep_result = 60

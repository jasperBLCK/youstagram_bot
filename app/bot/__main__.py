import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.bot.factory import create_bot
from app.bot.handlers import channels, common, download, premium, referral
from app.bot.middlewares import DbMiddleware
from app.config import get_settings
from app.db.session import dispose_engine, session_factory
from app.services.state import State

log = logging.getLogger("bot")

COMMANDS = {
    "ru": [
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="premium", description="⭐ Без рекламы и подписок"),
        BotCommand(command="ref", description="🎁 Пригласить друга"),
        BotCommand(command="help", description="ℹ️ Помощь"),
        BotCommand(command="lang", description="🌐 Язык / Language"),
    ],
    "en": [
        BotCommand(command="start", description="🏠 Main menu"),
        BotCommand(command="premium", description="⭐ No ads, no subscriptions"),
        BotCommand(command="ref", description="🎁 Invite a friend"),
        BotCommand(command="help", description="ℹ️ Help"),
        BotCommand(command="lang", description="🌐 Language / Язык"),
    ],
}


def build_dispatcher(redis: Redis) -> Dispatcher:
    dp = Dispatcher()
    dp["store"] = State(redis)
    dp.update.outer_middleware(DbMiddleware(session_factory()))
    dp.include_routers(channels.router, premium.router, referral.router, common.router, download.router)
    return dp


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(COMMANDS["en"])
    await bot.set_my_commands(COMMANDS["ru"], language_code="ru")


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN is not set")

    bot = create_bot()
    redis = Redis.from_url(settings.redis_url)
    arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    dp = build_dispatcher(redis)
    dp["arq"] = arq
    await set_commands(bot)
    allowed = dp.resolve_used_update_types()
    log.info("allowed updates: %s", allowed)

    try:
        if settings.webhook_url:
            await bot.set_webhook(
                settings.webhook_url,
                secret_token=settings.webhook_secret or None,
                allowed_updates=allowed,
                drop_pending_updates=False,
            )
            app = web.Application()
            SimpleRequestHandler(dp, bot, secret_token=settings.webhook_secret or None).register(
                app, path="/webhook"
            )
            setup_application(app, dp, bot=bot)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, settings.webhook_host, settings.webhook_port).start()
            log.info("webhook server on %s:%s", settings.webhook_host, settings.webhook_port)
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=allowed, handle_as_tasks=True)
    finally:
        await arq.aclose()
        await redis.aclose()
        await bot.session.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

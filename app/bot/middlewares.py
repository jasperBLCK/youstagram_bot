from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Chat, TelegramObject, Update
from aiogram.types import User as TgUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.texts import t
from app.config import get_settings
from app.services import settings_store, users


class DbMiddleware(BaseMiddleware):
    """Сессия БД на апдейт, бизнес-настройки и пользователь (только для личных чатов)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        self.admin_ids = set(get_settings().admin_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        chat: Chat | None = data.get("event_chat")
        async with self.sessions() as session:
            data["session"] = session
            data["cfg"] = await settings_store.load_all(session)
            data["user"] = None
            data["is_admin"] = bool(tg_user and tg_user.id in self.admin_ids)
            if tg_user and not tg_user.is_bot and (chat is None or chat.type == ChatType.PRIVATE):
                user, is_new = await users.get_or_create(
                    session,
                    tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name,
                    language_code=tg_user.language_code,
                    now=datetime.now(UTC),
                )
                data["user"], data["is_new_user"] = user, is_new
                if user.is_banned and not data["is_admin"]:
                    await session.commit()
                    if isinstance(event, Update) and event.message:
                        await event.message.answer(t("banned", user.lang))
                    return None
            result = await handler(event, data)
            await session.commit()
            return result

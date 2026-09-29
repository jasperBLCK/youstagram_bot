from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Chat, Message, Update
from fakeredis.aioredis import FakeRedis

from app.bot.__main__ import build_dispatcher
from app.db import session as db_session
from app.db.base import Base

USER = {"id": 777, "is_bot": False, "first_name": "Test", "language_code": "ru"}


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> TelegramType:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            chat = Chat(id=int(method.chat_id), type="private")
            msg = Message(message_id=len(self.calls), date=datetime.now(UTC), chat=chat, text=method.text)
            return msg  # type: ignore[return-value]
        return True  # type: ignore[return-value]

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield b""

    async def close(self) -> None:
        return None


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((name, kwargs))


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[tuple[Dispatcher, Bot, FakeSession, FakeArq]]:
    db_session.init_engine(f"sqlite+aiosqlite:///{tmp_path / 'bot.db'}")
    async with db_session.get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    dp = build_dispatcher(FakeRedis())
    arq = FakeArq()
    dp["arq"] = arq
    fake = FakeSession()
    bot = Bot("42:TEST", session=fake)
    yield dp, bot, fake, arq
    await db_session.dispose_engine()


def message_update(update_id: int, text: str) -> Update:
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": int(datetime.now(UTC).timestamp()),
                "chat": {"id": USER["id"], "type": "private"},
                "from": USER,
                "text": text,
            },
        }
    )


def sent_texts(fake: FakeSession) -> list[str]:
    return [c.text for c in fake.calls if isinstance(c, SendMessage)]


async def test_private_links(env: tuple[Dispatcher, Bot, FakeSession, FakeArq]) -> None:
    dp, bot, fake, arq = env
    await dp.feed_update(bot, message_update(1, "https://youtu.be/jNQXAC9IVRw"))
    calls = [c for c in fake.calls if isinstance(c, SendMessage)]
    assert len(calls) == 1 and calls[0].reply_markup is not None
    assert arq.jobs == []

    await dp.feed_update(bot, message_update(2, "https://www.instagram.com/reel/C1a2B3c4D5e/"))
    assert [name for name, _ in arq.jobs] == ["download_job"]
    assert arq.jobs[0][1]["user_id"] == USER["id"]
    assert len(sent_texts(fake)) == 2

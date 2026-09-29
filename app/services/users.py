from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Source, User
from app.services import stats

SUPPORTED_LANGS = ("ru", "en")
BUILTIN_SOURCES = {"share": "Пересланные видео (вирусный рост)", "group": "Групповые чаты"}


def detect_lang(language_code: str | None) -> str:
    code = (language_code or "").split("-")[0].lower()
    if code in SUPPORTED_LANGS:
        return code
    if code in {"uk", "be", "kk", "uz", "ky", "tg", "az", "hy", "ka"}:
        return "ru"
    return "en"


@dataclass(slots=True)
class StartPayload:
    source_code: str | None = None
    referrer_id: int | None = None


def parse_start_payload(arg: str | None) -> StartPayload:
    if not arg:
        return StartPayload()
    if arg.startswith("ref_") and arg[4:].isdigit():
        return StartPayload(referrer_id=int(arg[4:]))
    if arg.startswith("src_") and len(arg) > 4:
        return StartPayload(source_code=arg[4:64])
    return StartPayload()


async def get_or_create(
    session: AsyncSession,
    tg_id: int,
    *,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
    now: datetime,
) -> tuple[User, bool]:
    user = await session.get(User, tg_id)
    if user is not None:
        if user.last_seen_at.date() != now.date():
            await stats.incr(session, "dau")
        if now - user.last_seen_at > timedelta(minutes=5) or user.is_blocked:
            user.last_seen_at = now
            user.is_blocked = False
            user.username = username
            user.first_name = first_name
        return user, False
    user = User(
        id=tg_id,
        username=username,
        first_name=first_name,
        lang=detect_lang(language_code),
        created_at=now,
        last_seen_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(user)
    except IntegrityError:
        existing = await session.get(User, tg_id, populate_existing=True)
        if existing is None:
            raise
        return existing, False
    await stats.incr(session, "new_users")
    await stats.incr(session, "dau")
    return user, True


async def attach_payload(session: AsyncSession, user: User, payload: StartPayload) -> None:
    """Атрибуция нового пользователя: источник трафика и/или реферер."""
    if payload.source_code:
        source = await session.scalar(select(Source).where(Source.code == payload.source_code))
        if source is None and payload.source_code in BUILTIN_SOURCES:
            source = Source(code=payload.source_code, name=BUILTIN_SOURCES[payload.source_code], cost=0)
            session.add(source)
            await session.flush()
        if source:
            user.source_id = source.id
            await stats.incr(session, f"src:{source.id}:users")
    if payload.referrer_id and payload.referrer_id != user.id:
        referrer = await session.get(User, payload.referrer_id)
        if referrer is not None:
            user.referrer_id = payload.referrer_id

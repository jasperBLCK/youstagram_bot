import contextlib
import re
from datetime import UTC, datetime, timedelta

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import f_float, f_str
from app.admin.routes.common import DB, Admin, back, bot_of, flash, render
from app.db.models import Payment, Source, User
from app.services import delivery

router = APIRouter(prefix="/sources")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,60}$")


@router.get("", response_class=HTMLResponse)
async def index(request: Request, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    week = datetime.now(UTC) - timedelta(days=7)
    rows = (
        await session.execute(
            select(
                Source,
                func.count(User.id),
                func.count(User.id).filter(User.last_seen_at >= week),
                func.coalesce(func.sum(User.downloads_count), 0),
                func.count(User.id).filter(User.is_blocked.is_(True)),
            )
            .join(User, User.source_id == Source.id, isouter=True)
            .group_by(Source.id)
            .order_by(Source.id.desc())
        )
    ).all()
    star_rows = await session.execute(
        select(User.source_id, func.sum(Payment.stars))
        .join(User, User.id == Payment.user_id)
        .group_by(User.source_id)
    )
    stars = {sid: int(n or 0) for sid, n in star_rows}
    bot = bot_of(request)
    username = "your_bot"
    if bot:
        with contextlib.suppress(TelegramAPIError):
            username = await delivery.bot_username(bot)
    return render(request, "sources.html", rows=rows, stars=stars, bot_username=username)


@router.post("")
async def create(request: Request, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    form = await request.form()
    code, name = f_str(form, "code"), f_str(form, "name")
    if not CODE_RE.match(code):
        flash(request, "Код: латиница, цифры, _ и -, до 60 символов", "err")
        return back("/sources")
    if await session.scalar(select(Source.id).where(Source.code == code)):
        flash(request, "Такой код уже есть", "err")
        return back("/sources")
    session.add(
        Source(code=code, name=name or code, cost=f_float(form, "cost"), created_at=datetime.now(UTC))
    )
    await session.commit()
    flash(request, "Источник создан")
    return back("/sources")


@router.post("/{sid}/cost")
async def set_cost(
    request: Request, sid: int, _: str = Admin, session: AsyncSession = DB
) -> RedirectResponse:
    src = await session.get(Source, sid)
    if src:
        src.cost = f_float(await request.form(), "cost")
        await session.commit()
    return back("/sources")


@router.post("/{sid}/delete")
async def delete(request: Request, sid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    src = await session.get(Source, sid)
    if src:
        await session.delete(src)
        await session.commit()
    return back("/sources")

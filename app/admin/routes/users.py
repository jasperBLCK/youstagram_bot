from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.admin.deps import f_int
from app.admin.routes.common import DB, Admin, back, flash, render
from app.db.models import Download, Payment, Source, SponsorSubscription, User
from app.services.premium import extend_premium

router = APIRouter(prefix="/users")
PAGE = 50


@router.get("", response_class=HTMLResponse)
async def index(
    request: Request, q: str = "", page: int = 1, _: str = Admin, session: AsyncSession = DB
) -> HTMLResponse:
    query = select(User)
    q = q.strip().lstrip("@")
    if q:
        conds: list[ColumnElement[bool]] = [User.username.ilike(f"%{q}%"), User.first_name.ilike(f"%{q}%")]
        if q.isdigit():
            conds.append(User.id == int(q))
        query = query.where(or_(*conds))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = max(page, 1)
    rows = (
        (await session.execute(query.order_by(User.created_at.desc()).offset((page - 1) * PAGE).limit(PAGE)))
        .scalars()
        .all()
    )
    return render(
        request,
        "users.html",
        users=rows,
        q=q,
        page=page,
        pages=max((total + PAGE - 1) // PAGE, 1),
        total=total,
        now=datetime.now(UTC),
    )


@router.get("/{uid}", response_class=HTMLResponse)
async def detail(request: Request, uid: int, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    user = await session.get(User, uid)
    if user is None:
        raise HTTPException(404)
    source = await session.get(Source, user.source_id) if user.source_id else None
    downloads = (
        (
            await session.execute(
                select(Download).where(Download.user_id == uid).order_by(Download.id.desc()).limit(20)
            )
        )
        .scalars()
        .all()
    )
    payments = (
        (await session.execute(select(Payment).where(Payment.user_id == uid).order_by(Payment.id.desc())))
        .scalars()
        .all()
    )
    subs = (
        await session.scalar(
            select(func.count())
            .select_from(SponsorSubscription)
            .where(SponsorSubscription.user_id == uid, SponsorSubscription.via_bot.is_(True))
        )
        or 0
    )
    invited = await session.scalar(select(func.count()).select_from(User).where(User.referrer_id == uid)) or 0
    return render(
        request,
        "user.html",
        u=user,
        source=source,
        downloads=downloads,
        payments=payments,
        subs=subs,
        invited=invited,
        now=datetime.now(UTC),
    )


@router.post("/{uid}/ban")
async def ban(request: Request, uid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    user = await session.get(User, uid)
    if user:
        user.is_banned = not user.is_banned
        await session.commit()
        flash(request, "Заблокирован" if user.is_banned else "Разблокирован")
    return back(f"/users/{uid}")


@router.post("/{uid}/premium")
async def premium(request: Request, uid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    user = await session.get(User, uid)
    days = f_int(await request.form(), "days")
    if user and days:
        if days < 0:
            user.premium_until = None
        else:
            extend_premium(user, datetime.now(UTC), days=days)
        await session.commit()
        flash(request, "Premium обновлён")
    return back(f"/users/{uid}")

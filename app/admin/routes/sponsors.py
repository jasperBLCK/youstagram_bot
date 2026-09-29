from datetime import UTC, datetime

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from app.admin.deps import f_bool, f_dt, f_float, f_int, f_opt, f_str
from app.admin.routes.common import DB, Admin, back, bot_of, flash, render
from app.bot.handlers.channels import INVITE_PREFIX
from app.db.models import Sponsor, SponsorKind, SponsorSubscription, SubStatus

router = APIRouter(prefix="/sponsors")


def _apply(s: Sponsor, form: FormData) -> None:
    s.title = f_str(form, "title") or "Спонсор"
    s.kind = f_str(form, "kind", SponsorKind.CHANNEL)
    chat_id = f_str(form, "chat_id")
    s.chat_id = int(chat_id) if chat_id.lstrip("-").isdigit() else None
    s.url = f_str(form, "url")
    s.join_request = f_bool(form, "join_request")
    s.target_subs = f_int(form, "target_subs")
    s.price_per_sub = f_float(form, "price_per_sub")
    s.hold_days = f_int(form, "hold_days", 7)
    s.priority = f_int(form, "priority")
    s.lang = f_str(form, "lang", "all")
    s.only_new_users = f_bool(form, "only_new_users")
    s.is_active = f_bool(form, "is_active")
    s.starts_at = f_dt(form, "starts_at")
    s.ends_at = f_dt(form, "ends_at")
    s.note = f_opt(form, "note")
    if s.kind == SponsorKind.CHANNEL and s.chat_id is None:
        raise HTTPException(400, "Для канала нужен chat_id — нажмите «Проверить канал»")
    if not s.url:
        raise HTTPException(400, "Нужна ссылка для кнопки")


@router.get("", response_class=HTMLResponse)
async def index(request: Request, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    rows = (
        (await session.execute(select(Sponsor).order_by(Sponsor.is_active.desc(), Sponsor.id.desc())))
        .scalars()
        .all()
    )
    return render(request, "sponsors.html", sponsors=rows)


@router.get("/new", response_class=HTMLResponse)
async def new(request: Request, _: str = Admin) -> HTMLResponse:
    return render(
        request,
        "sponsor_form.html",
        s=Sponsor(
            kind=SponsorKind.CHANNEL,
            is_active=True,
            hold_days=7,
            lang="all",
            priority=0,
            target_subs=0,
            price_per_sub=0,
        ),
        subs=None,
    )


@router.post("/new")
async def create(request: Request, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    s = Sponsor(created_at=datetime.now(UTC), shows=0, joined=0, left=0)
    _apply(s, await request.form())
    session.add(s)
    await session.commit()
    flash(request, f"Спонсор «{s.title}» добавлен")
    return back("/sponsors")


@router.get("/{sid}", response_class=HTMLResponse)
async def edit(request: Request, sid: int, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    s = await session.get(Sponsor, sid)
    if s is None:
        raise HTTPException(404)
    rows = await session.execute(
        select(SponsorSubscription.status, func.count())
        .where(SponsorSubscription.sponsor_id == sid, SponsorSubscription.via_bot.is_(True))
        .group_by(SponsorSubscription.status)
    )
    subs = {status: n for status, n in rows}
    return render(request, "sponsor_form.html", s=s, subs=subs, statuses=SubStatus)


@router.post("/{sid}")
async def update_(request: Request, sid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    s = await session.get(Sponsor, sid)
    if s is None:
        raise HTTPException(404)
    _apply(s, await request.form())
    await session.commit()
    flash(request, "Сохранено")
    return back("/sponsors")


@router.post("/{sid}/toggle")
async def toggle(request: Request, sid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    s = await session.get(Sponsor, sid)
    if s:
        s.is_active = not s.is_active
        await session.commit()
    return back("/sponsors")


@router.post("/{sid}/delete")
async def delete(request: Request, sid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    s = await session.get(Sponsor, sid)
    if s:
        await session.delete(s)
        await session.commit()
        flash(request, "Спонсор удалён")
    return back("/sponsors")


@router.post("/api/check")
async def check_chat(request: Request, _: str = Admin) -> JSONResponse:
    """Находит канал по @username / ссылке / id, проверяет права бота и создаёт трекинговую ссылку."""
    bot = bot_of(request)
    if bot is None:
        return JSONResponse({"ok": False, "error": "BOT_TOKEN не задан"})
    form = await request.form()
    raw = f_str(form, "chat").replace("https://t.me/", "").replace("t.me/", "").strip("/")
    join_request = f_bool(form, "join_request")
    chat_ref: int | str = int(raw) if raw.lstrip("-").isdigit() else ("@" + raw.lstrip("@"))
    try:
        chat = await bot.get_chat(chat_ref)
        me = await bot.me()
        member = await bot.get_chat_member(chat.id, me.id)
    except TelegramAPIError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Telegram: {exc.message}. Добавьте бота в канал админом."}
        )
    is_admin = member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    result: dict[str, object] = {"ok": True, "chat_id": chat.id, "title": chat.title, "is_admin": is_admin}
    if not is_admin:
        result["warning"] = "Бот не админ канала — подписку проверить нельзя. Выдайте права администратора."
        return JSONResponse(result)
    try:
        link = await bot.create_chat_invite_link(
            chat.id, name=f"{INVITE_PREFIX}{datetime.now(UTC):%y%m%d%H%M}", creates_join_request=join_request
        )
        result["url"] = link.invite_link
    except TelegramAPIError as exc:
        result["warning"] = f"Не удалось создать ссылку-приглашение: {exc.message}"
        if chat.username:
            result["url"] = f"https://t.me/{chat.username}"
    return JSONResponse(result)

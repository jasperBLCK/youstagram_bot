from datetime import UTC, datetime

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from app.admin.deps import (
    GIF_EXT,
    PHOTO_EXT,
    VIDEO_EXT,
    f_bool,
    f_dt,
    f_float,
    f_int,
    f_str,
    media_type_for,
    save_upload,
)
from app.admin.routes.common import DB, Admin, arq_of, back, bot_of, flash, render
from app.config import get_settings
from app.db.models import Broadcast, BroadcastStatus
from app.services.broadcast import count_audience, extract_file_id, send_one

router = APIRouter(prefix="/broadcasts")
EDITABLE = (BroadcastStatus.DRAFT, BroadcastStatus.SCHEDULED)


async def _apply(b: Broadcast, form: FormData) -> None:
    b.title = f_str(form, "title") or "Рассылка"
    b.text = f_str(form, "text")
    if not b.text:
        raise HTTPException(400, "Текст обязателен")
    buttons = []
    for i in range(3):
        text, url = f_str(form, f"btn_text_{i}"), f_str(form, f"btn_url_{i}")
        if text and url:
            buttons.append({"text": text, "url": url})
    b.buttons = buttons
    b.target_lang = f_str(form, "target_lang", "all")
    b.target_active_days = f_int(form, "target_active_days")
    b.disable_preview = f_bool(form, "disable_preview")
    b.price = f_float(form, "price")
    uploaded = await save_upload(form, "media", PHOTO_EXT + VIDEO_EXT + GIF_EXT)
    if uploaded:
        b.media_path, b.media_type, b.media_file_id = uploaded[0], media_type_for(uploaded[1]), None
    if f_bool(form, "remove_media"):
        b.media_path = b.media_type = b.media_file_id = None


@router.get("", response_class=HTMLResponse)
async def index(request: Request, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    rows = (await session.execute(select(Broadcast).order_by(Broadcast.id.desc()).limit(100))).scalars().all()
    running = any(b.status == BroadcastStatus.RUNNING for b in rows)
    return render(request, "broadcasts.html", broadcasts=rows, running=running)


@router.get("/new", response_class=HTMLResponse)
async def new(request: Request, _: str = Admin) -> HTMLResponse:
    b = Broadcast(
        status=BroadcastStatus.DRAFT,
        buttons=[],
        target_lang="all",
        target_active_days=0,
        disable_preview=True,
        price=0,
        text="",
    )
    return render(request, "broadcast_form.html", b=b, audience=None)


@router.post("/new")
async def create(request: Request, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    b = Broadcast(
        created_at=datetime.now(UTC),
        status=BroadcastStatus.DRAFT,
        sent=0,
        failed=0,
        clicks=0,
        total=0,
        last_user_id=0,
    )
    await _apply(b, await request.form())
    session.add(b)
    await session.commit()
    flash(request, "Черновик сохранён — отправьте тест себе, затем запускайте")
    return back(f"/broadcasts/{b.id}")


@router.get("/{bid}", response_class=HTMLResponse)
async def edit(request: Request, bid: int, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    b = await session.get(Broadcast, bid)
    if b is None:
        raise HTTPException(404)
    audience = await count_audience(session, b, datetime.now(UTC))
    return render(request, "broadcast_form.html", b=b, audience=audience)


@router.post("/{bid}")
async def update_(request: Request, bid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    b = await session.get(Broadcast, bid)
    if b is None:
        raise HTTPException(404)
    if b.status not in EDITABLE:
        flash(request, "Запущенную рассылку редактировать нельзя", "err")
        return back(f"/broadcasts/{bid}")
    await _apply(b, await request.form())
    await session.commit()
    flash(request, "Сохранено")
    return back(f"/broadcasts/{bid}")


@router.post("/{bid}/test")
async def test(request: Request, bid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    b = await session.get(Broadcast, bid)
    bot = bot_of(request)
    if b is None or bot is None:
        flash(request, "Нет бота (BOT_TOKEN) или рассылки", "err")
        return back(f"/broadcasts/{bid}")
    admins = get_settings().admin_ids
    if not admins:
        flash(request, "Добавьте свой Telegram id в ADMIN_IDS", "err")
        return back(f"/broadcasts/{bid}")
    try:
        for admin_id in admins:
            msg = await send_one(bot, admin_id, b)
            if b.media_type and not b.media_file_id:
                b.media_file_id = extract_file_id(msg)
        await session.commit()
    except TelegramAPIError as exc:
        flash(request, f"Telegram: {exc.message}", "err")
        return back(f"/broadcasts/{bid}")
    flash(request, f"Тест отправлен ({len(admins)})")
    return back(f"/broadcasts/{bid}")


@router.post("/{bid}/start")
async def start(request: Request, bid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    b = await session.get(Broadcast, bid)
    if b is None or b.status not in EDITABLE:
        flash(request, "Рассылку нельзя запустить", "err")
        return back("/broadcasts")
    when = f_dt(await request.form(), "scheduled_at")
    if when and when > datetime.now(UTC):
        b.status, b.scheduled_at = BroadcastStatus.SCHEDULED, when
        await session.commit()
        flash(request, "Рассылка запланирована")
    else:
        b.status, b.scheduled_at = BroadcastStatus.SCHEDULED, datetime.now(UTC)
        await session.commit()
        await arq_of(request).enqueue_job("broadcast_job", bid, _job_id=f"broadcast:{bid}")
        flash(request, "Рассылка запущена 🚀")
    return back("/broadcasts")


@router.post("/{bid}/cancel")
async def cancel(request: Request, bid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    b = await session.get(Broadcast, bid)
    if b and b.status in (BroadcastStatus.SCHEDULED, BroadcastStatus.RUNNING):
        b.status, b.finished_at = BroadcastStatus.CANCELLED, datetime.now(UTC)
        await session.commit()
        flash(request, "Рассылка остановлена")
    return back("/broadcasts")


@router.post("/{bid}/duplicate")
async def duplicate(
    request: Request, bid: int, _: str = Admin, session: AsyncSession = DB
) -> RedirectResponse:
    src = await session.get(Broadcast, bid)
    if src is None:
        raise HTTPException(404)
    b = Broadcast(
        title=f"{src.title} (копия)",
        text=src.text,
        media_type=src.media_type,
        media_path=src.media_path,
        media_file_id=src.media_file_id,
        buttons=list(src.buttons or []),
        target_lang=src.target_lang,
        target_active_days=src.target_active_days,
        disable_preview=src.disable_preview,
        price=src.price,
        status=BroadcastStatus.DRAFT,
        created_at=datetime.now(UTC),
        sent=0,
        failed=0,
        clicks=0,
        total=0,
        last_user_id=0,
    )
    session.add(b)
    await session.commit()
    return back(f"/broadcasts/{b.id}")


@router.post("/{bid}/delete")
async def delete(request: Request, bid: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    b = await session.get(Broadcast, bid)
    if b and b.status != BroadcastStatus.RUNNING:
        await session.delete(b)
        await session.commit()
        flash(request, "Удалено")
    return back("/broadcasts")

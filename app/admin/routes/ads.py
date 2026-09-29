from datetime import UTC, datetime

from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from app.admin.deps import PHOTO_EXT, f_bool, f_dt, f_float, f_int, f_opt, f_str, save_upload
from app.admin.routes.common import DB, Admin, back, bot_of, flash, render
from app.config import get_settings
from app.db.models import Ad
from app.services.delivery import ad_keyboard

router = APIRouter(prefix="/ads")


async def _apply(ad: Ad, form: FormData) -> None:
    ad.title = f_str(form, "title") or "Реклама"
    ad.text = f_str(form, "text")
    ad.button_text = f_opt(form, "button_text")
    ad.url = f_opt(form, "url")
    ad.weight = f_int(form, "weight", 10)
    ad.lang = f_str(form, "lang", "all")
    ad.impressions_limit = f_int(form, "impressions_limit")
    ad.cpm = f_float(form, "cpm")
    ad.is_active = f_bool(form, "is_active")
    ad.starts_at = f_dt(form, "starts_at")
    ad.ends_at = f_dt(form, "ends_at")
    if not ad.text:
        raise HTTPException(400, "Текст обязателен")
    uploaded = await save_upload(form, "photo", PHOTO_EXT)
    if uploaded:
        ad.photo_path, ad.photo_file_id = uploaded[0], None
    if f_bool(form, "remove_photo"):
        ad.photo_path, ad.photo_file_id = None, None


@router.get("", response_class=HTMLResponse)
async def index(request: Request, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    rows = (await session.execute(select(Ad).order_by(Ad.is_active.desc(), Ad.id.desc()))).scalars().all()
    return render(request, "ads.html", ads=rows)


@router.get("/new", response_class=HTMLResponse)
async def new(request: Request, _: str = Admin) -> HTMLResponse:
    return render(
        request,
        "ad_form.html",
        ad=Ad(is_active=True, weight=10, lang="all", impressions_limit=0, cpm=0, text=""),
    )


@router.post("/new")
async def create(request: Request, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    ad = Ad(created_at=datetime.now(UTC), impressions=0, clicks=0)
    await _apply(ad, await request.form())
    session.add(ad)
    await session.commit()
    flash(request, f"Реклама «{ad.title}» создана")
    return back("/ads")


@router.get("/{ad_id}", response_class=HTMLResponse)
async def edit(request: Request, ad_id: int, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    ad = await session.get(Ad, ad_id)
    if ad is None:
        raise HTTPException(404)
    return render(request, "ad_form.html", ad=ad)


@router.post("/{ad_id}")
async def update_(
    request: Request, ad_id: int, _: str = Admin, session: AsyncSession = DB
) -> RedirectResponse:
    ad = await session.get(Ad, ad_id)
    if ad is None:
        raise HTTPException(404)
    await _apply(ad, await request.form())
    await session.commit()
    flash(request, "Сохранено")
    return back("/ads")


@router.post("/{ad_id}/toggle")
async def toggle(ad_id: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    ad = await session.get(Ad, ad_id)
    if ad:
        ad.is_active = not ad.is_active
        await session.commit()
    return back("/ads")


@router.post("/{ad_id}/delete")
async def delete(
    request: Request, ad_id: int, _: str = Admin, session: AsyncSession = DB
) -> RedirectResponse:
    ad = await session.get(Ad, ad_id)
    if ad:
        await session.delete(ad)
        await session.commit()
        flash(request, "Удалено")
    return back("/ads")


@router.post("/{ad_id}/test")
async def test(request: Request, ad_id: int, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    ad = await session.get(Ad, ad_id)
    bot = bot_of(request)
    if ad is None or bot is None:
        flash(request, "Нет бота или объявления", "err")
        return back("/ads")
    kb = ad_keyboard(ad.id, ad.button_text, ad.url)
    sent = 0
    for admin_id in get_settings().admin_ids:
        try:
            if ad.photo_file_id or ad.photo_path:
                photo = ad.photo_file_id or FSInputFile(ad.photo_path or "")
                await bot.send_photo(admin_id, photo, caption=ad.text[:1024], reply_markup=kb)
            else:
                await bot.send_message(admin_id, ad.text, reply_markup=kb, disable_web_page_preview=True)
            sent += 1
        except TelegramAPIError as exc:
            flash(request, f"Ошибка отправки: {exc.message}", "err")
            return back(f"/ads/{ad_id}")
    flash(
        request,
        f"Тест отправлен админам: {sent}" if sent else "Добавьте свой id в ADMIN_IDS",
        "ok" if sent else "err",
    )
    return back(f"/ads/{ad_id}")

"""Публичные редиректы для трекинга кликов (кнопки рекламы, рассылок, ОП-ссылок)."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.routes.common import DB
from app.db.models import Ad, Broadcast, Sponsor
from app.services import stats
from app.services.state import State

router = APIRouter()


@router.get("/r/{kind}/{obj_id}")
async def redirect(
    request: Request, kind: str, obj_id: int, u: int = 0, i: int = 0, session: AsyncSession = DB
) -> RedirectResponse:
    target: str | None = None
    if kind == "a":
        ad = await session.get(Ad, obj_id)
        if ad:
            target = ad.url
            await session.execute(update(Ad).where(Ad.id == obj_id).values(clicks=Ad.clicks + 1))
            await stats.incr(session, "ad_clicks")
    elif kind == "b":
        b = await session.get(Broadcast, obj_id)
        if b and 0 <= i < len(b.buttons or []):
            target = b.buttons[i].get("url")
            await session.execute(
                update(Broadcast).where(Broadcast.id == obj_id).values(clicks=Broadcast.clicks + 1)
            )
    elif kind == "s":
        s = await session.get(Sponsor, obj_id)
        if s:
            target = s.url
            if u:
                state: State = request.app.state.state
                await state.mark_click(obj_id, u)
    if not target:
        raise HTTPException(404)
    await session.commit()
    return RedirectResponse(target, status_code=302)

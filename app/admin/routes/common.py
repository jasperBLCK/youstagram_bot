from collections.abc import AsyncIterator
from typing import Any

from aiogram import Bot
from arq.connections import ArqRedis
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import TEMPLATES, require_admin


async def db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


def bot_of(request: Request) -> Bot | None:
    bot: Bot | None = request.app.state.bot
    return bot


def arq_of(request: Request) -> ArqRedis:
    pool: ArqRedis = request.app.state.arq
    return pool


def render(request: Request, template: str, **ctx: Any) -> HTMLResponse:
    flash = request.session.pop("flash", None)
    return TEMPLATES.TemplateResponse(request, template, {"flash": flash, "path": request.url.path, **ctx})


def flash(request: Request, message: str, kind: str = "ok") -> None:
    request.session["flash"] = {"message": message, "kind": kind}


def back(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


Admin = Depends(require_admin)
DB = Depends(db)

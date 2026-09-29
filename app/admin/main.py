import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from starlette.middleware.sessions import SessionMiddleware

from app.admin.deps import NotAuthenticated
from app.admin.routes import ads, auth, broadcasts, dashboard, public, settings, sources, sponsors, users
from app.bot.factory import create_bot
from app.config import get_settings
from app.db.session import dispose_engine, session_factory
from app.services.state import State

log = logging.getLogger("admin")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    app.state.sessions = session_factory()
    app.state.redis = Redis.from_url(s.redis_url)
    app.state.state = State(app.state.redis)
    app.state.arq = await create_pool(RedisSettings.from_dsn(s.redis_url))
    app.state.bot = create_bot() if s.bot_token else None
    if s.admin_password == "admin" or s.admin_secret_key == "change-me":
        log.warning("ADMIN_PASSWORD / ADMIN_SECRET_KEY are default — change them before going to production!")
    try:
        yield
    finally:
        if app.state.bot:
            await app.state.bot.session.close()
        await app.state.arq.aclose()
        await app.state.redis.aclose()
        await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Youstagram Admin", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=s.admin_secret_key,
        session_cookie="ys_admin",
        max_age=14 * 24 * 3600,
        same_site="lax",
        https_only=s.public_base_url.startswith("https"),
    )
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    @app.exception_handler(NotAuthenticated)
    async def _redirect_login(request: Request, exc: NotAuthenticated) -> RedirectResponse:
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (auth, public, dashboard, sponsors, ads, broadcasts, sources, users, settings):
        app.include_router(module.router)
    return app


app = create_app()

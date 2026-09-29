from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.admin.main import create_app
from app.db.models import Ad, Setting, Source, Sponsor


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue_job(self, name: str, *args: object, **_: object) -> None:
        self.jobs.append((name, args))


@pytest.fixture
async def client(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.state.sessions = sessions
    app.state.bot = None
    app.state.arq = FakeArq()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def login(c: httpx.AsyncClient) -> None:
    r = await c.post("/login", data={"username": "admin", "password": "secret", "next": "/"})
    assert r.status_code == 303


async def test_requires_login(client: httpx.AsyncClient) -> None:
    r = await client.get("/sponsors")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    r = await client.post("/login", data={"username": "admin", "password": "wrong"})
    assert "Неверный" in r.text


async def test_all_pages_render(client: httpx.AsyncClient) -> None:
    await login(client)
    for path in [
        "/",
        "/sponsors",
        "/sponsors/new",
        "/ads",
        "/ads/new",
        "/broadcasts",
        "/broadcasts/new",
        "/sources",
        "/users",
        "/settings",
    ]:
        r = await client.get(path)
        assert r.status_code == 200, path


async def test_sponsor_crud(client: httpx.AsyncClient, session: AsyncSession) -> None:
    await login(client)
    form = {
        "kind": "channel",
        "title": "Мемы",
        "chat_id": "-100123",
        "url": "https://t.me/+abc",
        "target_subs": "1000",
        "price_per_sub": "2,5",
        "hold_days": "7",
        "priority": "1",
        "lang": "all",
        "is_active": "on",
    }
    r = await client.post("/sponsors/new", data=form)
    assert r.status_code == 303
    s = (await session.execute(select(Sponsor))).scalar_one()
    assert s.chat_id == -100123 and float(s.price_per_sub) == 2.5 and s.is_active
    assert (await client.get(f"/sponsors/{s.id}")).status_code == 200
    await client.post(f"/sponsors/{s.id}/toggle")
    await session.refresh(s)
    assert not s.is_active
    await client.post(f"/sponsors/{s.id}/delete")
    session.expunge_all()
    assert (await session.execute(select(Sponsor))).first() is None


async def test_ad_and_click_tracking(client: httpx.AsyncClient, session: AsyncSession) -> None:
    await login(client)
    r = await client.post(
        "/ads/new",
        data={
            "title": "VPN",
            "text": "<b>Лучший VPN</b>",
            "button_text": "Открыть",
            "url": "https://example.com",
            "weight": "10",
            "lang": "all",
            "is_active": "on",
        },
        files={"photo": ("", b"", "application/octet-stream")},
    )
    assert r.status_code == 303
    ad = (await session.execute(select(Ad))).scalar_one()
    r = await client.get(f"/r/a/{ad.id}")
    assert r.status_code == 302 and r.headers["location"] == "https://example.com"
    await session.refresh(ad)
    assert ad.clicks == 1


async def test_broadcast_start_enqueues(client: httpx.AsyncClient) -> None:
    await login(client)
    r = await client.post(
        "/broadcasts/new",
        data={
            "title": "Promo",
            "text": "Hello",
            "btn_text_0": "Go",
            "btn_url_0": "https://example.com",
            "target_lang": "all",
        },
    )
    assert r.status_code == 303
    bid = int(r.headers["location"].rsplit("/", 1)[1])
    assert (await client.get(f"/broadcasts/{bid}")).status_code == 200
    r = await client.post(f"/broadcasts/{bid}/start", data={"scheduled_at": ""})
    assert r.status_code == 303
    arq: FakeArq = client._transport.app.state.arq  # type: ignore[attr-defined]
    assert arq.jobs == [("broadcast_job", (bid,))]


async def test_sources_and_settings(client: httpx.AsyncClient, session: AsyncSession) -> None:
    await login(client)
    await client.post("/sources", data={"name": "Канал", "code": "memes_1", "cost": "500"})
    await client.post("/sources", data={"name": "Bad", "code": "bad code!"})
    assert [s.code for s in (await session.execute(select(Source))).scalars()] == ["memes_1"]
    assert "src_memes_1" in (await client.get("/sources")).text

    r = await client.post(
        "/settings",
        data={
            "gate_enabled": "on",
            "gate_free_downloads": "2",
            "premium_plans": '[{"days": 30, "stars": 100}]',
        },
    )
    assert r.status_code == 303
    rows = {s.key: s.value for s in (await session.execute(select(Setting))).scalars()}
    assert rows["gate_free_downloads"] == 2 and rows["ads_enabled"] is False
    assert rows["premium_plans"] == [{"days": 30, "stars": 100}]

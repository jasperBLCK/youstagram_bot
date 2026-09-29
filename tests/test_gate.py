import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Sponsor, SponsorKind, SubStatus, User
from app.services import gate
from app.services.settings_store import DEFAULTS

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def make_user(**kw: object) -> User:
    base: dict[str, object] = {
        "id": 1,
        "lang": "ru",
        "downloads_count": 0,
        "downloads_since_gate": 0,
        "created_at": NOW - timedelta(days=1),
        "last_seen_at": NOW,
    }
    base.update(kw)
    return User(**base)


def make_sponsor(sid: int, **kw: object) -> Sponsor:
    base: dict[str, object] = {
        "id": sid,
        "title": f"S{sid}",
        "kind": SponsorKind.CHANNEL,
        "chat_id": -100 - sid,
        "url": "https://t.me/x",
        "is_active": True,
        "target_subs": 0,
        "joined": 0,
        "left": 0,
        "shows": 0,
        "priority": 0,
        "lang": "all",
        "only_new_users": False,
        "hold_days": 7,
        "created_at": NOW - timedelta(days=5),
        "price_per_sub": 2,
    }
    base.update(kw)
    return Sponsor(**base)


def test_first_download_is_free() -> None:
    assert not gate.needs_gate(make_user(), DEFAULTS, NOW)
    assert gate.needs_gate(make_user(downloads_count=1), DEFAULTS, NOW)


def test_cooldown_and_every_n() -> None:
    u = make_user(downloads_count=3, last_gate_passed_at=NOW - timedelta(hours=2), downloads_since_gate=2)
    assert not gate.needs_gate(u, DEFAULTS, NOW)
    u.downloads_since_gate = DEFAULTS["gate_every_n"]
    assert gate.needs_gate(u, DEFAULTS, NOW)
    u.downloads_since_gate = 0
    u.last_gate_passed_at = NOW - timedelta(hours=DEFAULTS["gate_cooldown_hours"] + 1)
    assert gate.needs_gate(u, DEFAULTS, NOW)


def test_premium_admin_and_disabled_skip_gate() -> None:
    u = make_user(downloads_count=10)
    assert not gate.needs_gate(u, DEFAULTS, NOW, is_admin=True)
    assert not gate.needs_gate(u, {**DEFAULTS, "gate_enabled": False}, NOW)
    u.premium_until = NOW + timedelta(days=1)
    assert not gate.needs_gate(u, DEFAULTS, NOW)


def test_rank_by_priority_then_least_filled() -> None:
    a = make_sponsor(1, priority=0, target_subs=100, joined=90)
    b = make_sponsor(2, priority=0, target_subs=100, joined=10)
    c = make_sponsor(3, priority=5, target_subs=100, joined=99)
    assert [s.id for s in gate.rank_sponsors([a, b, c], random.Random(1))] == [3, 2, 1]


def test_sponsor_availability_rules() -> None:
    u = make_user()
    assert gate.sponsor_available(make_sponsor(1), u, NOW)
    assert not gate.sponsor_available(make_sponsor(1, is_active=False), u, NOW)
    assert not gate.sponsor_available(make_sponsor(1, lang="en"), u, NOW)
    assert not gate.sponsor_available(make_sponsor(1, target_subs=5, joined=5), u, NOW)
    assert not gate.sponsor_available(make_sponsor(1, ends_at=NOW - timedelta(minutes=1)), u, NOW)
    assert not gate.sponsor_available(make_sponsor(1, only_new_users=True, created_at=NOW), u, NOW)


async def test_subscription_accounting(session: AsyncSession) -> None:
    session.add(make_user())
    s = make_sponsor(1, target_subs=2)
    session.add(s)
    await session.commit()

    assert await gate.record_subscription(session, s, 1, SubStatus.JOINED, via_bot=True, now=NOW)
    assert not await gate.record_subscription(session, s, 1, SubStatus.JOINED, via_bot=True, now=NOW)
    await session.commit()
    await session.refresh(s)
    assert s.joined == 1

    candidates = await gate.candidate_sponsors(session, make_user(), DEFAULTS, NOW)
    assert candidates == []

    await gate.record_leave(session, s.chat_id or 0, 1, NOW + timedelta(days=1))
    await session.commit()
    await session.refresh(s)
    assert s.left == 1
    candidates = await gate.candidate_sponsors(session, make_user(), DEFAULTS, NOW)
    assert [c.id for c in candidates] == [1]


async def test_sponsor_auto_disables_on_target(session: AsyncSession) -> None:
    s = make_sponsor(1, target_subs=1)
    session.add(s)
    await session.commit()
    await gate.record_subscription(session, s, 42, SubStatus.JOINED, via_bot=True, now=NOW)
    await session.commit()
    await session.refresh(s)
    assert s.joined == 1 and s.is_active is False


async def test_existing_subscriber_not_counted(session: AsyncSession) -> None:
    s = make_sponsor(1)
    session.add(s)
    await session.commit()
    assert not await gate.record_subscription(session, s, 7, SubStatus.JOINED, via_bot=False, now=NOW)
    await session.commit()
    await session.refresh(s)
    assert s.joined == 0

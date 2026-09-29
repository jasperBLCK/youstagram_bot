import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ad, Source, User
from app.services import ads, stats, users
from app.services.premium import extend_premium, find_plan

NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def make_ad(aid: int, **kw: object) -> Ad:
    base: dict[str, object] = {
        "id": aid,
        "title": "ad",
        "text": "hi",
        "weight": 10,
        "lang": "all",
        "impressions_limit": 0,
        "impressions": 0,
        "clicks": 0,
        "is_active": True,
        "cpm": 0,
    }
    base.update(kw)
    return Ad(**base)


def test_ad_filters() -> None:
    assert ads.ad_available(make_ad(1), "ru", NOW)
    assert not ads.ad_available(make_ad(1, lang="en"), "ru", NOW)
    assert not ads.ad_available(make_ad(1, impressions_limit=5, impressions=5), "ru", NOW)
    assert not ads.ad_available(make_ad(1, starts_at=NOW + timedelta(hours=1)), "ru", NOW)


def test_weighted_pick_distribution() -> None:
    rng = random.Random(0)
    pool = [make_ad(1, weight=90), make_ad(2, weight=10), make_ad(3, weight=0)]
    picks = [ads.weighted_pick(pool, rng) for _ in range(2000)]
    share = sum(1 for p in picks if p and p.id == 1) / len(picks)
    assert 0.85 < share < 0.95
    assert all(p and p.id != 3 for p in picks)
    assert ads.weighted_pick([]) is None


async def test_expire_ads(session: AsyncSession) -> None:
    session.add_all(
        [make_ad(1, impressions_limit=3, impressions=3), make_ad(2), make_ad(3, ends_at=NOW - timedelta(1))]
    )
    await session.commit()
    assert await ads.expire_ads(session, NOW) == 2
    await session.commit()
    picked = await ads.pick_ad(session, "ru", NOW)
    assert picked is not None and picked.id == 2


def test_premium_extends_from_current_expiry() -> None:
    u = User(id=1)
    extend_premium(u, NOW, days=7)
    assert u.premium_until == NOW + timedelta(days=7)
    extend_premium(u, NOW, hours=24)
    assert u.premium_until == NOW + timedelta(days=8)
    assert find_plan([{"days": 7, "stars": 50}], 7) == {"days": 7, "stars": 50}
    assert find_plan([{"days": 7, "stars": 50}], 30) is None


def test_start_payload() -> None:
    assert users.parse_start_payload("ref_123").referrer_id == 123
    assert users.parse_start_payload("src_memes").source_code == "memes"
    assert users.parse_start_payload("garbage") == users.StartPayload()
    assert users.detect_lang("uk") == "ru"
    assert users.detect_lang("de") == "en"


async def test_attribution(session: AsyncSession) -> None:
    session.add(Source(id=1, code="memes", name="Memes", cost=100, created_at=NOW))
    referrer, _ = await users.get_or_create(
        session, 10, username="a", first_name="A", language_code="ru", now=NOW
    )
    await session.commit()

    u, created = await users.get_or_create(
        session, 11, username="b", first_name="B", language_code="en", now=NOW
    )
    assert created and u.lang == "en"
    await users.attach_payload(session, u, users.parse_start_payload("src_memes"))
    await users.attach_payload(session, u, users.parse_start_payload("ref_10"))
    await session.commit()
    assert u.source_id == 1 and u.referrer_id == referrer.id

    self_ref, _ = await users.get_or_create(
        session, 12, username=None, first_name=None, language_code=None, now=NOW
    )
    await users.attach_payload(session, self_ref, users.parse_start_payload("ref_12"))
    assert self_ref.referrer_id is None
    await users.attach_payload(session, self_ref, users.parse_start_payload("src_share"))
    assert self_ref.source_id is not None
    await session.commit()
    assert await stats.total(session, "new_users", NOW.date()) == 3

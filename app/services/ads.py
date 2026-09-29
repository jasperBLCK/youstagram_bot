import random
from datetime import datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ad


def ad_available(ad: Ad, lang: str, now: datetime) -> bool:
    if not ad.is_active or ad.lang not in ("all", lang):
        return False
    if ad.starts_at and ad.starts_at > now:
        return False
    if ad.ends_at and ad.ends_at <= now:
        return False
    return not (ad.impressions_limit and ad.impressions >= ad.impressions_limit)


def weighted_pick(ads: list[Ad], rng: random.Random | None = None) -> Ad | None:
    ads = [a for a in ads if a.weight > 0]
    if not ads:
        return None
    rng = rng or random.Random()
    return rng.choices(ads, weights=[a.weight for a in ads], k=1)[0]


async def pick_ad(session: AsyncSession, lang: str, now: datetime) -> Ad | None:
    rows = (
        (
            await session.execute(
                select(Ad).where(
                    Ad.is_active.is_(True),
                    Ad.lang.in_(["all", lang]),
                    or_(Ad.ends_at.is_(None), Ad.ends_at > now),
                )
            )
        )
        .scalars()
        .all()
    )
    return weighted_pick([a for a in rows if ad_available(a, lang, now)])


async def register_impression(session: AsyncSession, ad_id: int) -> None:
    await session.execute(update(Ad).where(Ad.id == ad_id).values(impressions=Ad.impressions + 1))


async def expire_ads(session: AsyncSession, now: datetime) -> int:
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Ad)
            .where(
                Ad.is_active.is_(True),
                or_(
                    and_(Ad.ends_at.is_not(None), Ad.ends_at <= now),
                    and_(Ad.impressions_limit > 0, Ad.impressions >= Ad.impressions_limit),
                ),
            )
            .values(is_active=False)
        ),
    )
    return result.rowcount or 0

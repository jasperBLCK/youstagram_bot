"""Логика обязательной подписки (ОП).

Принципы (подробно — docs/MONETIZATION.md):
* Первое скачивание бесплатно: пользователь сначала получает ценность, потом видит «цену».
* ОП показывается в момент максимальной вовлечённости — уже после выбора формата,
  а запрос сохраняется и выполняется сразу после «✅ Проверить» (никаких повторных ссылок).
* После прохождения — период свободы (cooldown) или N скачиваний, чтобы не душить аудиторию.
* Показываем только каналы, на которые пользователь ещё не подписан. Нет инвентаря — нет ОП.
"""

import random
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Sponsor, SponsorKind, SponsorSubscription, SubStatus, User


def is_premium(user: User, now: datetime) -> bool:
    return user.premium_until is not None and user.premium_until > now


def needs_gate(user: User, cfg: dict[str, Any], now: datetime, *, is_admin: bool = False) -> bool:
    if not cfg["gate_enabled"] or is_admin or is_premium(user, now):
        return False
    if user.downloads_count < int(cfg["gate_free_downloads"]):
        return False
    if user.last_gate_passed_at is not None:
        in_cooldown = now - user.last_gate_passed_at < timedelta(hours=float(cfg["gate_cooldown_hours"]))
        every_n = int(cfg["gate_every_n"])
        under_quota = every_n <= 0 or user.downloads_since_gate < every_n
        if in_cooldown and under_quota:
            return False
    return True


def sponsor_available(s: Sponsor, user: User, now: datetime) -> bool:
    if not s.is_active:
        return False
    if s.starts_at and s.starts_at > now:
        return False
    if s.ends_at and s.ends_at <= now:
        return False
    if s.target_subs and s.joined >= s.target_subs:
        return False
    if s.lang not in ("all", user.lang):
        return False
    return not (s.only_new_users and user.created_at < s.created_at)


def rank_sponsors(sponsors: list[Sponsor], rng: random.Random | None = None) -> list[Sponsor]:
    """Сначала приоритет, затем те, кому меньше всего «докручено» (равномерное выполнение заказов)."""
    rng = rng or random.Random()

    def progress(s: Sponsor) -> float:
        return s.joined / s.target_subs if s.target_subs else 0.5

    shuffled = sponsors[:]
    rng.shuffle(shuffled)
    return sorted(shuffled, key=lambda s: (-s.priority, progress(s)))


async def candidate_sponsors(
    session: AsyncSession, user: User, cfg: dict[str, Any], now: datetime
) -> list[Sponsor]:
    """Активные спонсоры, на которых пользователь ещё не подписан через бота (с запасом для отсева)."""
    excluded_statuses = [SubStatus.JOINED, SubStatus.REQUESTED]
    if not cfg["gate_check_leavers"]:
        excluded_statuses.append(SubStatus.LEFT)
    done = select(SponsorSubscription.sponsor_id).where(
        SponsorSubscription.user_id == user.id, SponsorSubscription.status.in_(excluded_statuses)
    )
    rows = (
        (
            await session.execute(
                select(Sponsor).where(
                    Sponsor.is_active.is_(True),
                    Sponsor.id.not_in(done),
                    or_(Sponsor.starts_at.is_(None), Sponsor.starts_at <= now),
                    or_(Sponsor.ends_at.is_(None), Sponsor.ends_at > now),
                    or_(Sponsor.target_subs == 0, Sponsor.joined < Sponsor.target_subs),
                    Sponsor.lang.in_(["all", user.lang]),
                )
            )
        )
        .scalars()
        .all()
    )
    available = [s for s in rows if sponsor_available(s, user, now)]
    return rank_sponsors(available)


async def record_subscription(
    session: AsyncSession, sponsor: Sponsor, user_id: int, status: SubStatus, *, via_bot: bool, now: datetime
) -> bool:
    """Фиксирует подписку. Возвращает True, если это новый подписчик, засчитанный спонсору."""
    sub = await session.scalar(
        select(SponsorSubscription).where(
            SponsorSubscription.sponsor_id == sponsor.id, SponsorSubscription.user_id == user_id
        )
    )
    counted = False
    if sub is None:
        session.add(
            SponsorSubscription(
                sponsor_id=sponsor.id, user_id=user_id, status=status, via_bot=via_bot, joined_at=now
            )
        )
        counted = via_bot
    elif sub.status == SubStatus.LEFT:
        sub.status, sub.left_at, sub.joined_at = status, None, now
        counted = via_bot and not sub.via_bot
        sub.via_bot = sub.via_bot or via_bot
    elif sub.status == SubStatus.REQUESTED and status == SubStatus.JOINED:
        sub.status = SubStatus.JOINED
    if counted:
        await session.execute(
            update(Sponsor).where(Sponsor.id == sponsor.id).values(joined=Sponsor.joined + 1)
        )
        await session.execute(
            update(Sponsor)
            .where(Sponsor.id == sponsor.id, Sponsor.target_subs > 0, Sponsor.joined >= Sponsor.target_subs)
            .values(is_active=False)
        )
    return counted


async def record_leave(session: AsyncSession, chat_id: int, user_id: int, now: datetime) -> None:
    subs = (
        await session.execute(
            select(SponsorSubscription, Sponsor)
            .join(Sponsor, Sponsor.id == SponsorSubscription.sponsor_id)
            .where(
                Sponsor.chat_id == chat_id,
                SponsorSubscription.user_id == user_id,
                SponsorSubscription.status != SubStatus.LEFT,
            )
        )
    ).all()
    for sub, sponsor in subs:
        sub.status, sub.left_at = SubStatus.LEFT, now
        if sub.via_bot and now - sub.joined_at < timedelta(days=sponsor.hold_days):
            sponsor.left += 1


async def mark_gate_passed(session: AsyncSession, user: User, now: datetime) -> None:
    user.last_gate_passed_at = now
    user.downloads_since_gate = 0


def is_verifiable(s: Sponsor) -> bool:
    return s.kind == SponsorKind.CHANNEL and s.chat_id is not None


async def sponsors_by_ids(session: AsyncSession, ids: list[int]) -> list[Sponsor]:
    if not ids:
        return []
    rows = (await session.execute(select(Sponsor).where(Sponsor.id.in_(ids)))).scalars().all()
    order = {sid: i for i, sid in enumerate(ids)}
    return sorted(rows, key=lambda s: order.get(s.id, 0))


async def expire_sponsors(session: AsyncSession, now: datetime) -> int:
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(Sponsor)
            .where(
                Sponsor.is_active.is_(True),
                or_(
                    and_(Sponsor.ends_at.is_not(None), Sponsor.ends_at <= now),
                    and_(Sponsor.target_subs > 0, Sponsor.joined >= Sponsor.target_subs),
                ),
            )
            .values(is_active=False)
        ),
    )
    return result.rowcount or 0

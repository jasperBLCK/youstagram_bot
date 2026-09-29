from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyStat


def today() -> date:
    return datetime.now(UTC).date()


async def incr(session: AsyncSession, metric: str, value: int = 1, day: date | None = None) -> None:
    """Атомарный upsert счётчика. Не коммитит — коммит делает вызывающий код."""
    day = day or today()
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    insert = sqlite_insert if dialect == "sqlite" else pg_insert
    stmt = insert(DailyStat).values(day=day, metric=metric, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyStat.day, DailyStat.metric],
        set_={"value": DailyStat.value + stmt.excluded.value},
    )
    await session.execute(stmt)


async def series(session: AsyncSession, metrics: list[str], days: int = 30) -> dict[str, list[int]]:
    start = today() - timedelta(days=days - 1)
    rows = await session.execute(
        select(DailyStat.day, DailyStat.metric, DailyStat.value).where(
            DailyStat.day >= start, DailyStat.metric.in_(metrics)
        )
    )
    idx = {start + timedelta(days=i): i for i in range(days)}
    out = {m: [0] * days for m in metrics}
    for day, metric, value in rows:
        if day in idx:
            out[metric][idx[day]] = int(value)
    return out


async def total(session: AsyncSession, metric: str, since: date) -> int:
    value = await session.scalar(
        select(func.coalesce(func.sum(DailyStat.value), 0)).where(
            DailyStat.metric == metric, DailyStat.day >= since
        )
    )
    return int(value or 0)

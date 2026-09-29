from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.routes.common import DB, Admin, render
from app.db.models import Broadcast, BroadcastStatus, Payment, Source, Sponsor, SponsorSubscription, User
from app.services import stats

router = APIRouter()

METRICS = ["new_users", "dau", "downloads", "gate_shown", "gate_passed", "ad_impressions", "ad_clicks"]
PLATFORMS = ["youtube", "instagram", "tiktok"]


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    now = datetime.now(UTC)
    d30 = now - timedelta(days=30)
    today = stats.today()
    week = today - timedelta(days=6)

    async def count(*where: object) -> int:
        return int(await session.scalar(select(func.count()).select_from(User).where(*where)) or 0)  # type: ignore[arg-type]

    total = await count()
    alive = await count(User.is_blocked.is_(False))
    mau = await count(User.last_seen_at >= d30)
    premium = await count(User.premium_until > now)

    series = await stats.series(session, METRICS + [f"downloads:{p}" for p in PLATFORMS], days=30)
    shown7 = await stats.total(session, "gate_shown", week)
    passed7 = await stats.total(session, "gate_passed", week)

    op_revenue = float(
        await session.scalar(
            select(func.coalesce(func.sum(Sponsor.price_per_sub), 0))
            .select_from(SponsorSubscription)
            .join(Sponsor, Sponsor.id == SponsorSubscription.sponsor_id)
            .where(SponsorSubscription.via_bot.is_(True), SponsorSubscription.joined_at >= d30)
        )
        or 0
    )
    bc_revenue = float(
        await session.scalar(
            select(func.coalesce(func.sum(Broadcast.price), 0)).where(
                Broadcast.status.in_([BroadcastStatus.DONE, BroadcastStatus.RUNNING]),
                Broadcast.started_at >= d30,
            )
        )
        or 0
    )
    stars30 = int(
        await session.scalar(
            select(func.coalesce(func.sum(Payment.stars), 0)).where(Payment.created_at >= d30)
        )
        or 0
    )

    sponsors = (
        (
            await session.execute(
                select(Sponsor).where(Sponsor.is_active.is_(True)).order_by(Sponsor.priority.desc()).limit(8)
            )
        )
        .scalars()
        .all()
    )
    top_sources = (
        await session.execute(
            select(Source.name, Source.code, Source.cost, func.count(User.id))
            .join(User, User.source_id == Source.id, isouter=True)
            .group_by(Source.id)
            .order_by(func.count(User.id).desc())
            .limit(6)
        )
    ).all()

    labels = [(today - timedelta(days=29 - i)).strftime("%d.%m") for i in range(30)]
    platform_totals = {p: sum(series[f"downloads:{p}"]) for p in PLATFORMS}
    return render(
        request,
        "dashboard.html",
        kpi={
            "total": total,
            "alive": alive,
            "mau": mau,
            "premium": premium,
            "new_today": series["new_users"][-1],
            "dau": series["dau"][-1],
            "downloads_today": series["downloads"][-1],
            "gate_conv": round(passed7 / shown7 * 100) if shown7 else None,
            "op_revenue": op_revenue,
            "bc_revenue": bc_revenue,
            "stars30": stars30,
            "blocked_pct": round((total - alive) / total * 100) if total else 0,
        },
        chart={"labels": labels, **{m: series[m] for m in METRICS}},
        platforms=platform_totals,
        sponsors=sponsors,
        top_sources=top_sources,
    )

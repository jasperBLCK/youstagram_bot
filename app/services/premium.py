from datetime import datetime, timedelta
from typing import Any

from app.db.models import User


def extend_premium(user: User, now: datetime, *, days: float = 0, hours: float = 0) -> datetime:
    base = user.premium_until if user.premium_until and user.premium_until > now else now
    user.premium_until = base + timedelta(days=days, hours=hours)
    return user.premium_until


def find_plan(plans: list[dict[str, Any]], days: int) -> dict[str, Any] | None:
    for plan in plans:
        if int(plan.get("days", 0)) == days:
            return plan
    return None

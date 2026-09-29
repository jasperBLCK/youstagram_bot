"""Короткоживущее состояние в Redis: запросы, отложенные загрузки за ОП, блокировки, лимиты."""

import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from redis.asyncio import Redis

from app.services.links import MediaLink, Platform

REQ_TTL = 3600


def link_to_dict(link: MediaLink) -> dict[str, Any]:
    return {"platform": str(link.platform), "url": link.url, "media_id": link.media_id}


def link_from_dict(d: dict[str, Any]) -> MediaLink:
    return MediaLink(Platform(d["platform"]), d["url"], d.get("media_id"))


@dataclass(slots=True)
class Pending:
    token: str
    fmt: str
    sponsor_ids: list[int] = field(default_factory=list)
    message_id: int | None = None


class State:
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def save_request(self, user_id: int, link: MediaLink) -> str:
        token = secrets.token_urlsafe(8)
        await self.r.set(f"req:{token}", json.dumps({"user_id": user_id, **link_to_dict(link)}), ex=REQ_TTL)
        return token

    async def load_request(self, token: str, user_id: int) -> MediaLink | None:
        raw = await self.r.get(f"req:{token}")
        if not raw:
            return None
        data = json.loads(raw)
        if data.get("user_id") != user_id:
            return None
        return link_from_dict(data)

    async def set_pending(self, user_id: int, pending: Pending) -> None:
        await self.r.set(f"pending:{user_id}", json.dumps(asdict(pending)), ex=REQ_TTL)

    async def get_pending(self, user_id: int) -> Pending | None:
        raw = await self.r.get(f"pending:{user_id}")
        return Pending(**json.loads(raw)) if raw else None

    async def clear_pending(self, user_id: int) -> None:
        await self.r.delete(f"pending:{user_id}")

    async def acquire_lock(self, user_id: int, ttl: int = 900) -> bool:
        return bool(await self.r.set(f"lock:{user_id}", "1", nx=True, ex=ttl))

    async def release_lock(self, user_id: int) -> None:
        await self.r.delete(f"lock:{user_id}")

    async def hit_rate_limit(self, user_id: int, per_minute: int) -> bool:
        if per_minute <= 0:
            return False
        key = f"rl:{user_id}:{int(time.time() // 60)}"
        count = await self.r.incr(key)
        if count == 1:
            await self.r.expire(key, 70)
        return int(count) > per_minute

    async def mark_click(self, sponsor_id: int, user_id: int) -> None:
        await self.r.set(f"click:s:{sponsor_id}:{user_id}", "1", ex=REQ_TTL * 24)

    async def has_click(self, sponsor_id: int, user_id: int) -> bool:
        return bool(await self.r.exists(f"click:s:{sponsor_id}:{user_id}"))

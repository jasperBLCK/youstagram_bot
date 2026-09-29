"""Бизнес-настройки, редактируемые из админки без перезапуска."""

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting

DEFAULTS: dict[str, Any] = {
    # --- Обязательная подписка (ОП) ---
    "gate_enabled": True,
    "gate_free_downloads": 1,  # первые N скачиваний без ОП — пользователь сначала видит ценность
    "gate_cooldown_hours": 24,  # после прохождения ОП — N часов свободного скачивания
    "gate_every_n": 5,  # ...или через N скачиваний, что наступит раньше
    "gate_max_sponsors": 3,  # сколько каналов показывать за раз
    "gate_check_leavers": True,  # отписался раньше hold_days — канал вернётся в ОП
    # --- Монетизация после скачивания ---
    "ads_enabled": True,
    "ads_every_n": 1,  # показывать рекламный блок каждые N выдач
    "caption_branding": True,
    # --- Premium (Telegram Stars) ---
    "premium_enabled": True,
    "premium_plans": [{"days": 7, "stars": 50}, {"days": 30, "stars": 150}, {"days": 365, "stars": 990}],
    # --- Рефералка ---
    "referral_enabled": True,
    "referral_bonus_hours": 72,  # приглашающий получает N часов Premium за друга
    # --- Мягкие подсказки ---
    "upsell_every_n": 7,  # раз в N скачиваний предлагаем Premium / пригласить друга
    # --- Лимиты ---
    "rate_limit_per_min": 6,
    "max_duration_min": 90,
    "group_mode": True,
    "maintenance": False,
}

_TTL = 15.0
_cache: dict[str, Any] = {}
_cache_at = 0.0


async def load_all(session: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    global _cache, _cache_at
    if not force and _cache and time.monotonic() - _cache_at < _TTL:
        return _cache
    rows = (await session.execute(select(Setting))).scalars().all()
    merged = dict(DEFAULTS)
    merged.update({r.key: r.value for r in rows if r.key in DEFAULTS})
    _cache, _cache_at = merged, time.monotonic()
    return merged


async def save(session: AsyncSession, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            continue
        existing = await session.get(Setting, key)
        if existing is None:
            session.add(Setting(key=key, value=value))
        else:
            existing.value = value
    await session.commit()
    invalidate()


def invalidate() -> None:
    global _cache_at
    _cache_at = 0.0

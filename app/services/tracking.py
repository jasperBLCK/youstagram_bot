"""Трекинг переходов через редирект админки: /r/<kind>/<id>. Работает, если задан PUBLIC_BASE_URL."""

from urllib.parse import urlencode

from app.config import get_settings


def tracked_url(kind: str, obj_id: int, target: str, **params: int | str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    if not base:
        return target
    query = f"?{urlencode(params)}" if params else ""
    return f"{base}/r/{kind}/{obj_id}{query}"

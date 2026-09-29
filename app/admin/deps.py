import asyncio
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, UploadFile
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData

from app.config import get_settings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().admin_tz)


def fmt_dt(value: datetime | None, pattern: str = "%d.%m.%Y %H:%M") -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(tz()).strftime(pattern)


def input_dt(value: datetime | None) -> str:
    return fmt_dt(value, "%Y-%m-%dT%H:%M") if value else ""


def fmt_num(value: float | int | None) -> str:
    if value is None:
        return "0"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.2f}".replace(",", " ")
    return f"{int(value):,}".replace(",", " ")


TEMPLATES.env.filters["dt"] = fmt_dt
TEMPLATES.env.filters["input_dt"] = input_dt
TEMPLATES.env.filters["num"] = fmt_num


class NotAuthenticated(Exception):
    pass


def require_admin(request: Request) -> str:
    user = request.session.get("admin")
    if not user:
        raise NotAuthenticated
    return str(user)


def check_credentials(username: str, password: str) -> bool:
    s = get_settings()
    return secrets.compare_digest(username.encode(), s.admin_username.encode()) and secrets.compare_digest(
        password.encode(), s.admin_password.encode()
    )


def f_str(form: FormData, key: str, default: str = "") -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else default


def f_opt(form: FormData, key: str) -> str | None:
    return f_str(form, key) or None


def f_int(form: FormData, key: str, default: int = 0) -> int:
    raw = f_str(form, key)
    try:
        return int(float(raw.replace(" ", "").replace(",", "."))) if raw else default
    except ValueError as exc:
        raise HTTPException(400, f"Поле «{key}» должно быть числом") from exc


def f_float(form: FormData, key: str, default: float = 0.0) -> float:
    raw = f_str(form, key)
    try:
        return float(raw.replace(" ", "").replace(",", ".")) if raw else default
    except ValueError as exc:
        raise HTTPException(400, f"Поле «{key}» должно быть числом") from exc


def f_bool(form: FormData, key: str) -> bool:
    return f_str(form, key) in ("on", "1", "true", "yes")


def f_dt(form: FormData, key: str) -> datetime | None:
    raw = f_str(form, key)
    if not raw:
        return None
    return datetime.fromisoformat(raw).replace(tzinfo=tz()).astimezone(UTC)


async def save_upload(form: FormData, key: str, allowed: tuple[str, ...]) -> tuple[str, str] | None:
    """Сохраняет файл из формы, возвращает (путь, расширение)."""
    file = form.get(key)
    if not isinstance(file, UploadFile) or not file.filename:
        return None
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Недопустимый тип файла {ext}")
    data = await file.read()
    return await asyncio.to_thread(_write_upload, data, ext), ext


def _write_upload(data: bytes, ext: str) -> str:
    target_dir = Path(get_settings().uploads_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(data)
    return str(path)


PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXT = (".mp4", ".mov")
GIF_EXT = (".gif",)


def media_type_for(ext: str) -> str:
    if ext in PHOTO_EXT:
        return "photo"
    if ext in GIF_EXT:
        return "animation"
    return "video"

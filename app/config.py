from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Инфраструктурные настройки из окружения. Бизнес-настройки живут в БД (см. services/settings_store)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = ""
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    database_url: str = "postgresql+asyncpg://bot:bot@localhost:5432/bot"
    redis_url: str = "redis://localhost:6379/0"

    webhook_url: str = ""
    webhook_secret: str = ""
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8081

    bot_api_url: str = ""
    max_upload_mb: int = 0

    ytdlp_proxy: str = ""
    ytdlp_cookies_file: str = ""
    download_dir: str = "/tmp/youstagram"
    download_timeout_sec: int = 600
    worker_max_jobs: int = 8

    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_secret_key: str = "change-me"
    public_base_url: str = ""
    uploads_dir: str = "./data/uploads"
    admin_tz: str = "Europe/Moscow"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_ids(cls, v: object) -> object:
        if isinstance(v, str):
            return [int(x) for x in v.replace(";", ",").split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    @property
    def upload_limit_bytes(self) -> int:
        if self.max_upload_mb:
            return self.max_upload_mb * 1024 * 1024
        return (2000 if self.bot_api_url else 50) * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigIntPK, TZDateTime, utcnow


class SponsorKind(StrEnum):
    CHANNEL = "channel"  # канал/группа, бот — админ, подписка проверяется
    LINK = "link"  # бот/сайт/чужой канал — проверить нельзя, засчитываем переход


class SubStatus(StrEnum):
    JOINED = "joined"
    REQUESTED = "requested"  # подана заявка на вступление (закрытый канал)
    LEFT = "left"


class BroadcastStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"


class DownloadStatus(StrEnum):
    QUEUED = "queued"
    DONE = "done"
    CACHED = "cached"
    FAILED = "failed"


class Source(Base):
    """Источник трафика (закупка рекламы бота): t.me/<bot>?start=src_<code>."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(255))
    lang: Mapped[str] = mapped_column(String(8), default="ru")
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), index=True)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    downloads_count: Mapped[int] = mapped_column(Integer, default=0)
    downloads_since_gate: Mapped[int] = mapped_column(Integer, default=0)
    last_gate_passed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    premium_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)


class Sponsor(Base):
    """Спонсор обязательной подписки (ОП)."""

    __tablename__ = "sponsors"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16), default=SponsorKind.CHANNEL)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    url: Mapped[str] = mapped_column(String(512))
    join_request: Mapped[bool] = mapped_column(Boolean, default=False)
    target_subs: Mapped[int] = mapped_column(Integer, default=0)
    price_per_sub: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    hold_days: Mapped[int] = mapped_column(Integer, default=7)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    lang: Mapped[str] = mapped_column(String(8), default="all")
    only_new_users: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    shows: Mapped[int] = mapped_column(Integer, default=0)
    joined: Mapped[int] = mapped_column(Integer, default=0)
    left: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class SponsorSubscription(Base):
    __tablename__ = "sponsor_subscriptions"
    __table_args__ = (UniqueConstraint("sponsor_id", "user_id", name="uq_sponsor_user"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    sponsor_id: Mapped[int] = mapped_column(ForeignKey("sponsors.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(16), default=SubStatus.JOINED)
    via_bot: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Ad(Base):
    """Рекламный блок, который показывается после выдачи видео."""

    __tablename__ = "ads"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    button_text: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(512))
    photo_file_id: Mapped[str | None] = mapped_column(String(255))
    photo_path: Mapped[str | None] = mapped_column(String(512))
    weight: Mapped[int] = mapped_column(Integer, default=10)
    lang: Mapped[str] = mapped_column(String(8), default="all")
    impressions_limit: Mapped[int] = mapped_column(Integer, default=0)
    cpm: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    ends_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class Broadcast(Base):
    """Рассылка (платная реклама всем пользователям или анонс)."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column(String(16))  # photo | video | animation
    media_path: Mapped[str | None] = mapped_column(String(512))
    media_file_id: Mapped[str | None] = mapped_column(String(255))
    buttons: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    target_lang: Mapped[str] = mapped_column(String(8), default="all")
    target_active_days: Mapped[int] = mapped_column(Integer, default=0)
    disable_preview: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default=BroadcastStatus.DRAFT, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    last_user_id: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)


class Download(Base):
    __tablename__ = "downloads"
    __table_args__ = (Index("ix_downloads_created_platform", "created_at", "platform"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    platform: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(String(1024))
    fmt: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=DownloadStatus.QUEUED)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class MediaCache(Base):
    """Кэш file_id Telegram: одно и то же видео качается один раз, дальше отдаётся мгновенно."""

    __tablename__ = "media_cache"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    title: Mapped[str | None] = mapped_column(String(512))
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    stars: Mapped[int] = mapped_column(Integer)
    days: Mapped[int] = mapped_column(Integer)
    charge_id: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)


class DailyStat(Base):
    """Агрегированные счётчики по дням: дёшево по месту, быстро для графиков."""

    __tablename__ = "daily_stats"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)

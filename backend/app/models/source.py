"""Source model — system-level news source configuration."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # rss, api, scraper
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # finnhub, akshare, native_rss, rsshub, ...

    # Source-specific configuration (API keys, endpoints, etc.)
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    # What this source covers
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))
    markets: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)))  # For finance: us, cn, hk

    # Health
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown")  # ok, degraded, error, unknown
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    # Stats
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    article_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

"""Webhook model — event notifications to external consumers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Ownership: either an API consumer or a user (one must be set)
    consumer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_consumers.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False)
    # e.g. ["article.published", "market.impact", "sentiment.alert"]
    filters: Mapped[dict | None] = mapped_column(JSONB)
    # e.g. {"categories": ["finance"], "min_value_score": 60}

    secret: Mapped[str] = mapped_column(String(128), nullable=False)  # HMAC signing key
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

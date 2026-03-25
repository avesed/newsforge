"""Subscription model — user subscriptions to categories/keywords/sources."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Subscription type
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # category, keyword, source, feed
    target_id: Mapped[str | None] = mapped_column(String(255))  # category_id, source_id, feed_id
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String(100)))  # For keyword subscriptions

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

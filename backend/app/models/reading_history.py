"""Reading history -- tracks which articles users have read."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ReadingHistory(Base):
    __tablename__ = "reading_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_duration_ms: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "article_id", name="uq_reading_history_user_article"
        ),
        Index("ix_reading_history_user_read", "user_id", read_at.desc()),
    )

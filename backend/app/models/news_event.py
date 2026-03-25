"""News event model — cross-source event aggregation."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class NewsEvent(Base):
    __tablename__ = "news_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), default="breaking")  # breaking, ongoing, developing

    primary_entity: Mapped[str | None] = mapped_column(String(100), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(20))

    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))

    article_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    representative_article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="SET NULL")
    )
    sentiment_avg: Mapped[float | None] = mapped_column(Float)
    sources: Mapped[list[str] | None] = mapped_column(ARRAY(String(100)))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class EventArticle(Base):
    """Junction table — avoids UUID ARRAY race conditions."""

    __tablename__ = "event_articles"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )

    __table_args__ = (
        Index("ix_event_articles_article", "article_id"),
    )

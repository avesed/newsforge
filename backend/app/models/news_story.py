"""News story model — narrative-level event clustering across entities and categories."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class NewsStory(Base):
    """A mega-event / storyline that spans multiple entities and categories.

    Examples: "2026美伊战争", "OpenAI IPO", "英伟达Q4财报季"
    """

    __tablename__ = "news_stories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    story_type: Mapped[str] = mapped_column(String(30), nullable=False)  # war, crisis, election, ...
    status: Mapped[str] = mapped_column(String(20), default="developing")  # developing, ongoing, concluded

    key_entities: Mapped[list[str] | None] = mapped_column(ARRAY(String(100)))
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))
    timeline: Mapped[dict | None] = mapped_column(JSONB)  # [{date, summary}]

    article_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(512), nullable=True)  # average of linked article embeddings

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    representative_article_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="SET NULL")
    )
    sentiment_avg: Mapped[float | None] = mapped_column(Float)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    __table_args__ = (
        Index("ix_news_stories_story_type", "story_type"),
    )


class StoryArticle(Base):
    """Junction table linking stories to articles."""

    __tablename__ = "story_articles"

    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_stories.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    matched_by: Mapped[str] = mapped_column(String(20), nullable=False)  # direct, llm_confirmed, created
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_story_articles_article", "article_id"),
    )

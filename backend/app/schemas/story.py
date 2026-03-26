"""Story schemas — narrative-level event clustering responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.article import ArticleResponse
from app.schemas.base import CamelModel


class StoryResponse(CamelModel):
    id: UUID
    title: str
    description: str | None = None
    story_type: str
    status: str
    key_entities: list[str] | None = None
    categories: list[str] | None = None
    article_count: int
    first_seen_at: datetime | None = None
    last_updated_at: datetime | None = None
    sentiment_avg: float | None = None
    representative_title: str | None = None
    representative_summary: str | None = None


class StoryDetailResponse(StoryResponse):
    articles: list[ArticleResponse]
    timeline: list[dict] | None = None

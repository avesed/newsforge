"""Event schemas — cross-source event aggregation responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.article import ArticleResponse
from app.schemas.base import CamelModel


class EventResponse(CamelModel):
    id: UUID
    title: str
    event_type: str
    primary_entity: str | None = None
    entity_type: str | None = None
    categories: list[str] | None = None
    article_count: int
    first_seen_at: datetime | None = None
    last_updated_at: datetime | None = None
    sentiment_avg: float | None = None
    sources: list[str] | None = None
    # Representative article summary
    representative_title: str | None = None
    representative_summary: str | None = None


class EventDetailResponse(EventResponse):
    articles: list[ArticleResponse]

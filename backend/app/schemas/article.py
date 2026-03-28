"""Article schemas — aligned with multi-label classification model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.base import CamelModel


class ArticleResponse(CamelModel):
    id: UUID
    title: str
    url: str
    published_at: datetime | None = None
    language: str | None = None

    # Multi-label classification
    primary_category: str | None = None
    categories: list[str] | None = None
    category_details: list[dict] | None = None  # [{slug, confidence}]
    tags: list[str] | None = None

    # Value & market impact
    value_score: int | None = None
    has_market_impact: bool = False
    market_impact_hint: str | None = None

    # Content tiers
    summary: str | None = None
    ai_summary: str | None = None
    detailed_summary: str | None = None
    ai_analysis: str | None = None
    full_text: str | None = None

    # Translation
    title_zh: str | None = None
    full_text_zh: str | None = None

    # Entities & Sentiment
    entities: list[dict] | None = None
    primary_entity: str | None = None
    primary_entity_type: str | None = None
    sentiment_score: float | None = None
    sentiment_label: str | None = None

    # Finance metadata (WebStock compatible)
    finance_metadata: dict | None = None

    # Pipeline
    content_status: str = "pending"
    processing_path: str | None = None
    agents_executed: list[str] | None = None

    # Story
    story_id: UUID | None = None

    # Metadata
    source_name: str | None = None
    authors: list[str] | None = None
    top_image: str | None = None
    word_count: int | None = None
    created_at: datetime | None = None


class ArticleListResponse(CamelModel):
    articles: list[ArticleResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class CategoryResponse(CamelModel):
    id: UUID
    slug: str
    name_en: str
    name_zh: str
    icon: str | None = None
    color: str | None = None
    description: str | None = None
    article_count: int = 0
    is_active: bool = True

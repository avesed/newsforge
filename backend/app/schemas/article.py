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

    # Story & event grouping
    story_id: UUID | None = None
    event_group_id: UUID | None = None

    # Metadata
    source_name: str | None = None
    authors: list[str] | None = None
    top_image: str | None = None
    word_count: int | None = None
    created_at: datetime | None = None


class ArticleSummaryResponse(CamelModel):
    """Lightweight article for list endpoints — excludes large text fields."""
    id: UUID
    title: str
    url: str
    published_at: datetime | None = None
    language: str | None = None

    # Multi-label classification
    primary_category: str | None = None
    categories: list[str] | None = None
    category_details: list[dict] | None = None
    tags: list[str] | None = None

    # Value & market impact
    value_score: int | None = None
    has_market_impact: bool = False
    market_impact_hint: str | None = None

    # Summaries (lightweight)
    summary: str | None = None
    ai_summary: str | None = None

    # Boolean flag instead of full analysis text
    has_ai_analysis: bool = False

    # Translation (title only)
    title_zh: str | None = None

    # Entities & Sentiment
    entities: list[dict] | None = None
    primary_entity: str | None = None
    primary_entity_type: str | None = None
    sentiment_score: float | None = None
    sentiment_label: str | None = None

    # Finance metadata
    finance_metadata: dict | None = None

    # Pipeline
    content_status: str = "pending"
    processing_path: str | None = None
    agents_executed: list[str] | None = None

    # Story & event grouping
    story_id: UUID | None = None
    event_group_id: UUID | None = None

    # Metadata
    source_name: str | None = None
    authors: list[str] | None = None
    top_image: str | None = None
    word_count: int | None = None
    created_at: datetime | None = None


class ArticleListResponse(CamelModel):
    articles: list[ArticleSummaryResponse]
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


# --- Internal API: Ingest / Status / Results (WebStock integration) ---

class IngestArticle(CamelModel):
    """Single article from an external consumer like WebStock."""
    url: str
    title: str
    published_at: datetime | None = None
    summary: str | None = None
    source_name: str | None = None
    language: str | None = None
    symbol: str | None = None
    market: str | None = None
    external_id: str | None = None
    image_url: str | None = None
    provider: str | None = None


class IngestRequest(CamelModel):
    articles: list[IngestArticle]


class IngestArticleResult(CamelModel):
    url: str
    article_id: str | None = None
    external_id: str | None = None
    status: str  # "new" | "duplicate" | "error"
    error: str | None = None


class IngestResponse(CamelModel):
    total: int
    new_count: int
    duplicate_count: int
    error_count: int
    results: list[IngestArticleResult]


class ArticleStatusItem(CamelModel):
    article_id: str
    status: str  # "queued" | "processing" | "completed" | "failed" | "not_found"
    current_stage: str | None = None
    enqueued_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class StatusResponse(CamelModel):
    results: list[ArticleStatusItem]


class EnrichedArticleResponse(CamelModel):
    """Full enriched article response for external consumers."""
    id: str
    external_id: str | None = None
    title: str
    url: str
    published_at: datetime | None = None
    primary_category: str | None = None
    categories: list[str] | None = None
    tags: list[str] | None = None
    value_score: int | None = None
    has_market_impact: bool = False
    market_impact_hint: str | None = None
    ai_summary: str | None = None
    detailed_summary: str | None = None
    ai_analysis: str | None = None
    full_text: str | None = None
    title_zh: str | None = None
    full_text_zh: str | None = None
    entities: list[dict] | None = None
    primary_entity: str | None = None
    primary_entity_type: str | None = None
    sentiment_score: float | None = None
    sentiment_label: str | None = None
    finance_metadata: dict | None = None
    content_status: str = "pending"
    agents_executed: list[str] | None = None
    processing_path: str | None = None

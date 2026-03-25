"""Article model — core news article, universal (not finance-only).

Design principles:
- Multi-label classification: categories[] array, not single category_id FK
- Cross-category market impact: any news can affect stocks
- Dynamic agent pipeline: agents_executed tracks which agents processed this article
- Finance metadata JSONB: isolates WebStock-compatible fields
- Entities JSONB: universal types (person/org/location/stock/index/product/event)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Source tracking
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), index=True
    )
    feed_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("feeds.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255))

    # Core fields
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    language: Mapped[str | None] = mapped_column(String(10))  # en, zh, ja, ...

    # === Multi-label Classification (redesigned) ===
    # Primary category (highest confidence) — kept as FK for efficient queries
    primary_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    primary_category: Mapped[str | None] = mapped_column(String(50), index=True)  # slug denormalized for fast filtering
    # All categories this article belongs to
    categories: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))  # ["politics", "finance"]
    # Per-category confidence scores
    category_details: Mapped[dict | None] = mapped_column(JSONB)
    # [{"slug": "politics", "confidence": 0.88}, {"slug": "finance", "confidence": 0.45}]

    # Tags (from classifier)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))

    # === Value & Market Impact (from classifier, replaces L1 3-agent scoring) ===
    value_score: Mapped[int | None] = mapped_column(Integer)  # 0-100, information value
    value_reason: Mapped[str | None] = mapped_column(String(200))
    has_market_impact: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    market_impact_hint: Mapped[str | None] = mapped_column(String(500))

    # === Content Tiers (progressive disclosure) ===
    summary: Mapped[str | None] = mapped_column(Text)  # Original summary from source
    ai_summary: Mapped[str | None] = mapped_column(Text)  # AI 1-2 sentence (summarizer)
    detailed_summary: Mapped[str | None] = mapped_column(Text)  # 5-20 sentence (summarizer)
    ai_analysis: Mapped[str | None] = mapped_column(Text)  # Deep Markdown report (deep_reporter)
    # Cleaned full article text (from content cleaner agent)
    full_text: Mapped[str | None] = mapped_column(Text)

    # Content storage
    content_file_path: Mapped[str | None] = mapped_column(String(500))
    content_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # pending, fetched, processed, embedded, failed

    # === Entity Extraction (merged from all entity_* agents) ===
    entities: Mapped[dict | None] = mapped_column(JSONB)
    # [{name, type: "person"|"org"|"location"|"stock"|"index"|"macro"|"product"|"event", confidence}]
    primary_entity: Mapped[str | None] = mapped_column(String(100))
    primary_entity_type: Mapped[str | None] = mapped_column(String(20))

    # === Sentiment (from sentiment agent, all categories) ===
    sentiment_score: Mapped[float | None] = mapped_column(Float)  # -1.0 to 1.0
    sentiment_label: Mapped[str | None] = mapped_column(String(20))  # positive, negative, neutral

    # === Finance Metadata (from finance_* agents, WebStock compatible ★) ===
    finance_metadata: Mapped[dict | None] = mapped_column(JSONB)
    # {
    #   sentiment_tag: "bullish"|"bearish"|"neutral",  ★ WebStock
    #   investment_summary: "≤50字",                    ★ WebStock
    #   industry_tags: ["tech", "finance"],              ★ WebStock
    #   event_tags: ["regulatory", "earnings"],          ★ WebStock
    #   symbols: ["NVDA", "META"],                       ★ WebStock
    #   market: "us"                                     ★ WebStock
    # }

    # === Pipeline Metadata ===
    processing_path: Mapped[str | None] = mapped_column(String(20))  # high_value, medium, low
    agents_executed: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))  # ["summarizer", "entity", ...]
    pipeline_metadata: Mapped[dict | None] = mapped_column(JSONB)  # timing, token usage, etc.
    dedup_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # === Article Metadata ===
    authors: Mapped[dict | None] = mapped_column(JSONB)
    keywords: Mapped[dict | None] = mapped_column(JSONB)
    top_image: Mapped[str | None] = mapped_column(String(1024))
    word_count: Mapped[int | None] = mapped_column(Integer)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Primary category listing (most common query pattern)
        Index("ix_articles_primary_cat_status_pub", "primary_category", "content_status", published_at.desc()),
        # Multi-category containment queries (GIN on array)
        Index("ix_articles_categories_gin", "categories", postgresql_using="gin"),
        # Market impact queries (WebStock integration)
        Index("ix_articles_market_impact_pub", "has_market_impact", published_at.desc()),
        # Source listing
        Index("ix_articles_source_published", "source_id", published_at.desc()),
    )

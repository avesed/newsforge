"""Pipeline event model — observability for the processing pipeline."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    article_id: Mapped[str] = mapped_column(String(255), nullable=False)  # No FK for decoupling
    stage: Mapped[str] = mapped_column(String(50), nullable=False)  # dedup, classify, score, fetch, analyze, embed
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success, error, skip
    duration_ms: Mapped[float | None] = mapped_column(Float)

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_pipeline_events_article_created", "article_id", "created_at"),
        Index("ix_pipeline_events_stage_created", "stage", "created_at"),
    )

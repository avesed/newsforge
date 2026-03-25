"""LLM Profile model -- reusable parameter presets for pipeline agents.

Profiles define HOW the LLM is called (temperature, thinking, etc.),
while providers define WHERE the call goes (API endpoint, model).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LLMProfile(Base):
    __tablename__ = "llm_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Identity
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )  # "precise-extraction", "creative-analysis"
    description: Mapped[str | None] = mapped_column(Text)

    # Generation parameters
    temperature: Mapped[float | None] = mapped_column(Float)  # 0.0-2.0
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    top_p: Mapped[float | None] = mapped_column(Float)  # 0.0-1.0

    # Thinking / extended reasoning
    thinking_enabled: Mapped[bool | None] = mapped_column(
        Boolean
    )  # None = use provider default
    thinking_budget_tokens: Mapped[int | None] = mapped_column(Integer)

    # Timeout and retry
    timeout_seconds: Mapped[int | None] = mapped_column(
        Integer
    )  # Per-request timeout; None = use client default (120s)
    max_retries: Mapped[int | None] = mapped_column(
        Integer
    )  # Auto-retry count on failure; None = no retry (0)

    # Catch-all for provider-specific params
    extra_params: Mapped[dict | None] = mapped_column(JSONB)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

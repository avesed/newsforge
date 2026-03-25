"""LLM Provider model -- database-driven provider configuration.

Replaces environment variable-based config. Managed via admin UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LLMProvider(Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Provider identity
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )  # "openai-main", "anthropic-backup"
    provider_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # openai, anthropic, custom

    # Connection
    api_key: Mapped[str] = mapped_column(
        String(500), nullable=False
    )  # encrypted in production
    api_base: Mapped[str] = mapped_column(
        String(500), default="https://api.openai.com/v1"
    )

    # Models
    default_model: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # gpt-4o-mini
    embedding_model: Mapped[str | None] = mapped_column(
        String(100)
    )  # text-embedding-3-small

    # Purpose mappings: which purposes this provider handles
    # {"chat": "gpt-4o-mini", "classifier": "gpt-4o-mini", "analyzer": "gpt-4o",
    #  "embedding": "text-embedding-3-small"}
    purpose_models: Mapped[dict | None] = mapped_column(JSONB)

    # Extra params passed as extra_body to the API (e.g. chat_template_kwargs)
    # Example: {"chat_template_kwargs": {"enable_thinking": false}}
    extra_params: Mapped[dict | None] = mapped_column(JSONB)

    # Status
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Only one can be default
    priority: Mapped[int] = mapped_column(
        Integer, default=0
    )  # Higher = preferred, for fallback

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

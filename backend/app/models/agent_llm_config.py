"""Agent LLM Config model -- per-agent provider, model, and profile overrides.

Maps each pipeline agent to its specific LLM configuration:
- provider_id: which provider to use (null = use default)
- model: which model to use (null = use provider's purpose_models or default_model)
- profile_id: which parameter profile to apply (null = no profile overrides)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.llm_profile import LLMProfile  # noqa: F401
from app.models.llm_provider import LLMProvider  # noqa: F401


class AgentLLMConfig(Base):
    __tablename__ = "agent_llm_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Agent identity
    agent_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )  # "summarizer", "entity", "classifier"

    # Provider override (null = use default provider)
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_providers.id", ondelete="SET NULL"),
    )

    # Model override (null = use provider's purpose_models or default_model)
    model: Mapped[str | None] = mapped_column(String(100))

    # Profile override (null = no profile overrides)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_profiles.id", ondelete="SET NULL"),
    )

    # Relationships
    provider: Mapped[LLMProvider | None] = relationship(
        "LLMProvider", lazy="joined"
    )
    profile: Mapped[LLMProfile | None] = relationship(
        "LLMProfile", lazy="joined"
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

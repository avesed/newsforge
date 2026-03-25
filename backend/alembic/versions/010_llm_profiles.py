"""LLM profiles and agent LLM config tables.

Profiles store reusable parameter presets (temperature, thinking, etc.).
Agent configs map each pipeline agent to a provider, model, and profile.

Revision ID: 010_llm_profiles
Revises: 009_add_full_text
Create Date: 2026-03-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_llm_profiles"
down_revision: Union[str, None] = "009_add_full_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_profiles",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("top_p", sa.Float, nullable=True),
        sa.Column("thinking_enabled", sa.Boolean, nullable=True),
        sa.Column("thinking_budget_tokens", sa.Integer, nullable=True),
        sa.Column("extra_params", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "agent_llm_configs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("agent_id", sa.String(50), unique=True, nullable=False),
        sa.Column(
            "provider_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_providers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "profile_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("llm_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_agent_llm_configs_provider_id", "agent_llm_configs", ["provider_id"])
    op.create_index("ix_agent_llm_configs_profile_id", "agent_llm_configs", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_llm_configs_profile_id", table_name="agent_llm_configs")
    op.drop_index("ix_agent_llm_configs_provider_id", table_name="agent_llm_configs")
    op.drop_table("agent_llm_configs")
    op.drop_table("llm_profiles")

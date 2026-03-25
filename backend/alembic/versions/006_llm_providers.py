"""LLM providers table for database-driven LLM configuration.

Revision ID: 006_llm_providers
Revises: 005_events_history
Create Date: 2026-03-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_llm_providers"
down_revision: Union[str, None] = "005_events_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("provider_type", sa.String(20), nullable=False),
        sa.Column("api_key", sa.String(500), nullable=False),
        sa.Column(
            "api_base",
            sa.String(500),
            server_default="https://api.openai.com/v1",
        ),
        sa.Column("default_model", sa.String(100), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("purpose_models", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("is_enabled", sa.Boolean, server_default="true", nullable=False),
        sa.Column("is_default", sa.Boolean, server_default="false", nullable=False),
        sa.Column("priority", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_llm_providers_is_enabled",
        "llm_providers",
        ["is_enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_providers_is_enabled", table_name="llm_providers")
    op.drop_table("llm_providers")

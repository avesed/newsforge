"""Add extra_params JSONB column to llm_providers.

Allows passing arbitrary extra parameters to the LLM API (e.g.
chat_template_kwargs for thinking models like Qwen3/DeepSeek-R1).

Revision ID: 008_provider_extra_params
Revises: 007_timestamptz
Create Date: 2026-03-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "008_provider_extra_params"
down_revision = "007_timestamptz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_providers", sa.Column("extra_params", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("llm_providers", "extra_params")

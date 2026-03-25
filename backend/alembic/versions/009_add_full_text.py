"""Add full_text TEXT column to articles.

Stores cleaned full article text produced by the content cleaner agent.

Revision ID: 009_add_full_text
Revises: 008_provider_extra_params
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa

revision = "009_add_full_text"
down_revision = "008_provider_extra_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("full_text", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "full_text")

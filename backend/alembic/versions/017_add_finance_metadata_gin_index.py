"""Add GIN index on articles.finance_metadata for JSONB operator queries.

This index accelerates the ?, ?|, and @> operators used by the internal API
(articles/feed, articles/by-symbol, sentiment/batch) when filtering by
finance_metadata fields like symbols, market, and sentiment_tag.

Revision ID: 017_finance_meta_gin
Revises: 016_add_translation_fields
Create Date: 2026-04-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "017_finance_meta_gin"
down_revision: Union[str, None] = "016_add_translation_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # asyncpg requires exactly ONE SQL statement per op.execute()
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_article_finance_metadata_gin "
        "ON articles USING gin (finance_metadata)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_article_finance_metadata_gin")

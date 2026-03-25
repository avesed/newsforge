"""Multi-label classification + market impact + dynamic agents.

Revision ID: 002_multi_category
Revises: 001_initial_schema
Create Date: 2026-03-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_multi_category"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add new multi-category columns ---
    op.add_column("articles", sa.Column("primary_category", sa.String(50), index=True))
    op.add_column("articles", sa.Column("categories", sa.dialects.postgresql.ARRAY(sa.String(50))))
    op.add_column("articles", sa.Column("category_details", sa.dialects.postgresql.JSONB))

    # --- Value scoring (replaces L1 3-agent scoring) ---
    op.add_column("articles", sa.Column("value_score", sa.Integer))
    op.add_column("articles", sa.Column("value_reason", sa.String(200)))
    op.add_column("articles", sa.Column("has_market_impact", sa.Boolean, server_default=sa.text("false")))
    op.add_column("articles", sa.Column("market_impact_hint", sa.String(500)))

    # --- Dynamic agent tracking ---
    op.add_column("articles", sa.Column("agents_executed", sa.dialects.postgresql.ARRAY(sa.String(50))))
    op.add_column("articles", sa.Column("pipeline_metadata", sa.dialects.postgresql.JSONB))

    # --- Rename old single-category fields ---
    # Rename category_id to primary_category_id (keep FK)
    op.alter_column("articles", "category_id", new_column_name="primary_category_id")

    # --- Drop old fields that are replaced ---
    op.drop_column("articles", "subcategory")
    op.drop_column("articles", "category_confidence")
    op.drop_column("articles", "content_score")
    op.drop_column("articles", "score_details")

    # --- New indexes ---
    # GIN index for multi-category array containment queries
    op.execute(
        "CREATE INDEX ix_articles_categories_gin ON articles USING gin (categories)"
    )

    # Market impact + published_at for WebStock integration queries
    op.create_index("ix_articles_market_impact_pub", "articles", ["has_market_impact", sa.text("published_at DESC")])

    # Primary category composite (replaces old category_id composite)
    op.create_index(
        "ix_articles_primary_cat_status_pub",
        "articles",
        ["primary_category", "content_status", sa.text("published_at DESC")],
    )

    # Drop old composite index that used category_id
    op.drop_index("ix_articles_category_status_pub", table_name="articles")


def downgrade() -> None:
    op.drop_index("ix_articles_primary_cat_status_pub", table_name="articles")
    op.drop_index("ix_articles_market_impact_pub", table_name="articles")
    op.drop_index("ix_articles_categories_gin", table_name="articles")

    op.alter_column("articles", "primary_category_id", new_column_name="category_id")

    op.add_column("articles", sa.Column("subcategory", sa.String(50)))
    op.add_column("articles", sa.Column("category_confidence", sa.Float))
    op.add_column("articles", sa.Column("content_score", sa.Integer))
    op.add_column("articles", sa.Column("score_details", sa.dialects.postgresql.JSONB))

    op.drop_column("articles", "pipeline_metadata")
    op.drop_column("articles", "agents_executed")
    op.drop_column("articles", "market_impact_hint")
    op.drop_column("articles", "has_market_impact")
    op.drop_column("articles", "value_reason")
    op.drop_column("articles", "value_score")
    op.drop_column("articles", "category_details")
    op.drop_column("articles", "categories")
    op.drop_column("articles", "primary_category")

    op.create_index("ix_articles_category_status_pub", "articles", ["category_id", "content_status", sa.text("published_at DESC")])

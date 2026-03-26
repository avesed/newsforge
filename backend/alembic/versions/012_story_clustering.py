"""News stories and story-article junction tables for narrative clustering.

Revision ID: 012_story_clustering
Revises: 011_profile_timeout_retry
Create Date: 2026-03-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_story_clustering"
down_revision: Union[str, None] = "011_profile_timeout_retry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enable pg_trgm extension for text similarity matching ---
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- news_stories table ---
    op.create_table(
        "news_stories",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("story_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), server_default="developing", nullable=False),
        sa.Column("key_entities", sa.dialects.postgresql.ARRAY(sa.String(100)), nullable=True),
        sa.Column("categories", sa.dialects.postgresql.ARRAY(sa.String(50)), nullable=True),
        sa.Column("timeline", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("article_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "representative_article_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sentiment_avg", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
    )

    # Add vector column via raw SQL (pgvector type not available in SA column defs)
    op.execute("ALTER TABLE news_stories ADD COLUMN embedding vector(512)")

    op.create_index("ix_news_stories_story_type", "news_stories", ["story_type"])

    op.create_index("ix_news_stories_is_active", "news_stories", ["is_active"])

    # HNSW index for cosine similarity search on story embeddings
    op.execute(
        "CREATE INDEX ix_news_stories_embedding_hnsw ON news_stories "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )

    # GIN trigram index on news_stories.title for pg_trgm similarity()
    op.execute(
        "CREATE INDEX ix_news_stories_title_trgm ON news_stories "
        "USING gin (title gin_trgm_ops)"
    )

    # --- story_articles junction table ---
    op.create_table(
        "story_articles",
        sa.Column(
            "story_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_stories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "article_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("matched_by", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_story_articles_article", "story_articles", ["article_id"])

    # --- Add story columns to articles ---
    op.add_column("articles", sa.Column("story_hint", sa.String(100), nullable=True))

    op.add_column("articles", sa.Column("story_type", sa.String(30), nullable=True))

    op.add_column(
        "articles",
        sa.Column(
            "story_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_stories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_index("ix_articles_story_id", "articles", ["story_id"])

    # GIN trigram index on articles.story_hint for pg_trgm similarity()
    op.execute(
        "CREATE INDEX ix_articles_story_hint_trgm ON articles "
        "USING gin (story_hint gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_articles_story_hint_trgm")
    op.drop_index("ix_articles_story_id", table_name="articles")
    op.drop_column("articles", "story_id")
    op.drop_column("articles", "story_type")
    op.drop_column("articles", "story_hint")
    op.drop_index("ix_story_articles_article", table_name="story_articles")
    op.drop_table("story_articles")
    op.execute("DROP INDEX IF EXISTS ix_news_stories_title_trgm")
    op.execute("DROP INDEX IF EXISTS ix_news_stories_embedding_hnsw")
    op.drop_index("ix_news_stories_is_active", table_name="news_stories")
    op.drop_index("ix_news_stories_story_type", table_name="news_stories")
    op.drop_table("news_stories")
    # Note: pg_trgm extension NOT dropped — it's shared with other migrations

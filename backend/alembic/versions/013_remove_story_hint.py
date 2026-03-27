"""Remove story_hint and story_type columns from articles.

Revision ID: 013_remove_story_hint
Revises: 012_story_clustering
Create Date: 2026-03-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_remove_story_hint"
down_revision: Union[str, None] = "012_story_clustering"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_articles_story_hint_trgm")
    op.drop_column("articles", "story_hint")
    op.drop_column("articles", "story_type")

    # Fix embedding dimension: 512 → 1536 to match article embeddings
    op.execute("ALTER TABLE news_stories DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE news_stories ADD COLUMN embedding vector(1536)")
    # Recreate HNSW index with correct dimension
    op.execute("DROP INDEX IF EXISTS ix_news_stories_embedding_hnsw")
    op.execute(
        "CREATE INDEX ix_news_stories_embedding_hnsw ON news_stories "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )

    # Add GIN indexes for array overlap queries in find_candidate_stories
    op.execute(
        "CREATE INDEX ix_news_stories_categories_gin ON news_stories "
        "USING gin (categories)"
    )
    op.execute(
        "CREATE INDEX ix_news_stories_key_entities_gin ON news_stories "
        "USING gin (key_entities)"
    )


def downgrade() -> None:
    # Revert GIN indexes
    op.execute("DROP INDEX IF EXISTS ix_news_stories_categories_gin")
    op.execute("DROP INDEX IF EXISTS ix_news_stories_key_entities_gin")

    # Revert embedding dimension back to 512
    op.execute("DROP INDEX IF EXISTS ix_news_stories_embedding_hnsw")
    op.execute("ALTER TABLE news_stories DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE news_stories ADD COLUMN embedding vector(512)")
    op.execute(
        "CREATE INDEX ix_news_stories_embedding_hnsw ON news_stories "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )

    op.add_column("articles", sa.Column("story_hint", sa.String(100), nullable=True))
    op.add_column("articles", sa.Column("story_type", sa.String(30), nullable=True))
    op.execute(
        "CREATE INDEX ix_articles_story_hint_trgm ON articles "
        "USING gin (story_hint gin_trgm_ops)"
    )

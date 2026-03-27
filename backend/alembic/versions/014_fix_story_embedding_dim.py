"""Fix news_stories embedding dimension back to 512.

Revision ID: 014_fix_story_embedding_dim
Revises: 013_remove_story_hint
Create Date: 2026-03-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "014_fix_story_embedding_dim"
down_revision: Union[str, None] = "013_remove_story_hint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix: embeddings are 512-dim (from embedder agent), not 1536
    op.execute("ALTER TABLE news_stories DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE news_stories ADD COLUMN embedding vector(512)")
    op.execute("DROP INDEX IF EXISTS ix_news_stories_embedding_hnsw")
    op.execute(
        "CREATE INDEX ix_news_stories_embedding_hnsw ON news_stories "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE news_stories DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE news_stories ADD COLUMN embedding vector(1536)")
    op.execute("DROP INDEX IF EXISTS ix_news_stories_embedding_hnsw")
    op.execute(
        "CREATE INDEX ix_news_stories_embedding_hnsw ON news_stories "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )

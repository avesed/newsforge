"""Add event_group_id to articles + fix document_embeddings dimension.

Revision ID: 021
Revises: 020
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "021_semantic_dedup_event_group"
down_revision = "020_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- articles: event_group_id for multi-source event grouping ---
    op.execute(
        "ALTER TABLE articles ADD COLUMN event_group_id UUID"
    )
    op.execute(
        "CREATE INDEX ix_articles_event_group ON articles (event_group_id) WHERE event_group_id IS NOT NULL"
    )

    # --- document_embeddings: fix dimension 1536 → 512 ---
    # Drop the existing HNSW index first
    op.execute("DROP INDEX IF EXISTS ix_doc_embeddings_hnsw")

    # Alter the vector column dimension (drop + re-add since pgvector
    # doesn't support ALTER COLUMN TYPE for vector dimensions directly)
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE document_embeddings ADD COLUMN embedding vector(512)"
    )

    # Recreate HNSW index with correct dimensions
    op.execute(
        "CREATE INDEX ix_doc_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_articles_event_group")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS event_group_id")

    # Revert vector dimension
    op.execute("DROP INDEX IF EXISTS ix_doc_embeddings_hnsw")
    op.execute("ALTER TABLE document_embeddings DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE document_embeddings ADD COLUMN embedding vector(1536)"
    )
    op.execute(
        "CREATE INDEX ix_doc_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

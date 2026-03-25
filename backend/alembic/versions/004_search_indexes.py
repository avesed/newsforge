"""Search indexes — GIN trigram on articles, HNSW on embeddings.

Revision ID: 004_search_indexes
Revises: 003_consumers_webhooks
Create Date: 2026-03-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004_search_indexes"
down_revision: Union[str, None] = "003_consumers_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pg_trgm extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # GIN trigram index on articles.title
    op.execute(
        "CREATE INDEX ix_articles_title_trgm ON articles USING gin (title gin_trgm_ops)"
    )

    # GIN trigram index on articles.ai_summary
    op.execute(
        "CREATE INDEX ix_articles_ai_summary_trgm ON articles USING gin (ai_summary gin_trgm_ops)"
    )

    # HNSW index on document_embeddings.embedding for cosine similarity
    # (may already exist from 001_initial_schema)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_doc_embeddings_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_articles_ai_summary_trgm")
    op.execute("DROP INDEX IF EXISTS ix_articles_title_trgm")
    # Don't drop pg_trgm extension — other things may depend on it

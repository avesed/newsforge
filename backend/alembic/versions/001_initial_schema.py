"""Initial schema — all core tables.

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-03-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions (each in its own execute — asyncpg requirement)
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(100)),
        sa.Column("role", sa.String(20), server_default="user"),
        sa.Column("locale", sa.String(10), server_default="zh"),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # --- categories ---
    op.create_table(
        "categories",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("slug", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("name_en", sa.String(100), nullable=False),
        sa.Column("name_zh", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(50)),
        sa.Column("color", sa.String(20)),
        sa.Column("description", sa.Text),
        sa.Column("pipeline_config", sa.dialects.postgresql.JSONB, server_default="{}"),
        sa.Column("sort_order", sa.Integer, server_default="0"),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("article_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # --- sources ---
    op.create_table(
        "sources",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("config", sa.dialects.postgresql.JSONB, server_default="{}"),
        sa.Column("categories", sa.dialects.postgresql.ARRAY(sa.String(50))),
        sa.Column("markets", sa.dialects.postgresql.ARRAY(sa.String(10))),
        sa.Column("is_enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("health_status", sa.String(20), server_default="'unknown'"),
        sa.Column("consecutive_errors", sa.Integer, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("last_fetched_at", sa.DateTime),
        sa.Column("article_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # --- feeds ---
    op.create_table(
        "feeds",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("url", sa.String(1024), unique=True, nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("description", sa.Text),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("feed_type", sa.String(20), server_default="'native_rss'"),
        sa.Column("rsshub_route", sa.String(500)),
        sa.Column("category_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("poll_interval_minutes", sa.Integer, server_default="15"),
        sa.Column("fulltext_mode", sa.Boolean, server_default=sa.text("false")),
        sa.Column("is_enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("last_polled_at", sa.DateTime),
        sa.Column("last_error", sa.String(500)),
        sa.Column("consecutive_errors", sa.Integer, server_default="0"),
        sa.Column("article_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # --- articles ---
    op.create_table(
        "articles",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="SET NULL"), index=True),
        sa.Column("feed_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("feeds.id", ondelete="SET NULL"), index=True),
        sa.Column("external_id", sa.String(255)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1024), unique=True, nullable=False),
        sa.Column("published_at", sa.DateTime, index=True),
        sa.Column("language", sa.String(10)),
        sa.Column("category_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id", ondelete="SET NULL"), index=True),
        sa.Column("subcategory", sa.String(50)),
        sa.Column("category_confidence", sa.Float),
        sa.Column("tags", sa.dialects.postgresql.ARRAY(sa.String(50))),
        sa.Column("summary", sa.Text),
        sa.Column("ai_summary", sa.Text),
        sa.Column("detailed_summary", sa.Text),
        sa.Column("ai_analysis", sa.Text),
        sa.Column("content_file_path", sa.String(500)),
        sa.Column("content_status", sa.String(20), server_default="'pending'", index=True),
        sa.Column("entities", sa.dialects.postgresql.JSONB),
        sa.Column("primary_entity", sa.String(100)),
        sa.Column("primary_entity_type", sa.String(20)),
        sa.Column("sentiment_score", sa.Float),
        sa.Column("sentiment_label", sa.String(20)),
        sa.Column("finance_metadata", sa.dialects.postgresql.JSONB),
        sa.Column("content_score", sa.Integer),
        sa.Column("processing_path", sa.String(20)),
        sa.Column("score_details", sa.dialects.postgresql.JSONB),
        sa.Column("dedup_hash", sa.String(64), index=True),
        sa.Column("authors", sa.dialects.postgresql.JSONB),
        sa.Column("keywords", sa.dialects.postgresql.JSONB),
        sa.Column("top_image", sa.String(1024)),
        sa.Column("word_count", sa.Integer),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # Composite indexes for articles
    op.create_index("ix_articles_category_status_pub", "articles", ["category_id", "content_status", sa.text("published_at DESC")])
    op.create_index("ix_articles_source_published", "articles", ["source_id", sa.text("published_at DESC")])

    # --- document_embeddings ---
    op.create_table(
        "document_embeddings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("source_type", sa.String(50), nullable=False, index=True),
        sa.Column("source_id", sa.String(255), nullable=False, index=True),
        sa.Column("symbol", sa.String(20), index=True),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, server_default="0"),
        sa.Column("embedding", Vector(1536)),
        sa.Column("model", sa.String(100), server_default="'unknown'"),
        sa.Column("token_count", sa.Integer),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_doc_embeddings_source", "document_embeddings", ["source_type", "source_id"])

    # HNSW index for vector search (separate execute — asyncpg)
    op.execute(
        "CREATE INDEX ix_doc_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # GIN trigram index for text search
    op.execute(
        "CREATE INDEX ix_doc_embeddings_trgm ON document_embeddings "
        "USING gin (chunk_text gin_trgm_ops)"
    )

    # --- pipeline_events ---
    op.create_table(
        "pipeline_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("article_id", sa.String(255), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Float),
        sa.Column("metadata", sa.dialects.postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_index("ix_pe_article_created", "pipeline_events", ["article_id", "created_at"])
    op.create_index("ix_pe_stage_created", "pipeline_events", ["stage", "created_at"])

    # --- bookmarks ---
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("article_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "article_id", name="uq_bookmark_user_article"),
    )

    # --- subscriptions ---
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(255)),
        sa.Column("keywords", sa.dialects.postgresql.ARRAY(sa.String(100))),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    # --- Seed categories ---
    from app.models.category import SEED_CATEGORIES

    for cat in SEED_CATEGORIES:
        op.execute(
            sa.text(
                "INSERT INTO categories (slug, name_en, name_zh, icon, color, sort_order) "
                "VALUES (:slug, :name_en, :name_zh, :icon, :color, :sort_order) "
                "ON CONFLICT (slug) DO NOTHING"
            ).bindparams(**cat)
        )


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("bookmarks")
    op.drop_table("pipeline_events")
    op.drop_table("document_embeddings")
    op.drop_table("articles")
    op.drop_table("feeds")
    op.drop_table("sources")
    op.drop_table("categories")
    op.drop_table("users")

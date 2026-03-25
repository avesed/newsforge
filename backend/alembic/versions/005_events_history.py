"""Reading history, news events, and event-article junction tables.

Revision ID: 005_events_history
Revises: 004_search_indexes
Create Date: 2026-03-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_events_history"
down_revision: Union[str, None] = "004_search_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- reading_history table ---
    op.create_table(
        "reading_history",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("read_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("read_duration_ms", sa.Float, nullable=True),
        sa.UniqueConstraint("user_id", "article_id", name="uq_reading_history_user_article"),
    )

    op.create_index(
        "ix_reading_history_user_read",
        "reading_history",
        ["user_id", sa.text("read_at DESC")],
    )

    # --- news_events table ---
    op.create_table(
        "news_events",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("event_type", sa.String(20), server_default="breaking", nullable=False),
        sa.Column("primary_entity", sa.String(100), nullable=True),
        sa.Column("entity_type", sa.String(20), nullable=True),
        sa.Column("categories", sa.dialects.postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("tags", sa.dialects.postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("article_count", sa.Integer, server_default="1", nullable=False),
        sa.Column("first_seen_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("last_updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column(
            "representative_article_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sentiment_avg", sa.Float, nullable=True),
        sa.Column("sources", sa.dialects.postgresql.ARRAY(sa.String), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
    )

    op.create_index("ix_news_events_primary_entity", "news_events", ["primary_entity"])

    op.create_index("ix_news_events_is_active", "news_events", ["is_active"])

    # --- event_articles junction table ---
    op.create_table(
        "event_articles",
        sa.Column(
            "event_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "article_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_index("ix_event_articles_article_id", "event_articles", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_event_articles_article_id", table_name="event_articles")
    op.drop_table("event_articles")
    op.drop_index("ix_news_events_is_active", table_name="news_events")
    op.drop_index("ix_news_events_primary_entity", table_name="news_events")
    op.drop_table("news_events")
    op.drop_index("ix_reading_history_user_read", table_name="reading_history")
    op.drop_table("reading_history")

"""Add refresh tracking to news_stories.

Revision ID: 022
Revises: 021
"""

from alembic import op


revision = "022_story_refresh_tracking"
down_revision = "021_semantic_dedup_event_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE news_stories "
        "ADD COLUMN last_refreshed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE news_stories "
        "ADD COLUMN articles_since_refresh INTEGER NOT NULL DEFAULT 0"
    )
    # Bootstrap last_refreshed_at to first_seen_at for existing rows
    op.execute(
        "UPDATE news_stories SET last_refreshed_at = first_seen_at "
        "WHERE last_refreshed_at IS NULL"
    )
    # Index for the scheduled fallback query (find stories needing refresh)
    op.execute(
        "CREATE INDEX ix_news_stories_refresh_pending "
        "ON news_stories (last_refreshed_at) "
        "WHERE is_active = true AND articles_since_refresh > 0"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_news_stories_refresh_pending")
    op.execute("ALTER TABLE news_stories DROP COLUMN IF EXISTS articles_since_refresh")
    op.execute("ALTER TABLE news_stories DROP COLUMN IF EXISTS last_refreshed_at")

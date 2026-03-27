"""Merge NewsEvent system into NewsStory.

Migrates all event data into the stories table, then drops event tables.

Revision ID: 015_merge_events_into_stories
Revises: 014_fix_story_embedding_dim
Create Date: 2026-03-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "015_merge_events_into_stories"
down_revision: Union[str, None] = "014_fix_story_embedding_dim"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Create temp table mapping events to existing stories
    # Match by primary_entity in key_entities AND overlapping categories
    op.execute(
        """
        CREATE TEMP TABLE event_story_map AS
        SELECT DISTINCT ON (e.id)
            e.id AS event_id,
            s.id AS story_id
        FROM news_events e
        JOIN news_stories s ON
            e.primary_entity = ANY(s.key_entities)
            AND e.categories && s.categories
            AND s.is_active = true
        ORDER BY e.id, s.article_count DESC
        """
    )

    # Step 2: Insert new stories from unmatched events (reuse event UUID)
    # ON CONFLICT DO NOTHING guards against UUID collision with existing stories
    op.execute(
        """
        INSERT INTO news_stories (id, title, story_type, status, key_entities, categories,
            article_count, sentiment_avg, representative_article_id,
            first_seen_at, last_updated_at, is_active)
        SELECT
            e.id,
            e.title,
            'other',
            CASE e.event_type
                WHEN 'ongoing' THEN 'ongoing'
                ELSE 'developing'
            END,
            CASE WHEN e.primary_entity IS NOT NULL
                 THEN ARRAY[e.primary_entity]
                 ELSE ARRAY[]::varchar[]
            END,
            COALESCE(e.categories, ARRAY[]::varchar[]),
            e.article_count,
            e.sentiment_avg,
            e.representative_article_id,
            e.first_seen_at,
            e.last_updated_at,
            e.is_active
        FROM news_events e
        WHERE e.id NOT IN (SELECT event_id FROM event_story_map)
        ON CONFLICT (id) DO NOTHING
        """
    )

    # Step 2b: For events whose UUID collided, map them to the existing story
    op.execute(
        """
        INSERT INTO event_story_map (event_id, story_id)
        SELECT e.id, e.id
        FROM news_events e
        WHERE e.id NOT IN (SELECT event_id FROM event_story_map)
          AND e.id IN (SELECT id FROM news_stories)
        """
    )

    # Step 3: Add unmatched events to the map (they map to themselves)
    op.execute(
        """
        INSERT INTO event_story_map (event_id, story_id)
        SELECT e.id, e.id
        FROM news_events e
        WHERE e.id NOT IN (SELECT event_id FROM event_story_map)
        """
    )

    # Step 4: Migrate event_articles to story_articles
    op.execute(
        """
        INSERT INTO story_articles (story_id, article_id, matched_by, confidence, created_at)
        SELECT m.story_id, ea.article_id, 'migrated', NULL, now()
        FROM event_articles ea
        JOIN event_story_map m ON m.event_id = ea.event_id
        ON CONFLICT DO NOTHING
        """
    )

    # Step 5: Update articles.story_id for migrated articles that don't have one
    op.execute(
        """
        UPDATE articles SET story_id = sa.story_id
        FROM story_articles sa
        WHERE articles.id = sa.article_id
          AND articles.story_id IS NULL
          AND sa.matched_by = 'migrated'
        """
    )

    # Step 6: Recount article_count for all stories (LEFT JOIN to handle 0-article stories)
    op.execute(
        """
        UPDATE news_stories SET article_count = COALESCE(sub.cnt, 0)
        FROM (
            SELECT s.id AS story_id, COUNT(sa.article_id) as cnt
            FROM news_stories s
            LEFT JOIN story_articles sa ON sa.story_id = s.id
            GROUP BY s.id
        ) sub
        WHERE news_stories.id = sub.story_id
        """
    )

    # Step 7: Cleanup — drop temp table, then drop event tables
    op.execute("DROP TABLE IF EXISTS event_story_map")
    op.execute("DROP TABLE event_articles")
    op.execute("DROP TABLE news_events")


def downgrade() -> None:
    raise NotImplementedError("Cannot reverse event→story merge")

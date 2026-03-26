"""Story service — narrative-level event clustering across entities and categories."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.database import get_session_factory
from app.models.article import Article
from app.models.news_story import NewsStory, StoryArticle

logger = logging.getLogger(__name__)

# Matching thresholds
TEXT_SIMILARITY_HIGH = 0.6      # pg_trgm similarity for direct match
VECTOR_SIMILARITY_HIGH = 0.25   # cosine distance (lower = more similar) for direct match
VECTOR_SIMILARITY_GRAY = 0.35   # cosine distance threshold for gray zone (LLM confirm)
STORY_WINDOW_HOURS = 72         # Only match active stories updated within this window
MIN_ARTICLES_FOR_STORY = 3      # Minimum articles with similar hint before creating


async def find_matching_story(
    story_hint: str,
    embedding: list[float] | None = None,
) -> dict | None:
    """Find an existing active story matching the hint.

    Uses pg_trgm text similarity + pgvector cosine distance.
    Returns {"story_id": uuid, "title": str, "score": float, "match_type": str} or None.
    """
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STORY_WINDOW_HOURS)

    async with factory() as session:
        # Strategy 1: Text similarity via pg_trgm
        text_query = text("""
            SELECT id, title, similarity(title, :hint) AS sim_score
            FROM news_stories
            WHERE is_active = true
              AND last_updated_at >= :cutoff
              AND similarity(title, :hint) > :threshold
            ORDER BY sim_score DESC
            LIMIT 1
        """)
        result = await session.execute(
            text_query,
            {"hint": story_hint, "cutoff": cutoff, "threshold": TEXT_SIMILARITY_HIGH},
        )
        row = result.first()
        if row:
            logger.info(
                "Story text match: '%s' → '%s' (sim=%.3f)",
                story_hint[:30], row.title[:30], row.sim_score,
            )
            return {
                "story_id": str(row.id),
                "title": row.title,
                "score": float(row.sim_score),
                "match_type": "text",
            }

        # Strategy 2: Vector similarity (if embedding available)
        if embedding:
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            # Increase HNSW search quality for story dedup (default ef_search=40 → 100)
            await session.execute(text("SET LOCAL hnsw.ef_search = 100"))
            vec_query = text("""
                SELECT id, title, embedding <=> :vec AS distance
                FROM news_stories
                WHERE is_active = true
                  AND last_updated_at >= :cutoff
                  AND embedding IS NOT NULL
                ORDER BY distance ASC
                LIMIT 1
            """)
            result = await session.execute(
                vec_query,
                {"vec": vec_str, "cutoff": cutoff},
            )
            row = result.first()
            if row and row.distance < VECTOR_SIMILARITY_GRAY:
                # Convert distance to score (1 - distance for cosine)
                score = 1.0 - float(row.distance)
                match_type = "vector_high" if row.distance < VECTOR_SIMILARITY_HIGH else "vector_gray"
                logger.info(
                    "Story vector match: '%s' → '%s' (dist=%.3f, type=%s)",
                    story_hint[:30], row.title[:30], row.distance, match_type,
                )
                return {
                    "story_id": str(row.id),
                    "title": row.title,
                    "score": score,
                    "match_type": match_type,
                }

    return None


async def count_similar_pending_articles(story_hint: str, exclude_article_id: str) -> int:
    """Count recent articles with similar story_hint that aren't linked to any story yet."""
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STORY_WINDOW_HOURS)

    async with factory() as session:
        query = text("""
            SELECT COUNT(*) FROM articles
            WHERE story_hint IS NOT NULL
              AND story_id IS NULL
              AND created_at >= :cutoff
              AND id != :exclude_id
              AND similarity(story_hint, :hint) > :threshold
        """)
        result = await session.execute(
            query,
            {"hint": story_hint, "cutoff": cutoff, "exclude_id": exclude_article_id, "threshold": 0.4},
        )
        return result.scalar() or 0


async def create_story(
    title: str,
    description: str | None,
    story_type: str,
    key_entities: list[str] | None,
    categories: list[str] | None,
    embedding: list[float] | None,
    first_article_id: str,
) -> str:
    """Create a new story and link the first article. Returns story_id."""
    factory = get_session_factory()

    story_id = uuid.uuid4()
    async with factory() as session:
        story = NewsStory(
            id=story_id,
            title=title,
            description=description,
            story_type=story_type,
            status="developing",
            key_entities=key_entities,
            categories=categories,
            article_count=1,
            representative_article_id=first_article_id,
            is_active=True,
        )
        # Set embedding if available
        if embedding:
            story.embedding = embedding

        session.add(story)

        # Link first article
        sa = StoryArticle(
            story_id=story_id,
            article_id=first_article_id,
            matched_by="created",
            confidence=1.0,
        )
        session.add(sa)

        # Update article's story_id
        await session.execute(
            update(Article).where(Article.id == first_article_id).values(story_id=story_id)
        )

        await session.commit()

    logger.info("Created new story: '%s' (type=%s, id=%s)", title[:50], story_type, story_id)
    return str(story_id)


async def link_article_to_story(
    story_id: str,
    article_id: str,
    matched_by: str = "direct",
    confidence: float | None = None,
) -> None:
    """Link an article to an existing story."""
    factory = get_session_factory()

    async with factory() as session:
        # Upsert into story_articles (ignore if already linked)
        stmt = pg_insert(StoryArticle).values(
            story_id=story_id,
            article_id=article_id,
            matched_by=matched_by,
            confidence=confidence,
        ).on_conflict_do_nothing()
        result = await session.execute(stmt)

        # Only update count if a new row was actually inserted
        if result.rowcount > 0:
            await session.execute(
                update(NewsStory)
                .where(NewsStory.id == story_id)
                .values(
                    article_count=NewsStory.article_count + 1,
                    last_updated_at=func.now(),
                )
            )

            # Update article's story_id
            await session.execute(
                update(Article).where(Article.id == article_id).values(story_id=story_id)
            )

            await session.commit()
            logger.info("Linked article %s to story %s (by=%s)", article_id[:8], story_id[:8], matched_by)
        else:
            await session.commit()
            logger.debug("Article %s already linked to story %s, skipped", article_id[:8], story_id[:8])


async def link_similar_pending_articles(story_id: str, story_hint: str) -> int:
    """Find and link pending articles with similar story_hint to an existing story.
    Returns count of newly linked articles."""
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STORY_WINDOW_HOURS)
    linked = 0

    async with factory() as session:
        # Find similar pending articles
        query = text("""
            SELECT id FROM articles
            WHERE story_hint IS NOT NULL
              AND story_id IS NULL
              AND created_at >= :cutoff
              AND similarity(story_hint, :hint) > 0.4
            LIMIT 50
        """)
        result = await session.execute(query, {"hint": story_hint, "cutoff": cutoff})
        article_ids = [str(row.id) for row in result.fetchall()]

    # Link each (outside the session to avoid long transactions)
    for aid in article_ids:
        try:
            await link_article_to_story(story_id, aid, matched_by="batch", confidence=0.7)
            linked += 1
        except Exception:
            logger.debug("Failed to link article %s to story %s", aid[:8], story_id[:8])

    return linked


async def deactivate_stale_stories(hours: int = 72) -> int:
    """Mark stories as concluded if not updated recently."""
    factory = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    async with factory() as session:
        result = await session.execute(
            update(NewsStory)
            .where(NewsStory.is_active == True, NewsStory.last_updated_at < cutoff)  # noqa: E712
            .values(is_active=False, status="concluded")
        )
        count = result.rowcount
        await session.commit()

    if count:
        logger.info("Deactivated %d stale stories (>%dh)", count, hours)
    return count

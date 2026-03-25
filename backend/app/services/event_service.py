"""Event aggregation service — detects and manages cross-source news events.

Called ASYNCHRONOUSLY after pipeline processing (not inline).
Matching strategy: primary_entity + entity_type + 24h window.
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_session_factory
from app.models.article import Article
from app.models.news_event import EventArticle, NewsEvent

logger = logging.getLogger(__name__)

EVENT_WINDOW_HOURS = 24
MIN_ARTICLES_FOR_EVENT = 2


async def check_and_create_event(article_id: str) -> None:
    """Check if a newly processed article belongs to an existing event or creates a new one.

    This runs AFTER pipeline processing, asynchronously (does not block pipeline).
    """
    factory = get_session_factory()
    async with factory() as db:
        # Fetch the article
        article = await db.get(Article, article_id)
        if not article or not article.primary_entity:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(hours=EVENT_WINDOW_HOURS)

        # Find existing active event with same entity
        event_result = await db.execute(
            select(NewsEvent)
            .where(
                NewsEvent.primary_entity == article.primary_entity,
                NewsEvent.entity_type == article.primary_entity_type,
                NewsEvent.is_active == True,  # noqa: E712
                NewsEvent.last_updated_at >= cutoff,
            )
            .order_by(NewsEvent.last_updated_at.desc())
            .limit(1)
        )
        existing_event = event_result.scalar_one_or_none()

        if existing_event:
            # Check if article already linked
            link_check = await db.execute(
                select(EventArticle).where(
                    EventArticle.event_id == existing_event.id,
                    EventArticle.article_id == article.id,
                )
            )
            if link_check.scalar_one_or_none():
                return  # Already linked

            # Add article to existing event
            db.add(EventArticle(event_id=existing_event.id, article_id=article.id))

            # Update event metadata
            existing_event.article_count += 1
            existing_event.last_updated_at = datetime.now(timezone.utc)

            # Update sources list
            source_name = None
            if article.pipeline_metadata and isinstance(article.pipeline_metadata, dict):
                source_name = article.pipeline_metadata.get("source_name")

            if source_name and existing_event.sources:
                if source_name not in existing_event.sources:
                    existing_event.sources = [*existing_event.sources, source_name]

            # Update sentiment average
            if article.sentiment_score is not None:
                all_sentiments = await db.execute(
                    select(func.avg(Article.sentiment_score))
                    .join(EventArticle, EventArticle.article_id == Article.id)
                    .where(
                        EventArticle.event_id == existing_event.id,
                        Article.sentiment_score.is_not(None),
                    )
                )
                avg = all_sentiments.scalar()
                if avg is not None:
                    existing_event.sentiment_avg = round(avg, 4)

            # Update representative (highest value_score)
            best = await db.execute(
                select(Article.id)
                .join(EventArticle, EventArticle.article_id == Article.id)
                .where(EventArticle.event_id == existing_event.id)
                .order_by(Article.value_score.desc().nullslast())
                .limit(1)
            )
            best_id = best.scalar()
            if best_id:
                existing_event.representative_article_id = best_id

            await db.commit()
            logger.info(
                "Added article %s to event %s (now %d articles)",
                article_id, existing_event.id, existing_event.article_count,
            )
        else:
            # Check if there are other recent articles with same entity
            similar_count_result = await db.execute(
                select(func.count(Article.id))
                .where(
                    Article.primary_entity == article.primary_entity,
                    Article.primary_entity_type == article.primary_entity_type,
                    Article.published_at >= cutoff,
                    Article.id != article.id,
                )
            )
            similar_count = similar_count_result.scalar() or 0

            if similar_count >= MIN_ARTICLES_FOR_EVENT - 1:
                # Create new event
                event = NewsEvent(
                    title=f"{article.primary_entity}: {article.title[:100]}",
                    primary_entity=article.primary_entity,
                    entity_type=article.primary_entity_type,
                    categories=article.categories,
                    tags=article.tags,
                    article_count=similar_count + 1,
                    representative_article_id=article.id,
                    sentiment_avg=article.sentiment_score,
                    sources=[],
                )
                db.add(event)
                await db.flush()

                # Link all matching articles
                similar_articles = await db.execute(
                    select(Article.id)
                    .where(
                        Article.primary_entity == article.primary_entity,
                        Article.primary_entity_type == article.primary_entity_type,
                        Article.published_at >= cutoff,
                    )
                )
                for (aid,) in similar_articles.all():
                    db.add(EventArticle(event_id=event.id, article_id=aid))

                await db.commit()
                logger.info(
                    "Created event %s for entity '%s' with %d articles",
                    event.id, article.primary_entity, event.article_count,
                )


async def deactivate_stale_events(hours: int = 48) -> int:
    """Mark events as inactive if not updated within `hours`."""
    factory = get_session_factory()
    async with factory() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await db.execute(
            update(NewsEvent)
            .where(NewsEvent.is_active == True, NewsEvent.last_updated_at < cutoff)  # noqa: E712
            .values(is_active=False)
        )
        await db.commit()
        count = result.rowcount
        if count:
            logger.info("Deactivated %d stale events", count)
        return count

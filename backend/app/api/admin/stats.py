"""Admin dashboard statistics -- comprehensive system overview."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.db.redis import get_redis
from app.models.article import Article
from app.models.api_consumer import ApiConsumer
from app.models.news_story import NewsStory
from app.models.pipeline_event import PipelineEvent
from app.models.source import Source
from app.models.user import User
from app.services.cache_service import cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/stats", tags=["admin"])

CACHE_KEY = "admin:stats"
CACHE_TTL = 15  # seconds


@router.get("/dashboard")
async def dashboard_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Comprehensive dashboard statistics for admin UI."""
    # Check cache first
    cached = await cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    # --- Overview ---
    articles_total_result = await db.execute(select(func.count(Article.id)))
    articles_total = articles_total_result.scalar() or 0

    articles_today_result = await db.execute(
        select(func.count(Article.id)).where(Article.created_at >= today_start)
    )
    articles_today = articles_today_result.scalar() or 0

    articles_week_result = await db.execute(
        select(func.count(Article.id)).where(Article.created_at >= week_start)
    )
    articles_this_week = articles_week_result.scalar() or 0

    stories_active_result = await db.execute(
        select(func.count(NewsStory.id)).where(NewsStory.is_active == True)  # noqa: E712
    )
    stories_active = stories_active_result.scalar() or 0

    users_total_result = await db.execute(select(func.count(User.id)))
    users_total = users_total_result.scalar() or 0

    consumers_active_result = await db.execute(
        select(func.count(ApiConsumer.id)).where(ApiConsumer.is_active == True)  # noqa: E712
    )
    consumers_active = consumers_active_result.scalar() or 0

    # --- Category distribution ---
    cat_result = await db.execute(
        select(Article.primary_category, func.count(Article.id))
        .where(Article.primary_category.is_not(None))
        .group_by(Article.primary_category)
    )
    category_distribution = {row[0]: row[1] for row in cat_result.all()}

    # --- Hourly counts (last 24 hours) ---
    hourly_result = await db.execute(
        select(
            func.date_trunc("hour", Article.created_at).label("hour"),
            func.count(Article.id).label("count"),
        )
        .where(Article.created_at >= last_24h)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    hourly_counts = [
        {"hour": row.hour.isoformat(), "count": row.count}
        for row in hourly_result.all()
    ]

    # --- Daily counts (last 30 days) ---
    daily_result = await db.execute(
        select(
            func.date_trunc("day", Article.created_at).label("date"),
            func.count(Article.id).label("count"),
        )
        .where(Article.created_at >= last_30d)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    daily_counts = [
        {"date": row.date.strftime("%Y-%m-%d"), "count": row.count}
        for row in daily_result.all()
    ]

    # --- Source health ---
    source_result = await db.execute(
        select(Source).order_by(Source.article_count.desc())
    )
    sources = source_result.scalars().all()
    source_health = [
        {
            "source_id": str(s.id),
            "name": s.name,
            "is_enabled": s.is_enabled,
            "health_status": s.health_status,
            "consecutive_errors": s.consecutive_errors,
            "article_count": s.article_count,
            "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        }
        for s in sources
    ]

    # --- Pipeline performance (last 24h) ---
    perf_result = await db.execute(
        select(
            func.count(PipelineEvent.id).label("total"),
            func.avg(PipelineEvent.duration_ms).label("avg_duration"),
            func.count(PipelineEvent.id).filter(
                PipelineEvent.status == "success"
            ).label("success_count"),
            func.count(PipelineEvent.id).filter(
                PipelineEvent.status == "error"
            ).label("error_count"),
        ).where(PipelineEvent.created_at >= last_24h)
    )
    perf = perf_result.one()
    total_events = perf.total or 0
    pipeline_performance = {
        "avg_duration_ms": round(float(perf.avg_duration or 0), 1),
        "success_rate": round((perf.success_count or 0) / total_events, 3) if total_events > 0 else 0.0,
        "events_last_24h": total_events,
        "error_count_24h": perf.error_count or 0,
    }

    # --- Top entities (last 7 days) ---
    entity_result = await db.execute(
        select(
            Article.primary_entity,
            Article.primary_entity_type,
            func.count(Article.id).label("mention_count"),
        )
        .where(
            Article.primary_entity.is_not(None),
            Article.created_at >= last_7d,
        )
        .group_by(Article.primary_entity, Article.primary_entity_type)
        .order_by(func.count(Article.id).desc())
        .limit(15)
    )
    top_entities = [
        {"entity": row.primary_entity, "type": row.primary_entity_type, "mention_count": row.mention_count}
        for row in entity_result.all()
    ]

    # --- Sentiment distribution ---
    sentiment_result = await db.execute(
        select(
            func.count(Article.id).filter(Article.sentiment_label == "positive").label("positive"),
            func.count(Article.id).filter(Article.sentiment_label == "neutral").label("neutral"),
            func.count(Article.id).filter(Article.sentiment_label == "negative").label("negative"),
        )
    )
    sent = sentiment_result.one()
    sentiment_distribution = {
        "positive": sent.positive or 0,
        "neutral": sent.neutral or 0,
        "negative": sent.negative or 0,
    }

    # --- Queue stats (Redis) ---
    try:
        redis = await get_redis()
        queue_main = await redis.llen("nf:pipeline:queue")
        queue_retry = await redis.zcard("nf:pipeline:retry")
        queue_dead = await redis.llen("nf:pipeline:dead_letter")
    except Exception:
        queue_main = queue_retry = queue_dead = 0

    queue = {"main": queue_main, "retry": queue_retry, "dead_letter": queue_dead}

    # --- Assemble response ---
    result = {
        "overview": {
            "articles_total": articles_total,
            "articles_today": articles_today,
            "articles_this_week": articles_this_week,
            "stories_active": stories_active,
            "users_total": users_total,
            "consumers_active": consumers_active,
        },
        "category_distribution": category_distribution,
        "hourly_counts": hourly_counts,
        "daily_counts": daily_counts,
        "source_health": source_health,
        "pipeline_performance": pipeline_performance,
        "top_entities": top_entities,
        "sentiment_distribution": sentiment_distribution,
        "queue": queue,
    }

    # Cache for 15 seconds
    await cache.set(CACHE_KEY, result, ttl_seconds=CACHE_TTL)

    return result

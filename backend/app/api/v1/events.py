"""Events endpoints — cross-source event aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.article import Article
from app.models.news_event import EventArticle, NewsEvent
from app.schemas.article import ArticleResponse
from app.schemas.event import EventDetailResponse, EventResponse

router = APIRouter(prefix="/events", tags=["events"])


def _event_to_response(
    event: NewsEvent,
    rep_title: str | None = None,
    rep_summary: str | None = None,
) -> EventResponse:
    """Convert ORM NewsEvent to response schema."""
    return EventResponse(
        id=event.id,
        title=event.title,
        event_type=event.event_type,
        primary_entity=event.primary_entity,
        entity_type=event.entity_type,
        categories=event.categories,
        article_count=event.article_count,
        first_seen_at=event.first_seen_at,
        last_updated_at=event.last_updated_at,
        sentiment_avg=event.sentiment_avg,
        sources=event.sources,
        representative_title=rep_title,
        representative_summary=rep_summary,
    )


@router.get("/", response_model=list[EventResponse])
async def list_events(
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List active events sorted by article_count desc."""
    query = (
        select(NewsEvent, Article.title, Article.ai_summary)
        .outerjoin(Article, NewsEvent.representative_article_id == Article.id)
        .where(NewsEvent.is_active == True)  # noqa: E712
    )

    if category:
        query = query.where(NewsEvent.categories.any(category))

    query = query.order_by(NewsEvent.article_count.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    return [
        _event_to_response(event, rep_title=rep_title, rep_summary=rep_summary)
        for event, rep_title, rep_summary in rows
    ]


@router.get("/trending", response_model=list[EventResponse])
async def trending_events(
    db: AsyncSession = Depends(get_db),
):
    """Top 10 events by article_count in the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    query = (
        select(NewsEvent, Article.title, Article.ai_summary)
        .outerjoin(Article, NewsEvent.representative_article_id == Article.id)
        .where(
            NewsEvent.is_active == True,  # noqa: E712
            NewsEvent.last_updated_at >= cutoff,
        )
        .order_by(NewsEvent.article_count.desc())
        .limit(10)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        _event_to_response(event, rep_title=rep_title, rep_summary=rep_summary)
        for event, rep_title, rep_summary in rows
    ]


@router.get("/{event_id}", response_model=EventDetailResponse)
async def get_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get event detail with all related articles."""
    # Fetch event with representative article info
    result = await db.execute(
        select(NewsEvent, Article.title, Article.ai_summary)
        .outerjoin(Article, NewsEvent.representative_article_id == Article.id)
        .where(NewsEvent.id == event_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    event, rep_title, rep_summary = row

    # Fetch all linked articles
    articles_result = await db.execute(
        select(Article)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .where(EventArticle.event_id == event_id)
        .order_by(Article.published_at.desc().nullslast())
    )
    articles = articles_result.scalars().all()

    from app.api.v1.articles import _to_response

    return EventDetailResponse(
        id=event.id,
        title=event.title,
        event_type=event.event_type,
        primary_entity=event.primary_entity,
        entity_type=event.entity_type,
        categories=event.categories,
        article_count=event.article_count,
        first_seen_at=event.first_seen_at,
        last_updated_at=event.last_updated_at,
        sentiment_avg=event.sentiment_avg,
        sources=event.sources,
        representative_title=rep_title,
        representative_summary=rep_summary,
        articles=[_to_response(a) for a in articles],
    )

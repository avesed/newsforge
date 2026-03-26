"""Stories endpoints — narrative-level event clustering."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.article import Article
from app.models.news_story import NewsStory, StoryArticle
from app.schemas.story import StoryDetailResponse, StoryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stories", tags=["stories"])


def _story_to_response(
    story: NewsStory,
    rep_title: str | None = None,
    rep_summary: str | None = None,
) -> StoryResponse:
    """Convert ORM NewsStory to response schema."""
    return StoryResponse(
        id=story.id,
        title=story.title,
        description=story.description,
        story_type=story.story_type,
        status=story.status,
        key_entities=story.key_entities,
        categories=story.categories,
        article_count=story.article_count,
        first_seen_at=story.first_seen_at,
        last_updated_at=story.last_updated_at,
        sentiment_avg=story.sentiment_avg,
        representative_title=rep_title,
        representative_summary=rep_summary,
    )


@router.get("/", response_model=list[StoryResponse])
async def list_stories(
    category: str | None = Query(None, description="Filter by category"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List active stories sorted by article_count desc."""
    logger.debug("list_stories category=%s status=%s limit=%d", category, status, limit)
    query = (
        select(NewsStory, Article.title, Article.ai_summary)
        .outerjoin(Article, NewsStory.representative_article_id == Article.id)
        .where(NewsStory.is_active == True)  # noqa: E712
    )

    if category:
        query = query.where(NewsStory.categories.any(category))

    if status:
        query = query.where(NewsStory.status == status)

    query = query.order_by(NewsStory.article_count.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.all()

    return [
        _story_to_response(story, rep_title=rep_title, rep_summary=rep_summary)
        for story, rep_title, rep_summary in rows
    ]


@router.get("/trending", response_model=list[StoryResponse])
async def trending_stories(
    db: AsyncSession = Depends(get_db),
):
    """Top stories by article_count in the last 24 hours."""
    logger.debug("trending_stories requested")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    query = (
        select(NewsStory, Article.title, Article.ai_summary)
        .outerjoin(Article, NewsStory.representative_article_id == Article.id)
        .where(
            NewsStory.is_active == True,  # noqa: E712
            NewsStory.last_updated_at >= cutoff,
        )
        .order_by(NewsStory.article_count.desc())
        .limit(10)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        _story_to_response(story, rep_title=rep_title, rep_summary=rep_summary)
        for story, rep_title, rep_summary in rows
    ]


@router.get("/{story_id}", response_model=StoryDetailResponse)
async def get_story(
    story_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get story detail with all related articles."""
    logger.debug("get_story id=%s", story_id)
    # Fetch story with representative article info
    result = await db.execute(
        select(NewsStory, Article.title, Article.ai_summary)
        .outerjoin(Article, NewsStory.representative_article_id == Article.id)
        .where(NewsStory.id == story_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Story not found")

    story, rep_title, rep_summary = row

    # Fetch all linked articles
    articles_result = await db.execute(
        select(Article)
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .where(StoryArticle.story_id == story_id)
        .order_by(Article.published_at.desc().nullslast())
    )
    articles = articles_result.scalars().all()

    from app.api.v1.articles import _to_response

    return StoryDetailResponse(
        id=story.id,
        title=story.title,
        description=story.description,
        story_type=story.story_type,
        status=story.status,
        key_entities=story.key_entities,
        categories=story.categories,
        article_count=story.article_count,
        first_seen_at=story.first_seen_at,
        last_updated_at=story.last_updated_at,
        sentiment_avg=story.sentiment_avg,
        representative_title=rep_title,
        representative_summary=rep_summary,
        articles=[_to_response(a) for a in articles],
        timeline=story.timeline,
    )

"""Reading history endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.article import Article
from app.models.reading_history import ReadingHistory
from app.models.user import User
from app.schemas.article import ArticleListResponse, ArticleResponse
from app.schemas.base import CamelModel

router = APIRouter(prefix="/reading-history", tags=["reading-history"])


class MarkReadRequest(CamelModel):
    read_duration_ms: float | None = Field(None, description="Time spent reading in ms")


class ReadArticleIdsResponse(CamelModel):
    article_ids: list[str]


def _to_response(article: Article) -> ArticleResponse:
    """Convert ORM Article to response schema."""
    return ArticleResponse(
        id=article.id,
        title=article.title,
        url=article.url,
        published_at=article.published_at,
        language=article.language,
        primary_category=article.primary_category,
        categories=article.categories,
        category_details=article.category_details if isinstance(article.category_details, list) else None,
        tags=article.tags,
        value_score=article.value_score,
        has_market_impact=article.has_market_impact,
        market_impact_hint=article.market_impact_hint,
        summary=article.summary,
        ai_summary=article.ai_summary,
        detailed_summary=article.detailed_summary,
        ai_analysis=article.ai_analysis,
        full_text=article.full_text,
        title_zh=article.title_zh,
        full_text_zh=article.full_text_zh,
        entities=article.entities if isinstance(article.entities, list) else None,
        primary_entity=article.primary_entity,
        primary_entity_type=article.primary_entity_type,
        sentiment_score=article.sentiment_score,
        sentiment_label=article.sentiment_label,
        finance_metadata=article.finance_metadata,
        content_status=article.content_status,
        processing_path=article.processing_path,
        agents_executed=article.agents_executed,
        authors=article.authors if isinstance(article.authors, list) else None,
        top_image=article.top_image,
        word_count=article.word_count,
        created_at=article.created_at,
    )


@router.post("/{article_id}", status_code=201)
async def mark_article_read(
    article_id: UUID,
    body: MarkReadRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark article as read (upsert on conflict)."""
    # Verify article exists
    exists = await db.execute(select(Article.id).where(Article.id == article_id))
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Article not found")

    read_duration = body.read_duration_ms if body else None

    stmt = pg_insert(ReadingHistory).values(
        user_id=user.id,
        article_id=article_id,
        read_duration_ms=read_duration,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_reading_history_user_article",
        set_={
            "read_at": func.now(),
            "read_duration_ms": read_duration,
        },
    )
    await db.execute(stmt)
    return {"status": "ok"}


@router.get("", response_model=ArticleListResponse)
async def list_reading_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated reading history (most recent first)."""
    # Count total
    count_q = select(func.count(ReadingHistory.id)).where(
        ReadingHistory.user_id == user.id
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Fetch articles joined with reading history
    offset = (page - 1) * page_size
    query = (
        select(Article)
        .join(ReadingHistory, ReadingHistory.article_id == Article.id)
        .where(ReadingHistory.user_id == user.id)
        .order_by(ReadingHistory.read_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    articles = result.scalars().all()

    return ArticleListResponse(
        articles=[_to_response(a) for a in articles],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/ids", response_model=ReadArticleIdsResponse)
async def get_read_article_ids(
    since: datetime | None = Query(None, description="Only IDs since this datetime"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Just article IDs that user has read (for marking cards).

    Called once on app load, kept lightweight. Defaults to last 30 days.
    """
    cutoff = since or (datetime.now(timezone.utc) - timedelta(days=30))

    query = (
        select(ReadingHistory.article_id)
        .where(ReadingHistory.user_id == user.id)
        .where(ReadingHistory.read_at >= cutoff)
    )
    result = await db.execute(query)
    ids = [str(row) for row in result.scalars().all()]

    return ReadArticleIdsResponse(article_ids=ids)

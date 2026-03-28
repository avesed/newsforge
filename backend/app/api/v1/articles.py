"""Article endpoints — list, detail, category-based filtering.

Supports /news/{category} pattern (user requirement #3).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.article import Article
from app.models.feed import Feed
from app.schemas.article import ArticleListResponse, ArticleResponse
from app.services.cache_service import cache

router = APIRouter(tags=["articles"])


@router.get("/news", response_model=ArticleListResponse)
async def list_articles(
    category: str | None = Query(None, description="Filter by category slug"),
    language: str | None = Query(None, description="Filter by language (en, zh)"),
    status: str | None = Query(None, description="Filter by content_status"),
    q: str | None = Query(None, description="Search in title"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List articles with optional filtering."""
    # Cache only simple category+page queries (no search/language/status filters)
    cache_key = None
    if not language and not status and not q:
        cache_key = f"articles:{category or 'all'}:{page}"
        cached = await cache.get(cache_key)
        if cached:
            return ArticleListResponse(**cached)

    query = (
        select(Article, Feed.title.label("feed_title"))
        .outerjoin(Feed, Article.feed_id == Feed.id)
        .order_by(Article.published_at.desc().nullslast(), Article.created_at.desc())
    )
    count_query = select(func.count(Article.id))

    # Filters
    if category:
        # Use primary_category slug (denormalized) or array containment
        query = query.where(Article.primary_category == category)
        count_query = count_query.where(Article.primary_category == category)

    if language:
        query = query.where(Article.language == language)
        count_query = count_query.where(Article.language == language)

    if status:
        query = query.where(Article.content_status == status)
        count_query = count_query.where(Article.content_status == status)

    if q:
        query = query.where(Article.title.ilike(f"%{q}%"))
        count_query = count_query.where(Article.title.ilike(f"%{q}%"))

    # Pagination
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    response = ArticleListResponse(
        articles=[_to_response(a, feed_title=ft) for a, ft in rows],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )

    if cache_key:
        await cache.set(cache_key, response.model_dump(mode="json"), ttl_seconds=60)

    return response


@router.get("/news/{category}", response_model=ArticleListResponse)
async def list_by_category(
    category: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List articles for a specific category (e.g., /news/finance)."""
    return await list_articles(category=category, page=page, page_size=page_size, db=db)


@router.get("/articles/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single article by ID."""
    cache_key = f"article:{article_id}"
    cached = await cache.get(cache_key)
    if cached:
        return ArticleResponse(**cached)

    result = await db.execute(
        select(Article, Feed.title.label("feed_title"))
        .outerjoin(Feed, Article.feed_id == Feed.id)
        .where(Article.id == article_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")

    article, feed_title = row
    response = _to_response(article, feed_title=feed_title)
    await cache.set(cache_key, response.model_dump(mode="json"), ttl_seconds=300)
    return response


@router.get("/articles/{article_id}/related", response_model=list[ArticleResponse])
async def get_related_articles(
    article_id: UUID,
    limit: int = Query(6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Get related articles using multi-strategy approach.

    Strategy priority:
    1. Vector similarity (if article has embedding) — best quality
    2. Shared primary_entity + categories overlap + recency
    3. Same primary_category fallback
    """
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    seen_ids: set[UUID] = {article_id}
    related: list[Article] = []

    # --- Strategy 1: Vector similarity ---
    from sqlalchemy import text

    embedding_result = await db.execute(
        text(
            "SELECT embedding FROM document_embeddings "
            "WHERE source_type = 'article' AND source_id = :source_id "
            "ORDER BY chunk_index LIMIT 1"
        ),
        {"source_id": str(article_id)},
    )
    embedding_row = embedding_result.fetchone()

    if embedding_row and embedding_row[0] is not None:
        vector_result = await db.execute(
            text(
                "SELECT de.source_id "
                "FROM document_embeddings de "
                "WHERE de.source_type = 'article' "
                "  AND de.source_id != :self_id "
                "  AND de.chunk_index = 0 "
                "ORDER BY de.embedding <=> :target_embedding "
                "LIMIT :lim"
            ),
            {
                "self_id": str(article_id),
                "target_embedding": str(embedding_row[0]),
                "lim": limit,
            },
        )
        vector_ids = [row[0] for row in vector_result.fetchall()]

        if vector_ids:
            articles_result = await db.execute(
                select(Article).where(Article.id.in_(vector_ids))
            )
            for a in articles_result.scalars().all():
                if a.id not in seen_ids:
                    related.append(a)
                    seen_ids.add(a.id)

    # --- Strategy 2: Entity + Category matching ---
    remaining = limit - len(related)
    if remaining > 0 and (article.primary_entity or article.categories):
        conditions = [Article.id.notin_(seen_ids)]

        # Build OR conditions for entity/category match
        or_parts = []
        params: dict = {}

        if article.primary_entity:
            entity_q = text(
                "SELECT a.* FROM articles a "
                "WHERE a.id NOT IN (SELECT unnest(:seen)) "
                "  AND ((a.primary_entity = :entity AND a.primary_entity IS NOT NULL) "
                "       OR (a.categories && :cats)) "
                "ORDER BY "
                "  CASE WHEN a.primary_entity = :entity THEN 1 ELSE 0 END DESC, "
                "  a.published_at DESC NULLS LAST "
                "LIMIT :lim"
            )
            entity_result = await db.execute(
                entity_q,
                {
                    "seen": list(str(sid) for sid in seen_ids),
                    "entity": article.primary_entity,
                    "cats": article.categories or [],
                    "lim": remaining,
                },
            )
            from sqlalchemy.orm import Session

            for row in entity_result.fetchall():
                a_id = row[0]
                if a_id not in seen_ids:
                    # Fetch full ORM object
                    a_result = await db.execute(
                        select(Article).where(Article.id == a_id)
                    )
                    a_obj = a_result.scalar_one_or_none()
                    if a_obj:
                        related.append(a_obj)
                        seen_ids.add(a_id)
        elif article.categories:
            cat_q = text(
                "SELECT id FROM articles "
                "WHERE id NOT IN (SELECT unnest(:seen)) "
                "  AND categories && :cats "
                "ORDER BY published_at DESC NULLS LAST "
                "LIMIT :lim"
            )
            cat_result = await db.execute(
                cat_q,
                {
                    "seen": list(str(sid) for sid in seen_ids),
                    "cats": article.categories,
                    "lim": remaining,
                },
            )
            for row in cat_result.fetchall():
                a_id = row[0]
                if a_id not in seen_ids:
                    a_result = await db.execute(
                        select(Article).where(Article.id == a_id)
                    )
                    a_obj = a_result.scalar_one_or_none()
                    if a_obj:
                        related.append(a_obj)
                        seen_ids.add(a_id)

    # --- Strategy 3: Same primary_category fallback ---
    remaining = limit - len(related)
    if remaining > 0 and article.primary_category:
        fallback_result = await db.execute(
            select(Article)
            .where(
                Article.id.notin_(seen_ids),
                Article.primary_category == article.primary_category,
            )
            .order_by(Article.published_at.desc().nullslast())
            .limit(remaining)
        )
        for a in fallback_result.scalars().all():
            if a.id not in seen_ids:
                related.append(a)
                seen_ids.add(a.id)

    return [_to_response(a) for a in related[:limit]]


def _to_response(article: Article, feed_title: str | None = None) -> ArticleResponse:
    """Convert ORM Article to response schema."""
    # Derive source_name: extract from "Title - Source" pattern, fallback to feed title
    source_name = None
    if article.title and " - " in article.title:
        source_name = article.title.rsplit(" - ", 1)[-1].strip()
    if not source_name:
        source_name = feed_title

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
        story_id=article.story_id,
        source_name=source_name,
        authors=article.authors if isinstance(article.authors, list) else None,
        top_image=article.top_image,
        word_count=article.word_count,
        created_at=article.created_at,
    )

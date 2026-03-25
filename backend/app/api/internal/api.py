"""Internal API — for machine consumers like WebStock.

Authenticated via X-API-Key header against api_consumers table.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.api_consumer import ApiConsumer
from app.models.article import Article
from app.schemas.base import CamelModel

router = APIRouter(prefix="/internal", tags=["internal"])


async def verify_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiConsumer:
    """Validate API key against api_consumers table.

    Hashes the provided key with SHA-256 and looks up the consumer.
    Updates last_used_at on success.
    """
    raw_key = request.headers.get("X-API-Key")
    if not raw_key:
        raise HTTPException(status_code=401, detail="X-API-Key required")

    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    result = await db.execute(
        select(ApiConsumer).where(
            ApiConsumer.api_key == key_hash,
            ApiConsumer.is_active.is_(True),
        )
    )
    consumer = result.scalar_one_or_none()

    if consumer is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    # Update last_used_at (non-blocking, committed with request session)
    await db.execute(
        update(ApiConsumer)
        .where(ApiConsumer.id == consumer.id)
        .values(last_used_at=datetime.now(timezone.utc))
    )

    return consumer


@router.get("/articles/recent")
async def recent_articles(
    since: datetime | None = Query(None),
    category: str | None = Query(None),
    has_market_impact: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get recent articles for consumers like WebStock.

    Supports filtering by category, market impact, and time range.
    """
    query = select(Article).order_by(Article.published_at.desc().nullslast()).limit(limit)

    if since:
        query = query.where(Article.published_at >= since)
    if category:
        query = query.where(Article.primary_category == category)
    if has_market_impact is not None:
        query = query.where(Article.has_market_impact == has_market_impact)

    result = await db.execute(query)
    articles = result.scalars().all()

    return [_to_internal_response(a) for a in articles]


@router.get("/sentiment/batch")
async def sentiment_batch(
    symbols: str = Query(..., description="Comma-separated symbols"),
    days: int = Query(30, ge=1, le=90),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Batch sentiment data for WebStock ML features.

    Returns sentiment scores grouped by symbol.
    """
    from datetime import timedelta
    from sqlalchemy import func, text

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    results: dict[str, Any] = {}
    for symbol in symbol_list:
        # Find articles with this symbol in finance_metadata.symbols
        query = (
            select(
                func.avg(Article.sentiment_score).label("avg_score"),
                func.count(Article.id).label("count"),
            )
            .where(
                Article.finance_metadata["symbols"].astext.contains(symbol),
                Article.published_at >= cutoff,
                Article.sentiment_score.is_not(None),
            )
        )
        row = (await db.execute(query)).one()
        results[symbol] = {
            "avg_sentiment": round(row.avg_score, 4) if row.avg_score else None,
            "article_count": row.count,
        }

    return results


@router.post("/embeddings/search")
async def embedding_search(
    request: Request,
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search — WebStock RAG integration."""
    body = await request.json()
    query_text = body.get("query", "")
    symbol = body.get("symbol")
    top_k = body.get("top_k", 5)

    from app.services.embedding_service import semantic_search

    results = await semantic_search(db, query=query_text, top_k=top_k, source_type="article", symbol=symbol)
    return [{"source_id": r.source_id, "chunk_text": r.chunk_text, "similarity": r.similarity} for r in results]


def _to_internal_response(article: Article) -> dict:
    """Simplified response for internal consumers."""
    return {
        "id": str(article.id),
        "title": article.title,
        "url": article.url,
        "published_at": str(article.published_at) if article.published_at else None,
        "primary_category": article.primary_category,
        "categories": article.categories,
        "has_market_impact": article.has_market_impact,
        "market_impact_hint": article.market_impact_hint,
        "sentiment_score": article.sentiment_score,
        "sentiment_label": article.sentiment_label,
        "ai_summary": article.ai_summary,
        "detailed_summary": article.detailed_summary,
        "finance_metadata": article.finance_metadata,
        "entities": article.entities,
    }

"""Internal API — for machine consumers like WebStock.

Authenticated via X-API-Key header against api_consumers table.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import ARRAY, Text, func, or_, select, text, type_coerce, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.api_consumer import ApiConsumer
from app.models.article import Article
from app.models.watched_symbol import WatchedSymbol
from app.schemas.article import (
    ArticleStatusItem,
    IngestArticleResult,
    IngestRequest,
    IngestResponse,
    StatusResponse,
)
from app.schemas.base import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _escape_like(s: str) -> str:
    """Escape special ILIKE characters (%, _, \\) to prevent wildcard injection."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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


@router.get("/articles/list")
async def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    category: str | None = Query(None, description="Filter by primary_category slug"),
    market: str | None = Query(None, description="Filter by finance_metadata.market (lowercase: us, cn, hk)"),
    search: str | None = Query(None, description="Search in title (ILIKE)"),
    sentiment_tag: str | None = Query(None, description="Filter by finance_metadata.sentiment_tag"),
    since: datetime | None = Query(None, description="Articles published after this datetime"),
    sort_by: str = Query("published_at", description="Sort field: published_at or value_score"),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """List articles with optional filters — no required parameters.

    Designed for general article browsing (e.g., WebStock market news page)
    where no specific symbols are required, unlike /articles/feed.
    """
    base_query = select(Article)

    if category:
        base_query = base_query.where(Article.primary_category == category)
    if market:
        base_query = base_query.where(
            Article.finance_metadata["market"].astext == market.lower()
        )
    if search:
        escaped = _escape_like(search)
        base_query = base_query.where(Article.title.ilike(f"%{escaped}%"))
    if sentiment_tag:
        base_query = base_query.where(
            Article.finance_metadata["sentiment_tag"].astext == sentiment_tag
        )
    if since:
        base_query = base_query.where(Article.published_at >= since)

    # Count total matching articles
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Sort order
    if sort_by == "value_score":
        order_clause = Article.value_score.desc().nullslast()
    else:
        order_clause = Article.published_at.desc().nullslast()

    # Paginated results
    offset = (page - 1) * page_size
    data_query = (
        base_query
        .order_by(order_clause)
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(data_query)
    articles = result.scalars().all()

    return {
        "items": [_to_enriched_response(a) for a in articles],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


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
    Uses a single query with jsonb_array_elements_text to avoid N+1.
    """
    from datetime import timedelta
    from sqlalchemy import bindparam, literal_column

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Single query: unnest finance_metadata->'symbols' array, filter by
    # requested symbols using the JSONB ?| operator for the initial filter,
    # then group by the unnested symbol value.
    #
    # The ?| operator uses the GIN index on finance_metadata for efficient
    # pre-filtering, then jsonb_array_elements_text expands for grouping.
    symbols_filter = text(
        "articles.finance_metadata->'symbols' ?| :symbol_arr"
    ).bindparams(bindparam("symbol_arr", value=symbol_list, type_=ARRAY(Text)))

    symbol_col = func.jsonb_array_elements_text(
        Article.finance_metadata["symbols"]
    ).label("symbol")

    # CTE: pre-filter articles that contain any of the requested symbols
    cte = (
        select(
            symbol_col,
            Article.sentiment_score,
        )
        .where(
            symbols_filter,
            Article.published_at >= cutoff,
            Article.sentiment_score.is_not(None),
        )
        .cte("matched")
    )

    # Aggregate per symbol, filtering to only the requested symbols
    # (jsonb_array_elements_text may produce symbols we did not ask for)
    query = (
        select(
            cte.c.symbol,
            func.avg(cte.c.sentiment_score).label("avg_score"),
            func.count().label("count"),
        )
        .where(cte.c.symbol.in_(symbol_list))
        .group_by(cte.c.symbol)
    )

    rows = (await db.execute(query)).all()

    # Build result dict, including symbols with zero matches
    results: dict[str, Any] = {
        s: {"avg_sentiment": None, "article_count": 0}
        for s in symbol_list
    }
    for row in rows:
        results[row.symbol] = {
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


@router.post("/articles/ingest")
async def ingest_articles(
    body: IngestRequest,
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Ingest articles from external consumers like WebStock."""
    from app.pipeline.dedup import DedupEngine
    from app.db.redis import get_redis

    logger.info("Ingest request from consumer '%s': %d articles", consumer.name, len(body.articles))

    if len(body.articles) > 50:
        raise HTTPException(status_code=422, detail="Maximum 50 articles per request")

    redis = await get_redis()
    dedup = DedupEngine(redis)

    results = []
    new_count = 0
    dup_count = 0
    err_count = 0
    enqueue_jobs: list[dict] = []

    for art in body.articles:
        try:
            # Dedup check
            is_dup, norm_url, detected_lang = await dedup.is_duplicate(art.url, art.title)
            if is_dup:
                # Check if we already have this article and return its ID
                existing = await db.execute(
                    select(Article).where(Article.url == norm_url).limit(1)
                )
                existing_article = existing.scalar_one_or_none()
                results.append(IngestArticleResult(
                    url=art.url,
                    article_id=str(existing_article.id) if existing_article else None,
                    external_id=art.external_id,
                    status="duplicate",
                ))
                dup_count += 1
                continue

            # Build finance_metadata seed
            finance_meta = {"ingested_by": consumer.name}
            if art.symbol:
                finance_meta["symbols"] = [art.symbol]
            if art.market:
                finance_meta["market"] = art.market.lower()

            # Insert article with SAVEPOINT for per-article isolation
            article_id = uuid.uuid4()
            source_name = art.source_name or art.provider or consumer.name
            article = Article(
                id=article_id,
                external_id=art.external_id,
                source_name=source_name,
                title=art.title,
                url=norm_url,
                published_at=art.published_at,
                language=art.language or detected_lang,
                summary=art.summary,
                top_image=art.image_url,
                finance_metadata=finance_meta,
                content_status="pending",
            )
            try:
                async with db.begin_nested():
                    db.add(article)
                    await db.flush()
            except Exception as e:
                logger.debug("Flush failed for %s: %s", art.url[:80], e)
                results.append(IngestArticleResult(
                    url=art.url, external_id=art.external_id,
                    status="duplicate",
                ))
                dup_count += 1
                continue

            # Collect enqueue jobs — will be sent AFTER commit
            enqueue_jobs.append({
                "article_id": str(article_id),
                "url": norm_url,
                "title": art.title,
                "summary": art.summary or "",
                "language": art.language,
                "source_name": art.source_name or art.provider or consumer.name,
            })

            results.append(IngestArticleResult(
                url=art.url,
                article_id=str(article_id),
                external_id=art.external_id,
                status="new",
            ))
            new_count += 1

        except Exception as e:
            logger.exception("Ingest error for %s", art.url[:80])
            results.append(IngestArticleResult(
                url=art.url, external_id=art.external_id,
                status="error", error=str(e)[:200],
            ))
            err_count += 1

    await db.commit()

    # Enqueue for pipeline AFTER commit to prevent ghost queue entries
    from app.pipeline import queue as q
    for job in enqueue_jobs:
        await q.enqueue_article(redis, job, priority="low")

    return IngestResponse(
        total=len(body.articles),
        new_count=new_count,
        duplicate_count=dup_count,
        error_count=err_count,
        results=results,
    )


@router.get("/articles/status")
async def article_status(
    article_ids: str = Query(..., description="Comma-separated article UUIDs"),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Check pipeline processing status for articles."""
    from app.db.redis import get_redis
    from app.pipeline.queue import ARTICLE_META

    ids = [s.strip() for s in article_ids.split(",") if s.strip()][:100]
    redis = await get_redis()
    items = []

    for aid in ids:
        # Try Redis first (in-flight tracking)
        meta = await redis.hgetall(ARTICLE_META.format(aid))
        if meta:
            # Decode bytes if needed
            meta = {
                (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                for k, v in meta.items()
            }
            items.append(ArticleStatusItem(
                article_id=aid,
                status=meta.get("status", "queued"),
                current_stage=meta.get("stage"),
                enqueued_at=meta.get("enqueued_at"),
                completed_at=meta.get("completed_at"),
                error=meta.get("error"),
            ))
        else:
            # Fallback to DB
            result = await db.execute(
                select(Article.content_status).where(Article.id == aid)
            )
            row = result.scalar_one_or_none()
            if row is None:
                items.append(ArticleStatusItem(article_id=aid, status="not_found"))
            else:
                status_map = {
                    "pending": "queued",
                    "processed": "completed",
                    "embedded": "completed",
                    "fetched": "processing",
                    "partial": "completed",
                    "failed": "failed",
                    "fetch_failed": "failed",
                }
                items.append(ArticleStatusItem(
                    article_id=aid,
                    status=status_map.get(row, "processing"),
                ))

    return StatusResponse(results=items)


@router.get("/articles/results")
async def article_results(
    article_ids: str | None = Query(None, description="Comma-separated UUIDs"),
    since: datetime | None = Query(None),
    consumer_name: str | None = Query(None),
    include_full_text: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get enriched article results for external consumers."""
    query = select(Article).order_by(Article.published_at.desc().nullslast()).limit(limit)

    if article_ids:
        ids = [s.strip() for s in article_ids.split(",") if s.strip()][:100]
        query = select(Article).where(Article.id.in_(ids))
    else:
        # Filter by consumer's ingested articles
        filter_name = consumer_name or consumer.name
        query = query.where(
            Article.finance_metadata["ingested_by"].astext == filter_name
        )
        if since:
            query = query.where(Article.published_at >= since)

    result = await db.execute(query)
    articles = result.scalars().all()

    return [_to_enriched_response(a, include_full_text) for a in articles]


@router.get("/articles/by-symbol")
async def articles_by_symbol(
    symbol: str = Query(..., description="Stock symbol to search for"),
    limit: int = Query(20, ge=1, le=100),
    since: datetime | None = Query(None),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get articles related to a stock symbol via finance_metadata.symbols.

    Queries the JSONB `finance_metadata->'symbols'` array using the PostgreSQL
    `?` (contains element) operator for exact symbol matching.
    """
    # Use the JSONB ? operator for exact array element matching
    symbol_filter = text(
        "articles.finance_metadata->'symbols' ? :symbol"
    ).bindparams(symbol=symbol.strip().upper())

    query = select(Article).where(symbol_filter)

    if since:
        query = query.where(Article.published_at >= since)

    query = query.order_by(Article.published_at.desc().nullslast()).limit(limit)

    result = await db.execute(query)
    articles = result.scalars().all()

    return [_to_enriched_response(a) for a in articles]


@router.get("/articles/feed")
async def articles_feed(
    symbols: str = Query(..., description="Comma-separated stock symbols"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    sentiment_tag: str | None = Query(None, description="Filter by finance_metadata.sentiment_tag"),
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get a paginated feed of articles matching any of the provided symbols.

    Uses PostgreSQL JSONB `?|` (has any of) operator on finance_metadata->'symbols'.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=422, detail="At least one symbol is required")

    # Base filter: finance_metadata->'symbols' has any of the provided symbols
    # The ?| operator requires the RHS to be a PostgreSQL text[] array.
    # Use type_coerce to cast the Python list to ARRAY(Text) so asyncpg
    # sends the correct parameter type.
    from sqlalchemy import bindparam
    symbols_filter = text(
        "articles.finance_metadata->'symbols' ?| :symbol_arr"
    ).bindparams(bindparam("symbol_arr", value=symbol_list, type_=ARRAY(Text)))

    base_query = select(Article).where(symbols_filter)

    if sentiment_tag:
        base_query = base_query.where(
            Article.finance_metadata["sentiment_tag"].astext == sentiment_tag
        )

    # Count total matching articles
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginated results
    offset = (page - 1) * page_size
    data_query = (
        base_query
        .order_by(Article.published_at.desc().nullslast())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(data_query)
    articles = result.scalars().all()

    return {
        "items": [_to_enriched_response(a) for a in articles],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/articles/search")
async def search_articles(
    q: str,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    category: str | None = None,
    since: datetime | None = None,
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Full-text search articles by title or content (ILIKE).

    Supports optional category and time range filters.
    """
    pattern = f"%{_escape_like(q)}%"
    query = (
        select(Article)
        .where(
            or_(
                Article.title.ilike(pattern),
                Article.full_text.ilike(pattern),
            )
        )
        .order_by(Article.published_at.desc().nullslast())
    )

    if category:
        query = query.where(Article.primary_category == category)
    if since:
        query = query.where(Article.published_at >= since)

    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    articles = result.scalars().all()

    return {
        "items": [_to_enriched_response(a) for a in articles],
        "count": len(articles),
        "offset": offset,
        "limit": limit,
    }


@router.get("/articles/{article_id}")
async def get_article(
    article_id: str,
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Get a single article by its ID."""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return _to_enriched_response(article, include_full_text=True)


@router.get("/articles/{article_id}/analysis/stream")
async def stream_analysis(
    article_id: str,
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Stream article AI analysis as Server-Sent Events (SSE).

    Sends the ai_analysis field in chunks for progressive rendering.
    """
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    async def _generate():
        analysis = article.ai_analysis
        if not analysis:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No analysis available for this article'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Send metadata first
        yield f"data: {json.dumps({'type': 'meta', 'article_id': str(article.id), 'title': article.title})}\n\n"

        # Stream analysis in chunks (~200 chars per chunk, split on paragraph boundaries)
        chunk_size = 200
        pos = 0
        while pos < len(analysis):
            # Try to break at a paragraph or sentence boundary
            end = min(pos + chunk_size, len(analysis))
            if end < len(analysis):
                # Look for paragraph break first
                para_break = analysis.rfind("\n", pos, end)
                if para_break > pos:
                    end = para_break + 1
                else:
                    # Look for sentence break
                    for sep in (". ", "。", "! ", "? "):
                        sent_break = analysis.rfind(sep, pos, end)
                        if sent_break > pos:
                            end = sent_break + len(sep)
                            break

            chunk = analysis[pos:end]
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            pos = end
            await asyncio.sleep(0.02)  # Small delay for streaming effect

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class WatchedSymbolItem(CamelModel):
    """One symbol in a watched-symbols sync payload.

    For bare 6-digit A-share codes (e.g. "600519"), the caller MUST send
    `market="sh"` or `market="sz"` — otherwise StockPulse's auto-detection
    will treat them as US tickers and akshare/tushare won't run.
    """
    symbol: str
    market: str | None = None
    last_viewed_at: datetime | None = None


class WatchedSymbolsSyncRequest(CamelModel):
    symbols: list[WatchedSymbolItem]


class WatchedSymbolsSyncResponse(CamelModel):
    received: int
    upserted: int
    removed: int = 0
    consumer: str


@router.post("/watched-symbols/sync", response_model=WatchedSymbolsSyncResponse)
async def sync_watched_symbols(
    body: WatchedSymbolsSyncRequest,
    consumer: ApiConsumer = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Upsert the consumer's full watchlist of symbols.

    Idempotent: caller sends the full current set on every sync. We upsert
    by (symbol, market) and bump `last_viewed_at` to the max of the existing
    and incoming value so that a symbol staying viewed keeps its hot tier.

    NewsForge's StockPulse poller reads from this table to drive per-symbol
    fetches, tiered hot/warm/cold by `last_viewed_at`.
    """
    if not body.symbols:
        return WatchedSymbolsSyncResponse(
            received=0, upserted=0, consumer=consumer.name,
        )

    if len(body.symbols) > 5000:
        raise HTTPException(
            status_code=422,
            detail="Maximum 5000 symbols per sync; split into multiple calls",
        )

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for it in body.symbols:
        sym = (it.symbol or "").strip().upper()
        if not sym:
            continue
        market = (it.market or "").strip().lower()
        key = (sym, market)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "symbol": sym[:32],
            "market": market,
            "registered_by": consumer.name[:64],
            "last_viewed_at": it.last_viewed_at,
        })

    if not rows:
        # Consumer sent an empty list — remove all its subscriptions.
        await db.execute(
            text("DELETE FROM watched_symbols WHERE registered_by = :name"),
            {"name": consumer.name},
        )
        await db.commit()
        return WatchedSymbolsSyncResponse(
            received=len(body.symbols), upserted=0, removed=0, consumer=consumer.name,
        )

    # Upsert per (symbol, market, consumer).
    # Each consumer owns its own rows; last_viewed_at only bumps for THIS
    # consumer, so two consumers watching the same ticker have independent
    # freshness tracking.
    stmt = text(
        """
        INSERT INTO watched_symbols
            (symbol, market, registered_by, last_viewed_at)
        VALUES
            (:symbol, :market, :registered_by, :last_viewed_at)
        ON CONFLICT (symbol, market, registered_by) DO UPDATE SET
            last_viewed_at = GREATEST(
                watched_symbols.last_viewed_at,
                EXCLUDED.last_viewed_at
            ),
            updated_at = NOW()
        """
    )
    for row in rows:
        await db.execute(stmt, row)

    # Full-sync cleanup: remove rows this consumer previously registered
    # but did NOT include in the current payload (i.e. user unsubscribed).
    incoming_keys = {(r["symbol"], r["market"]) for r in rows}
    existing = (await db.execute(
        text(
            "SELECT id, symbol, market FROM watched_symbols "
            "WHERE registered_by = :name"
        ),
        {"name": consumer.name},
    )).all()
    stale_ids = [
        r.id for r in existing
        if (r.symbol, r.market) not in incoming_keys
    ]
    removed = 0
    if stale_ids:
        await db.execute(
            text("DELETE FROM watched_symbols WHERE id = ANY(:ids)"),
            {"ids": stale_ids},
        )
        removed = len(stale_ids)

    await db.commit()

    return WatchedSymbolsSyncResponse(
        received=len(body.symbols),
        upserted=len(rows),
        removed=removed,
        consumer=consumer.name,
    )


def _to_enriched_response(article: Article, include_full_text: bool = False) -> dict:
    """Full enriched response for external consumers."""
    # Use persisted source_name first, then fallback to finance_metadata.ingested_by
    source_name = article.source_name
    if not source_name:
        fm = article.finance_metadata or {}
        source_name = fm.get("ingested_by")

    resp = {
        "id": str(article.id),
        "external_id": article.external_id,
        "title": article.title,
        "url": article.url,
        "published_at": str(article.published_at) if article.published_at else None,
        "source_name": source_name,
        "summary": article.summary,
        "primary_category": article.primary_category,
        "categories": article.categories or [],
        "tags": article.tags or [],
        "value_score": article.value_score,
        "has_market_impact": article.has_market_impact,
        "market_impact_hint": article.market_impact_hint,
        "ai_summary": article.ai_summary,
        "detailed_summary": article.detailed_summary,
        "ai_analysis": article.ai_analysis,
        "title_zh": article.title_zh,
        "full_text_zh": article.full_text_zh,
        "entities": article.entities or [],
        "primary_entity": article.primary_entity,
        "primary_entity_type": article.primary_entity_type,
        "sentiment_score": article.sentiment_score,
        "sentiment_label": article.sentiment_label,
        "finance_metadata": article.finance_metadata or {},
        "content_status": article.content_status,
        "agents_executed": article.agents_executed or [],
        "processing_path": article.processing_path,
    }
    if include_full_text:
        resp["full_text"] = article.full_text
    return resp


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

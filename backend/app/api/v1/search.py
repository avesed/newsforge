"""Search endpoints — hybrid GIN trigram + pgvector RRF fusion, external search, import.

Three search modes:
- hybrid: trigram text match + vector semantic search, fused via RRF (k=60)
- text_only: fallback when embedding service is unavailable
- semantic_only: fallback when trigram returns no results but vectors do
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from uuid import UUID

import feedparser
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import EmbedRequest
from app.db.database import get_db
from app.db.redis import get_redis
from app.models.user import User
from app.pipeline.queue import enqueue_article
from app.schemas.article import ArticleResponse
from app.schemas.base import CamelModel
from app.sources.rss.google_news import build_search_url, resolve_urls_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

# RRF fusion constant (standard value from the original RRF paper)
RRF_K = 60


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SearchResponse(CamelModel):
    articles: list[ArticleResponse]
    total: int
    page: int
    page_size: int
    has_more: bool
    search_mode: str  # "hybrid", "text_only", "semantic_only"
    query_time_ms: float


class SuggestionItem(CamelModel):
    title: str
    article_id: UUID
    score: float


class SuggestResponse(CamelModel):
    suggestions: list[SuggestionItem]


class ExternalSearchResult(CamelModel):
    title: str
    url: str
    source_name: str
    published_at: datetime | None = None
    summary: str | None = None
    provider: str  # "google_news" or "tavily"


class ExternalSearchResponse(CamelModel):
    results: list[ExternalSearchResult]
    total: int
    query_time_ms: float


class ImportRequest(CamelModel):
    urls: list[str]


class ImportResponse(CamelModel):
    imported: int
    article_ids: list[UUID]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_filter_clause(
    *,
    category: str | None,
    categories: str | None,
    language: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    has_market_impact: bool | None,
    sentiment_min: float | None,
    sentiment_max: float | None,
    source: str | None,
) -> tuple[str, dict]:
    """Build a SQL WHERE clause fragment and params from filter parameters.

    Returns (clause_str, params_dict). clause_str starts with "AND ..." if any
    filters are present, or is empty string.
    """
    clauses: list[str] = []
    params: dict = {}

    if category:
        clauses.append("a.primary_category = :f_category")
        params["f_category"] = category

    if categories:
        cat_list = [c.strip() for c in categories.split(",") if c.strip()]
        if cat_list:
            clauses.append("a.categories && :f_categories")
            params["f_categories"] = cat_list

    if language:
        clauses.append("a.language = :f_language")
        params["f_language"] = language

    if date_from:
        clauses.append("a.published_at >= :f_date_from")
        params["f_date_from"] = date_from

    if date_to:
        clauses.append("a.published_at <= :f_date_to")
        params["f_date_to"] = date_to

    if has_market_impact is not None:
        clauses.append("a.has_market_impact = :f_market_impact")
        params["f_market_impact"] = has_market_impact

    if sentiment_min is not None:
        clauses.append("a.sentiment_score >= :f_sent_min")
        params["f_sent_min"] = sentiment_min

    if sentiment_max is not None:
        clauses.append("a.sentiment_score <= :f_sent_max")
        params["f_sent_max"] = sentiment_max

    if source:
        clauses.append("a.source_id::text = :f_source")
        params["f_source"] = source

    clause_str = ""
    if clauses:
        clause_str = " AND " + " AND ".join(clauses)

    return clause_str, params


def _to_response_from_row(row) -> ArticleResponse:
    """Convert a raw SQL row (with named columns) to ArticleResponse."""
    return ArticleResponse(
        id=row.id,
        title=row.title,
        url=row.url,
        published_at=row.published_at,
        language=row.language,
        primary_category=row.primary_category,
        categories=row.categories,
        value_score=row.value_score,
        has_market_impact=row.has_market_impact,
        summary=row.summary,
        ai_summary=row.ai_summary,
        title_zh=getattr(row, "title_zh", None),
        sentiment_score=row.sentiment_score,
        sentiment_label=row.sentiment_label,
        content_status=row.content_status,
        top_image=row.top_image,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# GET /search — Hybrid search (GIN trigram + pgvector RRF fusion)
# ---------------------------------------------------------------------------

@router.get("", response_model=SearchResponse)
async def search_articles(
    q: str = Query(..., min_length=1),
    # Filters
    category: str | None = Query(None),
    categories: str | None = Query(None, description="Comma-separated category slugs"),
    language: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    has_market_impact: bool | None = Query(None),
    sentiment_min: float | None = Query(None, ge=-1, le=1),
    sentiment_max: float | None = Query(None, ge=-1, le=1),
    source: str | None = Query(None),
    # Sort & pagination
    sort: str = Query("relevance", pattern=r"^(relevance|date|value_score)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Hybrid search: GIN trigram text match + pgvector semantic search with RRF fusion."""
    start = time.monotonic()

    filter_clause, filter_params = _build_filter_clause(
        category=category,
        categories=categories,
        language=language,
        date_from=date_from,
        date_to=date_to,
        has_market_impact=has_market_impact,
        sentiment_min=sentiment_min,
        sentiment_max=sentiment_max,
        source=source,
    )

    # --- Path A: GIN trigram search ---
    trigram_sql = text(f"""
        SELECT a.id, a.title, a.title_zh, a.url, a.published_at, a.language,
               a.primary_category, a.categories, a.value_score,
               a.has_market_impact, a.summary, a.ai_summary,
               a.sentiment_score, a.sentiment_label, a.content_status,
               a.top_image, a.created_at,
               similarity(a.title, :q) + similarity(COALESCE(a.ai_summary, ''), :q) AS trgm_score
        FROM articles a
        WHERE (a.title % :q OR a.ai_summary % :q)
        {filter_clause}
        ORDER BY trgm_score DESC
        LIMIT 50
    """)

    trigram_params = {"q": q, **filter_params}
    trigram_result = await db.execute(trigram_sql, trigram_params)
    trigram_rows = trigram_result.fetchall()

    # Build ranked mapping: article_id -> (rank, row)
    trigram_ranked: dict[UUID, tuple[int, object]] = {}
    for rank, row in enumerate(trigram_rows):
        trigram_ranked[row.id] = (rank, row)

    # --- Path B: pgvector semantic search ---
    vector_ranked: dict[UUID, int] = {}
    search_mode = "text_only"

    try:
        gateway = get_llm_gateway()
        embed_response = await gateway.embed(EmbedRequest(texts=[q], dimensions=512))
        if embed_response.embeddings:
            query_vec = embed_response.embeddings[0]

            vector_sql = text("""
                SELECT source_id,
                       1 - (embedding <=> :vec::vector) AS vec_score
                FROM document_embeddings
                WHERE source_type = 'article'
                ORDER BY embedding <=> :vec::vector
                LIMIT 50
            """)
            vec_result = await db.execute(vector_sql, {"vec": str(query_vec)})
            vec_rows = vec_result.fetchall()

            for rank, row in enumerate(vec_rows):
                try:
                    article_id = UUID(row.source_id)
                    vector_ranked[article_id] = rank
                except (ValueError, TypeError):
                    continue

            if trigram_ranked:
                search_mode = "hybrid"
            else:
                search_mode = "semantic_only"
    except Exception:
        logger.warning("Embedding search failed, falling back to text-only", exc_info=True)

    # --- RRF Fusion ---
    all_ids = set(trigram_ranked.keys()) | set(vector_ranked.keys())

    scored_articles: list[tuple[float, UUID]] = []
    for article_id in all_ids:
        rrf_score = 0.0
        if article_id in trigram_ranked:
            rrf_score += 1.0 / (RRF_K + trigram_ranked[article_id][0])
        if article_id in vector_ranked:
            rrf_score += 1.0 / (RRF_K + vector_ranked[article_id])
        scored_articles.append((rrf_score, article_id))

    # Sort by chosen criterion
    if sort == "relevance":
        scored_articles.sort(key=lambda x: x[0], reverse=True)
    # For date/value_score sorting, we need the article data, so we fetch it below

    total = len(scored_articles)

    # Paginate
    offset = (page - 1) * page_size
    page_ids = scored_articles[offset : offset + page_size]

    if not page_ids:
        duration = (time.monotonic() - start) * 1000
        return SearchResponse(
            articles=[],
            total=total,
            page=page,
            page_size=page_size,
            has_more=False,
            search_mode=search_mode,
            query_time_ms=round(duration, 2),
        )

    # Fetch full article data for page results.
    # Articles from trigram path already have full data. For vector-only results, fetch from DB.
    articles_out: list[ArticleResponse] = []
    missing_ids: list[UUID] = []

    # Map article_id to its position for ordering
    id_order = {aid: idx for idx, (_, aid) in enumerate(page_ids)}

    for _, article_id in page_ids:
        if article_id in trigram_ranked:
            _, row = trigram_ranked[article_id]
            articles_out.append(_to_response_from_row(row))
        else:
            missing_ids.append(article_id)

    # Fetch any articles that were only in vector results
    if missing_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(missing_ids)))
        fetch_sql = text(f"""
            SELECT a.id, a.title, a.title_zh, a.url, a.published_at, a.language,
                   a.primary_category, a.categories, a.value_score,
                   a.has_market_impact, a.summary, a.ai_summary,
                   a.sentiment_score, a.sentiment_label, a.content_status,
                   a.top_image, a.created_at
            FROM articles a
            WHERE a.id IN ({placeholders})
        """)
        fetch_params = {f"id_{i}": str(mid) for i, mid in enumerate(missing_ids)}
        fetch_result = await db.execute(fetch_sql, fetch_params)
        fetched_rows = {row.id: row for row in fetch_result.fetchall()}

        for mid in missing_ids:
            row = fetched_rows.get(mid)
            if row:
                articles_out.append(_to_response_from_row(row))

    # Re-sort articles_out by the original fusion order
    articles_out.sort(key=lambda a: id_order.get(a.id, 999))

    # If sorting by date or value_score, re-sort the final list
    if sort == "date":
        articles_out.sort(key=lambda a: a.published_at or datetime.min, reverse=True)
    elif sort == "value_score":
        articles_out.sort(key=lambda a: a.value_score or 0, reverse=True)

    duration = (time.monotonic() - start) * 1000

    return SearchResponse(
        articles=articles_out,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
        search_mode=search_mode,
        query_time_ms=round(duration, 2),
    )


# ---------------------------------------------------------------------------
# GET /search/suggest — Autocomplete via trigram similarity
# ---------------------------------------------------------------------------

@router.get("/suggest", response_model=SuggestResponse)
async def search_suggest(
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Autocomplete suggestions using trigram similarity on article titles."""
    sql = text("""
        SELECT DISTINCT ON (title) id, title, similarity(title, :q) AS score
        FROM articles
        WHERE title % :q
        ORDER BY title, score DESC
        LIMIT :limit
    """)
    # Re-sort by score since DISTINCT ON forces ORDER BY title first
    # We wrap in a subquery
    sql = text("""
        SELECT id, title, score FROM (
            SELECT DISTINCT ON (title) id, title, similarity(title, :q) AS score
            FROM articles
            WHERE title % :q
            ORDER BY title, score DESC
        ) sub
        ORDER BY score DESC
        LIMIT :limit
    """)

    result = await db.execute(sql, {"q": q, "limit": limit})
    rows = result.fetchall()

    return SuggestResponse(
        suggestions=[
            SuggestionItem(title=row.title, article_id=row.id, score=round(row.score, 4))
            for row in rows
        ]
    )


# ---------------------------------------------------------------------------
# GET /search/external — External search (Google News RSS + Tavily)
# ---------------------------------------------------------------------------

@router.get("/external", response_model=ExternalSearchResponse)
async def search_external(
    q: str = Query(..., min_length=1),
    locale: str = Query("zh-CN"),
    limit: int = Query(20, ge=1, le=100),
    date_from: str | None = Query(None, description="YYYY-MM-DD or relative: 1h, 1d, 7d"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
):
    """Search external sources (Google News RSS, optionally Tavily).

    Time filtering via Google News search operators:
    - date_from/date_to as YYYY-MM-DD: uses after:/before: operators
    - date_from as relative (1h, 1d, 7d): uses when: operator
    """
    start = time.monotonic()
    results: list[ExternalSearchResult] = []

    # Build time-qualified query
    time_query = _build_time_query(q, date_from, date_to)

    # Run Google News and Tavily in parallel
    tasks: list[asyncio.Task] = []

    google_task = asyncio.create_task(_search_google_news(time_query, locale, limit))
    tasks.append(google_task)

    settings = get_settings()
    tavily_task = None
    if settings.tavily_api_key:
        tavily_task = asyncio.create_task(_search_tavily(q, limit, settings.tavily_api_key))
        tasks.append(tavily_task)

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    for result in gathered:
        if isinstance(result, list):
            results.extend(result)
        elif isinstance(result, Exception):
            logger.warning("External search error: %s", result)

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique_results: list[ExternalSearchResult] = []
    for r in results:
        if r.url not in seen_urls:
            seen_urls.add(r.url)
            unique_results.append(r)

    unique_results = unique_results[:limit]
    duration = (time.monotonic() - start) * 1000

    return ExternalSearchResponse(
        results=unique_results,
        total=len(unique_results),
        query_time_ms=round(duration, 2),
    )


def _build_time_query(q: str, date_from: str | None, date_to: str | None) -> str:
    """Append Google News time operators to search query.

    Supports:
    - date_from as YYYY-MM-DD → "q after:2026-03-15"
    - date_to as YYYY-MM-DD   → "q before:2026-03-20"
    - date_from as relative    → "q when:1d" / "q when:7d" / "q when:1h"
    - Both date_from + date_to → "q after:... before:..."
    """
    parts = [q]

    if date_from:
        # Check if it's a relative time (e.g., "1h", "1d", "7d")
        relative_match = re.match(r"^(\d+)([hd])$", date_from)
        if relative_match:
            parts.append(f"when:{date_from}")
        else:
            # Assume YYYY-MM-DD format
            parts.append(f"after:{date_from}")

    if date_to:
        parts.append(f"before:{date_to}")

    return " ".join(parts)


async def _search_google_news(q: str, locale: str, limit: int) -> list[ExternalSearchResult]:
    """Search Google News via RSS feed."""
    url = build_search_url(q, locale)

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        response = await client.get(url, headers={
            "User-Agent": "NewsForge/1.0 (RSS Reader)",
            "Accept": "application/rss+xml, application/xml, text/xml",
        })
        response.raise_for_status()

    parsed = feedparser.parse(response.text)
    results: list[ExternalSearchResult] = []

    for entry in parsed.entries[:limit]:
        title_raw = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title_raw or not link:
            continue

        # Google News title format: "Article Title - Source Name"
        source_name = ""
        title = title_raw
        if " - " in title_raw:
            parts = title_raw.rsplit(" - ", 1)
            title = parts[0].strip()
            source_name = parts[1].strip()

        if not source_name:
            source_name = entry.get("source", {}).get("title", "")

        published = None
        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                published = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                pass

        summary = None
        if entry.get("summary"):
            summary = re.sub(r"<[^>]+>", "", entry["summary"]).strip()[:500]

        results.append(ExternalSearchResult(
            title=title,
            url=link,
            source_name=source_name or "Google News",
            published_at=published,
            summary=summary,
            provider="google_news",
        ))

    return results


async def _search_tavily(q: str, limit: int, api_key: str) -> list[ExternalSearchResult]:
    """Search via Tavily API."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": q,
                "max_results": min(limit, 20),
                "search_depth": "basic",
                "include_answer": False,
            },
        )
        response.raise_for_status()
        data = response.json()

    results: list[ExternalSearchResult] = []
    for item in data.get("results", []):
        results.append(ExternalSearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            source_name=item.get("source", "Unknown"),
            published_at=None,  # Tavily doesn't always return dates
            summary=item.get("content", "")[:500] if item.get("content") else None,
            provider="tavily",
        ))

    return results


# ---------------------------------------------------------------------------
# POST /search/external/import — Import external articles into pipeline
# ---------------------------------------------------------------------------

@router.post("/external/import", response_model=ImportResponse)
async def import_external_articles(
    body: ImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import external articles by URL into the processing pipeline.

    For Google News URLs, resolves redirects to real source URLs first.
    Creates Article records with status 'pending' and enqueues for pipeline processing.
    """
    if not body.urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    if len(body.urls) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 URLs per import")

    # Separate Google News URLs from direct URLs
    google_urls: list[str] = []
    direct_urls: list[str] = []

    for url in body.urls:
        if "news.google.com" in url:
            google_urls.append(url)
        else:
            direct_urls.append(url)

    # Resolve Google News URLs in batch
    resolved_map: dict[str, str | None] = {}
    if google_urls:
        try:
            resolved_map = await resolve_urls_batch(google_urls, concurrency=5, timeout_ms=15000)
        except Exception:
            logger.exception("Failed to resolve Google News URLs")
            # Fall back to using Google URLs as-is
            resolved_map = {url: url for url in google_urls}

    # Build final URL list
    final_urls: list[str] = list(direct_urls)
    for gurl in google_urls:
        resolved = resolved_map.get(gurl)
        if resolved:
            final_urls.append(resolved)
        else:
            logger.warning("Could not resolve Google News URL, skipping: %s", gurl[:80])

    if not final_urls:
        return ImportResponse(imported=0, article_ids=[])

    # Check for existing articles (dedup by URL)
    import uuid as uuid_mod
    from sqlalchemy import select
    from app.models.article import Article

    existing_result = await db.execute(
        select(Article.url).where(Article.url.in_(final_urls))
    )
    existing_urls = {row[0] for row in existing_result.fetchall()}

    new_urls = [u for u in final_urls if u not in existing_urls]

    # Create Article records
    article_ids: list[UUID] = []
    redis = await get_redis()

    for url in new_urls:
        article_id = uuid_mod.uuid4()
        article = Article(
            id=article_id,
            title=url.split("/")[-1][:200] or "Imported article",  # Placeholder title
            url=url,
            content_status="pending",
        )
        db.add(article)
        article_ids.append(article_id)

        # Enqueue for pipeline processing
        await enqueue_article(redis, {
            "article_id": str(article_id),
            "url": url,
            "source": "manual_import",
        })

    await db.flush()

    return ImportResponse(
        imported=len(article_ids),
        article_ids=article_ids,
    )

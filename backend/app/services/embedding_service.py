"""Embedding service — semantic search via pgvector.

Provides vector search for articles, used by:
- Frontend search page
- WebStock internal API (RAG integration)
- Hybrid search RRF fusion
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import EmbedRequest

logger = logging.getLogger(__name__)

# Default reduced dimensions for search queries (matches pipeline embedding stage)
SEARCH_DIMENSIONS = 512


@dataclass
class SearchResult:
    source_id: str
    chunk_text: str
    similarity: float
    symbol: str | None = None


async def semantic_search(
    db: AsyncSession,
    query: str,
    top_k: int = 10,
    source_type: str | None = None,
    symbol: str | None = None,
    categories: list[str] | None = None,
) -> list[SearchResult]:
    """Search document embeddings using vector similarity.

    Args:
        query: Search query text
        top_k: Number of results to return
        source_type: Filter by source type (e.g., "article")
        symbol: Filter by stock symbol (for finance articles)
        categories: Filter by article categories (requires join with articles table)
    """
    gateway = get_llm_gateway()

    # Generate query embedding with reduced dimensions
    embed_response = await gateway.embed(
        EmbedRequest(texts=[query], dimensions=SEARCH_DIMENSIONS)
    )
    if not embed_response.embeddings:
        return []

    query_embedding = embed_response.embeddings[0]

    # Determine if we need to join with articles table (for category filtering)
    needs_article_join = bool(categories) and source_type == "article"

    # Build query
    filters: list[str] = []
    params: dict = {"embedding": str(query_embedding), "top_k": top_k}

    if source_type:
        filters.append("de.source_type = :source_type")
        params["source_type"] = source_type

    if symbol:
        filters.append("de.symbol = :symbol")
        params["symbol"] = symbol

    if needs_article_join and categories:
        filters.append("a.categories && :categories")
        params["categories"] = categories

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    if needs_article_join:
        sql = text(f"""
            SELECT de.source_id, de.chunk_text, de.symbol,
                   1 - (de.embedding <=> :embedding::vector) AS similarity
            FROM document_embeddings de
            JOIN articles a ON a.id::text = de.source_id
            {where_clause}
            ORDER BY de.embedding <=> :embedding::vector
            LIMIT :top_k
        """)
    else:
        sql = text(f"""
            SELECT de.source_id, de.chunk_text, de.symbol,
                   1 - (de.embedding <=> :embedding::vector) AS similarity
            FROM document_embeddings de
            {where_clause}
            ORDER BY de.embedding <=> :embedding::vector
            LIMIT :top_k
        """)

    result = await db.execute(sql, params)
    rows = result.fetchall()

    return [
        SearchResult(
            source_id=row.source_id,
            chunk_text=row.chunk_text,
            similarity=round(row.similarity, 4),
            symbol=row.symbol,
        )
        for row in rows
    ]

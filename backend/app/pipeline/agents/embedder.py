"""Embedding pipeline stage — generates a single vector embedding per article.

Embeds structured text combining title, summary, and cleaned content.
Runs as a pipeline stage (between clean and classify), NOT as an agent.
The embedding is used for semantic dedup and multi-source event grouping.
"""

from __future__ import annotations

import logging
import time

from app.core.config import load_pipeline_config
from app.core.llm.gateway import LLMGateway, get_llm_gateway
from app.core.llm.types import EmbedRequest

logger = logging.getLogger(__name__)


def _get_embedding_dimensions() -> int:
    """Read embedding_dimensions from pipeline.yml dedup config."""
    config = load_pipeline_config()
    return config.get("dedup", {}).get("embedding_dimensions", 512)


def build_embed_text(
    title: str,
    summary: str | None = None,
    cleaned_text: str | None = None,
) -> str:
    """Build structured text for embedding from pre-agent context.

    Uses title + source summary + cleaned article text (truncated).
    This runs before classification/agents, so no AI summary or entities.
    """
    parts: list[str] = [title]

    if summary:
        parts.append(summary)

    if cleaned_text:
        # Truncate to ~2000 chars to stay within token limits
        parts.append(cleaned_text[:2000])

    return "\n".join(parts)


async def generate_embedding(
    title: str,
    summary: str | None = None,
    cleaned_text: str | None = None,
    llm: LLMGateway | None = None,
) -> dict:
    """Generate embedding for an article.

    Returns dict with:
        - success: bool
        - embedding: list[float] | None
        - embed_text: str
        - tokens_used: int
        - duration_ms: float
        - model: str
        - error: str | None
    """
    start = time.monotonic()
    dimensions = _get_embedding_dimensions()

    embed_text = build_embed_text(title, summary, cleaned_text)
    if not embed_text.strip():
        return {
            "success": False,
            "embedding": None,
            "embed_text": "",
            "tokens_used": 0,
            "duration_ms": (time.monotonic() - start) * 1000,
            "model": "unknown",
            "error": "No text available for embedding",
        }

    if llm is None:
        llm = get_llm_gateway()

    try:
        response = await llm.embed(
            EmbedRequest(texts=[embed_text], dimensions=dimensions)
        )
        embedding = response.embeddings[0] if response.embeddings else None
        tokens_used = response.usage.total_tokens
        model = response.model
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        logger.exception("Embedding generation failed")
        return {
            "success": False,
            "embedding": None,
            "embed_text": embed_text,
            "tokens_used": 0,
            "duration_ms": duration,
            "model": "unknown",
            "error": f"Embedding failed: {e!s}"[:500],
        }

    duration = (time.monotonic() - start) * 1000
    return {
        "success": True,
        "embedding": embedding,
        "embed_text": embed_text,
        "tokens_used": tokens_used,
        "duration_ms": duration,
        "model": model,
        "error": None,
    }

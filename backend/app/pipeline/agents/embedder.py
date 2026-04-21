"""Embedder agent — generates a single vector embedding per article.

Embeds a structured text combining title, summary, entities, sectors, and
categories to capture both content semantics and structured metadata.
This produces richer vectors for related-article recommendation and search.
"""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.core.llm.types import EmbedRequest
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

# Embedding dimensions — use reduced dimensions for efficiency
EMBED_DIMENSIONS = 512


def _build_embed_text(context: AgentContext) -> str:
    """Build structured text for embedding from context + agent results.

    Combines: title, AI summary, financial entities, sectors, general
    entities, and categories. Keeps it concise to stay within token limits.
    """
    parts: list[str] = []

    # Title (always present)
    parts.append(context.title)

    # AI summary from summarizer > source summary
    ai_summary = None
    brief_result = context.agent_results.get("summarizer")
    if brief_result and brief_result.success:
        ai_summary = brief_result.data.get("ai_summary")
    summary = ai_summary or context.summary or ""
    if summary:
        parts.append(summary)

    # Financial entities + sectors from finance_analyzer
    fa_result = context.agent_results.get("finance_analyzer")
    if fa_result and fa_result.success:
        fa_data = fa_result.data
        fin_entities = fa_data.get("financial_entities", [])
        if fin_entities:
            names = [e["name"] for e in fin_entities if e.get("name")]
            if names:
                parts.append("相关公司: " + ", ".join(names))
        sectors = fa_data.get("sectors", [])
        if sectors:
            parts.append("板块: " + ", ".join(sectors))

    # General entities from entity agent
    entity_result = context.agent_results.get("entity")
    if entity_result and entity_result.success:
        entities = entity_result.data.get("entities", [])
        # Only add person-type entities not already covered by finance_analyzer
        person_names = [
            e["name"] for e in entities
            if e.get("type") == "person" and e.get("name")
        ]
        if person_names:
            parts.append("关键人物: " + ", ".join(person_names[:5]))

    # Categories
    if context.categories:
        parts.append("分类: " + ", ".join(context.categories))

    return "\n".join(parts)


class EmbedderAgent(AgentDefinition):
    """Generate a single vector embedding from structured article content."""

    agent_id = "embedder"
    name = "向量嵌入"
    description = "基于摘要+实体+板块+分类生成向量嵌入"
    phase = 3  # Post-processing phase — runs after all other agents
    requires = []
    input_fields = ["title", "ai_summary"]
    output_fields = ["chunks", "embeddings"]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        embed_text = _build_embed_text(context)

        if not embed_text.strip():
            duration = (time.monotonic() - start) * 1000
            return AgentResult(
                agent_id=self.agent_id,
                success=False,
                data={"chunks": [], "embeddings": [], "chunk_count": 0},
                duration_ms=duration,
                error="No text available for embedding",
            )

        try:
            embed_request = EmbedRequest(
                texts=[embed_text],
                dimensions=EMBED_DIMENSIONS,
            )
            embed_response = await llm.embed(embed_request)
            embeddings = embed_response.embeddings
            tokens_used = embed_response.usage.total_tokens
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.exception("Embedding generation failed for article %s", context.article_id)
            return AgentResult(
                agent_id=self.agent_id,
                success=False,
                data={"chunks": [embed_text], "embeddings": [], "chunk_count": 1},
                duration_ms=duration,
                error=f"Embedding failed: {e!s}"[:500],
            )

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={
                "chunks": [embed_text],
                "embeddings": embeddings,
                "chunk_count": 1,
                "embedding_dim": len(embeddings[0]) if embeddings else 0,
            },
            duration_ms=duration,
            tokens_used=tokens_used,
        )

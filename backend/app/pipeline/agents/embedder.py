"""Embedder agent — generates a single vector embedding per article from ai_summary.

Optimized approach: embed only the AI summary (not full text), producing one embedding
per article instead of multiple chunks. This reduces storage, cost, and search latency
while maintaining high semantic quality (summaries are distilled meaning).
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


class EmbedderAgent(AgentDefinition):
    """Generate a single vector embedding from the article's AI summary."""

    agent_id = "embedder"
    name = "向量嵌入"
    description = "基于AI摘要生成单一向量嵌入"
    phase = 3  # Post-processing phase
    requires = []
    input_fields = ["title", "ai_summary"]
    output_fields = ["chunks", "embeddings"]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        # Determine the best summary text to embed.
        # Priority: ai_summary (from summarizer) > source summary > title
        ai_summary = None
        brief_result = context.agent_results.get("summarizer")
        if brief_result and brief_result.success:
            ai_summary = brief_result.data.get("ai_summary")

        if ai_summary:
            embed_text = f"{context.title}. {ai_summary}"
        elif context.summary:
            embed_text = f"{context.title}. {context.summary}"
        else:
            embed_text = context.title

        if not embed_text.strip():
            duration = (time.monotonic() - start) * 1000
            return AgentResult(
                agent_id=self.agent_id,
                success=False,
                data={"chunks": [], "embeddings": [], "chunk_count": 0},
                duration_ms=duration,
                error="No text available for embedding",
            )

        # Generate a single embedding with reduced dimensions
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

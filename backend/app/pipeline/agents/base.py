"""Agent framework base — core abstractions for pipeline agents.

Each agent is a self-contained unit that:
1. Receives an AgentContext (article data + results from other agents)
2. Executes via LLM or computation
3. Returns an AgentResult with structured data

Agents declare their phase, dependencies, and required input/output fields.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.llm.gateway import LLMGateway, get_llm_gateway
from app.core.llm.types import ChatMessage, ChatRequest

logger = logging.getLogger(__name__)

# Shared system prompt for prefix-cache optimization: identical across all agents
# so the LLM provider can cache and reuse the KV-cache prefix for the same article.
SHARED_SYSTEM_PROMPT = "你是新闻分析专家，请按要求处理新闻。"


def strip_code_fence(content: str) -> str:
    """Strip leading/trailing ```json ... ``` markdown fences if present.

    Some models ignore response_format=json_object and wrap the JSON in a
    markdown code block. This helper makes json.loads tolerant of that.
    """
    s = content.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


@dataclass
class AgentContext:
    """Input context available to all agents."""

    article_id: str
    title: str
    summary: str | None
    full_text: str | None  # From content_fetcher (markdown)
    language: str | None
    categories: list[str]  # Category slugs from classifier
    has_market_impact: bool
    value_score: int = 0
    url: str | None = None
    # Results from other agents (filled as pipeline progresses)
    agent_results: dict[str, AgentResult] = field(default_factory=dict)

    @property
    def best_text(self) -> str:
        """Return the best available text for analysis (full_text > summary > title)."""
        if self.full_text and len(self.full_text) > 100:
            return self.full_text
        if self.summary and len(self.summary) > 20:
            return self.summary
        return self.title

    @property
    def short_text(self) -> str:
        """Return short text (summary > title) for lightweight agents."""
        if self.summary and len(self.summary) > 20:
            return f"标题: {self.title}\n摘要: {self.summary}"
        return f"标题: {self.title}"


@dataclass
class AgentResult:
    """Output from an agent execution."""

    agent_id: str
    success: bool
    data: dict[str, Any]
    duration_ms: float
    tokens_used: int = 0
    error: str | None = None


class AgentDefinition:
    """Base class for all pipeline agents.

    Subclasses must implement execute() and set class attributes:
    - agent_id: Unique identifier
    - name: Human-readable name
    - description: What this agent does
    - phase: Execution phase (0=classify, 1=content, 2=analysis, 3=post)
    - requires: List of agent_ids this depends on
    - input_fields: What context fields are needed
    - output_fields: What fields this agent produces
    """

    agent_id: str = ""
    name: str = ""
    description: str = ""
    phase: int = 2  # Default to analysis phase
    requires: list[str] = []
    input_fields: list[str] = []
    output_fields: list[str] = []

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        """Execute the agent. Must be overridden by subclasses."""
        raise NotImplementedError

    async def safe_execute(self, context: AgentContext) -> AgentResult:
        """Execute with error handling and timing. Never raises."""
        start = time.monotonic()
        try:
            llm = get_llm_gateway()
            result = await self.execute(context, llm)
            return result
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.exception("Agent %s failed for article %s", self.agent_id, context.article_id)
            return AgentResult(
                agent_id=self.agent_id,
                success=False,
                data={},
                duration_ms=duration,
                error=str(e)[:500],
            )

    async def _llm_json_call(
        self,
        llm: LLMGateway,
        system_prompt: str,
        user_content: str,
        purpose: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict, int]:
        """Helper: make an LLM call expecting JSON response.

        Returns (parsed_dict, total_tokens). Raises on failure.
        """
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_content),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        response = await llm.chat(request, purpose=purpose)
        try:
            data = json.loads(strip_code_fence(response.content))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Agent %s: JSON parse failed (purpose=%s): %s\nRaw response: %s",
                self.agent_id, purpose, e, response.content[:500],
            )
            raise
        return data, response.usage.total_tokens

    async def _llm_text_call(
        self,
        llm: LLMGateway,
        system_prompt: str,
        user_content: str,
        purpose: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, int]:
        """Helper: make an LLM call expecting text response.

        Returns (text_content, total_tokens).
        """
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_content),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await llm.chat(request, purpose=purpose)
        return response.content, response.usage.total_tokens

    # ------------------------------------------------------------------
    # Prefix-cache-optimized helpers
    # ------------------------------------------------------------------
    # These methods use a shared system prompt and a standardized article
    # block so that the LLM provider can reuse the KV-cache prefix when
    # multiple agents process the same article sequentially.
    # ------------------------------------------------------------------

    def _build_article_block(self, context: AgentContext) -> str:
        """Build a standardized article content block.

        The block is identical across all agents for the same article,
        maximizing prefix-cache hit rate on the LLM provider side.
        """
        body = context.full_text or context.summary or context.title
        return (
            f"标题: {context.title}\n"
            f"分类: {', '.join(context.categories)}\n"
            f"\n正文:\n{body}"
        )

    def _build_system_with_article(self, context: AgentContext) -> str:
        """Build system prompt with article block appended.

        By putting the article in the system message, the entire
        [system_prompt + article] prefix is byte-identical across all
        agents for the same article. This maximizes LLM prefix cache
        hits when agents execute sequentially.

        The user message then contains ONLY the task-specific prompt,
        which is the only part that differs between agents.
        """
        article_block = self._build_article_block(context)
        return f"{SHARED_SYSTEM_PROMPT}\n\n---\n\n{article_block}"

    async def _cached_json_call(
        self,
        llm: LLMGateway,
        context: AgentContext,
        task_prompt: str,
        purpose: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict, int]:
        """Prefix-cache-optimized LLM call expecting JSON response.

        System message = shared prompt + article (identical across agents).
        User message = task-specific prompt only (differs per agent).

        Returns (parsed_dict, total_tokens). Raises on failure.
        """
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=self._build_system_with_article(context)),
                ChatMessage(role="user", content=task_prompt),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        response = await llm.chat(request, purpose=purpose)
        try:
            data = json.loads(strip_code_fence(response.content))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Agent %s: JSON parse failed (purpose=%s): %s\nRaw response: %s",
                self.agent_id, purpose, e, response.content[:500],
            )
            raise
        return data, response.usage.total_tokens

    async def _cached_text_call(
        self,
        llm: LLMGateway,
        context: AgentContext,
        task_prompt: str,
        purpose: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, int]:
        """Prefix-cache-optimized LLM call expecting text response.

        Same prefix-cache strategy as _cached_json_call.

        Returns (text_content, total_tokens).
        """
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=self._build_system_with_article(context)),
                ChatMessage(role="user", content=task_prompt),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await llm.chat(request, purpose=purpose)
        return response.content, response.usage.total_tokens

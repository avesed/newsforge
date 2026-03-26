"""Story matcher agent — links articles to narrative-level storylines.

Phase 3 agent that runs after tagger (for story_hint) and embedder (for embedding).
Most matches are DB-only (no LLM call). LLM is only used for:
1. Gray-zone confirmation (vector similarity 0.65-0.75)
2. Creating new stories (generating title + description)
"""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult
from app.services.story_service import MIN_ARTICLES_FOR_STORY

logger = logging.getLogger(__name__)


class StoryMatcherAgent(AgentDefinition):
    """Match articles to existing stories or create new ones."""

    agent_id = "story_matcher"
    name = "故事线归类"
    description = "将新闻匹配到大事件故事线（如'2026美伊战争'），或创建新故事线"
    phase = 3
    requires = ["tagger", "embedder"]
    input_fields = ["title", "full_text"]
    output_fields = ["story_id", "story_title", "story_action"]

    _CONFIRM_PROMPT = """\
判断这篇新闻是否属于以下故事线。

故事线标题: {story_title}
新闻的故事线提示: {story_hint}

请判断这篇新闻是否确实属于该故事线，严格输出JSON：
{{"belongs": true/false, "reason": "简短理由"}}"""

    _CREATE_PROMPT = """\
基于这篇新闻创建一个新的故事线/大事件。

故事线提示: {story_hint}
故事类型: {story_type}

请生成故事线信息，严格输出JSON：
{{
  "title": "故事线标题（10-30字，简洁明确）",
  "description": "故事线概述（50-200字，说明事件背景和进展）",
  "key_entities": ["核心实体1", "核心实体2", ...],
  "categories": ["相关分类1", ...]
}}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        # Extract story_hint from tagger results
        tagger_result = context.agent_results.get("tagger")
        if not tagger_result or not tagger_result.success:
            return self._result(start, data={"story_action": "skip", "reason": "no tagger result"})

        story_hint = tagger_result.data.get("story_hint")
        if not story_hint:
            return self._result(start, data={"story_action": "skip", "reason": "no story_hint"})

        story_type = tagger_result.data.get("story_type", "other")

        # Extract embedding from embedder results
        embedder_result = context.agent_results.get("embedder")
        embedding = None
        if embedder_result and embedder_result.success:
            embeddings = embedder_result.data.get("embeddings", [])
            if embeddings and len(embeddings) > 0:
                embedding = embeddings[0]

        # Import here to avoid circular imports
        from app.services.story_service import (
            count_similar_pending_articles,
            create_story,
            find_matching_story,
            link_article_to_story,
            link_similar_pending_articles,
        )

        # Step 1: Try to find matching story
        match = await find_matching_story(story_hint, embedding)

        if match:
            match_type = match["match_type"]
            score = match["score"]

            # High confidence: direct link (no LLM)
            if match_type in ("text", "vector_high"):
                await link_article_to_story(
                    match["story_id"], context.article_id,
                    matched_by="direct", confidence=score,
                )
                duration = (time.monotonic() - start) * 1000
                return AgentResult(
                    agent_id=self.agent_id,
                    success=True,
                    data={
                        "story_id": match["story_id"],
                        "story_title": match["title"],
                        "story_action": "linked",
                        "match_type": match_type,
                        "confidence": round(score, 3),
                    },
                    duration_ms=duration,
                    tokens_used=0,
                )

            # Gray zone: LLM confirmation
            if match_type == "vector_gray":
                task_prompt = self._CONFIRM_PROMPT.format(
                    story_title=match["title"],
                    story_hint=story_hint,
                )
                try:
                    data, tokens = await self._cached_json_call(
                        llm, context, task_prompt, purpose="story_matcher",
                    )
                    if data.get("belongs"):
                        await link_article_to_story(
                            match["story_id"], context.article_id,
                            matched_by="llm_confirmed", confidence=score,
                        )
                        duration = (time.monotonic() - start) * 1000
                        return AgentResult(
                            agent_id=self.agent_id,
                            success=True,
                            data={
                                "story_id": match["story_id"],
                                "story_title": match["title"],
                                "story_action": "llm_confirmed",
                                "confidence": round(score, 3),
                            },
                            duration_ms=duration,
                            tokens_used=tokens,
                        )
                    else:
                        logger.info(
                            "LLM rejected match: '%s' != '%s' (%s)",
                            story_hint[:30], match["title"][:30], data.get("reason", ""),
                        )
                except Exception:
                    logger.warning("LLM confirm failed for story match", exc_info=True)

        # Step 2: No match — check if enough similar articles to create new story
        similar_count = await count_similar_pending_articles(story_hint, context.article_id)

        if similar_count >= (MIN_ARTICLES_FOR_STORY - 1):  # -1 because current article counts too
            # Create new story via LLM
            task_prompt = self._CREATE_PROMPT.format(
                story_hint=story_hint,
                story_type=story_type,
            )
            try:
                data, tokens = await self._cached_json_call(
                    llm, context, task_prompt, purpose="story_matcher",
                )
                story_id = await create_story(
                    title=data.get("title", story_hint),
                    description=data.get("description"),
                    story_type=story_type,
                    key_entities=data.get("key_entities"),
                    categories=data.get("categories") or context.categories,
                    embedding=embedding,
                    first_article_id=context.article_id,
                )
                # Also link other pending articles with similar hints
                linked = await link_similar_pending_articles(story_id, story_hint)

                duration = (time.monotonic() - start) * 1000
                return AgentResult(
                    agent_id=self.agent_id,
                    success=True,
                    data={
                        "story_id": story_id,
                        "story_title": data.get("title", story_hint),
                        "story_action": "created",
                        "linked_pending": linked,
                    },
                    duration_ms=duration,
                    tokens_used=tokens,
                )
            except Exception:
                logger.warning("Failed to create story for '%s'", story_hint[:30], exc_info=True)

        # No match, not enough articles — mark as pending
        return self._result(start, data={
            "story_action": "pending",
            "story_hint": story_hint,
            "similar_count": similar_count,
        })

    def _result(self, start: float, data: dict, tokens: int = 0) -> AgentResult:
        duration = (time.monotonic() - start) * 1000
        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data=data,
            duration_ms=duration,
            tokens_used=tokens,
        )

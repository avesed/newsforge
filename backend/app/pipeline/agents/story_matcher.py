"""Batch story matcher — groups articles into narrative storylines.

NOT an AgentDefinition (not per-article). Called by the agent worker
when processing a story group (group_type="story").
"""

from __future__ import annotations

import json
import logging
import time

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import ChatMessage, ChatRequest

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = "你是新闻事件分析专家，负责将新闻归类到大事件故事线。"

_TASK_PROMPT_TEMPLATE = """\
请将以下新闻归类到已有故事线，或创建新的故事线。

## 待归类新闻
{articles_block}

## 已有活跃故事线
{stories_block}

## 输出要求
严格输出JSON：
{{
  "matches": [
    {{"article_index": 1, "action": "link", "story_id": "故事线UUID"}},
    {{"article_index": 2, "action": "new", "title": "故事线标题（10-30字）", "description": "故事线概述（50-200字）", "story_type": "类型", "key_entities": ["实体1", ...], "categories": ["分类1", ...]}},
    {{"article_index": 3, "action": "skip"}}
  ]
}}

规则：
- 相同事件的新闻必须归到同一故事线
- 新建故事线需要本批中至少2篇相关新闻支撑
- 普通独立新闻（无明显大事件关联）标记为 skip
- title 必须是简短的事件概述（10-25字），不要用新闻原标题。例："2026美伊战争"、"SpaceX IPO"、"Meta大规模裁员"
- story_type 从以下选择：war, crisis, election, policy, scandal, disaster, earnings, merger, ipo, regulation, breakthrough, pandemic, summit, protest, trial, other"""


class BatchStoryMatcher:
    """Batch story matching — processes a group of articles at once."""

    async def execute(self, article_ids: list[str]) -> dict:
        """Run batch story matching for a list of article IDs.

        1. Fetch article data from DB
        2. Find candidate stories (tags/categories overlap + embedding sort)
        3. Call LLM to match/create/skip
        4. Execute DB operations (link articles, create stories)

        Returns {"success": bool, "matched": int, "created": int, "skipped": int, "errors": list}
        """
        start = time.monotonic()

        from app.services.story_service import (
            create_story,
            find_candidate_stories,
            get_articles_for_story_matching,
            link_article_to_story,
            update_story_embedding,
        )

        # 1. Fetch article data
        articles = await get_articles_for_story_matching(article_ids)
        if not articles:
            logger.info("Story matcher: no articles found for IDs %s", article_ids[:3])
            return {"success": True, "matched": 0, "created": 0, "skipped": len(article_ids), "errors": []}

        # 2. Find candidate stories
        all_tags = [a.get("tags", []) for a in articles]
        all_categories = [a.get("categories", []) for a in articles]
        all_embeddings = [a.get("embedding") for a in articles if a.get("embedding")]

        candidates = await find_candidate_stories(all_tags, all_categories, all_embeddings, limit=30)

        # 3. Build LLM prompt
        articles_block = self._build_articles_block(articles)
        stories_block = self._build_stories_block(candidates)

        task_prompt = _TASK_PROMPT_TEMPLATE.format(
            articles_block=articles_block,
            stories_block=stories_block if stories_block else "暂无活跃故事线",
        )

        # 4. Call LLM
        llm = get_llm_gateway()
        request = ChatRequest(
            messages=[
                ChatMessage(role="system", content=_SYSTEM_PROMPT),
                ChatMessage(role="user", content=task_prompt),
            ],
            response_format={"type": "json_object"},
        )

        try:
            response = await llm.chat(request, purpose="story_matcher")
            data = json.loads(response.content)
            tokens = response.usage.total_tokens
        except Exception:
            logger.exception("Story matcher LLM call failed")
            return {"success": False, "matched": 0, "created": 0, "skipped": 0, "errors": ["llm_call_failed"]}

        # 5. Process matches
        matches = data.get("matches", [])
        matched = 0
        created = 0
        skipped = 0
        errors = []

        # Track newly created stories in this batch (to avoid duplicates within same batch)
        new_stories: dict[str, str] = {}  # title -> story_id

        for match in matches:
            try:
                idx = match.get("article_index", 0) - 1  # 1-indexed in prompt
                if idx < 0 or idx >= len(articles):
                    errors.append(f"invalid article_index: {match.get('article_index')}")
                    continue

                article = articles[idx]
                action = match.get("action", "skip")

                if action == "link":
                    story_id = match.get("story_id")
                    if story_id:
                        # Validate story_id exists in candidates
                        valid_ids = {str(c["id"]) for c in candidates}
                        if story_id not in valid_ids:
                            logger.warning(
                                "LLM returned non-existent story_id: %s", story_id
                            )
                            errors.append(f"invalid story_id: {story_id}")
                            continue
                        await link_article_to_story(story_id, article["id"], matched_by="llm_batch", confidence=0.9)
                        await update_story_embedding(story_id)
                        matched += 1
                    else:
                        errors.append(f"link action missing story_id for article {idx+1}")

                elif action == "new":
                    title = match.get("title", "")
                    # Check if we already created this story in this batch
                    if title in new_stories:
                        await link_article_to_story(
                            new_stories[title], article["id"],
                            matched_by="llm_batch", confidence=0.9,
                        )
                        matched += 1
                    else:
                        story_id = await create_story(
                            title=title,
                            description=match.get("description"),
                            story_type=match.get("story_type", "other"),
                            key_entities=match.get("key_entities"),
                            categories=match.get("categories") or article.get("categories", []),
                            embedding=article.get("embedding"),
                            first_article_id=article["id"],
                        )
                        new_stories[title] = story_id
                        created += 1

                elif action == "skip":
                    skipped += 1
                else:
                    errors.append(f"unknown action: {action}")

            except Exception as e:
                logger.warning("Story match processing error for article %d: %s", idx + 1, e, exc_info=True)
                errors.append(str(e)[:200])

        duration = (time.monotonic() - start) * 1000
        logger.info(
            "Story matcher complete: %d articles -> %d matched, %d created, %d skipped | %d tokens | %.0fms",
            len(articles), matched, created, skipped, tokens, duration,
        )

        return {
            "success": True,
            "matched": matched,
            "created": created,
            "skipped": skipped,
            "tokens_used": tokens,
            "duration_ms": round(duration, 1),
            "errors": errors,
        }

    def _build_articles_block(self, articles: list[dict]) -> str:
        """Build the articles section of the LLM prompt."""
        lines = []
        for i, a in enumerate(articles, 1):
            summary = (a.get("ai_summary") or a.get("summary") or "")[:100]
            cats = ", ".join(a.get("categories", [])[:3])
            tags = ", ".join(a.get("tags", [])[:5])
            lines.append(f"{i}. {a['title']}\n   摘要：{summary}\n   分类：{cats} | 标签：{tags}")
        return "\n".join(lines)

    def _build_stories_block(self, candidates: list[dict]) -> str:
        """Build the existing stories section of the LLM prompt."""
        if not candidates:
            return ""
        lines = []
        for c in candidates:
            lines.append(f"- {c['title']} ({c['article_count']}篇) [{c['story_type']}] ID:{c['id']}")
        return "\n".join(lines)

"""Batch story refresher — keeps storylines updated as new articles join.

Triggered by:
  1. ``link_article_to_story`` once articles_since_refresh >= threshold
     (consumer side enqueues a story_refresh agent group)
  2. Scheduler fallback — picks up stories with pending articles that
     haven't been refreshed recently.

The agent takes a list of story IDs, loads each story's recent article
snapshots, calls one LLM per story to regenerate description / timeline /
sentiment / status, and persists the result. Errors on one story do not
block the rest.

Like ``story_matcher``, this is NOT an ``AgentDefinition`` (not per-article).
The ``story_refresher`` purpose label is used so admins can route it to a
dedicated provider/profile via the standard agent-config mechanism.
"""

from __future__ import annotations

import json
import logging
import time

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import ChatMessage, ChatRequest
from app.pipeline.agents.base import robust_json_loads

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = "你是新闻事件分析专家，负责将分散的新闻汇总成连贯的事件叙事。"

_TASK_TEMPLATE = """\
请基于以下故事线及其最新关联新闻，输出更新后的故事线元数据。

## 当前故事线
- 标题：{title}
- 类型：{story_type}
- 状态：{status}
- 关联文章数：{article_count}（其中{since}篇为本次新增）
- 现有概述：{description}
- 关键实体：{entities}
- 现有时间轴最近条目：
{timeline_block}

## 最新关联新闻（按时间倒序，最多{n}篇）
{articles_block}

## 输出要求（严格 JSON）
{{
  "description": "更新后的整体概述，80-220字，覆盖最新进展",
  "timeline": [
    {{"date": "YYYY-MM-DD", "summary": "该日核心进展（30-80字）", "kind": "event"}}
  ],
  "sentiment_avg": -1.0 到 1.0 之间的浮点数（综合所有文章的情绪倾向）,
  "key_entities": ["主要人物/组织/地点", ... 最多 12 项],
  "status": "developing | ongoing | concluded",
  "representative_article_id": "最具代表性文章的 UUID（必须来自上面提供的新闻列表）"
}}

规则：
- timeline 按日期升序排序，相同日期合并为一条；总条目控制在 8-15 条
- 若事件已有明显结论，status 设为 concluded；持续报道但已稳定为 ongoing；其它为 developing
- description 必须基于事实，不要臆造
- 若新增信息不足以更新某字段，可直接保持原值（仍需返回该字段）"""


class BatchStoryRefresher:
    """Refresh a batch of stories by calling LLM per story."""

    async def execute(self, story_ids: list[str]) -> dict:
        if not story_ids:
            return {"success": True, "refreshed": 0, "skipped": 0, "errors": []}

        from app.services.story_service import (
            apply_refresh_result,
            get_story_for_refresh,
        )

        start = time.monotonic()
        llm = get_llm_gateway()
        refreshed = 0
        skipped = 0
        errors: list[str] = []
        total_tokens = 0

        for sid in story_ids:
            try:
                payload = await get_story_for_refresh(sid)
                if payload is None:
                    skipped += 1
                    continue
                story = payload["story"]
                articles = payload["articles"]
                if not articles:
                    skipped += 1
                    continue

                prompt = self._build_prompt(story, articles)
                request = ChatRequest(
                    messages=[
                        ChatMessage(role="system", content=_SYSTEM_PROMPT),
                        ChatMessage(role="user", content=prompt),
                    ],
                    response_format={"type": "json_object"},
                )
                response = await llm.chat(request, purpose="story_refresher")
                total_tokens += response.usage.total_tokens

                try:
                    data = robust_json_loads(response.content)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("story_refresher: JSON parse failed for %s: %s",
                                   sid[:8], e)
                    errors.append(f"{sid[:8]}: parse_failed")
                    continue
                if not isinstance(data, dict):
                    errors.append(f"{sid[:8]}: non_dict_response")
                    continue

                # Validate representative_article_id is one we provided
                rep_id = data.get("representative_article_id")
                valid_ids = {a["id"] for a in articles}
                if rep_id and rep_id not in valid_ids:
                    rep_id = None

                # Validate timeline shape
                timeline = data.get("timeline")
                if not isinstance(timeline, list):
                    timeline = None
                else:
                    timeline = [
                        e for e in timeline
                        if isinstance(e, dict) and e.get("date") and e.get("summary")
                    ]

                await apply_refresh_result(
                    sid,
                    description=data.get("description"),
                    timeline=timeline,
                    sentiment_avg=data.get("sentiment_avg"),
                    key_entities=(
                        data.get("key_entities") if isinstance(data.get("key_entities"), list) else None
                    ),
                    status=data.get("status"),
                    representative_article_id=rep_id,
                )
                refreshed += 1
            except Exception as e:
                logger.warning("story_refresher failed for %s: %s", sid[:8], e, exc_info=True)
                errors.append(f"{sid[:8]}: {str(e)[:120]}")

        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "Story refresher complete: %d stories | %d refreshed, %d skipped | %d tokens | %.0fms",
            len(story_ids), refreshed, skipped, total_tokens, duration_ms,
        )
        return {
            "success": True,
            "refreshed": refreshed,
            "skipped": skipped,
            "tokens_used": total_tokens,
            "duration_ms": round(duration_ms, 1),
            "errors": errors,
        }

    def _build_prompt(self, story: dict, articles: list[dict]) -> str:
        cfg_n = len(articles)
        timeline_lines = []
        # Pull tail of existing timeline (most recent) as context
        # Note: get_story_for_refresh doesn't include timeline; the LLM gets
        # a fresh full re-derivation from articles, so timeline_block is just
        # a hint about prior structure. Keep minimal.
        timeline_lines.append("（基于下面文章重建即可）")

        article_lines = []
        for i, a in enumerate(articles, 1):
            summary = (a.get("ai_summary") or a.get("summary") or "")[:200]
            date = a.get("published_at") or "未知"
            sentiment = a.get("sentiment_score")
            sent_str = f" 情绪={sentiment:.2f}" if isinstance(sentiment, (int, float)) else ""
            article_lines.append(
                f"{i}. [{date[:10] if isinstance(date, str) else date}]"
                f" id={a['id']}{sent_str}\n"
                f"   标题：{a.get('title', '')}\n"
                f"   摘要：{summary}"
            )

        return _TASK_TEMPLATE.format(
            title=story.get("title", ""),
            story_type=story.get("story_type", "other"),
            status=story.get("status", "developing"),
            article_count=story.get("article_count", 0),
            since=story.get("articles_since_refresh", 0),
            description=(story.get("description") or "（暂无）")[:400],
            entities=", ".join((story.get("key_entities") or [])[:10]) or "（暂无）",
            timeline_block="\n".join(timeline_lines),
            n=cfg_n,
            articles_block="\n\n".join(article_lines),
        )

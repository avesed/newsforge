"""Unified summarizer agent — produces both brief and detailed summaries in one LLM call."""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)


class UnifiedSummarizerAgent(AgentDefinition):
    """Generate both brief (1-2 sentences) and detailed (5-20 sentences) summaries in a single LLM call."""

    agent_id = "summarizer"
    name = "统一摘要"
    description = "一次LLM调用同时生成简要摘要和详细摘要"
    phase = 2
    requires: list[str] = []
    input_fields = ["title", "full_text"]
    output_fields = ["ai_summary", "detailed_summary"]

    _TASK_PROMPT = """请根据上述新闻内容，同时生成简要摘要和详细摘要。

要求：
1. ai_summary：1-2句话，不超过100字，抓住核心事实（谁、做了什么、影响是什么），客观中立
2. detailed_summary：5-20句话，全面覆盖关键信息，包含背景、核心事件、关键数据/引用、各方反应，按逻辑顺序组织，保留重要的数字、日期、人名，客观中立

严格禁止：
- 禁止添加原文中不存在的分析、推理或评论（如"此举将影响…"、"市场参与者正密切关注…"）
- 禁止补充原文未提及的背景知识
- 只概括原文明确陈述的事实，不做任何延伸
- 如果原文信息有限（如仅有标题），摘要应相应简短，不得凭空扩写

输出严格JSON格式：
{"ai_summary": "简要摘要内容", "detailed_summary": "详细摘要内容"}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm,
            context,
            self._TASK_PROMPT,
            purpose="summarizer",
        )

        ai_summary = str(data.get("ai_summary", "")).strip()
        detailed_summary = str(data.get("detailed_summary", "")).strip()
        duration = (time.monotonic() - start) * 1000

        result_data: dict[str, str] = {}
        if ai_summary:
            result_data["ai_summary"] = ai_summary
        if detailed_summary:
            result_data["detailed_summary"] = detailed_summary

        return AgentResult(
            agent_id=self.agent_id,
            success=bool(ai_summary),
            data=result_data,
            duration_ms=duration,
            tokens_used=tokens,
        )

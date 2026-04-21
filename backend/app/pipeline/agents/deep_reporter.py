"""Deep reporter agent — generates full Markdown analysis report.

Currently async-only. SSE streaming support will be added later.
"""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)


class DeepReporterAgent(AgentDefinition):
    """Generate a comprehensive Markdown analysis report."""

    agent_id = "deep_reporter"
    name = "深度分析报告"
    description = "生成完整的Markdown格式深度分析报告"
    phase = 2
    requires = ["summarizer", "sentiment"]
    input_fields = ["title", "full_text", "categories"]
    output_fields = ["analysis_report"]

    _TASK_PROMPT = """你是资深新闻分析师和报告撰写专家。根据新闻全文撰写一篇结构化的深度分析报告。

报告要求：
1. 使用Markdown格式
2. 包含以下章节（按需增减）：

## 核心摘要
1-2段话概括核心要点

## 背景分析
事件发生的背景和上下文

## 关键事实
- 用列表列出关键事实和数据点
- 包括时间、人物、数字

## 影响分析
### 短期影响
### 长期影响

## 多方观点
如有不同立场，列出各方观点

## 风险与不确定性
潜在风险和需要关注的变量

## 结论与展望
总结性分析和前瞻

报告写作要求：
- 长度：根据原文信息量决定，信息充分时800-2000字，信息有限时相应缩短
- 语言：中文
- 风格：专业、客观、有深度
- 引用原文中的关键数据和引言
- 严禁编造或补充原文未提及的信息、背景知识、分析或推测
- 所有观点和事实必须能在原文中找到依据
- 如果原文信息有限（如仅有标题或简短摘要），应如实缩减报告篇幅，省略无法基于原文撰写的章节，不得凭空扩写"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        # Build extra context from prior agent results to prepend to task prompt
        extra_context = ""
        brief = context.agent_results.get("summarizer")
        if brief and brief.success:
            extra_context += f"\n已有摘要: {brief.data.get('ai_summary', '')}"

        sentiment = context.agent_results.get("sentiment")
        if sentiment and sentiment.success:
            score = sentiment.data.get("sentiment_score", 0)
            label = sentiment.data.get("sentiment_label", "neutral")
            extra_context += f"\n情感分析: {label} ({score})"

        task_prompt = self._TASK_PROMPT
        if extra_context:
            task_prompt = f"参考信息:{extra_context}\n\n{task_prompt}"

        report_text, tokens = await self._cached_text_call(
            llm,
            context,
            task_prompt,
            purpose=self.agent_id,
        )

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=bool(report_text and len(report_text) > 100),
            data={"analysis_report": report_text},
            duration_ms=duration,
            tokens_used=tokens,
        )

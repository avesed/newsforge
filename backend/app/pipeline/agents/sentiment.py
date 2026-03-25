"""Unified sentiment analysis agent — general + finance in a single LLM call."""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

_VALID_LABELS = {"positive", "negative", "neutral"}
_VALID_FINANCE = {"bullish", "bearish", "neutral"}

_TASK_PROMPT = """\
请同时完成以下两项情感分析任务，输出严格JSON格式。

## 任务一：通用情感分析
- sentiment_score: 情感分数，范围 -1.0 到 1.0
  - -1.0 ~ -0.6: 强烈负面（灾难、重大损失、严厉批评）
  - -0.6 ~ -0.2: 负面（不利消息、下滑、问题）
  - -0.2 ~ 0.2: 中性（客观报道、数据发布、日常新闻）
  - 0.2 ~ 0.6: 正面（好消息、增长、突破）
  - 0.6 ~ 1.0: 强烈正面（重大利好、历史性成就）
- sentiment_label: 仅限 positive / negative / neutral

## 任务二：金融情感分析（仅当新闻与金融/投资相关时填写，否则填 null）
- finance_sentiment: bullish（看多）/ bearish（看空）/ neutral（中性），非金融新闻填 null
- investment_summary: 不超过50字的投资摘要，概括对市场/个股的核心影响，非金融新闻填 null

金融分析评判维度（仅适用于金融相关新闻）：
- 业绩/财务影响
- 政策/监管影响
- 行业竞争格局变化
- 市场情绪/资金面影响
- 短期 vs 长期影响

输出示例：
{"sentiment_score": 0.5, "sentiment_label": "positive", "finance_sentiment": "bullish", "investment_summary": "公司业绩超预期，利好股价短期表现"}

非金融新闻输出示例：
{"sentiment_score": -0.3, "sentiment_label": "negative", "finance_sentiment": null, "investment_summary": null}"""


class UnifiedSentimentAgent(AgentDefinition):
    """Unified sentiment analysis: general score/label + finance bullish/bearish in one call."""

    agent_id = "sentiment"
    name = "统一情感分析"
    description = "通用情感分析 + 金融多空判断，单次LLM调用完成"
    phase = 2
    requires: list[str] = []
    input_fields = ["title", "summary", "full_text"]
    output_fields = ["sentiment_score", "sentiment_label", "finance_sentiment", "investment_summary"]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm,
            context,
            _TASK_PROMPT,
            purpose="sentiment",
        )

        # --- Validate sentiment_score ---
        score = data.get("sentiment_score", 0.0)
        try:
            score = max(-1.0, min(1.0, float(score)))
        except (ValueError, TypeError):
            score = 0.0

        # --- Validate sentiment_label ---
        label = str(data.get("sentiment_label", "neutral"))
        if label not in _VALID_LABELS:
            label = "neutral"

        # --- Finance fields: gracefully default to None ---
        finance_sentiment = data.get("finance_sentiment")
        if finance_sentiment is not None:
            finance_sentiment = str(finance_sentiment)
            if finance_sentiment not in _VALID_FINANCE:
                finance_sentiment = None

        investment_summary = data.get("investment_summary")
        if investment_summary is not None:
            investment_summary = str(investment_summary)[:50] or None

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={
                "sentiment_score": score,
                "sentiment_label": label,
                "finance_sentiment": finance_sentiment,
                "investment_summary": investment_summary,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

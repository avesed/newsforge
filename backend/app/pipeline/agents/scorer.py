"""Impact scorer agent — importance scoring with reasoning."""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)


class ImpactScorerAgent(AgentDefinition):
    """Score article importance (0-100) with reasoning."""

    agent_id = "impact_scorer"
    name = "影响力评分"
    description = "评估新闻影响力分数（0-100）并给出理由"
    phase = 2
    requires = []
    input_fields = ["title", "summary", "full_text", "categories"]
    output_fields = ["impact_score", "impact_reasoning"]

    _TASK_PROMPT = """你是新闻价值评估专家。对新闻进行多维度影响力评分。

评分维度（总分100）：

1. 时效性 (0-20)
   - 突发/首次报道 vs 跟踪/旧闻

2. 影响范围 (0-25)
   - 全球 > 全国 > 行业 > 区域 > 个体

3. 影响深度 (0-25)
   - 结构性变革 > 重大调整 > 常规变化 > 微小影响

4. 信息质量 (0-15)
   - 独家/一手 > 权威引用 > 二手转述 > 无来源

5. 受众关注度 (0-15)
   - 大众高关注 > 专业领域关注 > 小众

给出总分和每个维度的简要评分理由。

输出严格JSON格式：
{
  "impact_score": 75,
  "dimensions": {
    "timeliness": {"score": 18, "reason": "首次报道"},
    "scope": {"score": 20, "reason": "影响全球供应链"},
    "depth": {"score": 20, "reason": "行业格局变化"},
    "quality": {"score": 10, "reason": "多方信源确认"},
    "attention": {"score": 7, "reason": "专业领域高关注"}
  },
  "reasoning": "一段话总结评分理由"
}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm,
            context,
            self._TASK_PROMPT,
            purpose=self.agent_id,
        )

        impact_score = data.get("impact_score", 0)
        try:
            impact_score = max(0, min(100, int(impact_score)))
        except (ValueError, TypeError):
            impact_score = 0

        reasoning = str(data.get("reasoning", ""))
        dimensions = data.get("dimensions", {})
        if not isinstance(dimensions, dict):
            dimensions = {}

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={
                "impact_score": impact_score,
                "impact_reasoning": reasoning,
                "impact_dimensions": dimensions,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

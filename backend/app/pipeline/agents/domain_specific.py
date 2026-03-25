"""Domain-specific agents — politics impact and tech trend analysis."""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)


class PoliticsImpactAgent(AgentDefinition):
    """Analyze political/policy impact on society and markets."""

    agent_id = "politics_impact"
    name = "政策影响分析"
    description = "分析政治/政策新闻对社会和市场的影响"
    phase = 2
    requires = []
    input_fields = ["title", "full_text"]
    output_fields = ["policy_analysis"]

    _TASK_PROMPT = """你是政策分析专家。深入分析政治/政策新闻的影响。

分析维度：
1. 政策类型：财政/货币/产业/贸易/外交/监管/社会
2. 直接影响：哪些群体/行业/地区直接受影响
3. 间接影响：传导链条（如：关税→出口企业→供应链→就业）
4. 时间维度：短期（1-3月）、中期（3-12月）、长期（1年+）影响
5. 确定性：已确定/大概率/存在不确定性
6. 市场影响：对股市、债市、汇率、大宗商品的可能影响

输出严格JSON格式：
{
  "policy_type": "产业政策",
  "target_sectors": ["新能源", "汽车"],
  "direct_impact": "描述直接影响",
  "indirect_impact": "描述传导效应",
  "timeline": {
    "short_term": "短期影响",
    "medium_term": "中期影响",
    "long_term": "长期影响"
  },
  "certainty": "大概率",
  "market_implications": "对市场的影响描述",
  "key_risks": ["风险1", "风险2"]
}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm,
            context,
            self._TASK_PROMPT,
            purpose=self.agent_id,
        )

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={"policy_analysis": data},
            duration_ms=duration,
            tokens_used=tokens,
        )


class TechTrendAgent(AgentDefinition):
    """Analyze technology trend and maturity assessment."""

    agent_id = "tech_trend"
    name = "技术趋势分析"
    description = "分析技术趋势和成熟度"
    phase = 2
    requires = []
    input_fields = ["title", "full_text"]
    output_fields = ["tech_analysis"]

    _TASK_PROMPT = """你是科技产业分析师。分析技术类新闻的趋势和商业影响。

分析维度：
1. 技术领域：AI/芯片/云计算/区块链/量子计算/生物科技/新能源/机器人/XR/其他
2. 技术成熟度（Gartner Hype Cycle阶段）：
   - trigger: 技术萌芽期
   - peak: 期望膨胀期
   - trough: 泡沫破裂低谷期
   - slope: 稳步爬升复苏期
   - plateau: 生产成熟期
3. 商业化进展：概念/原型/测试/小规模商用/大规模商用
4. 竞争格局：主要玩家、竞争态势
5. 投资机会：相关投资方向和风险

输出严格JSON格式：
{
  "tech_domain": "AI/大模型",
  "maturity_stage": "slope",
  "maturity_reason": "解释判断理由",
  "commercialization": "小规模商用",
  "key_players": ["公司1", "公司2"],
  "competitive_landscape": "竞争格局描述",
  "investment_angle": "投资角度分析",
  "risks": ["风险1", "风险2"],
  "timeline_to_mainstream": "预计主流化时间"
}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm,
            context,
            self._TASK_PROMPT,
            purpose=self.agent_id,
        )

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={"tech_analysis": data},
            duration_ms=duration,
            tokens_used=tokens,
        )

"""Unified tagger agent — free-form tags + finance-specific structured tags in one call."""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)


class UnifiedTaggerAgent(AgentDefinition):
    """Generate free-form tags, industry tags, and event tags in a single LLM call.

    For non-finance articles, industry_tags and event_tags will be empty arrays.
    """

    agent_id = "tagger"
    name = "统一标签"
    description = "生成关键词标签、行业标签和事件标签（合并通用+金融标签）"
    phase = 2
    requires = []
    input_fields = ["title", "summary", "full_text", "categories"]
    output_fields = ["tags", "industry_tags", "event_tags", "story_hint", "story_type"]

    _TASK_PROMPT = """\
请为这篇新闻生成标签，严格输出JSON格式。

## tags（必填）
5-10个中文关键词标签，涵盖主题/实体/事件类型/地域。
- 标签简洁（2-6个字）
- 避免过于笼统的标签（如"新闻"、"报道"）

## industry_tags（金融相关时填写，否则空数组）
从以下行业中选择相关的（可多选）：
半导体、消费电子、互联网、云计算、AI/大模型、新能源、汽车、医药、银行、保险、\
证券、房地产、消费品、食品饮料、白酒、零售、物流、航空、旅游、教育、\
传媒、游戏、电信、基建、化工、钢铁、有色金属、农业、军工、航天
如果不属于以上行业，可自定义（2-4个字）。

## event_tags（金融相关时填写，否则空数组）
标注事件类型（可多选）：
财报发布、业绩预告、并购重组、IPO、增发配股、回购注销、高管变动、\
股权激励、大宗交易、解禁减持、政策利好、政策利空、技术突破、产品发布、\
合作签约、诉讼仲裁、监管处罚、评级变动、分红派息、战略调整
如无匹配事件，返回空数组。

## story_hint（必填）
这篇新闻所属的大事件/故事线名称（5-20字）。
例："2026美伊战争"、"英伟达Q4财报季"、"OpenAI上市"、"日本大地震"。
如果是普通独立新闻（无明显大事件关联），填 null。

## story_type（story_hint非null时必填）
事件类型，从以下选择：
war, crisis, election, policy, scandal, disaster, earnings, merger, ipo, regulation, breakthrough, pandemic, summit, protest, trial, other
如果 story_hint 为 null，此字段也填 null。

输出格式：
{"tags": [...], "industry_tags": [...], "event_tags": [...], "story_hint": "..." or null, "story_type": "..." or null}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm, context, self._TASK_PROMPT, purpose="tagger",
        )

        tags = data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        tags = [str(t).strip() for t in tags if t][:10]

        industry_tags = data.get("industry_tags", [])
        if not isinstance(industry_tags, list):
            industry_tags = []
        industry_tags = [str(t).strip() for t in industry_tags if t][:10]

        event_tags = data.get("event_tags", [])
        if not isinstance(event_tags, list):
            event_tags = []
        event_tags = [str(t).strip() for t in event_tags if t][:10]

        story_hint = data.get("story_hint")
        if story_hint and isinstance(story_hint, str):
            story_hint = story_hint.strip()[:100]
        else:
            story_hint = None

        story_type = data.get("story_type")
        VALID_STORY_TYPES = {"war", "crisis", "election", "policy", "scandal", "disaster", "earnings", "merger", "ipo", "regulation", "breakthrough", "pandemic", "summit", "protest", "trial", "other"}
        if story_type and isinstance(story_type, str) and story_type.strip().lower() in VALID_STORY_TYPES:
            story_type = story_type.strip().lower()
        else:
            story_type = None

        # Clear story_type if no story_hint
        if not story_hint:
            story_type = None

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=bool(tags),
            data={
                "tags": tags,
                "industry_tags": industry_tags,
                "event_tags": event_tags,
                "story_hint": story_hint,
                "story_type": story_type,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

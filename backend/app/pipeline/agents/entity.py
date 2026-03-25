"""Unified entity extraction agent — extracts all entity types in one LLM call.

Replaces the previous 6 specialized agents (person, org, location, stock,
product, event) with a single agent that extracts everything in one pass,
reducing LLM calls from 6 to 1.
"""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

_TASK_PROMPT = """\
请从上述新闻中提取所有实体，分为以下6类。每个实体必须包含 "type" 字段。

## 实体类型与字段

### 1. person（人物）
- name: 姓名
- title: 职位/头衔
- organization: 所属机构
- confidence: high/medium/low

### 2. org（机构）
- name: 名称
- type: 公司/政府/NGO/学术
- country: 所在国家
- confidence: high/medium/low

### 3. location（地点）
- name: 名称
- type: 国家/城市/地区
- context: 在新闻中的角色
- confidence: high/medium/low

### 4. stock（股票/金融工具）
- name: 公司/工具名称
- symbol: 标准化代码（规则见下方）
- market: us/cn/hk
- relevance: direct（主角）/indirect（关联）/mentioned（仅提及）
- confidence: high/medium/low

符号标准化规则：
- 美股：纯字母（如 AAPL、MSFT、GOOGL）
- A股上海：6位数字 + .SS（如 600519.SS、601318.SS）
- A股深圳：6位数字 + .SZ（如 000001.SZ、300750.SZ）
- 港股：4-5位数字 + .HK（如 0700.HK、9988.HK）

### 5. product（产品/服务）
- name: 产品名称
- type: 软件/硬件/游戏/电影/服务
- company: 所属公司
- status: 发布/泄露/传闻/更新
- confidence: high/medium/low

### 6. event（事件）
- name: 事件名称
- type: 会议/选举/灾害/政策等
- date: 发生日期（如有，格式 YYYY-MM-DD）
- location: 发生地点（如有）
- significance: high/medium/low
- confidence: high/medium/low

## 要求
- 仔细阅读全文，不要遗漏
- 同一实体只出现一次（合并别名）
- 用中文输出（专有名词保留原文）
- 如某类无实体，不必填充
- market 字段必须小写

输出严格JSON格式：
{"entities": [{"type": "person", "name": "...", ...}, {"type": "stock", "name": "...", ...}, ...]}"""


class UnifiedEntityAgent(AgentDefinition):
    """Extract all entity types (person, org, location, stock, product, event) in one LLM call."""

    agent_id = "entity"
    name = "统一实体提取"
    description = "一次LLM调用提取所有类型的实体（人物、机构、地点、股票、产品、事件）"
    phase = 2
    requires: list[str] = []
    input_fields = ["title", "full_text"]
    output_fields = ["entities"]

    _VALID_TYPES = {"person", "org", "location", "stock", "product", "event"}

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        data, tokens = await self._cached_json_call(
            llm, context, _TASK_PROMPT, purpose="entity"
        )

        entities = data.get("entities", [])
        if not isinstance(entities, list):
            logger.warning(
                "Entity agent returned non-list for article %s, discarding",
                context.article_id,
            )
            entities = []

        # Filter out entries without a valid type
        entities = [
            e for e in entities
            if isinstance(e, dict) and e.get("type") in self._VALID_TYPES
        ]

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={"entities": entities},
            duration_ms=duration,
            tokens_used=tokens,
        )

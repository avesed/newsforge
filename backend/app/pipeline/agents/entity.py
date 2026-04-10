"""Unified entity extraction agent — extracts all entity types in one LLM call.

Replaces the previous 6 specialized agents (person, org, location, stock,
product, event) with a single agent that extracts everything in one pass,
reducing LLM calls from 6 to 1.

Also extracts themes (broader concept tags) and primary_market for the article.
"""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

_VALID_MARKETS = {"cn", "hk", "us"}

_TASK_PROMPT = """\
请从上述新闻中提取所有实体，分为以下8类。每个实体必须包含 "type" 字段。
同时提取文章主题标签和主要市场归属。

## 实体类型与字段

### 1. person（人物）
- name: 姓名
- title: 职位/头衔
- organization: 所属机构
- confidence: 0.0-1.0 的数值

### 2. org（机构）
- name: 名称
- org_type: 公司/政府/NGO/学术
- country: 所在国家
- relation: 与新闻主题的关系（direct/industry_peer/supply_chain/competitor/beneficiary/subsidiary）
- confidence: 0.0-1.0 的数值

### 3. location（地点）
- name: 名称
- location_type: 国家/城市/地区
- context: 在新闻中的角色
- confidence: 0.0-1.0 的数值

### 4. stock（股票/金融工具）
- name: 公司/工具名称
- symbol: 标准化代码（规则见下方）
- market: us/cn/hk
- relation: 与新闻主题的关系（direct/industry_peer/supply_chain/competitor/beneficiary/subsidiary）
- confidence: 0.0-1.0 的数值

符号标准化规则：
- 美股：纯字母（如 AAPL、MSFT、GOOGL）
- A股上海：6位数字 + .SS（如 600519.SS、601318.SS）
- A股深圳：6位数字 + .SZ（如 000001.SZ、300750.SZ）
- 港股：4-5位数字 + .HK（如 0700.HK、9988.HK）

### 5. product（产品/服务）
- name: 产品名称
- product_type: 软件/硬件/游戏/电影/服务
- company: 所属公司
- status: 发布/泄露/传闻/更新
- confidence: 0.0-1.0 的数值

### 6. event（事件）
- name: 事件名称
- event_type: 会议/选举/灾害/政策等
- date: 发生日期（如有，格式 YYYY-MM-DD）
- location: 发生地点（如有）
- significance: high/medium/low
- confidence: 0.0-1.0 的数值

### 7. index（指数）
- name: 指数名称（如 上证指数、标普500、恒生指数）
- symbol: 标准化代码（如 000001.SS、SPX、HSI）
- market: us/cn/hk
- relation: direct/industry_peer/supply_chain/competitor/beneficiary/subsidiary
- confidence: 0.0-1.0 的数值

### 8. macro（宏观经济指标）
- name: 指标名称（如 CPI、GDP、非农就业、PMI）
- region: 所属国家或地区
- direction: up/down/stable/unknown
- confidence: 0.0-1.0 的数值

## confidence 评分标准
- 0.9-1.0: 文章直接主角
- 0.7-0.89: 显著相关
- 0.5-0.69: 间接相关
- 0.3-0.49: 弱相关
- 0.0-0.29: 仅被提及

## relation 字段说明（stock/org/index 实体必填）
- direct: 新闻的直接主角
- industry_peer: 同行业公司
- supply_chain: 供应链上下游
- competitor: 竞争对手
- beneficiary: 受益方
- subsidiary: 子公司/母公司关系

## themes（主题标签）
提取 1-5 个概括文章核心主题的标签，用于知识图谱扩展。
例如："AI芯片"、"新能源汽车供应链"、"美联储加息"、"半导体出口管制"。
应比分类更具体，反映文章涉及的产业链、政策方向或技术趋势。

## primary_market（主要市场）
判断文章整体的市场管辖归属，输出 cn/hk/us 之一。
若文章不涉及特定市场或无法判断，输出 null。

## 要求
- 仔细阅读全文，不要遗漏
- 同一实体只出现一次（合并别名）
- 用中文输出（专有名词保留原文）
- 如某类无实体，不必填充
- market 字段必须小写
- confidence 必须为 0.0-1.0 的数值

输出严格JSON格式：
{
  "entities": [{"type": "person", "name": "...", ...}, {"type": "stock", "name": "...", ...}, ...],
  "themes": ["主题1", "主题2"],
  "primary_market": "cn"
}"""

_VALID_TYPES = {"person", "org", "location", "stock", "product", "event", "index", "macro"}
_VALID_RELATIONS = {"direct", "industry_peer", "supply_chain", "competitor", "beneficiary", "subsidiary"}
_RELATION_ENTITY_TYPES = {"stock", "org", "index"}


def _normalize_confidence(value: object) -> float | None:
    """Coerce confidence to a float in [0.0, 1.0].

    Accepts numeric values directly. Also maps legacy string values
    (high/medium/low) for backward compatibility.
    """
    if isinstance(value, (int, float)):
        return round(max(0.0, min(1.0, float(value))), 2)

    if isinstance(value, str):
        legacy_map = {"high": 0.9, "medium": 0.7, "low": 0.4}
        mapped = legacy_map.get(value.lower())
        if mapped is not None:
            return mapped
        # Try parsing as a numeric string
        try:
            return round(max(0.0, min(1.0, float(value))), 2)
        except ValueError:
            pass

    return None


def _validate_entity(entity: dict) -> dict | None:
    """Validate and normalize a single entity dict. Returns None if invalid."""
    if not isinstance(entity, dict):
        return None

    etype = entity.get("type")
    if etype not in _VALID_TYPES:
        return None

    if not entity.get("name"):
        return None

    # Normalize confidence to numeric scale
    raw_conf = entity.get("confidence")
    normalized = _normalize_confidence(raw_conf)
    if normalized is not None:
        entity["confidence"] = normalized
    else:
        entity["confidence"] = 0.5  # Default mid-range if missing/invalid

    # Validate relation field for applicable entity types
    if etype in _RELATION_ENTITY_TYPES:
        relation = entity.get("relation")
        if relation not in _VALID_RELATIONS:
            entity["relation"] = "direct"  # Safe default

    # Ensure market is lowercase for financial entity types
    if etype in {"stock", "index"} and "market" in entity:
        entity["market"] = str(entity["market"]).lower()

    return entity


class UnifiedEntityAgent(AgentDefinition):
    """Extract all entity types, themes, and primary_market in one LLM call."""

    agent_id = "entity"
    name = "统一实体提取"
    description = (
        "一次LLM调用提取所有类型的实体（人物、机构、地点、股票、产品、事件、指数、宏观指标）"
        "及主题标签和主要市场归属"
    )
    phase = 2
    requires: list[str] = []
    input_fields = ["title", "full_text"]
    output_fields = ["entities", "themes", "primary_market"]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        try:
            data, tokens = await self._cached_json_call(
                llm, context, _TASK_PROMPT, purpose="entity"
            )
        except Exception as e:
            logger.error("Entity extraction LLM call failed for article %s: %s", context.article_id, e)
            return AgentResult(
                agent_id=self.agent_id,
                success=False,
                data={},
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(e)[:200],
            )

        # --- Entities ---
        entities = data.get("entities", [])
        if not isinstance(entities, list):
            logger.warning(
                "Entity agent returned non-list entities for article %s, discarding",
                context.article_id,
            )
            entities = []

        validated: list[dict] = []
        for raw in entities:
            entity = _validate_entity(raw)
            if entity is not None:
                validated.append(entity)

        # --- Themes ---
        themes = data.get("themes", [])
        if not isinstance(themes, list):
            logger.warning(
                "Entity agent returned non-list themes for article %s, discarding",
                context.article_id,
            )
            themes = []
        themes = [t for t in themes if isinstance(t, str) and t.strip()][:10]

        # --- Primary market ---
        primary_market = data.get("primary_market")
        if primary_market is not None:
            primary_market = str(primary_market).lower()
            if primary_market not in _VALID_MARKETS:
                primary_market = None

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={
                "entities": validated,
                "themes": themes,
                "primary_market": primary_market,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

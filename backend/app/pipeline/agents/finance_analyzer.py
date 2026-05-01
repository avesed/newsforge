"""Financial analysis agent — sentiment, entities, sectors, and analysis report.

Merges the former sentiment + deep_reporter agents into a single call from a
financial analyst perspective. Outputs:
- Sentiment (score, label, finance-specific bullish/bearish)
- Financial entities (companies, funds, government bodies mentioned)
- Sectors (stock market sectors related to the article)
- Analysis report (Markdown, from a financial analyst viewpoint)

Results are cached in ai_analysis to avoid duplicate generation.
Only runs when ai_analysis is not already populated.
"""

from __future__ import annotations

import logging
import re
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

_VALID_LABELS = {"positive", "negative", "neutral"}
_VALID_FINANCE = {"bullish", "bearish", "neutral"}

# News sources to filter from financial entities
_NEWS_SOURCES = {
    "reuters", "bloomberg", "cnbc", "cnn", "bbc", "ap", "afp",
    "the new york times", "new york times", "nyt",
    "the washington post", "washington post", "wsj",
    "the wall street journal", "wall street journal",
    "the guardian", "financial times", "ft",
    "the verge", "techcrunch", "espn", "nbc sports",
    "yahoo finance", "yahoo news", "marketwatch",
    "politico", "the hill", "axios", "vox media",
    "new york post", "usa today", "associated press",
    "新华社", "人民日报", "环球时报", "第一财经", "财新",
    "界面新闻", "澎湃新闻", "证券时报", "南华早报",
}

_VAGUE_RE = re.compile(
    r"^(companies|investors|analysts|customers|consumers|traders|"
    r"officials|regulators|market|markets|投资者|分析师|市场|监管机构)$",
    re.IGNORECASE,
)

_TASK_PROMPT = """\
你是一名资深金融分析师。请从金融投资视角分析上述新闻，完成以下任务，输出严格JSON。

## 1. 情感分析
- sentiment_score: -1.0 到 1.0
  - -1.0~-0.6: 强烈负面 | -0.6~-0.2: 负面 | -0.2~0.2: 中性 | 0.2~0.6: 正面 | 0.6~1.0: 强烈正面
- sentiment_label: positive / negative / neutral
- finance_sentiment: bullish（看多）/ bearish（看空）/ neutral，非金融新闻填 null
- investment_summary: 一句话投资摘要（≤50字），非金融新闻填 null

## 2. 金融相关实体
提取新闻中涉及的**公司、基金、政府机构**等金融实体（上限8个）。
每个实体：
- name: 正式名称（如 "Amazon"、"美联储"、"Berkshire Hathaway"）
- type: company / fund / government / exchange
- relation: direct（主角）/ supply_chain / competitor / beneficiary / subsidiary
- confidence: 0.5-1.0

严禁提取：
- 新闻来源/媒体（Reuters、CNBC等）
- 泛化名词（"investors"、"市场"）
- 记者/作者
- 不确定的实体

## 3. 相关板块 (sectors)
列出与本新闻相关的股市板块/行业（1-5个），从以下选择或自定义：
半导体、消费电子、互联网、云计算、AI/大模型、新能源、汽车、医药、
银行、保险、证券、房地产、消费品、食品饮料、零售、物流、航空、
旅游、教育、传媒、游戏、电信、基建、化工、钢铁、有色金属、农业、军工、
SaaS、网络安全、机器人、量子计算
非金融/商业新闻返回空数组。

## 4. 政策分析 (policy_analysis) — 仅政策/政治相关新闻需要填写
如果新闻涉及政策、法规、政府行为、监管变化，则填写此字段，否则填 null。
- policy_type: 财政/货币/产业/贸易/外交/监管/社会
- target_sectors: 受影响的行业列表
- direct_impact: 原文明确提及的直接影响
- indirect_impact: 传导链条（如有），原文未涉及填 null
- certainty: 已确定/大概率/存在不确定性
- market_implications: 对股市/债市/汇率的影响（原文有提及时填写）

## 5. 金融分析报告 (analysis_report)
用Markdown撰写一份**金融视角**的分析报告。

报告结构（按需增减章节，信息不足时缩减）：
### 核心摘要
1-2段，概括新闻对金融市场的意义

### 市场影响
- 受影响的公司/标的
- 短期 vs 长期影响
- 利好/利空判断及逻辑

### 政策传导（政策类新闻必写此章节）
- 政策类型与受影响行业
- 传导路径（政策 → 行业 → 企业 → 市场）
- 确定性评估

### 行业格局
该新闻如何改变行业竞争态势（如有）

### 风险提示
投资者需关注的风险和不确定性

### 投资建议
基于本新闻的投资策略提示（如适用）

写作要求：
- 中文，专业客观
- 长度根据信息量决定（300-1500字）
- **严禁编造**：所有事实和数据必须来自原文，不得补充原文未提及的信息
- 如果原文信息有限（仅标题/摘要），缩减报告，不要凭空扩写
- 如果新闻非金融相关，只写简短摘要，不强行套用金融分析框架

## 输出格式
{
  "sentiment_score": 0.5,
  "sentiment_label": "positive",
  "finance_sentiment": "bullish",
  "investment_summary": "亚马逊切入减肥药赛道，利好其医疗业务线",
  "financial_entities": [
    {"name": "Amazon", "type": "company", "relation": "direct", "confidence": 0.95},
    {"name": "Hims & Hers Health", "type": "company", "relation": "competitor", "confidence": 0.8}
  ],
  "sectors": ["医药", "互联网", "零售"],
  "policy_analysis": null,
  "analysis_report": "### 核心摘要\\n..."
}

政策类新闻的 policy_analysis 示例：
{
  "policy_type": "贸易",
  "target_sectors": ["半导体", "消费电子"],
  "direct_impact": "对华芯片出口限制升级",
  "indirect_impact": "国产替代加速，相关设备商受益",
  "certainty": "已确定",
  "market_implications": "A股半导体板块短期承压，中长期利好国产替代标的"
}"""


def _validate_entity(entity: dict) -> dict | None:
    """Validate a financial entity. Returns None if invalid."""
    if not isinstance(entity, dict):
        return None
    name = entity.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) < 2:
        return None
    name = name.strip()
    if name.lower() in _NEWS_SOURCES:
        return None
    if _VAGUE_RE.match(name):
        return None

    valid_types = {"company", "fund", "government", "exchange"}
    etype = entity.get("type", "company")
    if etype not in valid_types:
        etype = "company"
    entity["name"] = name
    entity["type"] = etype

    valid_relations = {"direct", "supply_chain", "competitor", "beneficiary", "subsidiary"}
    if entity.get("relation") not in valid_relations:
        entity["relation"] = "direct"

    conf = entity.get("confidence", 0.5)
    try:
        conf = max(0.0, min(1.0, float(conf)))
    except (ValueError, TypeError):
        conf = 0.5
    if conf < 0.5:
        return None
    entity["confidence"] = round(conf, 2)

    return entity


class FinanceAnalyzerAgent(AgentDefinition):
    """Financial analysis: sentiment + entities + sectors + report in one call."""

    agent_id = "finance_analyzer"
    name = "金融分析"
    description = "金融视角分析：情感、相关实体、板块、分析报告"
    phase = 2
    requires = ["summarizer"]
    input_fields = ["title", "full_text", "categories"]
    output_fields = [
        "sentiment_score", "sentiment_label",
        "finance_sentiment", "investment_summary",
        "financial_entities", "sectors",
        "analysis_report",
    ]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        from app.core.llm.types import LLMCallError
        try:
            data, tokens = await self._cached_json_call(
                llm, context, _TASK_PROMPT, purpose="finance_analyzer",
            )
        except LLMCallError:
            # LLM-attributable failure — let safe_execute mark llm_failed and
            # propagate to the circuit breaker.
            raise
        except Exception as e:
            logger.error(
                "Finance analyzer post-LLM failure for article %s: %s",
                context.article_id, e,
            )
            return AgentResult(
                agent_id=self.agent_id,
                success=False,
                data={},
                duration_ms=(time.monotonic() - start) * 1000,
                error=str(e)[:200],
            )

        # --- Sentiment ---
        score = data.get("sentiment_score", 0.0)
        try:
            score = max(-1.0, min(1.0, float(score)))
        except (ValueError, TypeError):
            score = 0.0

        label = str(data.get("sentiment_label", "neutral"))
        if label not in _VALID_LABELS:
            label = "neutral"

        finance_sentiment = data.get("finance_sentiment")
        if finance_sentiment is not None:
            finance_sentiment = str(finance_sentiment)
            if finance_sentiment not in _VALID_FINANCE:
                finance_sentiment = None

        investment_summary = data.get("investment_summary")
        if investment_summary is not None:
            investment_summary = str(investment_summary)[:80] or None

        # --- Financial entities ---
        raw_entities = data.get("financial_entities", [])
        if not isinstance(raw_entities, list):
            raw_entities = []
        entities: list[dict] = []
        seen: set[str] = set()
        for raw in raw_entities:
            ent = _validate_entity(raw)
            if ent is None:
                continue
            key = ent["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            entities.append(ent)
            if len(entities) >= 8:
                break

        # --- Sectors ---
        sectors = data.get("sectors", [])
        if not isinstance(sectors, list):
            sectors = []
        sectors = [str(s).strip() for s in sectors if s and isinstance(s, str)][:5]

        # --- Policy analysis (only for policy/politics news) ---
        policy_analysis = data.get("policy_analysis")
        if policy_analysis is not None and not isinstance(policy_analysis, dict):
            policy_analysis = None

        # --- Analysis report ---
        report = data.get("analysis_report", "")
        if not isinstance(report, str):
            report = ""

        duration = (time.monotonic() - start) * 1000

        return AgentResult(
            agent_id=self.agent_id,
            success=True,
            data={
                "sentiment_score": score,
                "sentiment_label": label,
                "finance_sentiment": finance_sentiment,
                "investment_summary": investment_summary,
                "financial_entities": entities,
                "sectors": sectors,
                "policy_analysis": policy_analysis,
                "analysis_report": report,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

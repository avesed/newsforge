"""Financial analysis agent — sentiment, entities, sectors, and analysis report.

Merges the former sentiment + deep_reporter agents into a single call from a
financial analyst perspective. Outputs:
- Sentiment (score, label, finance-specific bullish/bearish)
- Financial entities (companies, funds, government bodies mentioned)
- Sectors (stock market sectors related to the article)
- Related symbols (resolved via StockPulse profile search tool call)
- Analysis report (Markdown, from a financial analyst viewpoint)

Results are cached in ai_analysis to avoid duplicate generation.
Only runs when ai_analysis is not already populated.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from app.core.llm.gateway import LLMGateway
from app.core.llm.types import ChatMessage, ChatRequest, ChatResponse
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult, robust_json_loads

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

# Max tool call rounds to prevent infinite loops
_MAX_TOOL_ROUNDS = 3

# Tool definition for stock profile search
_STOCK_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_stock_profiles",
        "description": (
            "在股票档案数据库中搜索股票。可按公司名、行业、板块关键词搜索。"
            "返回匹配的股票代码(symbol)、名称、市场、行业等信息。"
            "例如搜索'石油'可找到中国石油、中国石化等；搜索'Apple'可找到AAPL。"
            "可多次调用以搜索不同关键词或市场。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词：公司名(Apple/苹果)、行业(半导体)、板块(石油石化)等",
                },
                "market": {
                    "type": "string",
                    "enum": ["us", "hk", "sh", "sz"],
                    "description": "可选，限定搜索市场: us=美股, hk=港股, sh=沪市, sz=深市",
                },
            },
            "required": ["query"],
        },
    },
}

_TASK_PROMPT = """\
你是一名资深金融分析师。请从金融投资视角分析上述新闻，完成以下任务，输出严格JSON。

**重要**：你可以使用 `search_stock_profiles` 工具搜索股票档案数据库，查找与新闻相关的股票代码。
- 如果新闻提到了具体公司，搜索该公司名称获取准确的股票代码
- 如果新闻涉及某个行业/板块（如石油、半导体），搜索该行业找到相关股票
- 如果新闻非金融相关或无法关联到具体股票，可以不搜索
- 搜索后，将找到的相关股票填入 related_symbols 字段

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

## 4. 相关股票 (related_symbols)
基于你的分析和搜索结果，列出与本新闻直接相关的股票（上限5个）。
每个股票：
- symbol: 股票代码（如 "AAPL"、"600519.SS"、"00700.HK"）
- market: 市场（us / sh / sz / hk）
- name: 股票名称
- relevance: direct（直接相关）/ indirect（间接相关，如上下游、竞品）
非金融新闻或无法关联到具体股票时返回空数组。

## 5. 政策分析 (policy_analysis) — 仅政策/政治相关新闻需要填写
如果新闻涉及政策、法规、政府行为、监管变化，则填写此字段，否则填 null。
- policy_type: 财政/货币/产业/贸易/外交/监管/社会
- target_sectors: 受影响的行业列表
- direct_impact: 原文明确提及的直接影响
- indirect_impact: 传导链条（如有），原文未涉及填 null
- certainty: 已确定/大概率/存在不确定性
- market_implications: 对股市/债市/汇率的影响（原文有提及时填写）

## 6. 金融分析报告 (analysis_report)
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
  "related_symbols": [
    {"symbol": "AMZN", "market": "us", "name": "Amazon.com Inc", "relevance": "direct"},
    {"symbol": "HIMS", "market": "us", "name": "Hims & Hers Health Inc", "relevance": "direct"}
  ],
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


def _validate_symbol(sym: dict) -> dict | None:
    """Validate a related_symbol entry. Returns None if invalid."""
    if not isinstance(sym, dict):
        return None
    symbol = sym.get("symbol")
    if not symbol or not isinstance(symbol, str) or len(symbol.strip()) < 1:
        return None
    market = sym.get("market", "")
    if market not in {"us", "sh", "sz", "hk"}:
        market = "us"
    name = sym.get("name", "")
    relevance = sym.get("relevance", "direct")
    if relevance not in {"direct", "indirect"}:
        relevance = "direct"
    return {
        "symbol": symbol.strip().upper(),
        "market": market,
        "name": str(name)[:100],
        "relevance": relevance,
    }


async def _execute_tool_call(tool_call: dict) -> str:
    """Execute a single tool call and return the result as a JSON string."""
    func = tool_call.get("function", {})
    name = func.get("name", "")
    args_str = func.get("arguments", "{}")

    if name != "search_stock_profiles":
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        args = json.loads(args_str)
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid arguments"})

    query = args.get("query", "")
    market = args.get("market")

    if not query:
        return json.dumps({"error": "query is required"})

    from app.sources.api.stockpulse import search_stock_profiles

    results = await search_stock_profiles(query, market=market, limit=5)
    if not results:
        return json.dumps({"results": [], "message": f"No profiles found for '{query}'"})

    compact = [
        {
            "symbol": r.get("symbol", ""),
            "market": r.get("market", ""),
            "name": r.get("name", ""),
            "name_zh": r.get("name_zh", ""),
            "sector": r.get("sector", ""),
            "industry": r.get("industry", ""),
        }
        for r in results
    ]
    return json.dumps({"results": compact}, ensure_ascii=False)


class FinanceAnalyzerAgent(AgentDefinition):
    """Financial analysis: sentiment + entities + sectors + report in one call.

    Supports LLM tool calls for stock profile search: the LLM can call
    search_stock_profiles to look up ticker symbols by company name,
    sector, or industry keyword. Results are used to populate the
    related_symbols field in the output.

    Gracefully degrades if the model doesn't support tool calls — the
    analysis proceeds without symbol resolution.
    """

    agent_id = "finance_analyzer"
    name = "金融分析"
    description = "金融视角分析：情感、相关实体、板块、相关股票、分析报告"
    phase = 2
    requires = ["summarizer"]
    input_fields = ["title", "full_text", "categories"]
    output_fields = [
        "sentiment_score", "sentiment_label",
        "finance_sentiment", "investment_summary",
        "financial_entities", "sectors",
        "related_symbols",
        "analysis_report",
    ]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        from app.core.llm.types import LLMCallError
        try:
            data, tokens = await self._tool_call_flow(llm, context)
        except LLMCallError:
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

        # --- Related symbols ---
        raw_symbols = data.get("related_symbols", [])
        if not isinstance(raw_symbols, list):
            raw_symbols = []
        related_symbols: list[dict] = []
        seen_syms: set[str] = set()
        for raw_sym in raw_symbols:
            sym = _validate_symbol(raw_sym)
            if sym is None:
                continue
            sym_key = sym["symbol"]
            if sym_key in seen_syms:
                continue
            seen_syms.add(sym_key)
            related_symbols.append(sym)
            if len(related_symbols) >= 5:
                break

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
                "related_symbols": related_symbols,
                "policy_analysis": policy_analysis,
                "analysis_report": report,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

    async def _tool_call_flow(
        self,
        llm: LLMGateway,
        context: AgentContext,
    ) -> tuple[dict, int]:
        """Execute the LLM call with optional tool-call rounds.

        Flow:
        1. Send analysis request with search_stock_profiles tool defined.
        2. If LLM returns tool_calls: execute searches, send results back.
        3. Repeat up to _MAX_TOOL_ROUNDS times.
        4. Parse the final JSON response.

        Falls back gracefully if tool calls are not supported by the model.
        """
        system_prompt = self._build_system_with_article(context)
        total_tokens = 0

        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=_TASK_PROMPT),
        ]

        for round_idx in range(_MAX_TOOL_ROUNDS + 1):
            is_last_round = round_idx == _MAX_TOOL_ROUNDS

            request = ChatRequest(
                messages=list(messages),
                response_format={"type": "json_object"},
                tools=None if is_last_round else [_STOCK_SEARCH_TOOL],
            )

            response: ChatResponse = await llm.chat(
                request, purpose="finance_analyzer",
            )
            total_tokens += response.usage.total_tokens

            # If model returned no tool calls, parse content as final JSON
            if not response.tool_calls:
                content = response.content or ""
                if not content.strip():
                    raise ValueError(
                        f"LLM returned empty content (finish_reason={response.finish_reason})"
                    )
                data = robust_json_loads(content)
                if not isinstance(data, dict):
                    data = {}
                logger.info(
                    "Finance analyzer completed for article %s: "
                    "%d tool rounds, %d total tokens",
                    context.article_id[:8], round_idx, total_tokens,
                )
                return data, total_tokens

            # Model wants to use tools — execute them
            tool_calls = response.tool_calls
            logger.info(
                "Finance analyzer tool call round %d for article %s: %d calls",
                round_idx + 1, context.article_id[:8], len(tool_calls),
            )

            # Add assistant message with tool_calls
            messages.append(ChatMessage(
                role="assistant",
                content=None,
                tool_calls=tool_calls,
            ))

            # Execute each tool call and add results
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                result_str = await _execute_tool_call(tc)
                messages.append(ChatMessage(
                    role="tool",
                    content=result_str,
                    tool_call_id=tc_id,
                ))

        # Should not reach here, but just in case
        raise ValueError("Tool call loop exhausted without final response")

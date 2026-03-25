"""LLM Article Classifier — multi-label classification + value scoring + market impact.

Single LLM call per batch produces:
- Multi-label categories with confidence
- Free-form tags
- Value score (0-100)
- Market impact detection with hints

Batch size: up to 20 articles per call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import ChatMessage, ChatRequest

logger = logging.getLogger(__name__)

BATCH_SIZE = 20

SYSTEM_PROMPT = """你是高级新闻分析专家。对每篇新闻同时完成以下三项任务：

## 任务1：多标签分类
将新闻归入一个或多个类别（可以多选），并给出置信度 (0.0-1.0)：
- finance (财经): 股票、基金、经济、贸易、央行、财报、并购、IPO
- tech (科技): AI、软件、硬件、互联网、芯片、区块链、创业
- politics (政要): 政策、选举、外交、法规、政府、议会
- entertainment (娱乐): 影视、音乐、明星、综艺、文化
- gaming (游戏): 电子游戏、游戏公司、电竞、游戏评测
- sports (体育): 足球、篮球、奥运、赛事、运动员
- world (国际): 国际事件、地缘政治、跨国合作、国际组织
- science (科学): 研究、发现、太空、物理、生物
- health (健康): 医疗、疫苗、疾病、健身、心理健康
- other (其他): 不属于以上任何分类

## 任务2：价值评分
给出0-100的新闻价值评分：
- 90-100: 重大突发（战争、金融危机、巨头并购）
- 70-89: 高价值（政策变动、财报超预期、重要人事变动）
- 50-69: 中等价值（行业趋势、产品发布、常规政策）
- 30-49: 一般新闻（日常报道、小型事件）
- 0-29: 低价值（水文、旧闻翻炒、无实质内容）
并给出一句话打分理由。

## 任务3：市场影响判断
判断该新闻是否对金融市场有直接或间接影响，如果有，给出一句话影响路径提示。

## 任务4：关键标签
提取1-5个最核心的中文关键词标签。

对每篇文章输出严格JSON：
{
  "categories": [{"slug": "finance", "confidence": 0.88}, {"slug": "tech", "confidence": 0.45}],
  "tags": ["关键词1", "关键词2"],
  "value_score": 75,
  "value_reason": "一句话理由",
  "has_market_impact": true,
  "market_impact_hint": "影响路径，无则为null"
}

多篇文章时输出JSON数组。categories至少包含一个分类。"""


@dataclass
class CategoryScore:
    slug: str
    confidence: float


@dataclass
class ClassifyResult:
    categories: list[CategoryScore]
    tags: list[str]
    value_score: int
    value_reason: str
    has_market_impact: bool
    market_impact_hint: str | None = None

    @property
    def primary_category(self) -> str:
        """Return the highest-confidence category slug."""
        if not self.categories:
            return "other"
        return max(self.categories, key=lambda c: c.confidence).slug

    @property
    def category_slugs(self) -> list[str]:
        """Return all category slugs."""
        return [c.slug for c in self.categories]


def _default_result() -> ClassifyResult:
    """Return a safe default when classification fails."""
    return ClassifyResult(
        categories=[CategoryScore(slug="other", confidence=0.0)],
        tags=[],
        value_score=0,
        value_reason="",
        has_market_impact=False,
        market_impact_hint=None,
    )


async def classify_articles(articles: list[dict]) -> list[ClassifyResult]:
    """Classify a batch of articles with multi-label categories, value scoring, and market impact.

    Args:
        articles: List of {title, summary} dicts.

    Returns:
        List of ClassifyResult, same order as input.
    """
    if not articles:
        return []

    # Process in batches of BATCH_SIZE
    all_results: list[ClassifyResult] = []
    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        batch_results = await _classify_batch(batch)
        all_results.extend(batch_results)

    return all_results


async def _classify_batch(articles: list[dict]) -> list[ClassifyResult]:
    """Classify a single batch (up to BATCH_SIZE articles)."""
    gateway = get_llm_gateway()

    batch_text = "\n\n".join(
        f"[{i + 1}] 标题: {a['title']}\n摘要: {a.get('summary', '无')}"
        for i, a in enumerate(articles)
    )

    request = ChatRequest(
        messages=[
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=f"请分析以下 {len(articles)} 篇新闻：\n\n{batch_text}",
            ),
        ],
        response_format={"type": "json_object"},
    )

    try:
        response = await gateway.chat(request, purpose="classifier")
        logger.info(
            "Classifier LLM response: model=%s tokens=%d finish=%s content_len=%d",
            response.model, response.usage.total_tokens,
            response.finish_reason, len(response.content),
        )
        if not response.content.strip():
            logger.warning(
                "Classifier received empty content from LLM (model=%s, finish=%s). "
                "Returning defaults for %d articles.",
                response.model, response.finish_reason, len(articles),
            )
            return [_default_result() for _ in articles]
        results = _parse_response(response.content, len(articles))
        # Log if all results fell back to defaults
        all_default = all(
            r.primary_category == "other" and r.value_score == 0 for r in results
        )
        if all_default:
            logger.warning(
                "Classifier returned all-default results for %d articles. "
                "LLM response may be unparseable: %s",
                len(articles), response.content[:200],
            )
        return results
    except Exception:
        logger.exception(
            "Article classification failed for %d articles, returning defaults",
            len(articles),
        )
        return [_default_result() for _ in articles]


def _parse_response(content: str, expected_count: int) -> list[ClassifyResult]:
    """Parse LLM response into ClassifyResult list."""
    try:
        data = json.loads(content)

        # Handle both single object and array, and wrapped responses
        if isinstance(data, dict):
            if "results" in data:
                items = data["results"]
            elif "articles" in data:
                items = data["articles"]
            elif "categories" in data:
                # Single article response
                items = [data]
            else:
                # Try first list value
                for v in data.values():
                    if isinstance(v, list):
                        items = v
                        break
                else:
                    items = [data]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        results: list[ClassifyResult] = []
        for item in items:
            if not isinstance(item, dict):
                results.append(_default_result())
                continue
            results.append(_parse_single_item(item))

        # Pad with defaults if LLM returned fewer results
        while len(results) < expected_count:
            results.append(_default_result())

        return results[:expected_count]

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(
            "Failed to parse classification response (error=%s): %s",
            e, content[:300],
        )
        return [_default_result() for _ in range(expected_count)]


def _parse_single_item(item: dict) -> ClassifyResult:
    """Parse a single article classification result."""
    # Parse categories (multi-label)
    raw_cats = item.get("categories", [])
    categories: list[CategoryScore] = []

    if isinstance(raw_cats, list):
        for cat in raw_cats:
            if isinstance(cat, dict):
                slug = _validate_category(cat.get("slug", "other"))
                confidence = min(1.0, max(0.0, float(cat.get("confidence", 0.5))))
                categories.append(CategoryScore(slug=slug, confidence=confidence))
            elif isinstance(cat, str):
                categories.append(CategoryScore(slug=_validate_category(cat), confidence=0.5))
    elif isinstance(raw_cats, str):
        # Fallback: single category string
        categories.append(CategoryScore(slug=_validate_category(raw_cats), confidence=0.5))

    # Legacy single-category format support
    if not categories and "category" in item:
        slug = _validate_category(item.get("category", "other"))
        confidence = min(1.0, max(0.0, float(item.get("confidence", 0.5))))
        categories.append(CategoryScore(slug=slug, confidence=confidence))

    if not categories:
        categories.append(CategoryScore(slug="other", confidence=0.0))

    # Parse tags
    tags = item.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags[:5]]

    # Parse value score
    try:
        value_score = max(0, min(100, int(item.get("value_score", 0))))
    except (ValueError, TypeError):
        value_score = 0

    value_reason = str(item.get("value_reason", ""))

    # Parse market impact
    has_market_impact = bool(item.get("has_market_impact", False))
    market_impact_hint = item.get("market_impact_hint")
    if market_impact_hint is not None:
        market_impact_hint = str(market_impact_hint)

    return ClassifyResult(
        categories=categories,
        tags=tags,
        value_score=value_score,
        value_reason=value_reason,
        has_market_impact=has_market_impact,
        market_impact_hint=market_impact_hint,
    )


VALID_CATEGORIES = {
    "finance", "tech", "politics", "entertainment", "gaming",
    "sports", "world", "science", "health", "other",
}


def _validate_category(category: str) -> str:
    """Validate and normalize category slug."""
    cat = str(category).lower().strip()
    return cat if cat in VALID_CATEGORIES else "other"

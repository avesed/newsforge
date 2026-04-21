"""LLM Article Classifier — classification + tagging + value scoring + market impact.

Single LLM call per article produces:
- Multi-label categories with confidence
- Free-form tags + industry tags + event tags (merged from former tagger agent)
- Value score (0-100)
- Market impact detection with hints
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import ChatMessage, ChatRequest

logger = logging.getLogger(__name__)

BATCH_SIZE = 1  # Single-article classification so prompt prefix aligns with agent-phase cache.

SYSTEM_PROMPT = """你是高级新闻分析专家。对每篇新闻同时完成以下任务，输出严格JSON。

## 任务1：多标签分类
将新闻归入一个或多个类别（可多选），给出置信度 (0.0-1.0)。
只选真正相关的分类——宁少勿滥。

可选分类：
- finance (财经): 股票、基金、经济数据、贸易、央行、财报、并购、IPO
- tech (科技): AI、软件、硬件、互联网、芯片、区块链、创业公司
- politics (政要): 政策、选举、外交、法规、政府人事、议会
- entertainment (娱乐): 影视、音乐、明星、综艺、文化
- gaming (游戏): 电子游戏、游戏公司、电竞、游戏评测
- sports (体育): 足球、篮球、奥运、赛事、运动员
- world (国际): 国际事件、地缘政治、跨国合作、国际组织
- science (科学): 学术研究、科学发现、太空、物理、生物
- health (健康): 医疗、疫苗、疾病、公共卫生、药物
- other (其他): 不属于以上任何分类

## 任务2：多维价值评分
从5个维度打分，每个维度有固定分值范围，最终 value_score = 各维度之和。

### 维度1：时效性 (0-20分)
- 18-20: 突发/首次报道，信息全新
- 12-17: 持续跟踪中的重要进展
- 6-11: 已知事件的常规更新
- 0-5: 旧闻翻炒、无新增信息

### 维度2：影响范围 (0-25分)
- 21-25: 全球性影响（如国际冲突、全球政策）
- 16-20: 全国/全行业影响（如央行政策、行业监管）
- 11-15: 单一行业或区域影响
- 6-10: 单一公司/组织
- 0-5: 个人/局部事件

### 维度3：影响深度 (0-25分)
- 21-25: 结构性变革（如技术革命、制度性改变）
- 16-20: 重大调整（如大额并购、重要人事、政策转向）
- 11-15: 显著但可预期的变化（如产品发布、常规财报）
- 6-10: 一般性变化
- 0-5: 微小影响或无实质影响

### 维度4：信息质量 (0-15分)
- 12-15: 独家/一手信源、有数据支撑
- 8-11: 权威信源引用、信息完整
- 4-7: 二手转述、信息不完整
- 0-3: 无信源、传闻、标题党

### 维度5：受众关注度 (0-15分)
- 12-15: 大众高关注话题（如知名公司、热门技术）
- 8-11: 专业领域高关注
- 4-7: 小众但有价值
- 0-3: 极小众

输出每个维度的分数，value_score 为总和 (0-100)。

## 任务3：市场影响判断
判断新闻是否对金融市场有直接或间接影响。如果有，给出一句话影响路径。

## 任务4：关键标签 (tags)
提取 5-10 个中文关键词标签，涵盖主题/实体/事件/地域。
- 标签简洁（2-6个字），如"AI芯片"、"特斯拉"、"美联储降息"
- 避免笼统标签（"新闻"、"报道"、"国际"）
- 避免重复分类名称（已有 categories，tags 应更具体）

## 任务5：行业标签 (industry_tags)
仅金融/科技/商业相关新闻需要填写，其他类型返回空数组。
从以下行业选择（可多选，也可自定义2-4字行业名）：
半导体、消费电子、互联网、云计算、AI/大模型、新能源、汽车、医药、
银行、保险、证券、房地产、消费品、食品饮料、零售、物流、航空、
旅游、教育、传媒、游戏、电信、基建、化工、钢铁、有色金属、农业、军工

## 任务6：事件标签 (event_tags)
仅金融/商业相关新闻需要填写，其他类型返回空数组。
从以下事件类型选择（可多选）：
财报发布、业绩预告、并购重组、IPO、增发配股、回购注销、高管变动、
股权激励、大宗交易、解禁减持、政策利好、政策利空、技术突破、产品发布、
合作签约、诉讼仲裁、监管处罚、评级变动、分红派息、战略调整
不匹配则返回空数组。

## 输出格式
{
  "categories": [{"slug": "finance", "confidence": 0.9}, {"slug": "tech", "confidence": 0.6}],
  "value_dimensions": {
    "timeliness": 16,
    "scope": 20,
    "depth": 18,
    "quality": 12,
    "attention": 10
  },
  "value_score": 76,
  "value_reason": "一句话总结打分理由",
  "has_market_impact": true,
  "market_impact_hint": "影响路径，无则为null",
  "tags": ["AI芯片", "英伟达", "出口管制"],
  "industry_tags": ["半导体", "AI/大模型"],
  "event_tags": ["政策利空"]
}

注意：value_score 必须等于 value_dimensions 五个维度分数之和。
若提供了「正文」字段，请优先基于正文内容完成以上任务；若仅有标题和摘要，则依据可见信息判断。"""


@dataclass
class CategoryScore:
    slug: str
    confidence: float


@dataclass
class ValueDimensions:
    """Multi-dimensional value scoring breakdown."""
    timeliness: int = 0   # 0-20
    scope: int = 0        # 0-25
    depth: int = 0        # 0-25
    quality: int = 0      # 0-15
    attention: int = 0    # 0-15

    def total(self) -> int:
        return self.timeliness + self.scope + self.depth + self.quality + self.attention

    def to_dict(self) -> dict:
        return {
            "timeliness": self.timeliness,
            "scope": self.scope,
            "depth": self.depth,
            "quality": self.quality,
            "attention": self.attention,
        }


@dataclass
class ClassifyResult:
    categories: list[CategoryScore]
    tags: list[str]
    value_score: int
    value_reason: str
    has_market_impact: bool
    market_impact_hint: str | None = None
    industry_tags: list[str] = field(default_factory=list)
    event_tags: list[str] = field(default_factory=list)
    value_dimensions: ValueDimensions = field(default_factory=ValueDimensions)

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
        articles: List of {title, summary, full_text?} dicts. When full_text is
            present, classification uses the cleaned article body for higher
            accuracy (also primes the prompt cache for downstream agents).

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

    def _format_article(idx: int, a: dict) -> str:
        parts = [f"[{idx + 1}] 标题: {a['title']}", f"摘要: {a.get('summary') or '无'}"]
        full_text = a.get("full_text")
        if full_text:
            parts.append(f"正文:\n{full_text}")
        return "\n".join(parts)

    batch_text = "\n\n".join(_format_article(i, a) for i, a in enumerate(articles))

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
    from app.pipeline.agents.base import robust_json_loads
    try:
        data = robust_json_loads(content)

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
    tags = [str(t).strip() for t in tags if t][:10]

    # Parse industry_tags
    industry_tags = item.get("industry_tags", [])
    if not isinstance(industry_tags, list):
        industry_tags = []
    industry_tags = [str(t).strip() for t in industry_tags if t][:10]

    # Parse event_tags
    event_tags = item.get("event_tags", [])
    if not isinstance(event_tags, list):
        event_tags = []
    event_tags = [str(t).strip() for t in event_tags if t][:10]

    # Parse value dimensions
    _DIM_CAPS = {"timeliness": 20, "scope": 25, "depth": 25, "quality": 15, "attention": 15}
    raw_dims = item.get("value_dimensions", {})
    dims = ValueDimensions()
    if isinstance(raw_dims, dict):
        for dim_name, cap in _DIM_CAPS.items():
            try:
                setattr(dims, dim_name, max(0, min(cap, int(raw_dims.get(dim_name, 0)))))
            except (ValueError, TypeError):
                pass

    # value_score: prefer dimensions sum, fall back to explicit value_score
    dim_total = dims.total()
    if dim_total > 0:
        value_score = min(100, dim_total)
    else:
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
        industry_tags=industry_tags,
        event_tags=event_tags,
        value_dimensions=dims,
    )


VALID_CATEGORIES = {
    "finance", "tech", "politics", "entertainment", "gaming",
    "sports", "world", "science", "health", "other",
}


def _validate_category(category: str) -> str:
    """Validate and normalize category slug."""
    cat = str(category).lower().strip()
    return cat if cat in VALID_CATEGORIES else "other"

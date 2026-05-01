"""Entity extraction agent — extracts people, organizations, locations,
time references, and events from news articles.

Simplified to 4 core types with strict anti-hallucination rules:
only extract what is explicitly stated in the article text.
"""

from __future__ import annotations

import logging
import re
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

_VALID_MARKETS = {"cn", "hk", "us"}

# Well-known news sources — filtered out post-extraction
_NEWS_SOURCES = {
    # English media
    "reuters", "bloomberg", "cnbc", "cnn", "bbc", "ap", "afp",
    "the new york times", "new york times", "nyt",
    "the washington post", "washington post",
    "the wall street journal", "wall street journal", "wsj",
    "the guardian", "financial times", "ft",
    "the verge", "techcrunch", "ars technica", "wired",
    "espn", "nbc sports", "cbs sports", "fox sports", "the athletic",
    "nbc news", "abc news", "cbs news", "fox news", "msnbc",
    "yahoo finance", "yahoo news", "marketwatch",
    "politico", "the hill", "axios", "vox media", "vox",
    "buzzfeed", "huffpost", "usa today", "los angeles times",
    "u.s. news & world report", "u.s. news",
    "the seattle times", "associated press",
    "new york post", "nbc", "cbs", "abc", "fox",
    # Chinese media
    "新华社", "人民日报", "环球时报", "第一财经", "财新",
    "界面新闻", "澎湃新闻", "证券时报", "南华早报", "香港经济日报",
    "央视", "中新社", "经济日报", "每日经济新闻", "21世纪经济报道",
}

# Generic / vague names that should not be entities
_VAGUE_NAME_RE = re.compile(
    r"^(companies|investors|analysts|customers|users|consumers|traders|"
    r"officials|regulators|lawmakers|senators|people|experts|sources|"
    r"authorities|residents|citizens|voters|workers|employees|"
    r"市场|投资者|分析师|消费者|用户|官员|监管机构|民众|居民|选民|"
    r"公众|群众|网友|业内人士|知情人士|相关人士)$",
    re.IGNORECASE,
)

_TASK_PROMPT = """\
请从上述新闻中提取关键实体，按以下 5 种类型分别归类。**type 字段必须严格区分，不得混用。**

## 实体类型（严格区分，不可混用）

### 1. person（自然人，仅限真实个人）
**仅限真实存在的人类个人**：政治家、企业家、明星、运动员、科学家、记者主角等。
公司、机构、组织、国家、品牌、产品**绝对不允许**归入 person。
- name: 正式全名
  - 英文人名写全名："Donald Trump"（非 "Trump"）、"Jerome Powell"（非 "Powell"）
  - 中文人名保留原名："马斯克"、"任正非"
- role: 一句话说明在本文中的身份和角色（如 "美联储主席候选人"、"特斯拉CEO"）
- confidence: 0.5-1.0

### 2. organization（组织/机构）
公司、政府部门、监管机构、国际组织、NGO、学术机构、体育俱乐部、宗教团体等。
**国家不归入此类**（见 country）；具体人不归入此类（见 person）。
- name: 正式名称
  - 公司："Amazon"、"比亚迪"、"Alphabet"、"NASA"、"Apple"
  - 政府/监管："美联储"、"SEC"、"中国证监会"、"欧盟委员会"
  - 国际组织："联合国"、"WHO"、"OPEC"
- role: 一句话说明在本文中的角色（如 "发布GLP-1减肥产品的公司"、"加征关税的监管方"）
- confidence: 0.5-1.0

### 3. country（国家/主权实体）
具体国家或具有主权地位的实体。
- name: 国家名（"美国"、"中国"、"日本"、"俄罗斯"、"欧盟"——欧盟作为政治联合体可计入）
- role: 一句话说明在本文中的角色（如 "贸易战发起方"、"政策受影响国"）
- confidence: 0.5-1.0

### 4. location（具体地点）
具体的城市、地区、场所、地理特征（**国家不归入此类，归入 country**）。
- name: 地名（"硅谷"、"华尔街"、"乌克兰东部"、"东京"、"白宫"）
- role: 一句话说明在新闻中的作用
- confidence: 0.5-1.0

### 5. event（事件）
文中的核心事件或动作。
- name: 简洁事件名（如 "Amazon推出GLP-1减肥服务"、"美联储主席提名僵局"）
- event_type: 政策/人事/产品/冲突/灾害/赛事/财报/并购/法律/其他
- significance: high/medium/low
- confidence: 0.5-1.0

## type 字段判定速查表（避免误标）
| 实体例子 | 正确 type | 错误 type |
|---|---|---|
| Donald Trump、马斯克、Sam Altman | person | ❌ organization |
| Apple、NASA、美联储、Goldman Sachs | organization | ❌ person |
| 美国、中国、日本、俄罗斯、欧盟 | country | ❌ person、❌ organization |
| 硅谷、华尔街、白宫、东京 | location | ❌ country、❌ organization |
| iPhone发布会、特朗普就职、巴以冲突升级 | event | ❌ organization |

**典型错误（必须避免）**：
- ❌ Apple → person   ✅ Apple → organization
- ❌ NASA → person    ✅ NASA → organization
- ❌ 美国 → person     ✅ 美国 → country
- ❌ 美联储 → country  ✅ 美联储 → organization

## 严格规则（防止幻觉）
1. **只提取文中明确出现的信息**——不要推测、补充、联想
2. **新闻来源/媒体不是实体**：Reuters、CNN、ESPN、The Verge 等报道该新闻的媒体不要提取，除非它本身是新闻主角
3. **记者/作者不是实体**
4. **不要提取泛化名词**："investors"、"analysts"、"公众" 等集合名词不是实体
5. **不确定就不提取**——宁可漏提也不要编造

## 数量限制
- 实体总数上限 **10 个**
- 只保留与新闻主题直接相关的实体
- confidence < 0.5 的不要输出

## primary_market
文章的主要市场归属：cn/hk/us 之一。不涉及特定市场则输出 null。

## 输出示例
新闻: "Amazon launches GLP-1 weight loss program via Amazon One Medical in the US, competing with Hims & Hers..."
```json
{
  "entities": [
    {"type": "organization", "name": "Amazon", "role": "推出GLP-1减肥服务的公司", "confidence": 0.95},
    {"type": "organization", "name": "Hims & Hers Health", "role": "竞争对手", "confidence": 0.7},
    {"type": "organization", "name": "Novo Nordisk", "role": "GLP-1药物供应商", "confidence": 0.7},
    {"type": "country", "name": "美国", "role": "服务上线市场", "confidence": 0.8},
    {"type": "event", "name": "Amazon推出GLP-1减肥服务", "event_type": "产品", "significance": "high", "confidence": 0.95}
  ],
  "primary_market": "us"
}
```

输出严格JSON：
{"entities": [...], "primary_market": "..."}"""

_VALID_TYPES = {"person", "organization", "country", "location", "event"}
_VALID_RELATIONS = {"direct", "supply_chain", "competitor", "beneficiary", "subsidiary"}


def _normalize_confidence(value: object) -> float | None:
    """Coerce confidence to a float in [0.0, 1.0]."""
    if isinstance(value, (int, float)):
        return round(max(0.0, min(1.0, float(value))), 2)
    if isinstance(value, str):
        legacy_map = {"high": 0.9, "medium": 0.7, "low": 0.4}
        mapped = legacy_map.get(value.lower())
        if mapped is not None:
            return mapped
        try:
            return round(max(0.0, min(1.0, float(value))), 2)
        except ValueError:
            pass
    return None


def _is_news_source(name: str) -> bool:
    """Check if a name matches a known news source."""
    return name.lower().strip() in _NEWS_SOURCES


def _validate_entity(entity: dict) -> dict | None:
    """Validate and normalize a single entity dict. Returns None if invalid."""
    if not isinstance(entity, dict):
        return None

    etype = entity.get("type", "")
    # Map legacy types to new typed buckets
    _LEGACY_TYPE_MAP = {
        "org": "organization",
        "stock": "organization",
        "index": "organization",
        "macro": "organization",
    }
    if etype in _LEGACY_TYPE_MAP:
        etype = _LEGACY_TYPE_MAP[etype]
        entity["type"] = etype
    elif etype in ("product", "time"):
        return None  # Drop these entity types

    if etype not in _VALID_TYPES:
        return None

    name = entity.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) < 2:
        return None
    name = name.strip()
    entity["name"] = name

    # Filter out news sources from organization/person buckets
    if etype in ("person", "organization") and _is_news_source(name):
        return None

    # Filter out vague / generic names
    if _VAGUE_NAME_RE.match(name):
        return None

    # Normalize confidence
    raw_conf = entity.get("confidence")
    normalized = _normalize_confidence(raw_conf)
    entity["confidence"] = normalized if normalized is not None else 0.5

    # Drop low confidence
    if entity["confidence"] < 0.5:
        return None

    return entity


class UnifiedEntityAgent(AgentDefinition):
    """Extract people/orgs, locations, times, and events from news."""

    agent_id = "entity"
    name = "实体提取"
    description = "提取新闻中的人物/组织、地点、时间、事件"
    phase = 2
    requires: list[str] = []
    input_fields = ["title", "full_text"]
    output_fields = ["entities", "themes", "primary_market"]

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        from app.core.llm.types import LLMCallError
        try:
            data, tokens = await self._cached_json_call(
                llm, context, _TASK_PROMPT, purpose="entity"
            )
        except LLMCallError:
            # LLM-attributable failure — let safe_execute mark llm_failed and
            # propagate to the circuit breaker.
            raise
        except Exception as e:
            logger.error("Entity extraction post-LLM failure for article %s: %s", context.article_id, e)
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
            entities = []

        validated: list[dict] = []
        seen_names: set[str] = set()
        for raw in entities:
            entity = _validate_entity(raw)
            if entity is None:
                continue
            # Deduplicate by lowercase name
            key = entity["name"].lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            validated.append(entity)
            if len(validated) >= 10:
                break

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
                "themes": [],  # Tags now handled by classifier
                "primary_market": primary_market,
            },
            duration_ms=duration,
            tokens_used=tokens,
        )

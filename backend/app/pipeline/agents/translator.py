"""Translator agent — translates non-Chinese article title and full text to Chinese."""

from __future__ import annotations

import logging
import time

from app.core.llm.gateway import LLMGateway
from app.pipeline.agents.base import AgentContext, AgentDefinition, AgentResult

logger = logging.getLogger(__name__)

_CJK_RANGE = range(0x4E00, 0x9FFF + 1)


def _looks_chinese(text: str) -> bool:
    """Heuristic: if >30% of characters are CJK, treat as Chinese."""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if ord(ch) in _CJK_RANGE)
    return cjk_count / len(text) > 0.3


class TranslatorAgent(AgentDefinition):
    """Translate non-Chinese article title and full text to natural Chinese."""

    agent_id = "translator"
    name = "中文翻译"
    description = "将非中文文章的标题和正文翻译为地道的中文"
    phase = 2
    requires: list[str] = []
    input_fields = ["title", "full_text", "language", "source_name"]
    output_fields = ["title_zh", "full_text_zh"]

    _TASK_PROMPT_FULL = """请将上述新闻的标题和正文翻译为地道的中文。

核心原则：忠实传达原文的内容、语气和立场，同时确保中文表达自然流畅，没有翻译腔。

要求：
1. title_zh：中文标题。
   - 忠实传达原标题的含义，不要增删信息
   - 去掉标题末尾的来源标注（如"- Reuters"、"| CNN"等），只翻译正文部分
   - 用自然的中文表达，避免"某某称/表示"式的机械句式
2. full_text_zh：中文正文。要求：
   - 完整保留原文的信息量、论述逻辑和作者语气，不要删减或概括
   - 句式转换以自然为准：长定语从句可拆分，但不要过度改写原文结构
   - 人名首次出现时保留原文并附中文译名（如"埃隆·马斯克(Elon Musk)"），后续只用中文
   - 专有名词、机构名用约定俗成的中文译名
   - 保留原文的段落结构、关键数据和引用
   - 保留Markdown格式

翻译时跳过（不要翻译也不要包含在输出中）：
- 视频/音频播放器控件文字（如"Play", "Watch", "Next video", 时间戳等）
- 网站logo、图标、广告图、占位符图片引用
- 导航菜单、页眉页脚残留文字

图片规则（严格遵守）：
- ![alt](url) 格式的图片引用必须**逐字保留**，URL与alt文本均不得改动或翻译
- 原文已有的图片描述性说明（介绍图片内容的句子，如 "Trump speaks at the White House"）正常翻译为中文并保留
- **严禁自行添加版权署名**：原文没有独立图源行时，不要在图片上下方生成 *Getty Images*、
  *Reuters*、*路透*、*图源：XXX* 等署名，即使图片 alt 中含有 "getty"、"reuters" 等词也不要据此补充
- 原文已有的独立图源署名行（仅由机构名构成的署名）翻译时直接省略；与描述句混排时只省略署名部分，保留描述

输出严格JSON格式：
{"title_zh": "中文标题", "full_text_zh": "中文正文"}"""

    _TASK_PROMPT_TITLE_ONLY = """请将上述新闻的标题翻译为地道的中文。

核心原则：忠实传达原标题的含义，不要增删信息，同时确保中文表达自然。
去掉标题末尾的来源标注（如"- Reuters"、"| CNN"等），只翻译正文部分。

输出严格JSON格式：
{"title_zh": "中文标题"}"""

    async def execute(self, context: AgentContext, llm: LLMGateway) -> AgentResult:
        start = time.monotonic()

        # Skip Chinese articles — no translation needed
        # Also skip if language is None (unknown) and title looks Chinese
        lang = context.language or ""
        if lang.startswith("zh") or (
            not lang and _looks_chinese(context.title)
        ):
            logger.debug("Skipping translation for Chinese article %s (lang=%s)", context.article_id, lang or "auto-detected")
            return AgentResult(
                agent_id=self.agent_id,
                success=True,
                data={},
                duration_ms=(time.monotonic() - start) * 1000,
                tokens_used=0,
            )

        # Choose prompt based on whether full text is available
        has_full_text = bool(context.full_text and len(context.full_text) > 50)
        task_prompt = self._TASK_PROMPT_FULL if has_full_text else self._TASK_PROMPT_TITLE_ONLY

        data, tokens = await self._cached_json_call(
            llm,
            context,
            task_prompt,
            purpose="translator",
        )

        duration = (time.monotonic() - start) * 1000

        result_data: dict[str, str] = {}
        raw_title = data.get("title_zh")
        title_zh = (raw_title.strip() if isinstance(raw_title, str) else "")
        if title_zh:
            # Truncate to fit VARCHAR(500) column
            result_data["title_zh"] = title_zh[:500]

        if has_full_text:
            raw_text = data.get("full_text_zh")
            full_text_zh = (raw_text.strip() if isinstance(raw_text, str) else "")
            if full_text_zh:
                result_data["full_text_zh"] = full_text_zh

        logger.info(
            "Translated article %s: title_zh=%d chars, full_text_zh=%d chars, tokens=%d",
            context.article_id,
            len(result_data.get("title_zh", "")),
            len(result_data.get("full_text_zh", "")),
            tokens,
        )

        return AgentResult(
            agent_id=self.agent_id,
            success=bool(title_zh),
            data=result_data,
            duration_ms=duration,
            tokens_used=tokens,
        )

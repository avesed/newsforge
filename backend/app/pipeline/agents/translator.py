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
    input_fields = ["title", "full_text", "language"]
    output_fields = ["title_zh", "full_text_zh"]

    _TASK_PROMPT_FULL = """请将上述新闻的标题和正文翻译为地道的中文。

核心原则：译文应读起来像中文母语者写的新闻，而非翻译稿。避免"翻译腔"——不要逐字对译，不要生硬套用英文句式。

要求：
1. title_zh：中文标题。用中文新闻标题的表达习惯重新组织，简洁有力，不要"某某称/表示"式的机械翻译
2. full_text_zh：中文正文。要求：
   - 用中文的行文逻辑和表达习惯重新组织句子，而非逐句对译
   - 长定语从句拆分为短句，被动句改为主动句
   - 人名首次出现时保留原文并附中文译名（如"埃隆·马斯克(Elon Musk)"），后续只用中文
   - 专有名词、机构名用约定俗成的中文译名
   - 保留原文的段落结构、关键数据和引用
   - 保留Markdown格式

翻译时跳过（不要翻译也不要包含在输出中）：
- 视频/音频播放器控件文字（如"Play", "Watch", "Next video", 时间戳等）
- 网站logo、图标、广告图、占位符图片引用
- 导航菜单、页眉页脚残留文字

图片规则：仅保留正文配图的原始URL，不要编造、替换或翻译图片URL。

输出严格JSON格式：
{"title_zh": "中文标题", "full_text_zh": "中文正文"}"""

    _TASK_PROMPT_TITLE_ONLY = """请将上述新闻的标题翻译为地道的中文。

核心原则：译文应读起来像中文新闻标题，而非翻译稿。简洁有力，用中文标题习惯重新组织。

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

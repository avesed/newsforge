"""SSE streaming endpoints — on-demand deep analysis."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.llm.gateway import get_llm_gateway
from app.core.llm.types import ChatMessage, ChatRequest
from app.db.database import get_db
from app.models.article import Article
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["streaming"])

DEEP_ANALYSIS_PROMPT = """你是一名资深金融分析师。基于以下新闻内容，从金融投资视角撰写分析报告（Markdown格式）。

报告结构（按需增减，信息不足时缩减）：
### 核心摘要
1-2段，概括新闻对金融市场的意义

### 市场影响
- 受影响的公司/标的
- 短期 vs 长期影响
- 利好/利空判断及逻辑

### 行业格局
该新闻如何改变行业竞争态势（如有）

### 风险提示
投资者需关注的风险和不确定性

### 投资��议
基于本新闻的投资策略提示（如适用）

要求：
- 中文，专业客观，300-1500字
- 严禁编造原文未提及的信息
- 非金融新闻只写简短摘要，不强行套用金融框架"""


@router.get("/articles/{article_id}/stream/analysis")
async def stream_analysis(
    article_id: UUID,
    force_new: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream a deep analysis report for an article via SSE.

    If a cached analysis exists and force_new=False, returns it immediately.
    Otherwise generates a new analysis via LLM streaming.
    """
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    # Return cached analysis if available
    if article.ai_analysis and not force_new:
        async def cached_stream():
            yield _sse_event({"type": "analysis_start", "cached": True})
            yield _sse_event({"type": "analysis_chunk", "content": article.ai_analysis})
            yield _sse_event({"type": "complete", "content": article.ai_analysis})

        return StreamingResponse(
            cached_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Generate new analysis via streaming
    return StreamingResponse(
        _generate_analysis(article, db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _generate_analysis(article: Article, db: AsyncSession) -> AsyncGenerator[str, None]:
    """Generate deep analysis via LLM streaming."""
    yield _sse_event({"type": "analysis_start", "cached": False})

    # Build context from article
    context_parts = [f"标题: {article.title}"]
    if article.ai_summary:
        context_parts.append(f"摘要: {article.ai_summary}")
    if article.detailed_summary:
        context_parts.append(f"详细摘要: {article.detailed_summary}")
    if article.summary:
        context_parts.append(f"原始摘要: {article.summary}")
    if article.primary_category:
        context_parts.append(f"分类: {article.primary_category}")
    if article.sentiment_label:
        context_parts.append(f"情绪: {article.sentiment_label} ({article.sentiment_score})")

    context = "\n".join(context_parts)

    gateway = get_llm_gateway()
    request = ChatRequest(
        messages=[
            ChatMessage(role="system", content=DEEP_ANALYSIS_PROMPT),
            ChatMessage(role="user", content=context),
        ],
        temperature=0.3,
        max_tokens=3000,
    )

    full_content = ""
    try:
        async for event in gateway.chat_stream(request, purpose="analyzer"):
            if event.type == "content_delta" and event.data:
                full_content += event.data
                yield _sse_event({"type": "analysis_chunk", "content": event.data})

        # Cache the result
        from app.db.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(Article)
                .where(Article.id == article.id)
                .values(ai_analysis=full_content)
            )
            await session.commit()

        yield _sse_event({"type": "complete", "content": full_content})

    except Exception as e:
        logger.exception("SSE analysis generation failed for article %s", article.id)
        yield _sse_event({"type": "error", "message": str(e)})


def _sse_event(data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

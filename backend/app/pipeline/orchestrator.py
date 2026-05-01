"""Pipeline orchestrator — scheduling + dynamic agent pipeline execution.

Two responsibilities:
1. APScheduler-based scheduling for feed polling and cleanup.
2. Dynamic agent pipeline: classify -> route -> fetch -> agents -> store.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings, load_pipeline_config
from app.db.database import get_session_factory
from app.db.redis import get_redis
from app.pipeline import queue as q
from app.pipeline.dedup import DedupEngine
from app.sources.rss.native import NativeRSSSource
from app.sources.rss.rsshub import RSSHubSource

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


class ClassificationFailedError(RuntimeError):
    """Raised when classification falls back to default 'other'/value=0.

    Treated as a pipeline failure so the consumer triggers retry + circuit
    breaker rather than silently storing a partially-processed article.
    """


async def poll_feeds() -> None:
    """Poll all enabled RSS feeds and enqueue new articles."""
    from sqlalchemy import select, update
    from app.models.feed import Feed
    from app.models.article import Article

    factory = get_session_factory()
    redis = await get_redis()
    dedup = DedupEngine(redis)
    native_rss = NativeRSSSource()
    rsshub = RSSHubSource()

    async with factory() as session:
        result = await session.execute(
            select(Feed).where(Feed.is_enabled == True)  # noqa: E712
        )
        feeds = result.scalars().all()

    if not feeds:
        logger.debug("No enabled feeds to poll")
        return

    total_new = 0
    for feed in feeds:
        try:
            # Fetch articles based on feed type
            if feed.feed_type == "rsshub" and feed.rsshub_route:
                raw_articles = await rsshub.fetch_route(feed.rsshub_route)
            else:
                raw_articles = await native_rss.fetch_feed(feed.url)

            new_count = 0
            for raw in raw_articles:
                # Google News URLs are resolved lazily in the pipeline consumer,
                # not here. Dedup uses the Google redirect URL at poll-time so the
                # same redirect isn't re-enqueued; the consumer marks the real URL
                # as seen once resolution completes.
                is_dup, norm_url, detected_lang = await dedup.is_duplicate(raw.url, raw.title)
                if is_dup:
                    continue

                # Insert article
                article_id = uuid.uuid4()
                article_lang = raw.language or detected_lang
                async with factory() as session:
                    article = Article(
                        id=article_id,
                        source_id=feed.source_id,
                        feed_id=feed.id,
                        external_id=raw.external_id,
                        source_name=feed.title or raw.source_name,
                        title=raw.title,
                        url=norm_url,
                        published_at=raw.published_at,
                        language=article_lang,
                        summary=raw.summary,
                        authors=raw.authors,
                        top_image=raw.top_image,
                        content_status="pending",
                    )
                    session.add(article)
                    try:
                        await session.commit()
                    except Exception as e:
                        await session.rollback()
                        logger.debug("Insert failed for %s: %s", norm_url[:60], e)
                        continue  # Likely duplicate URL

                # Enqueue for pipeline processing
                await q.enqueue_article(redis, {
                    "article_id": str(article_id),
                    "url": norm_url,
                    "title": raw.title,
                    "summary": raw.summary or "",
                    "language": raw.language,
                    "source_name": feed.title or raw.source_name,
                })
                new_count += 1

            # Update feed stats
            async with factory() as session:
                await session.execute(
                    update(Feed)
                    .where(Feed.id == feed.id)
                    .values(
                        last_polled_at=datetime.now(timezone.utc),
                        consecutive_errors=0,
                        last_error=None,
                        article_count=Feed.article_count + new_count,
                    )
                )
                await session.commit()

            total_new += new_count
            if new_count > 0:
                logger.info("Feed '%s': %d new articles", feed.title or feed.url[:50], new_count)

        except Exception as e:
            logger.exception("Error polling feed: %s", feed.url[:50])
            async with factory() as session:
                await session.execute(
                    update(Feed)
                    .where(Feed.id == feed.id)
                    .values(
                        last_polled_at=datetime.now(timezone.utc),
                        consecutive_errors=Feed.consecutive_errors + 1,
                        last_error=str(e)[:500],
                    )
                )
                await session.commit()

    if total_new > 0:
        logger.info("Feed poll complete: %d new articles from %d feeds", total_new, len(feeds))


async def poll_api_sources() -> None:
    """Poll all enabled API-type news sources (e.g., Finnhub) and enqueue new articles.

    Unlike poll_feeds() which handles RSS/RSSHub feeds from the database,
    this function polls sources registered in the source registry with
    source_type == "api" and configuration in pipeline.yml.
    """
    from app.models.article import Article
    from app.sources.base import FetchParams

    config = load_pipeline_config()
    sources_config = config.get("sources", {})
    factory = get_session_factory()
    redis = await get_redis()
    dedup = DedupEngine(redis)

    from app.sources.registry import get_source_registry
    registry = get_source_registry()

    total_new = 0
    for source in registry.list_sources():
        if source.source_type != "api":
            continue

        source_cfg = sources_config.get(source.source_id, {})
        if not source_cfg.get("enabled", False):
            logger.debug("API source '%s' is disabled, skipping", source.source_id)
            continue

        try:
            # Build FetchParams from config
            symbols = source_cfg.get("default_symbols")
            params = FetchParams(symbols=symbols)

            raw_articles = await source.fetch(params)
            new_count = 0

            for raw in raw_articles:
                # Dedup check
                is_dup, norm_url, detected_lang = await dedup.is_duplicate(raw.url, raw.title)
                if is_dup:
                    continue

                # Build finance_metadata from source extra data
                finance_meta = {}
                if raw.extra:
                    if raw.extra.get("symbols"):
                        finance_meta["symbols"] = raw.extra["symbols"]
                    if raw.extra.get("market"):
                        finance_meta["market"] = raw.extra["market"]
                    if raw.extra.get("provider"):
                        finance_meta["provider"] = raw.extra["provider"]

                article_id = uuid.uuid4()
                article_lang = raw.language or detected_lang

                async with factory() as session:
                    article = Article(
                        id=article_id,
                        external_id=raw.external_id,
                        source_name=raw.source_name,
                        title=raw.title,
                        url=norm_url,
                        published_at=raw.published_at,
                        language=article_lang,
                        summary=raw.summary,
                        top_image=raw.top_image,
                        finance_metadata=finance_meta if finance_meta else None,
                        content_status="pending",
                    )
                    session.add(article)
                    try:
                        await session.commit()
                    except Exception as e:
                        await session.rollback()
                        logger.debug("Insert failed for %s: %s", norm_url[:60], e)
                        continue

                # Enqueue for pipeline processing
                await q.enqueue_article(redis, {
                    "article_id": str(article_id),
                    "url": norm_url,
                    "title": raw.title,
                    "summary": raw.summary or "",
                    "language": raw.language,
                    "source_name": raw.source_name,
                })
                new_count += 1

            total_new += new_count
            if new_count > 0:
                logger.info("API source '%s': %d new articles", source.source_id, new_count)

        except Exception:
            logger.exception("Error polling API source: %s", source.source_id)

    if total_new > 0:
        logger.info("API source poll complete: %d new articles", total_new)


async def poll_stockpulse_tier(tier: str) -> None:
    """Poll StockPulse for the full set of watched symbols.

    The ``tier`` argument is kept for the manual /admin trigger endpoint
    (which still accepts hot|warm|cold paths) but is ignored — every
    invocation polls every row in ``watched_symbols``. The single 5-minute
    scheduler job calls this with tier="hot" for backward compatibility.

    One tick:
      1. Read all watched_symbols rows
      2. Fetch most-recent N (default_limit) articles per symbol from
         StockPulse — no `since`, time window auto-adapts to news density
      3. Dedup by URL, insert pending articles, enqueue for the pipeline
    """
    from sqlalchemy import select, update
    from app.models.article import Article
    from app.models.watched_symbol import WatchedSymbol
    from app.sources.api.stockpulse import StockPulseSource
    from app.sources.base import FetchParams

    config = load_pipeline_config()
    sp_cfg = (config.get("sources") or {}).get("stockpulse") or {}
    if not sp_cfg.get("enabled", False):
        logger.debug("StockPulse source disabled in pipeline.yml, skipping tier=%s", tier)
        return

    per_symbol_limit = int(sp_cfg.get("default_limit", 10))

    factory = get_session_factory()
    now = datetime.now(timezone.utc)

    # All tiers poll the same symbol set on the same cadence (limit-only
    # fetch makes hot/warm/cold split pointless). The `tier` argument is
    # accepted for backward compatibility with the /admin manual trigger
    # but is otherwise ignored.
    if tier not in ("hot", "warm", "cold"):
        logger.warning("Unknown StockPulse tier: %s", tier)
        return
    async with factory() as session:
        stmt = select(WatchedSymbol)
        rows = (await session.execute(stmt)).scalars().all()

    if not rows:
        logger.debug("StockPulse tier=%s: no watched symbols", tier)
        return

    # Build one fetch per (symbol, market) pair. We use the StockPulseSource
    # directly with explicit per-call market (rather than its auto-inference)
    # so the registry can stay symbol-list-agnostic.
    source = StockPulseSource.from_settings()
    # Override per-symbol limit from config
    source._per_symbol_limit = per_symbol_limit

    if not source.is_configured:
        logger.warning("StockPulse not configured; skipping tier=%s", tier)
        return

    # Deduplicate symbols across consumers — multiple consumers may watch
    # the same ticker; we only need to fetch it once from StockPulse.
    seen_syms: set[str] = set()
    symbols: list[str] = []
    for w in rows:
        if w.symbol not in seen_syms:
            seen_syms.add(w.symbol)
            symbols.append(w.symbol)

    # No `since` — fetch the most recent N (per_symbol_limit) per symbol.
    # The time span auto-adapts to news density (hot ticker → narrow window,
    # cold ticker → wide window). NewsForge dedup handles repeat articles
    # on subsequent polls. Stored `market` from watched_symbols overrides
    # StockPulseSource's inference when they disagree (e.g. consumer knows
    # something inference can't, like a custom ticker class).
    raw_articles: list = []
    fetch_start = time.monotonic()
    try:
        params = FetchParams(symbols=symbols)
        raw_articles = await source.fetch(params)
    except Exception:
        logger.exception("StockPulse bulk fetch failed for tier=%s", tier)
        raw_articles = []
    fetch_ms = (time.monotonic() - fetch_start) * 1000

    if not raw_articles:
        logger.info(
            "StockPulse tier=%s: 0 articles for %d symbols (%.0fms)",
            tier, len(symbols), fetch_ms,
        )
        # Still bump last_polled_at so we can see the scheduler is running.
        async with factory() as session:
            await session.execute(
                update(WatchedSymbol)
                .where(WatchedSymbol.symbol.in_(symbols))
                .values(last_polled_at=now, last_error=None)
            )
            await session.commit()
        return

    redis = await get_redis()
    dedup = DedupEngine(redis)

    new_count = 0
    dup_count = 0
    err_count = 0

    for raw in raw_articles:
        try:
            is_dup, norm_url, detected_lang = await dedup.is_duplicate(raw.url, raw.title)
            if is_dup:
                dup_count += 1
                continue

            finance_meta: dict[str, Any] = {}
            if raw.extra:
                if raw.extra.get("symbols"):
                    finance_meta["symbols"] = raw.extra["symbols"]
                if raw.extra.get("provider"):
                    finance_meta["provider"] = raw.extra["provider"]
                if raw.extra.get("stockpulse_source"):
                    finance_meta["stockpulse_source"] = raw.extra["stockpulse_source"]
                if raw.extra.get("raw_payload"):
                    finance_meta["raw_payload"] = raw.extra["raw_payload"]

            article_id = uuid.uuid4()
            article_lang = raw.language or detected_lang
            async with factory() as session:
                article = Article(
                    id=article_id,
                    external_id=raw.external_id,
                    source_name=raw.source_name,
                    title=raw.title,
                    url=norm_url,
                    published_at=raw.published_at,
                    language=article_lang,
                    summary=raw.summary,
                    top_image=raw.top_image,
                    finance_metadata=finance_meta or None,
                    content_status="pending",
                )
                session.add(article)
                try:
                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    logger.debug(
                        "StockPulse insert failed for %s: %s", norm_url[:80], e,
                    )
                    dup_count += 1
                    continue

            await q.enqueue_article(redis, {
                "article_id": str(article_id),
                "url": norm_url,
                "title": raw.title,
                "summary": raw.summary or "",
                "language": raw.language,
                "source_name": raw.source_name,
            })
            new_count += 1
        except Exception:
            logger.exception("StockPulse ingest error for %s", raw.url[:80])
            err_count += 1

    # Bump last_polled_at on the watched symbols we just polled
    async with factory() as session:
        await session.execute(
            update(WatchedSymbol)
            .where(WatchedSymbol.symbol.in_(symbols))
            .values(last_polled_at=now, last_error=None)
        )
        await session.commit()

    logger.info(
        "StockPulse tier=%s: %d new / %d dup / %d err from %d articles "
        "across %d symbols (%.0fms)",
        tier, new_count, dup_count, err_count,
        len(raw_articles), len(symbols), fetch_ms,
    )


async def cleanup_old_articles() -> None:
    """Delete articles older than retention period."""
    from datetime import timedelta
    from sqlalchemy import delete
    from app.models.article import Article
    from app.models.pipeline_event import PipelineEvent

    config = load_pipeline_config()
    scheduler_config = config.get("scheduler", {})
    article_days = scheduler_config.get("article_retention_days", 30)
    event_days = scheduler_config.get("pipeline_event_retention_days", 7)

    factory = get_session_factory()
    now = datetime.now(timezone.utc)

    async with factory() as session:
        # Clean old articles
        cutoff = now - timedelta(days=article_days)
        result = await session.execute(
            delete(Article).where(Article.created_at < cutoff)
        )
        article_count = result.rowcount

        # Clean old pipeline events
        event_cutoff = now - timedelta(days=event_days)
        result = await session.execute(
            delete(PipelineEvent).where(PipelineEvent.created_at < event_cutoff)
        )
        event_count = result.rowcount

        await session.commit()

    if article_count or event_count:
        logger.info("Cleanup: removed %d articles, %d pipeline events", article_count, event_count)


async def _clean_content(raw_text: str, title: str) -> tuple[str, int]:
    """Clean fetched article content via LLM, removing boilerplate and noise.

    Returns (cleaned_text, tokens_used). On error, returns original text + 0.
    """
    from app.core.llm.gateway import get_llm_gateway
    from app.core.llm.types import ChatMessage, ChatRequest
    from app.pipeline.agents.base import SHARED_SYSTEM_PROMPT

    task_instructions = (
        "## 任务：内容清洗\n\n"
        "清洗以上新闻正文，原样保留正文内容，仅移除噪声。\n\n"
        "移除以下所有类型的噪声：\n"
        "- 导航菜单、面包屑、页眉页脚模板\n"
        "- 广告、cookie提示、订阅弹窗、付费墙提示\n"
        "- 社交按钮及文字（Share、Save、Like、Comment、分享到、收藏等）\n"
        "- 视频/音频播放器控件（Play、Watch、Pause、Next video、时间戳等）\n"
        "- 平台小组件（\"Add as preferred on Google\"、\"Download the app\"等）\n"
        "- \"相关文章\"、\"推荐阅读\"、\"更多新闻\"推荐区块\n"
        "- 版权声明模板、免责声明\n"
        "- 相对时间戳（\"6 minutes ago\"、\"2小时前\"等）\n"
        "- 作者署名行和作者职位描述（\"XXX reporter\"、\"记者 XXX\"等），这些信息已在元数据中\n"
        "- 纯图源/版权署名行：仅由机构名构成且没有任何描述性内容的图源标注（如孤立成行的"
        " \"Getty Images\"、\"Reuters\"、\"AP\"、\"AFP\"、\"Bloomberg\"、\"新华社\"，或 "
        "\"Photo by John Doe / Reuters\"、\"图源：路透\" 这类纯署名格式）整行删除；"
        "**但图片的描述性说明（caption）必须保留**——例如 \"特朗普在白宫记者会上发言\"、"
        "\"图为发布会现场\"、\"该卫星于2026年4月发射\" 等说明文字属于正文，不要删\n\n"
        "保留：文章正文段落、数据表格、引用块、正文内嵌的人名提及、正文配图、配图的描述性说明文字。\n\n"
        "图片规则（最高优先级，必须严格遵守）：\n"
        "- 所有 ![alt](url) 格式的Markdown图片引用必须**逐字保留**（包括URL、alt文本均不得改动），"
        "  除非URL明显是logo/图标/占位符（含 placeholder、1x1 追踪像素，或 URL 以 data: 开头）\n"
        "- 图片的描述性说明（介绍图片内容的文字）原文有就**逐字保留**，原文无就**不要凭空生成**\n"
        "- **严禁自行添加版权署名**：原文没有独立的图源行时，不要在图片上下方写入 *Getty Images*、"
        "  *Reuters*、*路透*、*图源：XXX* 等署名，即使图片 alt 中含有 \"getty\"、\"reuters\" 等词也不要据此补充\n"
        "- 原文已有的独立图源署名行按上一节规则整行删除，但**与说明文字混排时**（如"
        " \"图为现场情况。图源：路透\"），仅删除\"图源：路透\"部分，保留描述句\n"
        "- 严禁编造、替换、翻译或生成任何图片URL或alt文本\n\n"
        "重要：不要对正文做任何改写、总结、缩写或重组。"
        "清洗后的内容必须与原文逐字一致，只是去掉了噪声部分。\n\n"
        "不要输出与元数据中标题重复的标题行（即原文开头的 # 标题），但保留副标题（##）和正文开头的图片。\n"
        "直接输出清洗后的Markdown正文，不要添加任何解释或标记。"
    )

    user_content = f"# {title}\n\n{raw_text}\n\n---\n\n{task_instructions}"

    request = ChatRequest(
        messages=[
            ChatMessage(role="system", content=SHARED_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ],
    )

    try:
        llm = get_llm_gateway()
        response = await llm.chat(request, purpose="cleaner")
        # Cleaner succeeded — record success on its cb purpose.
        try:
            from app.db.redis import get_redis
            from app.pipeline import circuit_breaker as cb
            await cb.record_success(await get_redis(), "cleaner")
        except Exception:
            logger.debug("Failed to record cleaner cb success", exc_info=True)
        return response.content, response.usage.total_tokens
    except Exception as e:
        logger.warning("Content cleaning failed for '%s', using raw text", title[:60], exc_info=True)
        # Attribute LLM failures to the cleaner purpose so the cb can trip.
        from app.core.llm.types import LLMCallError
        if isinstance(e, LLMCallError):
            try:
                from app.db.redis import get_redis
                from app.pipeline import circuit_breaker as cb
                from app.core.config import load_pipeline_config
                threshold = load_pipeline_config().get("consumer", {}).get(
                    "circuit_breaker_failure_threshold", cb.DEFAULT_FAILURE_THRESHOLD,
                )
                await cb.record_failure(await get_redis(), "cleaner", failure_threshold=threshold)
            except Exception:
                logger.debug("Failed to record cleaner cb failure", exc_info=True)
        return raw_text, 0


async def run_pipeline(article_id: str, article_data: dict, progress_callback=None) -> dict[str, Any]:
    """Run the full dynamic agent pipeline for one article.

    Phase 1: Content fetch (Crawl4AI with fallback chain)
    Phase 2: Content cleaning (LLM boilerplate removal)
    Phase 3: Classification (multi-label + value scoring + market impact) on cleaned full text
    Phase 4: Dynamic agents (parallel via asyncio.gather, respecting dependencies)

    Returns a dict with all pipeline results for DB storage.
    """
    from app.pipeline.classifier import classify_articles
    from app.content.fetcher import fetch_content
    from app.pipeline.agents.registry import get_agent_registry
    from app.pipeline.events import record_event

    async def _report_progress(stage: str):
        if progress_callback:
            try:
                await progress_callback(stage)
            except Exception:
                logger.debug("Progress callback failed for stage %s", stage)

    pipeline_start = time.monotonic()
    url = article_data.get("url", "")
    title = article_data.get("title", "")
    summary = article_data.get("summary", "")

    logger.info("Pipeline start: %s", title[:80])
    results: dict[str, Any] = {"article_id": article_id, "agents": {}}
    checkpoint = article_data.get("_checkpoint")
    article_data.setdefault("_checkpoint", {})

    # --- Phase 1: Content fetch ---
    await _report_progress("fetch")
    content = None
    rss_full_text = article_data.get("rss_full_text")
    rss_language = article_data.get("language")
    rss_authors = article_data.get("authors")
    rss_title = article_data.get("rss_title")

    if checkpoint and "content" in checkpoint:
        # Restore content from checkpoint
        results["content"] = checkpoint["content"]
        if checkpoint["content"] is not None:
            from types import SimpleNamespace
            content = SimpleNamespace(
                full_text=checkpoint.get("content_full_text", ""),
                language=checkpoint.get("content_language"),
                provider=checkpoint["content"].get("provider", "checkpoint"),
                word_count=checkpoint["content"].get("word_count", 0),
            )
        else:
            content = None
        logger.info("Restored content from checkpoint")
    else:
        fetch_start = time.monotonic()
        if url:
            content = await fetch_content(
                url,
                rss_full_text=rss_full_text,
                rss_language=rss_language,
                rss_authors=rss_authors if isinstance(rss_authors, list) else None,
                rss_title=rss_title,
            )
        fetch_ms = (time.monotonic() - fetch_start) * 1000

        if content:
            results["content"] = {
                "provider": content.provider,
                "word_count": content.word_count,
                "language": content.language,
                "final_url": content.final_url,
            }
            await record_event(
                article_id, "fetch", "success",
                duration_ms=fetch_ms,
                metadata={"provider": content.provider, "word_count": content.word_count},
            )
        else:
            results["content"] = None
            logger.warning("Content fetch failed for %s", url[:80] if url else "(no url)")
            await record_event(
                article_id, "fetch", "error" if url else "skip",
                duration_ms=fetch_ms,
                error=f"All content providers failed for {url[:100]}" if url else "No URL provided",
            )

    # Save content to checkpoint
    if not checkpoint or "content" not in (checkpoint or {}):
        article_data["_checkpoint"]["content"] = results.get("content")
        if content and content.full_text:
            article_data["_checkpoint"]["content_full_text"] = content.full_text
            article_data["_checkpoint"]["content_language"] = content.language

    # --- Dedup: check resolved URL before spending LLM tokens ---
    final_url = results.get("content", {}).get("final_url") if results.get("content") else None
    original_url = article_data.get("url")
    if final_url and original_url and final_url != original_url:
        from sqlalchemy import select as sql_select, update as sql_update
        from app.models.article import Article
        from app.pipeline.dedup import is_live_update_url

        redis = await get_redis()
        dedup = DedupEngine(redis)
        seen, norm_real = await dedup.is_url_seen(final_url)
        existing_id = None
        # Always verify against DB — Redis key alone is not enough
        # (key may exist from a prior fetch of the same batch, but
        #  the article itself may not have been stored yet)
        async with get_session_factory()() as chk_session:
            existing_id = (await chk_session.execute(
                sql_select(Article.id).where(
                    Article.url == norm_real,
                    Article.id != article_id,
                )
            )).scalar_one_or_none()
        if existing_id:
            seen = True
        elif seen:
            # Redis says seen but DB has no matching article — false positive
            logger.info(
                "Redis dedup key exists but no DB article for %s, allowing",
                norm_real[:80],
            )
            seen = False

        if seen and is_live_update_url(norm_real):
            # Live-update pages change content while keeping the same URL.
            # Supersede the old article so the fresh version gets processed.
            if not existing_id:
                async with get_session_factory()() as chk_session:
                    existing_id = (await chk_session.execute(
                        sql_select(Article.id).where(
                            Article.url == norm_real,
                            Article.id != article_id,
                        )
                    )).scalar_one_or_none()
            if existing_id:
                async with get_session_factory()() as sup_session:
                    # Append suffix to old URL to free the unique constraint
                    # for the new article that will claim the resolved URL.
                    await sup_session.execute(
                        sql_update(Article)
                        .where(Article.id == existing_id)
                        .values(
                            content_status="superseded",
                            url=norm_real + f"#superseded-{str(existing_id)[:8]}",
                        )
                    )
                    await sup_session.commit()
                logger.info(
                    "Live-update URL: superseded old article %s, re-processing %s: %s",
                    str(existing_id)[:8], article_id[:8], norm_real[:80],
                )
            await record_event(
                article_id, "dedup", "live_update_refresh",
                metadata={"resolved_url": norm_real[:200], "superseded": str(existing_id) if existing_id else None},
            )
            # Let this article proceed — it will get the resolved URL below
            seen = False

        if seen:
            logger.info(
                "Resolved URL already exists, marking %s as duplicate early: %s",
                article_id[:8], norm_real[:80],
            )
            await record_event(
                article_id, "dedup", "duplicate",
                metadata={"resolved_url": norm_real[:200]},
            )
            async with get_session_factory()() as dup_session:
                await dup_session.execute(
                    sql_update(Article)
                    .where(Article.id == article_id)
                    .values(content_status="duplicate")
                )
                await dup_session.commit()
            results["duplicate"] = True
            results["pipeline_duration_ms"] = (time.monotonic() - pipeline_start) * 1000
            return results
        # Not a duplicate — record the resolved URL for consumer to UPDATE
        results["_url_resolved"] = norm_real
        await dedup.mark_url_seen(final_url)
        await dedup.mark_url_seen(original_url)

    # --- Phase 2: Content cleaning ---
    await _report_progress("clean")
    cleaned_text = None

    if checkpoint and "cleaned_text" in checkpoint:
        # Restore cleaned text from checkpoint
        cleaned_text = checkpoint["cleaned_text"]
        results["cleaned_text"] = cleaned_text
        logger.info("Restored cleaned text from checkpoint (%d chars)", len(cleaned_text) if cleaned_text else 0)
    elif content and content.full_text:
        clean_start = time.monotonic()
        cleaned_text, clean_tokens = await _clean_content(content.full_text, title)
        clean_ms = (time.monotonic() - clean_start) * 1000
        results["cleaned_text"] = cleaned_text
        await record_event(
            article_id, "clean", "success",
            duration_ms=clean_ms,
            metadata={"tokens": clean_tokens},
        )
        logger.info("Content cleaned: %d→%d chars (%.0fms)", len(content.full_text), len(cleaned_text), clean_ms)
    else:
        results["cleaned_text"] = None

    # Save cleaned text to checkpoint
    if not checkpoint or "cleaned_text" not in (checkpoint or {}):
        article_data["_checkpoint"]["cleaned_text"] = cleaned_text

    # --- Phase 2b: Embedding + Semantic Dedup ---
    await _report_progress("embedding")
    from app.pipeline.agents.embedder import generate_embedding
    from app.pipeline.dedup import semantic_dedup, store_embedding

    embed_source_text = cleaned_text or (content.full_text if content else None)

    embedding_from_checkpoint = bool(checkpoint and "embedding" in checkpoint)
    if embedding_from_checkpoint:
        embedding_result = checkpoint["embedding"]
        logger.info("Restored embedding from checkpoint")
    else:
        embedding_result = await generate_embedding(
            title=title,
            summary=summary,
            cleaned_text=embed_source_text,
        )
        embed_status = "success" if embedding_result["success"] else "error"
        await record_event(
            article_id, "embedding", embed_status,
            duration_ms=embedding_result["duration_ms"],
            metadata={
                "tokens": embedding_result["tokens_used"],
                "model": embedding_result["model"],
            },
            error=embedding_result.get("error"),
        )

    results["embedding"] = embedding_result

    # Save embedding to checkpoint (without the full vector to keep payload small)
    if not checkpoint or "embedding" not in (checkpoint or {}):
        checkpoint_embed = {k: v for k, v in embedding_result.items() if k != "embedding"}
        checkpoint_embed["_has_embedding"] = bool(embedding_result.get("embedding"))
        article_data["_checkpoint"]["embedding"] = checkpoint_embed

    # Semantic dedup: compare embedding against recent articles
    # Skip if restored from checkpoint (dedup was already done on first run)
    if not embedding_from_checkpoint and embedding_result.get("success") and embedding_result.get("embedding"):
        embed_vec = embedding_result["embedding"]

        # Store embedding in document_embeddings table first
        try:
            await store_embedding(
                article_id,
                embed_vec,
                chunk_text=embedding_result.get("embed_text", "")[:2000],
                model=embedding_result.get("model", "unknown"),
                token_count=embedding_result.get("tokens_used"),
            )
        except Exception:
            logger.warning("Failed to store embedding for %s", article_id[:8], exc_info=True)

        # Read dedup thresholds from config
        pipeline_config = load_pipeline_config()
        dedup_config = pipeline_config.get("dedup", {})
        dedup_threshold = dedup_config.get("semantic_threshold", 0.95)
        group_threshold = dedup_config.get("event_group_threshold", 0.88)
        semantic_window = dedup_config.get("semantic_window_hours", 12)

        try:
            dedup_result = await semantic_dedup(
                article_id,
                embed_vec,
                dedup_threshold=dedup_threshold,
                group_threshold=group_threshold,
                window_hours=semantic_window,
            )
        except Exception:
            logger.warning("Semantic dedup failed for %s, proceeding", article_id[:8], exc_info=True)
            dedup_result = {"action": "new", "event_group_id": str(uuid.uuid4()), "similarity": None}

        results["semantic_dedup"] = dedup_result

        if dedup_result["action"] == "duplicate":
            logger.info(
                "Semantic dedup: article %s is duplicate of %s (cosine=%.4f)",
                article_id[:8], dedup_result["matched_article_id"][:8],
                dedup_result["similarity"],
            )
            await record_event(
                article_id, "semantic_dedup", "duplicate",
                metadata={
                    "matched_article_id": dedup_result["matched_article_id"],
                    "similarity": dedup_result["similarity"],
                },
            )
            from sqlalchemy import update as sql_update
            from app.models.article import Article
            async with get_session_factory()() as dup_session:
                await dup_session.execute(
                    sql_update(Article)
                    .where(Article.id == article_id)
                    .values(content_status="duplicate")
                )
                await dup_session.commit()
            results["duplicate"] = True
            results["pipeline_duration_ms"] = (time.monotonic() - pipeline_start) * 1000
            return results

        elif dedup_result["action"] == "group":
            logger.info(
                "Semantic dedup: article %s grouped with %s (cosine=%.4f)",
                article_id[:8], dedup_result["matched_article_id"][:8],
                dedup_result["similarity"],
            )
            await record_event(
                article_id, "semantic_dedup", "grouped",
                metadata={
                    "matched_article_id": dedup_result["matched_article_id"],
                    "event_group_id": dedup_result["event_group_id"],
                    "similarity": dedup_result["similarity"],
                },
            )
            results["event_group_id"] = dedup_result["event_group_id"]
        else:
            # New event
            await record_event(
                article_id, "semantic_dedup", "new",
                metadata={"similarity": dedup_result.get("similarity")},
            )
            results["event_group_id"] = dedup_result["event_group_id"]
    elif not embedding_from_checkpoint:
        # Embedding failed (not a checkpoint restore) — assign new group
        results["event_group_id"] = str(uuid.uuid4())

    # --- Phase 3: Classification (uses cleaned full text to prime prompt cache) ---
    await _report_progress("classify")

    classifier_full_text = cleaned_text if cleaned_text else (content.full_text if content else None)

    classify_ran = False
    if checkpoint and "classification" in checkpoint:
        results["classification"] = checkpoint["classification"]
        categories = [c["slug"] for c in checkpoint["classification"]["categories"]]
        value_score = checkpoint["classification"]["value_score"]
        has_market_impact = checkpoint["classification"]["has_market_impact"]
        logger.info(
            "Restored classification from checkpoint: categories=%s value=%d",
            categories, value_score,
        )
        is_default = (
            checkpoint["classification"].get("primary_category") == "other"
            and value_score == 0
        )
    else:
        classify_ran = True
        classify_start = time.monotonic()
        classify_input = {"title": title, "summary": summary}
        if classifier_full_text:
            classify_input["full_text"] = classifier_full_text
        try:
            classify_results = await classify_articles([classify_input])
        except Exception as e:
            from app.core.llm.types import LLMCallError
            if isinstance(e, LLMCallError):
                try:
                    from app.db.redis import get_redis as _get_redis
                    from app.pipeline import circuit_breaker as cb
                    threshold = load_pipeline_config().get("consumer", {}).get(
                        "circuit_breaker_failure_threshold", cb.DEFAULT_FAILURE_THRESHOLD,
                    )
                    await cb.record_failure(
                        await _get_redis(), "classifier", failure_threshold=threshold,
                    )
                except Exception:
                    logger.debug("Failed to record classifier cb failure", exc_info=True)
            raise
        classification = classify_results[0]
        classify_ms = (time.monotonic() - classify_start) * 1000

        categories = classification.category_slugs
        value_score = classification.value_score
        has_market_impact = classification.has_market_impact

        results["classification"] = {
            "categories": [{"slug": c.slug, "confidence": c.confidence} for c in classification.categories],
            "primary_category": classification.primary_category,
            "tags": classification.tags,
            "industry_tags": classification.industry_tags,
            "event_tags": classification.event_tags,
            "value_score": value_score,
            "value_dimensions": classification.value_dimensions.to_dict(),
            "value_reason": classification.value_reason,
            "has_market_impact": has_market_impact,
            "market_impact_hint": classification.market_impact_hint,
        }

        is_default = classification.primary_category == "other" and value_score == 0
        classify_status = "warning" if is_default else "success"
        await record_event(
            article_id, "classify", classify_status,
            duration_ms=classify_ms,
            metadata={
                "categories": categories,
                "value_score": value_score,
                "has_market_impact": has_market_impact,
                "used_full_text": classifier_full_text is not None,
            },
            error="Classification returned defaults — LLM may have failed" if is_default else None,
        )

        logger.info(
            "Classified: categories=%s value=%d market_impact=%s full_text=%s (%.0fms)",
            categories, value_score, has_market_impact,
            bool(classifier_full_text), classify_ms,
        )

    # Only checkpoint successful classifications — defaults should re-run on retry.
    if not is_default and (not checkpoint or "classification" not in (checkpoint or {})):
        article_data["_checkpoint"]["classification"] = results["classification"]

    # Update classifier cb based on outcome (only when we just ran classify, not on
    # a checkpoint restore — the failure/success was already recorded then).
    if classify_ran:
        try:
            from app.db.redis import get_redis as _get_redis
            from app.pipeline import circuit_breaker as cb
            if is_default:
                threshold = load_pipeline_config().get("consumer", {}).get(
                    "circuit_breaker_failure_threshold", cb.DEFAULT_FAILURE_THRESHOLD,
                )
                await cb.record_failure(
                    await _get_redis(), "classifier", failure_threshold=threshold,
                )
            else:
                await cb.record_success(await _get_redis(), "classifier")
        except Exception:
            logger.debug("Failed to record classifier cb outcome", exc_info=True)

    if is_default:
        # Raise so the article is treated as failed and re-enqueued for retry.
        # Keeping fetch/clean checkpoints means the retry won't re-fetch — only classify reruns.
        raise ClassificationFailedError(
            f"Classification returned defaults for {title[:80]}"
        )

    # --- Phase 4: Dynamic agents (tiered: P1 blocking + P2 fire-and-forget) ---
    await _report_progress("agents")
    registry = get_agent_registry()

    # Look up source/feed categories for finance_analyzer trigger logic
    source_categories: list[str] = []
    try:
        from app.db.database import get_session_factory as _gsf
        _factory = _gsf()
        async with _factory() as _sess:
            from sqlalchemy import text as _text
            _row = await _sess.execute(_text(
                "SELECT c.slug FROM articles a "
                "JOIN feeds f ON a.feed_id = f.id "
                "JOIN categories c ON f.category_id = c.id "
                "WHERE a.id = :aid"
            ), {"aid": article_id})
            _cat = _row.scalar_one_or_none()
            if _cat:
                source_categories = [_cat]
    except Exception:
        pass  # Feed may not have a category set — that's fine

    p1_agent_ids, p2_agent_ids = registry.resolve_agents_tiered(
        categories, value_score, has_market_impact, source_categories
    )

    all_resolved_ids = p1_agent_ids + p2_agent_ids
    if not all_resolved_ids:
        logger.info("No agents resolved for article (value=%d): %s", value_score, title[:60])
        results["pipeline_duration_ms"] = (time.monotonic() - pipeline_start) * 1000
        return results

    # Read per-agent checkpoint from Redis Hash
    checkpoint_key = f"nf:agent:checkpoint:{article_id}"
    redis = await get_redis()
    try:
        raw_checkpoint = await redis.hgetall(checkpoint_key)
    except Exception:
        logger.warning(
            "Failed to read agent checkpoint for %s, running all agents",
            article_id[:8], exc_info=True,
        )
        raw_checkpoint = {}
    completed_from_checkpoint: dict[str, dict] = {}
    failed_agent_ids: set[str] = set()
    if raw_checkpoint:
        for aid_raw, data_raw in raw_checkpoint.items():
            aid = aid_raw.decode() if isinstance(aid_raw, bytes) else aid_raw
            try:
                parsed = json.loads(data_raw if isinstance(data_raw, str) else data_raw.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning(
                    "Corrupt checkpoint entry for %s agent %s, skipping",
                    article_id[:8], aid,
                )
                continue
            if parsed.get("success"):
                completed_from_checkpoint[aid] = parsed
            else:
                failed_agent_ids.add(aid)

    if completed_from_checkpoint:
        for aid, adata in completed_from_checkpoint.items():
            results["agents"][aid] = adata
        logger.info(
            "Restored %d agent results from checkpoint: %s",
            len(completed_from_checkpoint), list(completed_from_checkpoint.keys()),
        )

    # Filter out already-completed agents (checkpoint) from P1 and P2
    def _needs_run(agent_id: str) -> bool:
        if agent_id in completed_from_checkpoint and agent_id not in failed_agent_ids:
            agent_def = registry.get_agent(agent_id)
            if agent_def:
                dep_needs_rerun = any(dep in failed_agent_ids for dep in agent_def.requires)
                if not dep_needs_rerun:
                    return False
        return True

    p1_to_run = [aid for aid in p1_agent_ids if _needs_run(aid)]
    p2_to_run = [aid for aid in p2_agent_ids if _needs_run(aid)]

    if not p1_to_run and not p2_to_run:
        logger.info("All agents already completed from checkpoint")
        results["pipeline_duration_ms"] = (time.monotonic() - pipeline_start) * 1000
        return results

    # Build serializable context for the agent worker
    full_text = cleaned_text if cleaned_text else (content.full_text if content else None)
    context_data = {
        "article_id": article_id,
        "title": title,
        "summary": summary,
        "full_text": full_text,
        "language": content.language if content else rss_language,
        "categories": categories,
        "has_market_impact": has_market_impact,
        "value_score": value_score,
        "url": url,
        "source_name": article_data.get("source_name"),
    }

    from app.pipeline import agent_queue as aq

    p1_results: dict[str, dict] = {}

    # --- Phase 4a: Submit P1 group (blocking wait) ---
    if p1_to_run:
        p1_group_id, p1_result_key = await aq.submit_agent_group(
            redis,
            group_type="article",
            context_data=context_data,
            agents=p1_to_run,
            prior_results=completed_from_checkpoint,
        )
        logger.info(
            "P1 agent group submitted: %s agents=%s (group=%s)",
            title[:50], p1_to_run, p1_group_id[:8],
        )

        p1_results = await aq.wait_results(redis, p1_result_key)

        if p1_results is None:
            raise RuntimeError(
                f"Agent worker did not respond (P1) for article: {title[:80]}"
            )
        if "_error" in p1_results:
            raise RuntimeError(
                f"Agent worker error P1 ({p1_results['_error']}) for article: {title[:80]}"
            )

        for aid, result_data in p1_results.items():
            results["agents"][aid] = result_data

    # --- Phase 4b: Submit P2 group (fire-and-forget) ---
    p2_group_id = None
    if p2_to_run:
        # P2 gets checkpoint + P1 results as prior_results (for dependency resolution)
        p2_prior = {**completed_from_checkpoint, **p1_results}
        p2_group_id, _ = await aq.submit_agent_group(
            redis,
            group_type="article",
            context_data=context_data,
            agents=p2_to_run,
            prior_results=p2_prior,
            fire_and_forget=True,
        )
        logger.info(
            "P2 agent group submitted (fire-and-forget): %s agents=%s (group=%s)",
            title[:50], p2_to_run, p2_group_id[:8],
        )

    # Checkpoint cleanup: only if no P2 group was submitted.
    # P2 worker will clean up after it finishes.
    if not p2_to_run:
        try:
            await redis.delete(checkpoint_key)
        except Exception:
            logger.debug("Failed to cleanup agent checkpoint for %s", article_id[:8])

    total_duration = (time.monotonic() - pipeline_start) * 1000
    results["pipeline_duration_ms"] = total_duration
    if p2_group_id:
        results["_p2_group_id"] = p2_group_id

    p1_tokens = sum(
        r.get("tokens_used", 0) for r in p1_results.values()
        if isinstance(r, dict) and r.get("success")
    )
    p1_ok = sum(1 for r in p1_results.values() if isinstance(r, dict) and r.get("success"))
    p1_fail = sum(1 for r in p1_results.values() if isinstance(r, dict) and not r.get("success"))

    logger.info(
        "Pipeline P1 complete: %s | %d agents (%d ok, %d fail) | %d tokens | %.0fms%s",
        title[:50], p1_ok + p1_fail, p1_ok, p1_fail, p1_tokens, total_duration,
        f" | P2 pending: {p2_to_run}" if p2_to_run else "",
    )

    await _report_progress("complete")

    return results



def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler."""
    config = load_pipeline_config()
    scheduler_config = config.get("scheduler", {})

    poll_interval = scheduler_config.get("feed_poll_interval_seconds", 300)
    cleanup_hours = scheduler_config.get("cleanup_interval_hours", 24)

    # API source poll interval (from sources.finnhub.poll_interval_seconds, default 600s)
    sources_config = config.get("sources", {})
    api_poll_interval = sources_config.get("finnhub", {}).get("poll_interval_seconds", 600)

    scheduler = AsyncIOScheduler()

    # Feed polling (default: every 5 minutes)
    scheduler.add_job(
        poll_feeds,
        "interval",
        seconds=poll_interval,
        id="poll_feeds",
        name="Poll RSS feeds",
        misfire_grace_time=60,
        coalesce=True,
        max_instances=1,
    )

    # API source polling — Finnhub and other API-type sources (default: every 10 minutes)
    scheduler.add_job(
        poll_api_sources,
        "interval",
        seconds=api_poll_interval,
        id="poll_api_sources",
        name="Poll API news sources (Finnhub, etc.)",
        misfire_grace_time=120,
        coalesce=True,
        max_instances=1,
    )

    # Cleanup (default: daily)
    scheduler.add_job(
        cleanup_old_articles,
        "interval",
        hours=cleanup_hours,
        id="cleanup",
        name="Cleanup old articles",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    # StockPulse polling — single job that fans out to every row in
    # watched_symbols every N minutes. limit-only fetch (no since), so
    # there's no value in splitting hot/warm/cold tiers; one symbol set,
    # one cadence. Internally we still call poll_stockpulse_tier("hot")
    # for backward compatibility with the manual /admin trigger endpoint.
    sp_cfg = sources_config.get("stockpulse", {}) or {}
    sp_tiers = sp_cfg.get("tiers", {}) or {}
    if sp_cfg.get("enabled", False):
        # Use the hot-tier interval as the single poll cadence; hot subset
        # naturally widens to "all rows" once warm/cold windows are long.
        # Manual trigger endpoint still accepts hot|warm|cold paths but they
        # all hit the same code path.
        for tier_name, default_interval in (("hot", 5),):
            tier_conf = sp_tiers.get(tier_name) or {}
            interval_minutes = int(tier_conf.get("interval_minutes", default_interval))
            scheduler.add_job(
                poll_stockpulse_tier,
                "interval",
                minutes=interval_minutes,
                args=[tier_name],
                id=f"stockpulse_{tier_name}",
                name=f"StockPulse poll ({tier_name})",
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
            )

    # Deactivate stale stories (every 6 hours)
    from app.services.story_service import deactivate_stale_stories

    scheduler.add_job(
        deactivate_stale_stories,
        "interval",
        hours=6,
        id="deactivate_stale_stories",
        name="Deactivate stale stories",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    # Merge duplicate stories (every 6 hours)
    from app.services.story_service import merge_similar_stories

    scheduler.add_job(
        merge_similar_stories,
        "interval",
        hours=6,
        id="merge_stories",
        name="Merge duplicate stories",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    # Refresh stories with pending articles (fallback for threshold misses)
    from app.services.story_service import refresh_pending_stories

    refresh_cfg = config.get("story_refresh", {}) or {}
    refresh_interval_hours = int(refresh_cfg.get("fallback_interval_hours", 1))
    scheduler.add_job(
        refresh_pending_stories,
        "interval",
        hours=refresh_interval_hours,
        id="refresh_pending_stories",
        name="Refresh stories with pending articles",
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    return _scheduler



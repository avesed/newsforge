"""Pipeline orchestrator — scheduling + dynamic agent pipeline execution.

Two responsibilities:
1. APScheduler-based scheduling for feed polling and cleanup.
2. Dynamic agent pipeline: classify -> route -> fetch -> agents -> store.
"""

from __future__ import annotations

import asyncio
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
_event_checker_task: asyncio.Task | None = None


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
                # Dedup check
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
                    "source_name": raw.source_name,
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
        "清洗以上新闻正文。\n\n"
        "移除：导航菜单、广告、cookie提示、订阅弹窗、社交媒体按钮、"
        "页眉页脚模板、\"相关文章\"推荐、版权声明模板。\n"
        "保留：文章正文、数据表格、引用块。\n\n"
        "图片规则：保留原文中的图片引用，必须使用原文中的真实URL。"
        "严禁编造、替换或生成任何图片URL。如果原文没有图片URL则不要添加图片。\n\n"
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
        return response.content, response.usage.total_tokens
    except Exception:
        logger.warning("Content cleaning failed for '%s', using raw text", title[:60], exc_info=True)
        return raw_text, 0


async def run_pipeline(article_id: str, article_data: dict, progress_callback=None) -> dict[str, Any]:
    """Run the full dynamic agent pipeline for one article.

    Phase 0: Classification (multi-label + value scoring + market impact)
    Phase 1: Content fetch (Crawl4AI with fallback chain)
    Phase 2: Dynamic agents (parallel via asyncio.gather, respecting dependencies)
    Phase 3: Post-processing (embed + store)

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

    # --- Phase 0: Classification ---
    await _report_progress("classify")

    if checkpoint and "classification" in checkpoint:
        # Restore classification from checkpoint
        results["classification"] = checkpoint["classification"]
        categories = [c["slug"] for c in checkpoint["classification"]["categories"]]
        value_score = checkpoint["classification"]["value_score"]
        has_market_impact = checkpoint["classification"]["has_market_impact"]
        checkpoint_stages = [k for k in checkpoint if k != "classification"]
        logger.info(
            "Restored classification from checkpoint: categories=%s value=%d (also cached: %s)",
            categories, value_score, checkpoint_stages,
        )
        is_default = checkpoint["classification"].get("primary_category") == "other" and value_score == 0
    else:
        classify_start = time.monotonic()
        classify_results = await classify_articles([{"title": title, "summary": summary}])
        classification = classify_results[0]
        classify_ms = (time.monotonic() - classify_start) * 1000

        categories = classification.category_slugs
        value_score = classification.value_score
        has_market_impact = classification.has_market_impact

        results["classification"] = {
            "categories": [{"slug": c.slug, "confidence": c.confidence} for c in classification.categories],
            "primary_category": classification.primary_category,
            "tags": classification.tags,
            "value_score": value_score,
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
            },
            error="Classification returned defaults — LLM may have failed" if is_default else None,
        )

        logger.info(
            "Classified: categories=%s value=%d market_impact=%s (%.0fms)",
            categories, value_score, has_market_impact, classify_ms,
        )

    # Save classification to checkpoint
    article_data.setdefault("_checkpoint", {})
    if not checkpoint or "classification" not in (checkpoint or {}):
        article_data["_checkpoint"]["classification"] = results["classification"]

    # Classification failure → raise so consumer retries
    if is_default:
        raise RuntimeError(
            f"Classification failed (returned defaults) for article: {title[:80]}"
        )

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

    # --- Phase 1.5: Content cleaning ---
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

    # --- Phase 2+3: Dynamic agents (via unified agent queue) ---
    await _report_progress("agents")
    registry = get_agent_registry()
    phase_agents = registry.resolve_agents(categories, value_score, has_market_impact)

    if not phase_agents:
        logger.info("No agents resolved for article (value=%d): %s", value_score, title[:60])
        results["pipeline_duration_ms"] = (time.monotonic() - pipeline_start) * 1000
        return results

    # Collect agent IDs to run, respecting checkpoint
    completed_from_checkpoint = (checkpoint or {}).get("completed_agents", {})
    failed_agent_ids = set((checkpoint or {}).get("failed_agents", []))

    if completed_from_checkpoint:
        for aid, adata in completed_from_checkpoint.items():
            results["agents"][aid] = adata
        logger.info(
            "Restored %d agent results from checkpoint: %s",
            len(completed_from_checkpoint), list(completed_from_checkpoint.keys()),
        )

    agent_ids_to_run: list[str] = []
    for phase_num in sorted(phase_agents.keys()):
        for agent in phase_agents[phase_num]:
            if agent.agent_id in completed_from_checkpoint and agent.agent_id not in failed_agent_ids:
                dep_needs_rerun = any(dep in failed_agent_ids for dep in agent.requires)
                if not dep_needs_rerun:
                    continue
            agent_ids_to_run.append(agent.agent_id)

    if not agent_ids_to_run:
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
    }

    # Submit agent group to unified queue
    from app.pipeline import agent_queue as aq

    redis = await get_redis()

    group_id, result_key = await aq.submit_agent_group(
        redis,
        group_type="article",
        context_data=context_data,
        agents=agent_ids_to_run,
        prior_results=completed_from_checkpoint,
    )

    logger.info(
        "Agent group submitted: %s agents=%s (group=%s)",
        title[:50], agent_ids_to_run, group_id[:8],
    )

    # Wait for results — worker owns the timeout and always posts a result
    # (either success or {"_error": "timeout"}), so we just wait.
    agent_results = await aq.wait_results(redis, result_key)

    if agent_results is None:
        raise RuntimeError(
            f"Agent worker did not respond for article: {title[:80]}"
        )

    if "_error" in agent_results:
        raise RuntimeError(
            f"Agent worker error ({agent_results['_error']}) for article: {title[:80]}"
        )

    # Merge results back
    for aid, result_data in agent_results.items():
        results["agents"][aid] = result_data
        # Update checkpoint
        article_data["_checkpoint"].setdefault("completed_agents", {})
        if result_data.get("success"):
            article_data["_checkpoint"]["completed_agents"][aid] = result_data
        else:
            article_data["_checkpoint"].setdefault("failed_agents", [])
            if aid not in article_data["_checkpoint"]["failed_agents"]:
                article_data["_checkpoint"]["failed_agents"].append(aid)

    total_duration = (time.monotonic() - pipeline_start) * 1000
    results["pipeline_duration_ms"] = total_duration

    total_tokens = sum(
        r.get("tokens_used", 0) for r in agent_results.values()
        if isinstance(r, dict) and r.get("success")
    )
    successful = sum(1 for r in agent_results.values() if isinstance(r, dict) and r.get("success"))
    failed = sum(1 for r in agent_results.values() if isinstance(r, dict) and not r.get("success"))

    logger.info(
        "Pipeline complete: %s | %d agents (%d ok, %d fail) | %d tokens | %.0fms",
        title[:50], successful + failed, successful, failed, total_tokens, total_duration,
    )

    await _report_progress("complete")

    return results


async def run_event_checker() -> None:
    """Background loop that processes event aggregation checks.

    Reads from nf:events:check Redis list. Non-blocking, separate from main pipeline.
    """
    from app.services.event_service import check_and_create_event

    redis = await get_redis()
    logger.info("Event checker started")

    while True:
        try:
            result = await redis.blpop("nf:events:check", timeout=5)
            if result:
                _, article_id = result
                if isinstance(article_id, bytes):
                    article_id = article_id.decode()
                try:
                    await check_and_create_event(article_id)
                except Exception:
                    logger.exception("Event check failed for article %s", article_id)
        except asyncio.CancelledError:
            logger.info("Event checker cancelled")
            return
        except Exception:
            logger.exception("Event checker error")
            await asyncio.sleep(5)


def create_scheduler() -> AsyncIOScheduler:
    """Create and configure the APScheduler."""
    config = load_pipeline_config()
    scheduler_config = config.get("scheduler", {})

    poll_interval = scheduler_config.get("feed_poll_interval_seconds", 300)
    cleanup_hours = scheduler_config.get("cleanup_interval_hours", 24)

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

    # Deactivate stale events (every 6 hours)
    from app.services.event_service import deactivate_stale_events

    scheduler.add_job(
        deactivate_stale_events,
        "interval",
        hours=6,
        id="deactivate_stale_events",
        name="Deactivate stale events",
        misfire_grace_time=600,
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

    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = create_scheduler()
    return _scheduler


def start_event_checker() -> asyncio.Task:
    """Start the event checker background task. Call after event loop is running."""
    global _event_checker_task
    if _event_checker_task is None or _event_checker_task.done():
        _event_checker_task = asyncio.create_task(run_event_checker())
    return _event_checker_task


async def stop_event_checker() -> None:
    """Cancel the event checker background task."""
    global _event_checker_task
    if _event_checker_task and not _event_checker_task.done():
        _event_checker_task.cancel()
        try:
            await _event_checker_task
        except asyncio.CancelledError:
            pass
        _event_checker_task = None

"""Async pipeline consumer — BLPOP from Redis, process articles.

Pattern from WebStock's news_consumer.py but simplified:
- No Celery dependency
- Standalone asyncio process
- Dynamic concurrency via Redis-driven target (replaces Semaphore)
- Pause / resume via Redis control key
- Per-article progress tracking with stage callbacks
- Retry with exponential backoff
- Dead-letter queue for exhausted retries
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
import uuid

import sqlalchemy.exc

from app.core.config import get_settings, load_pipeline_config
from app.db.redis import get_redis
from app.pipeline import agent_queue as aq
from app.pipeline import queue as q
from app.pipeline.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class PipelineConsumer:
    """Async consumer that processes articles from the Redis queue."""

    def __init__(self):
        config = load_pipeline_config()
        consumer_config = config.get("consumer", {})

        self._concurrency = consumer_config.get("concurrency", 10)
        self._per_article_timeout = consumer_config.get("per_article_timeout_seconds", 600)
        self._max_retries = consumer_config.get("max_retries", 3)
        self._max_articles = consumer_config.get("max_articles_before_restart", 5000)
        self._max_uptime = consumer_config.get("max_uptime_seconds", 86400)

        # Story batching
        self._story_batch_size = consumer_config.get("story_batch_size", 8)
        self._story_batch_size_target = self._story_batch_size
        self._story_batch: list[str] = []

        self._active_count = 0
        self._concurrency_target = self._concurrency  # initial from config
        self._paused = False

        self._shutdown = False
        self._processed = 0
        self._start_time = time.time()
        self._tasks: set[asyncio.Task] = set()
        self._circuit_breaker: CircuitBreaker | None = None

    async def run(self) -> None:
        """Main consumer loop."""
        logger.info(
            "Pipeline consumer starting (concurrency=%d)", self._concurrency_target
        )

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_shutdown)

        redis = await get_redis()

        # Clean up stale processing state from previous consumer run
        stale = await redis.smembers(q.QUEUE_PROCESSING)
        if stale:
            stale_ids = [s.decode() if isinstance(s, bytes) else s for s in stale]
            logger.warning("Clearing %d stale processing entries from previous run: %s",
                           len(stale_ids), stale_ids[:5])
            await redis.delete(q.QUEUE_PROCESSING)

        # Migrate legacy queue key to new priority queues (one-time)
        legacy_len = await redis.llen("nf:pipeline:queue")
        if legacy_len > 0:
            logger.info("Migrating %d items from legacy queue to low-priority queue", legacy_len)
            while True:
                item = await redis.lpop("nf:pipeline:queue")
                if item is None:
                    break
                await redis.rpush(q.QUEUE_LOW, item)
            logger.info("Legacy queue migration complete")

        # Recover articles that were in-flight when previous consumer crashed
        recovered = await q.recover_in_flight(redis)
        if recovered:
            logger.warning("Recovered %d in-flight articles from previous crash", recovered)

        # Initialize circuit breaker
        config = load_pipeline_config()
        self._circuit_breaker = CircuitBreaker(
            redis,
            failure_threshold=config.get("consumer", {}).get("circuit_breaker_failure_threshold", 5),
            recovery_timeout=config.get("consumer", {}).get("circuit_breaker_recovery_timeout", 60),
        )
        await self._circuit_breaker.load_state()

        # Load agent priority override from Redis
        from app.pipeline.agents.registry import load_priority_override_from_redis
        await load_priority_override_from_redis()

        # Sync pause + concurrency from Redis BEFORE entering the main loop
        self._paused = await q.is_paused(redis)
        target = await q.get_concurrency(redis)
        if target is not None:
            self._concurrency_target = target
        if self._paused:
            logger.info("Pipeline is paused, consumer will wait")

        # Start background pollers
        retry_task = asyncio.create_task(self._retry_poller(redis))
        config_task = asyncio.create_task(self._config_poller(redis))
        story_flusher_task = asyncio.create_task(self._story_batch_flusher(redis))

        try:
            while not self._should_stop():
                # Pause check
                if self._paused:
                    await asyncio.sleep(0.5)
                    continue

                # Circuit breaker check
                if self._circuit_breaker and not await self._circuit_breaker.on_dequeue_attempt():
                    await asyncio.sleep(1)
                    continue

                # Capacity check (counter-based, no semaphore)
                if self._active_count >= self._concurrency_target:
                    await asyncio.sleep(0.1)
                    continue

                article_data = await q.dequeue_article(redis, timeout=2)
                if article_data is None:
                    continue

                # Re-check pause after BLPOP (may have changed during the 2s wait)
                if self._paused:
                    await q.enqueue_article(redis, article_data, priority=article_data.get("priority", "high"))
                    logger.info("Re-enqueued article dequeued during pause: %s", article_data.get("title", "")[:60])
                    continue

                self._active_count += 1
                task = asyncio.create_task(
                    self._process_with_tracking(redis, article_data)
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

                # Periodic health update
                await q.update_health(
                    redis,
                    active=self._active_count,
                    concurrency=self._concurrency_target,
                    processed=self._processed,
                    paused="1" if self._paused else "0",
                    uptime=int(time.time() - self._start_time),
                )

        except asyncio.CancelledError:
            logger.info("Consumer cancelled")
        finally:
            # Flush remaining story batch before shutdown
            if self._story_batch:
                try:
                    await self._submit_story_group(redis)
                except Exception:
                    logger.warning("Failed to flush story batch on shutdown")

            retry_task.cancel()
            config_task.cancel()
            story_flusher_task.cancel()
            # Wait for in-flight tasks
            if self._tasks:
                logger.info("Waiting for %d in-flight tasks...", len(self._tasks))
                await asyncio.wait(self._tasks, timeout=45)

            logger.info("Consumer stopped (processed=%d)", self._processed)

    async def _process_with_tracking(self, redis, article_data: dict) -> None:
        """Process article with status tracking and progress callback."""
        article_id = article_data.get("article_id", "")
        start_time = time.monotonic()
        try:
            async def progress_callback(stage: str):
                try:
                    await q.update_article_stage(redis, article_id, stage)
                except Exception:
                    logger.warning("Failed to update stage for article: %s", article_id)

            is_duplicate = await asyncio.wait_for(
                self._process_article(
                    redis, article_data, progress_callback=progress_callback
                ),
                timeout=self._per_article_timeout,
            )

            duration_ms = (time.monotonic() - start_time) * 1000
            try:
                await q.mark_completed(redis, article_id, duration_ms)
            except Exception:
                logger.warning("Failed to mark article completed: %s", article_id)
            self._processed += 1
            await q.increment_metrics(redis, "processed", 1)

            # Accumulate for story batch (skip duplicates)
            if not is_duplicate:
                self._story_batch.append(article_id)
                if len(self._story_batch) >= self._story_batch_size_target:
                    await self._submit_story_group(redis)

            if self._circuit_breaker:
                await self._circuit_breaker.record_success()
        except asyncio.TimeoutError:
            logger.error(
                "Article timed out (%ds): %s",
                self._per_article_timeout,
                article_data.get("title", "?")[:60],
            )
            try:
                await q.mark_failed(redis, article_id, "timeout")
            except Exception:
                logger.warning("Failed to mark article failed: %s", article_id)
            if self._circuit_breaker:
                await self._circuit_breaker.record_failure()
            await self._handle_failure(redis, article_data, "timeout")
        except Exception as e:
            logger.exception(
                "Article failed: %s", article_data.get("title", "?")[:60]
            )
            try:
                await q.mark_failed(redis, article_id, str(e)[:500])
            except Exception:
                logger.warning("Failed to mark article failed: %s", article_id)
            # Update DB content_status to failed
            try:
                from sqlalchemy import update as sql_update
                from app.db.database import get_session_factory
                from app.models.article import Article
                factory = get_session_factory()
                async with factory() as session:
                    await session.execute(
                        sql_update(Article)
                        .where(Article.id == article_id)
                        .values(content_status="failed")
                    )
                    await session.commit()
            except Exception:
                logger.warning("Failed to update content_status for %s", article_id, exc_info=True)
            if self._circuit_breaker:
                await self._circuit_breaker.record_failure()
            await self._handle_failure(redis, article_data, str(e))
        finally:
            self._active_count -= 1

    async def _process_article(self, redis, article_data: dict, *, progress_callback=None) -> bool:
        """Process a single article through the dynamic agent pipeline.

        Delegates to orchestrator.run_pipeline which handles:
        classify -> route -> fetch content -> agents (parallel) -> store
        """
        from app.pipeline.orchestrator import run_pipeline
        from app.db.database import get_session_factory

        article_id = article_data.get("article_id", str(uuid.uuid4()))
        title = article_data.get("title", "")

        # Hydrate missing fields from DB when queue payload is incomplete
        # (e.g. manual re-enqueue with only article_id)
        if not article_data.get("url") or not title:
            from sqlalchemy import select
            from app.models.article import Article
            factory_hydrate = get_session_factory()
            async with factory_hydrate() as session:
                row = (await session.execute(
                    select(
                        Article.url, Article.title, Article.summary,
                        Article.language, Article.source_name, Article.full_text,
                    ).where(Article.id == article_id)
                )).one_or_none()
                if row:
                    article_data.setdefault("url", row.url or "")
                    article_data.setdefault("title", row.title or "")
                    article_data.setdefault("summary", row.summary or "")
                    article_data.setdefault("language", row.language)
                    article_data.setdefault("source_name", row.source_name)
                    # If article already has full_text from a prior fetch, pass it through
                    if row.full_text and not article_data.get("rss_full_text"):
                        article_data["rss_full_text"] = row.full_text
                    title = article_data.get("title", "")
                    logger.info("Hydrated article from DB: %s", title[:80])

        logger.info("Processing article: %s", title[:80])

        # Run the full pipeline
        pipeline_results = await run_pipeline(
            article_id, article_data, progress_callback=progress_callback
        )

        # Early exit if orchestrator already marked as duplicate
        if pipeline_results.get("duplicate"):
            return True

        # Store results to database
        classification = pipeline_results.get("classification", {})
        content_info = pipeline_results.get("content")
        agent_data = pipeline_results.get("agents", {})

        # Resolved URL from orchestrator dedup check (Google News → real URL)
        url_updated_to: str | None = pipeline_results.get("_url_resolved")

        factory = get_session_factory()
        async with factory() as session:
            from sqlalchemy import select, update
            from app.models.article import Article
            from app.models.category import Category

            # Find primary category ID
            primary_cat = classification.get("primary_category", "other")
            cat_result = await session.execute(
                select(Category.id).where(Category.slug == primary_cat)
            )
            category_id = cat_result.scalar_one_or_none()

            # Extract cleaned text from pipeline
            cleaned_text = pipeline_results.get("cleaned_text")

            # Check for partial processing (fail-open classification)
            is_partial = pipeline_results.get("partial", False)

            # Determine content status
            if is_partial:
                content_status = "partial"
            elif cleaned_text:
                content_status = "processed"
            elif content_info:
                content_status = "fetched"
            else:
                content_status = "fetch_failed"

            # Guard: don't downgrade a previously successful status
            _STATUS_RANK = {"processed": 4, "fetched": 3, "partial": 2, "fetch_failed": 1, "pending": 0, "failed": 0}
            existing_result = await session.execute(
                select(Article.content_status).where(Article.id == article_id)
            )
            existing_status = existing_result.scalar_one_or_none()
            if existing_status and _STATUS_RANK.get(existing_status, 0) > _STATUS_RANK.get(content_status, 0):
                logger.info(
                    "Keeping higher content_status '%s' (not downgrading to '%s') for %s",
                    existing_status, content_status, article_id[:8],
                )
                content_status = existing_status

            # Build update values (aligned with Article model from migration 002)
            cat_slugs = [c.get("slug") for c in classification.get("categories", [])]
            update_values: dict = {
                # Update URL to resolved real URL if Google News was deferred
                **({"url": url_updated_to} if url_updated_to else {}),
                # Store cleaned full text if available
                **({"full_text": cleaned_text} if cleaned_text else {}),
                "primary_category_id": category_id,
                "primary_category": primary_cat,
                "categories": cat_slugs,
                "category_details": classification.get("categories", []),
                "tags": classification.get("tags", []),
                "value_score": classification.get("value_score", 0),
                "value_reason": classification.get("value_reason", ""),
                "has_market_impact": classification.get("has_market_impact", False),
                "market_impact_hint": classification.get("market_impact_hint"),
                "content_status": content_status,
                "word_count": content_info.get("word_count") if content_info else None,
                "language": content_info.get("language") if content_info else article_data.get("language"),
                "processing_path": "partial" if is_partial else (
                    "high_value" if classification.get("value_score", 0) >= 60
                    or classification.get("has_market_impact") else "medium"
                ),
                "agents_executed": list(agent_data.keys()) if agent_data else [],
                "pipeline_metadata": {
                    "duration_ms": pipeline_results.get("pipeline_duration_ms"),
                    "agents": agent_data,
                    **({"p2_group_id": pipeline_results["_p2_group_id"]}
                       if pipeline_results.get("_p2_group_id") else {}),
                },
            }

            # Per-agent columns (summarizer, translator, sentiment) are already
            # written incrementally by agent_worker via agent_db_writer.
            # Here we only finalize merged fields (entities, finance_metadata).
            from app.pipeline.agent_db_writer import finalize_merged_fields

            try:
                merged = await finalize_merged_fields(article_id, agent_data, session)
                update_values.update(merged)
            except Exception:
                logger.warning(
                    "finalize_merged_fields failed for %s, proceeding without merged fields",
                    article_id[:8], exc_info=True,
                )

            stmt = (
                update(Article)
                .where(Article.id == article_id)
                .values(**update_values)
            )
            try:
                await session.execute(stmt)
                await session.commit()
            except sqlalchemy.exc.IntegrityError as exc:
                await session.rollback()
                if "articles_url_key" not in str(exc):
                    raise  # Re-raise non-URL constraint violations
                # URL unique constraint violation — the resolved real URL
                # already belongs to another article (dedup Redis key expired
                # but the DB row persists). Mark this copy as duplicate.
                logger.warning(
                    "URL conflict on UPDATE for %s, marking as duplicate: %s",
                    article_id[:8],
                    update_values.get("url", "N/A"),
                )
                async with get_session_factory()() as dup_session:
                    await dup_session.execute(
                        update(Article)
                        .where(Article.id == article_id)
                        .values(content_status="duplicate")
                    )
                    await dup_session.commit()
                return True

        # Invalidate caches after successful article processing
        from app.services.cache_service import cache
        await cache.invalidate_pattern("articles:*")
        await cache.invalidate_pattern("homepage:*")
        await cache.invalidate("categories")

        # Trigger webhooks for article.published event
        try:
            from app.services.webhook_service import trigger_webhooks
            webhook_payload = {
                "article_id": str(article_id) if not isinstance(article_id, str) else article_id,
                "title": title,
                "url": article_data.get("url", ""),
                "primary_category": primary_cat,
                "categories": cat_slugs,
                "value_score": classification.get("value_score", 0),
                "has_market_impact": classification.get("has_market_impact", False),
                "content_status": content_status,
                "finance_metadata": update_values.get("finance_metadata"),
            }
            async with factory() as webhook_session:
                await trigger_webhooks(webhook_session, "article.published", webhook_payload)
        except Exception:
            logger.warning("Webhook trigger failed for article %s", article_id, exc_info=True)

        logger.info(
            "Processed: category=%s value=%d agents=%d url=%s",
            primary_cat,
            classification.get("value_score", 0),
            len(agent_data),
            article_data.get("url", "")[:60],
        )
        return False

    async def _handle_failure(self, redis, article_data: dict, error: str) -> None:
        """Handle article processing failure — retry or dead-letter."""
        retry_count = article_data.get("retry_count", 0)
        if retry_count < self._max_retries:
            await q.enqueue_retry(redis, article_data, retry_count)
        else:
            await q.enqueue_dead_letter(redis, article_data, error)
            await q.increment_metrics(redis, "dead_lettered", 1)

    async def _submit_story_group(self, redis) -> None:
        """Submit a story clustering agent group to the unified queue."""
        if not self._story_batch:
            return

        batch = self._story_batch.copy()
        self._story_batch.clear()

        try:
            group_id, result_key = await aq.submit_agent_group(
                redis,
                group_type="story",
                context_data={"article_ids": batch},
                agents=["story_matcher"],
                display_info={"label": f"{len(batch)}篇文章故事线归类", "article_count": len(batch)},
            )
            # Fire-and-forget: story_matcher writes directly to DB
            # Set short TTL on result_key since no one waits for it
            await redis.expire(result_key, 60)

            logger.info(
                "Story group submitted: %d articles (group=%s)",
                len(batch), group_id[:8],
            )
        except Exception:
            logger.warning("Failed to submit story group", exc_info=True)
            # Put articles back for next batch
            self._story_batch.extend(batch)

    async def _story_batch_flusher(self, redis) -> None:
        """Periodically flush incomplete story batches."""
        while not self._shutdown:
            try:
                await asyncio.sleep(60)
                if self._story_batch:
                    logger.debug(
                        "Flushing story batch: %d articles (< %d target)",
                        len(self._story_batch), self._story_batch_size_target,
                    )
                    await self._submit_story_group(redis)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Story batch flusher error")

    async def _config_poller(self, redis) -> None:
        """Poll Redis for concurrency target and pause state changes."""
        while not self._shutdown:
            try:
                # Check concurrency
                target = await q.get_concurrency(redis)
                if target is not None and target != self._concurrency_target:
                    logger.info(
                        "Concurrency changed: %d -> %d",
                        self._concurrency_target,
                        target,
                    )
                    self._concurrency_target = target

                # Check story batch size
                sb_val = await redis.get("nf:pipeline:story_batch_size")
                if sb_val is not None:
                    new_size = int(sb_val)
                    if new_size != self._story_batch_size_target:
                        logger.info(
                            "Story batch size changed: %d -> %d",
                            self._story_batch_size_target, new_size,
                        )
                        self._story_batch_size_target = new_size

                # Check pause state
                paused = await q.is_paused(redis)
                if paused != self._paused:
                    self._paused = paused
                    logger.info(
                        "Pipeline %s", "paused" if paused else "resumed"
                    )

                # Sync circuit breaker state (admin may have manually reset)
                if self._circuit_breaker:
                    cb_data = await redis.hgetall("nf:pipeline:circuit_breaker")
                    if cb_data:
                        redis_state = cb_data.get("state", "closed")
                        if redis_state == "closed" and self._circuit_breaker.state != "closed":
                            await self._circuit_breaker.load_state()
                            logger.info("Circuit breaker synced from Redis: %s", redis_state)
            except Exception:
                logger.exception("Config poller error")
            await asyncio.sleep(2)

    async def _retry_poller(self, redis) -> None:
        """Periodically check for due retries."""
        while not self._shutdown:
            try:
                due = await q.get_due_retries(redis)
                for article_data in due:
                    # Retries are lower priority than fresh polled news.
                    await q.enqueue_article(redis, article_data, priority="low")
            except Exception:
                logger.exception("Retry poller error")
            await asyncio.sleep(5)

    def _should_stop(self) -> bool:
        """Check if consumer should stop."""
        if self._shutdown:
            return True
        if self._processed >= self._max_articles:
            logger.info("Max articles reached (%d), stopping for restart", self._max_articles)
            return True
        if time.time() - self._start_time >= self._max_uptime:
            logger.info("Max uptime reached, stopping for restart")
            return True
        return False

    def _handle_shutdown(self) -> None:
        logger.info("Shutdown signal received")
        self._shutdown = True


async def run_consumer() -> None:
    """Entry point for the consumer process.

    Starts both the PipelineConsumer (article queue) and the AgentWorker
    (unified agent queue) in the same event loop.
    """
    from app.pipeline.agent_worker import AgentWorker

    consumer = PipelineConsumer()
    worker = AgentWorker()

    # Run both concurrently — if either exits, both stop
    done, pending = await asyncio.wait(
        [
            asyncio.create_task(consumer.run(), name="pipeline-consumer"),
            asyncio.create_task(worker.run(), name="agent-worker"),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Cancel remaining tasks on exit
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    for task in done:
        if task.exception():
            logger.error("Task %s failed: %s", task.get_name(), task.exception())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [consumer] %(levelname)s %(message)s")
    asyncio.run(run_consumer())

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
                    await q.enqueue_article(redis, article_data)
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

            await asyncio.wait_for(
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

            # Accumulate for story batch
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

    async def _process_article(self, redis, article_data: dict, *, progress_callback=None) -> None:
        """Process a single article through the dynamic agent pipeline.

        Delegates to orchestrator.run_pipeline which handles:
        classify -> route -> fetch content -> agents (parallel) -> store
        """
        from app.pipeline.orchestrator import run_pipeline
        from app.db.database import get_session_factory

        article_id = article_data.get("article_id", str(uuid.uuid4()))
        title = article_data.get("title", "")

        logger.info("Processing article: %s", title[:80])

        # Run the full pipeline
        pipeline_results = await run_pipeline(
            article_id, article_data, progress_callback=progress_callback
        )

        # Store results to database
        classification = pipeline_results.get("classification", {})
        content_info = pipeline_results.get("content")
        agent_data = pipeline_results.get("agents", {})

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

            # Determine content status
            if cleaned_text:
                content_status = "processed"
            elif content_info:
                content_status = "fetched"
            else:
                content_status = "fetch_failed"

            # Build update values (aligned with Article model from migration 002)
            cat_slugs = [c.get("slug") for c in classification.get("categories", [])]
            update_values: dict = {
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
                "processing_path": "high_value" if classification.get("value_score", 0) >= 60
                    or classification.get("has_market_impact") else "medium",
                "agents_executed": list(agent_data.keys()) if agent_data else [],
                "pipeline_metadata": {
                    "duration_ms": pipeline_results.get("pipeline_duration_ms"),
                    "agents": agent_data,
                },
            }

            # Extract specific agent outputs for dedicated columns
            summarizer = agent_data.get("summarizer", {})
            if summarizer.get("success"):
                summary_data = summarizer.get("data", {})
                if summary_data.get("ai_summary"):
                    update_values["ai_summary"] = summary_data["ai_summary"]
                if summary_data.get("detailed_summary"):
                    update_values["detailed_summary"] = summary_data["detailed_summary"]

            sentiment = agent_data.get("sentiment", {})
            if sentiment.get("success"):
                update_values["sentiment_score"] = sentiment.get("data", {}).get("sentiment_score")
                update_values["sentiment_label"] = sentiment.get("data", {}).get("sentiment_label")

            # Collect entity results (unified "entity" agent or legacy "entity_*" agents)
            all_entities = []
            for agent_id, agent_result in agent_data.items():
                if (agent_id == "entity" or agent_id.startswith("entity_")) and agent_result.get("success"):
                    entities = agent_result.get("data", {}).get("entities", [])
                    all_entities.extend(entities)
            _CONF_MAP = {"high": 0.9, "medium": 0.5, "low": 0.1}
            if all_entities:
                update_values["entities"] = all_entities
                # Primary entity = highest confidence
                best = max(
                    all_entities,
                    key=lambda e: e.get("confidence", 0)
                    if isinstance(e.get("confidence"), (int, float))
                    else _CONF_MAP.get(str(e.get("confidence", "")), 0),
                )
                update_values["primary_entity"] = best.get("name")
                update_values["primary_entity_type"] = best.get("type")

            # Finance metadata (WebStock compatible ★)
            finance_meta = {}
            sentiment_result = agent_data.get("sentiment", {})
            if sentiment_result.get("success"):
                sd = sentiment_result.get("data", {})
                if sd.get("finance_sentiment"):
                    finance_meta["sentiment_tag"] = sd["finance_sentiment"]
                if sd.get("investment_summary"):
                    finance_meta["investment_summary"] = sd["investment_summary"]

            tagger_result = agent_data.get("tagger", {})
            if tagger_result.get("success"):
                td = tagger_result.get("data", {})
                if td.get("industry_tags"):
                    finance_meta["industry_tags"] = td["industry_tags"]
                if td.get("event_tags"):
                    finance_meta["event_tags"] = td["event_tags"]

            # Extract stock symbols from entity results
            stock_entities = [e for e in all_entities if e.get("type") in ("stock", "index")]
            if stock_entities:
                finance_meta["symbols"] = [e.get("name") for e in stock_entities]

            if finance_meta:
                update_values["finance_metadata"] = finance_meta

            stmt = (
                update(Article)
                .where(Article.id == article_id)
                .values(**update_values)
            )
            await session.execute(stmt)
            await session.commit()

        # Invalidate caches after successful article processing
        from app.services.cache_service import cache
        await cache.invalidate_pattern("articles:*")
        await cache.invalidate_pattern("homepage:*")
        await cache.invalidate("categories")

        # Enqueue event aggregation check (async, non-blocking)
        try:
            redis = await get_redis()
            await redis.rpush("nf:events:check", str(article_id))
        except Exception:
            logger.debug("Failed to enqueue event check for %s", article_id)

        logger.info(
            "Processed: category=%s value=%d agents=%d url=%s",
            primary_cat,
            classification.get("value_score", 0),
            len(agent_data),
            article_data.get("url", "")[:60],
        )

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
                    await q.enqueue_article(redis, article_data)
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

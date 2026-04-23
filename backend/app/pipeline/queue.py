"""Redis queue protocol for pipeline article processing.

Pattern from WebStock's news_queue.py — Redis LIST with BLPOP consumer.
Extended with per-article tracking, Redis Stream events, concurrency control,
in-flight crash recovery, and pause support for the admin dashboard.
"""

from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Queue key names — priority queues
QUEUE_HIGH = "nf:pipeline:queue:high"
QUEUE_LOW = "nf:pipeline:queue:low"
QUEUE_MAIN = QUEUE_HIGH  # backward compat alias
QUEUE_RETRY = "nf:pipeline:retry"
QUEUE_DEAD_LETTER = "nf:pipeline:dead_letter"
QUEUE_IN_FLIGHT = "nf:pipeline:in_flight"
QUEUE_HEALTH = "nf:pipeline:health"
QUEUE_METRICS = "nf:pipeline:metrics"

# Per-article tracking & control
ARTICLE_META = "nf:pipeline:articles:{}"  # .format(article_id)
QUEUE_PROCESSING = "nf:pipeline:processing"
QUEUE_RECENT = "nf:pipeline:recent"
QUEUE_CONCURRENCY = "nf:pipeline:concurrency"
QUEUE_PAUSED = "nf:pipeline:paused"
QUEUE_STREAM = "nf:pipeline:stream"


async def enqueue_article(
    redis: aioredis.Redis, article_data: dict, *, priority: str = "high",
) -> None:
    """Enqueue an article for pipeline processing.

    Args:
        priority: "high" for fresh news from scheduled polling,
                  "low" for imports, recovered crash articles, etc.
    """
    article_data["enqueued_at"] = time.time()
    article_data["priority"] = priority
    raw_json = json.dumps(article_data)

    queue_key = QUEUE_HIGH if priority == "high" else QUEUE_LOW
    article_id = str(article_data.get("article_id") or article_data.get("id") or "")
    title = article_data.get("title", "")

    if article_id:
        meta_key = ARTICLE_META.format(article_id)
        try:
            pipe = redis.pipeline(transaction=True)
            pipe.rpush(queue_key, raw_json)
            pipe.hset(
                meta_key,
                mapping={
                    "status": "queued",
                    "title": title,
                    "priority": priority,
                    "enqueued_at": str(article_data["enqueued_at"]),
                },
            )
            pipe.expire(meta_key, 86400)  # 24h — must outlive queue wait + processing
            pipe.xadd(
                QUEUE_STREAM,
                {"type": "enqueued", "article_id": article_id, "title": title, "priority": priority},
                maxlen=500,
                approximate=True,
            )
            await pipe.execute()
        except Exception:
            logger.warning(
                "Failed to enqueue article %s atomically, falling back to rpush only",
                article_id, exc_info=True,
            )
            await redis.rpush(queue_key, raw_json)
    else:
        await redis.rpush(queue_key, raw_json)


async def dequeue_article(redis: aioredis.Redis, timeout: int = 2) -> dict | None:
    """Dequeue an article (blocking pop).

    Uses multi-key BLPOP to prefer high-priority articles over low-priority.
    BLPOP checks keys left-to-right and pops from the first non-empty list.
    """
    result = await redis.blpop([QUEUE_HIGH, QUEUE_LOW], timeout=timeout)
    if result is None:
        return None
    _, raw_json = result
    parsed = json.loads(raw_json)

    # Tracking (best-effort, don't block core operation)
    try:
        article_id = str(parsed.get("article_id") or parsed.get("id") or "")
        if article_id:
            title = parsed.get("title", "")[:100]
            meta_key = ARTICLE_META.format(article_id)
            pipe = redis.pipeline(transaction=True)
            pipe.sadd(QUEUE_PROCESSING, article_id)
            pipe.hset(QUEUE_IN_FLIGHT, article_id, raw_json)
            # Always write title — meta hash may have expired while queued
            pipe.hset(
                meta_key,
                mapping={
                    "status": "processing",
                    "title": title,
                    "started_at": str(time.time()),
                },
            )
            pipe.expire(meta_key, 86400)  # 24h — must outlive queue wait + processing
            pipe.xadd(
                QUEUE_STREAM,
                {"type": "processing", "article_id": article_id, "title": title},
                maxlen=500,
                approximate=True,
            )
            await pipe.execute()
    except Exception:
        logger.warning("Failed to track dequeue for article %s", parsed.get("article_id", parsed.get("id", "?")), exc_info=True)

    return parsed


async def enqueue_retry(redis: aioredis.Redis, article_data: dict, retry_count: int) -> None:
    """Add article to retry queue with exponential backoff."""
    backoff = 30 * (2 ** retry_count)
    retry_at = time.time() + backoff
    article_data["retry_count"] = retry_count + 1
    article_data["retry_at"] = retry_at
    await redis.zadd(QUEUE_RETRY, {json.dumps(article_data): retry_at})
    logger.info("Enqueued retry #%d for article %s (backoff=%ds)", retry_count + 1, article_data.get("url", "?"), backoff)


async def get_due_retries(redis: aioredis.Redis) -> list[dict]:
    """Get articles ready for retry."""
    now = time.time()
    items = await redis.zrangebyscore(QUEUE_RETRY, "-inf", now, start=0, num=10)
    if not items:
        return []
    results = []
    for item in items:
        await redis.zrem(QUEUE_RETRY, item)
        results.append(json.loads(item))
    return results


async def enqueue_dead_letter(redis: aioredis.Redis, article_data: dict, error: str) -> None:
    """Move to dead letter queue after max retries."""
    article_data["dead_reason"] = error
    article_data["dead_at"] = time.time()
    await redis.rpush(QUEUE_DEAD_LETTER, json.dumps(article_data))
    # Cap dead letter queue
    await redis.ltrim(QUEUE_DEAD_LETTER, -1000, -1)
    logger.warning("Article moved to dead letter queue: %s (reason: %s)", article_data.get("url", "?")[:60], error[:200])


async def requeue_dead_letters(redis: aioredis.Redis, limit: int = 0) -> int:
    """Move articles from dead-letter queue back to the low-priority queue.

    Resets retry_count so the article gets a fresh set of attempts.
    Clears dedup keys to prevent poll-time blocking.

    Args:
        limit: Max articles to requeue (0 = all).

    Returns number of articles requeued.
    """
    total = await redis.llen(QUEUE_DEAD_LETTER)
    if total == 0:
        return 0

    count = limit if limit > 0 else total
    requeued = 0

    for _ in range(count):
        raw = await redis.lpop(QUEUE_DEAD_LETTER)
        if raw is None:
            break
        try:
            article_data = json.loads(raw)
            # Reset retry state
            article_data.pop("retry_count", None)
            article_data.pop("retry_at", None)
            article_data.pop("dead_reason", None)
            article_data.pop("dead_at", None)

            # Clear dedup keys so the article is not blocked
            url = article_data.get("url")
            if url:
                try:
                    from app.pipeline.dedup import clear_dedup_keys
                    await clear_dedup_keys(redis, url, article_data.get("title", ""))
                except Exception:
                    logger.warning("Failed to clear dedup for requeued article: %s", url[:60])

            await enqueue_article(redis, article_data, priority="low")
            requeued += 1

            # Reset DB content_status from "failed" to "pending" so the article
            # is treated as fresh by the pipeline.
            article_id = article_data.get("article_id")
            if article_id:
                try:
                    from sqlalchemy import update as sql_update
                    from app.db.database import get_session_factory
                    from app.models.article import Article
                    factory = get_session_factory()
                    async with factory() as session:
                        await session.execute(
                            sql_update(Article)
                            .where(Article.id == article_id)
                            .values(content_status="pending")
                        )
                        await session.commit()
                except Exception:
                    logger.warning("Failed to reset content_status for requeued article: %s", article_id)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Skipping corrupt dead-letter entry")
            continue

    logger.info("Requeued %d/%d dead-letter articles", requeued, total)
    return requeued


async def update_health(redis: aioredis.Redis, **kwargs) -> None:
    """Update consumer health metrics."""
    await redis.hset(QUEUE_HEALTH, mapping={k: str(v) for k, v in kwargs.items()})
    await redis.expire(QUEUE_HEALTH, 120)  # 2 min TTL


async def increment_metrics(redis: aioredis.Redis, field: str, amount: int = 1) -> None:
    """Increment a metrics counter."""
    await redis.hincrby(QUEUE_METRICS, field, amount)


# ---------------------------------------------------------------------------
# Per-article lifecycle tracking
# ---------------------------------------------------------------------------


async def mark_completed(redis: aioredis.Redis, article_id: str, duration_ms: float) -> None:
    """Mark article as completed."""
    try:
        meta_key = ARTICLE_META.format(article_id)
        pipe = redis.pipeline(transaction=True)
        pipe.hdel(QUEUE_IN_FLIGHT, article_id)
        pipe.srem(QUEUE_PROCESSING, article_id)
        pipe.hset(
            meta_key,
            mapping={
                "status": "completed",
                "completed_at": str(time.time()),
                "duration_ms": str(round(duration_ms)),
            },
        )
        pipe.expire(meta_key, 3600)
        pipe.lpush(QUEUE_RECENT, article_id)
        pipe.ltrim(QUEUE_RECENT, 0, 99)
        pipe.xadd(
            QUEUE_STREAM,
            {"type": "completed", "article_id": article_id, "duration_ms": str(round(duration_ms))},
            maxlen=500,
            approximate=True,
        )
        await pipe.execute()
        logger.debug("Article %s marked completed (%.0fms)", article_id, duration_ms)
    except Exception:
        logger.warning("Failed to mark article completed: %s", article_id, exc_info=True)


async def mark_failed(redis: aioredis.Redis, article_id: str, error: str) -> None:
    """Mark article as failed."""
    try:
        meta_key = ARTICLE_META.format(article_id)
        pipe = redis.pipeline(transaction=True)
        pipe.hdel(QUEUE_IN_FLIGHT, article_id)
        pipe.srem(QUEUE_PROCESSING, article_id)
        pipe.hset(
            meta_key,
            mapping={
                "status": "failed",
                "completed_at": str(time.time()),
                "error": error[:500],
            },
        )
        pipe.expire(meta_key, 3600)
        pipe.lpush(QUEUE_RECENT, article_id)
        pipe.ltrim(QUEUE_RECENT, 0, 99)
        pipe.xadd(
            QUEUE_STREAM,
            {"type": "failed", "article_id": article_id, "error": error[:200]},
            maxlen=500,
            approximate=True,
        )
        await pipe.execute()
        logger.debug("Article %s marked failed: %s", article_id, error[:100])
    except Exception:
        logger.warning("Failed to mark article failed: %s", article_id, exc_info=True)


async def update_article_stage(redis: aioredis.Redis, article_id: str, stage: str) -> None:
    """Update the current processing stage for an article."""
    try:
        meta_key = ARTICLE_META.format(article_id)
        await redis.hset(meta_key, "current_stage", stage)
        await redis.xadd(
            QUEUE_STREAM,
            {"type": "stage", "article_id": article_id, "stage": stage},
            maxlen=500,
            approximate=True,
        )
        logger.debug("Article %s stage: %s", article_id, stage)
    except Exception:
        logger.warning("Failed to update article stage: %s", article_id, exc_info=True)


# ---------------------------------------------------------------------------
# Queue snapshot for admin UI
# ---------------------------------------------------------------------------


async def get_queue_snapshot(redis: aioredis.Redis) -> dict:
    """Get full queue state for admin UI."""
    # --- Queued: parse from both priority queues (capped at 50 each) ---
    def _parse_queue_items(raw_list: list, priority: str, offset: int = 0) -> list[dict]:
        items = []
        for i, raw in enumerate(raw_list):
            try:
                item = json.loads(raw)
                items.append({
                    "article_id": str(item.get("article_id") or item.get("id") or ""),
                    "title": item.get("title", ""),
                    "enqueued_at": str(item.get("enqueued_at", "")),
                    "priority": priority,
                    "position": offset + i + 1,
                })
            except (json.JSONDecodeError, TypeError):
                continue
        return items

    high_raw = await redis.lrange(QUEUE_HIGH, 0, 49)
    low_raw = await redis.lrange(QUEUE_LOW, 0, 49)

    queued_high = _parse_queue_items(high_raw, "high")
    queued_low = _parse_queue_items(low_raw, "low")

    # Merged list: high first, then low (capped at 50 total for backward compat)
    queued = (queued_high + queued_low)[:50]

    # --- Processing: fetch IDs then batch HGETALL via pipeline ---
    processing_ids = list(await redis.smembers(QUEUE_PROCESSING))

    processing_meta: dict[str, dict[str, str]] = {}
    if processing_ids:
        pipe = redis.pipeline(transaction=False)
        for aid in processing_ids:
            pipe.hgetall(ARTICLE_META.format(aid))
        results = await pipe.execute()
        for aid, data in zip(processing_ids, results):
            if data:
                processing_meta[aid] = data

    processing = []
    for aid in processing_ids:
        m = processing_meta.get(aid, {})
        processing.append({
            "article_id": aid,
            "title": m.get("title", ""),
            "current_stage": m.get("current_stage", ""),
            "started_at": m.get("started_at"),
        })

    # --- Recent: fetch IDs then batch HGETALL via pipeline ---
    recent_ids = await redis.lrange(QUEUE_RECENT, 0, 49)

    recent_meta: dict[str, dict[str, str]] = {}
    if recent_ids:
        pipe = redis.pipeline(transaction=False)
        for aid in recent_ids:
            pipe.hgetall(ARTICLE_META.format(aid))
        results = await pipe.execute()
        for aid, data in zip(recent_ids, results):
            if data:
                recent_meta[aid] = data

    recent = []
    for aid in recent_ids:
        m = recent_meta.get(aid, {})
        recent.append({
            "article_id": aid,
            "title": m.get("title", ""),
            "status": m.get("status", ""),
            "completed_at": m.get("completed_at"),
            "duration_ms": m.get("duration_ms"),
            "error": m.get("error"),
        })

    # --- Counts (accurate queue length from llen, not capped LRANGE) ---
    queue_high_len = await redis.llen(QUEUE_HIGH)
    queue_low_len = await redis.llen(QUEUE_LOW)
    retry_len = await redis.zcard(QUEUE_RETRY)
    dead_len = await redis.llen(QUEUE_DEAD_LETTER)

    return {
        "queued": queued,
        "queued_high": queued_high,
        "queued_low": queued_low,
        "processing": processing,
        "recent": recent,
        "counts": {
            "queued": queue_high_len + queue_low_len,
            "queued_high": queue_high_len,
            "queued_low": queue_low_len,
            "processing": len(processing_ids),
            "completed": len([r for r in recent if r.get("status") == "completed"]),
            "failed": len([r for r in recent if r.get("status") == "failed"]),
            "dead_letter": dead_len,
            "retry": retry_len,
        },
    }


# ---------------------------------------------------------------------------
# In-flight crash recovery
# ---------------------------------------------------------------------------


async def recover_in_flight(redis: aioredis.Redis) -> int:
    """Re-enqueue orphaned in-flight articles on consumer startup.

    Uses distributed lock to prevent race with multiple consumers.
    Returns number of recovered articles.
    """
    lock_acquired = await redis.set("nf:pipeline:recovery_lock", "1", nx=True, ex=30)
    if not lock_acquired:
        logger.info("In-flight recovery skipped (another consumer is recovering)")
        return 0

    try:
        in_flight = await redis.hgetall(QUEUE_IN_FLIGHT)
        if not in_flight:
            return 0

        recovered = 0
        for article_id, data_json in in_flight.items():
            try:
                article_data = json.loads(data_json)
                article_data["recovered_from_crash"] = True
                article_data["enqueued_at"] = time.time()
                article_data["priority"] = "low"
                await redis.rpush(QUEUE_LOW, json.dumps(article_data))
                await redis.hdel(QUEUE_IN_FLIGHT, article_id)
                recovered += 1
                logger.info(
                    "Recovered in-flight article: %s (%s)",
                    article_id,
                    article_data.get("title", "")[:60],
                )
            except Exception:
                logger.warning("Failed to recover in-flight article: %s", article_id, exc_info=True)

        if recovered:
            logger.info("In-flight recovery complete: %d articles re-enqueued", recovered)
        return recovered
    finally:
        await redis.delete("nf:pipeline:recovery_lock")


# ---------------------------------------------------------------------------
# Concurrency control
# ---------------------------------------------------------------------------


async def get_concurrency(redis: aioredis.Redis) -> int | None:
    """Get target concurrency from Redis. Returns None if not set."""
    val = await redis.get(QUEUE_CONCURRENCY)
    if val is None:
        return None
    return int(val)


async def set_concurrency(redis: aioredis.Redis, value: int) -> None:
    """Set target concurrency."""
    await redis.set(QUEUE_CONCURRENCY, str(value))
    await redis.xadd(
        QUEUE_STREAM,
        {"type": "concurrency", "value": str(value)},
        maxlen=500,
        approximate=True,
    )


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


async def is_paused(redis: aioredis.Redis) -> bool:
    """Check if pipeline is paused."""
    val = await redis.get(QUEUE_PAUSED)
    if val is None:
        return False
    return val == "1"


async def set_paused(redis: aioredis.Redis, paused: bool) -> None:
    """Set pipeline pause state."""
    await redis.set(QUEUE_PAUSED, "1" if paused else "0")
    await redis.xadd(
        QUEUE_STREAM,
        {"type": "paused", "paused": "1" if paused else "0"},
        maxlen=500,
        approximate=True,
    )


# ---------------------------------------------------------------------------
# Stream event reader
# ---------------------------------------------------------------------------


async def read_stream_events(
    redis: aioredis.Redis,
    last_id: str = "$",
    block_ms: int = 30000,
    count: int = 50,
) -> list[tuple[str, dict]]:
    """Read events from the pipeline stream. Returns [(event_id, event_data), ...]."""
    result = await redis.xread({QUEUE_STREAM: last_id}, count=count, block=block_ms)
    if not result:
        return []
    events: list[tuple[str, dict]] = []
    for _stream_name, entries in result:
        for event_id, data in entries:
            events.append((event_id, data))
    return events

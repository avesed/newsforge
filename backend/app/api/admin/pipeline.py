"""Admin pipeline monitoring endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.db.redis import get_redis
from app.models.article import Article
from app.models.pipeline_event import PipelineEvent
from app.models.user import User
from app.pipeline import queue as q
from app.schemas.base import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/pipeline", tags=["admin"])


@router.get("/stats")
async def pipeline_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Overall pipeline statistics."""
    # Article counts by status
    status_result = await db.execute(
        select(Article.content_status, func.count(Article.id)).group_by(Article.content_status)
    )
    status_counts = {row[0]: row[1] for row in status_result.all()}

    # Category distribution
    cat_result = await db.execute(
        select(Article.primary_category, func.count(Article.id))
        .where(Article.primary_category.is_not(None))
        .group_by(Article.primary_category)
    )
    category_counts = {row[0]: row[1] for row in cat_result.all()}

    # Market impact articles
    impact_result = await db.execute(
        select(func.count(Article.id)).where(Article.has_market_impact == True)  # noqa: E712
    )
    market_impact_count = impact_result.scalar() or 0

    # Value score distribution
    value_result = await db.execute(
        select(
            func.count(Article.id).filter(Article.value_score >= 60).label("high"),
            func.count(Article.id).filter(Article.value_score.between(30, 59)).label("medium"),
            func.count(Article.id).filter(Article.value_score < 30).label("low"),
        )
    )
    value_dist = value_result.one()

    # Redis queue stats
    redis = await get_redis()
    queue_len = await redis.llen("nf:pipeline:queue")
    retry_len = await redis.zcard("nf:pipeline:retry")
    dead_len = await redis.llen("nf:pipeline:dead_letter")

    return {
        "article_status": status_counts,
        "category_distribution": category_counts,
        "market_impact_count": market_impact_count,
        "value_distribution": {"high": value_dist[0], "medium": value_dist[1], "low": value_dist[2]},
        "queue": {"main": queue_len, "retry": retry_len, "dead_letter": dead_len},
    }


@router.get("/events")
async def pipeline_events(
    article_id: str | None = None,
    stage: str | None = None,
    limit: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Query pipeline events for debugging."""
    query = select(PipelineEvent).order_by(PipelineEvent.created_at.desc()).limit(limit)

    if article_id:
        query = query.where(PipelineEvent.article_id == article_id)
    if stage:
        query = query.where(PipelineEvent.stage == stage)

    result = await db.execute(query)
    events = result.scalars().all()

    return [
        {
            "id": str(e.id),
            "article_id": e.article_id,
            "stage": e.stage,
            "status": e.status,
            "duration_ms": e.duration_ms,
            "error": e.error,
            "created_at": str(e.created_at),
        }
        for e in events
    ]


@router.post("/trigger-poll")
async def trigger_poll(admin: User = Depends(require_admin)):
    """Manually trigger feed polling."""
    from app.pipeline.orchestrator import poll_feeds

    import asyncio
    asyncio.create_task(poll_feeds())
    return {"status": "triggered"}


@router.get("/queue")
async def queue_status(admin: User = Depends(require_admin)):
    """Current queue state with per-article details."""
    redis = await get_redis()
    snapshot = await q.get_queue_snapshot(redis)

    # Add concurrency + pause info
    concurrency_target = await q.get_concurrency(redis)
    health_data = await redis.hgetall(q.QUEUE_HEALTH)
    # decode health_data
    active = int(health_data.get(b"active", health_data.get("active", 0)))
    default_concurrency = 10  # from config

    paused = await q.is_paused(redis)

    # Circuit breaker status
    cb_data = await redis.hgetall("nf:pipeline:circuit_breaker")
    cb_state = "closed"
    cb_failures = 0
    if cb_data:
        cb_state = cb_data.get("state", "closed")
        cb_failures = int(cb_data.get("consecutive_failures", 0))

    return {
        **snapshot,
        "concurrency": {
            "active": active,
            "target": concurrency_target or default_concurrency,
        },
        "paused": paused,
        "circuitBreaker": {
            "state": cb_state,
            "consecutiveFailures": cb_failures,
        },
    }


@router.get("/queue/stream")
async def queue_stream(admin: User = Depends(require_admin)):
    """Real-time queue event stream via SSE."""
    from starlette.responses import StreamingResponse

    return StreamingResponse(
        _queue_stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _queue_stream_generator():
    """SSE generator reading from Redis Stream."""
    import asyncio
    import json as json_mod

    redis = await get_redis()
    last_id = "$"  # Only new events
    error_count = 0

    while True:
        try:
            events = await q.read_stream_events(redis, last_id=last_id, block_ms=30000)
            error_count = 0  # reset on success
            if events:
                for event_id, event_data in events:
                    yield f"data: {json_mod.dumps(event_data, ensure_ascii=False)}\n\n"
                    last_id = event_id
            else:
                # Keepalive
                yield ": keepalive\n\n"
        except Exception:
            error_count += 1
            logger.warning("SSE stream error (count=%d)", error_count)
            if error_count > 10:
                break  # Give up after persistent errors
            yield ": error\n\n"
            await asyncio.sleep(2)


@router.get("/concurrency")
async def get_concurrency(admin: User = Depends(require_admin)):
    """Get current concurrency settings."""
    from app.core.config import load_pipeline_config

    redis = await get_redis()

    target = await q.get_concurrency(redis)
    config = load_pipeline_config()
    default = config.get("consumer", {}).get("concurrency", 10)

    health_data = await redis.hgetall(q.QUEUE_HEALTH)
    active = 0
    if health_data:
        active_val = health_data.get(b"active", health_data.get("active", b"0"))
        active = int(active_val.decode() if isinstance(active_val, bytes) else active_val)

    return {"active": active, "target": target or default, "default": default}


class ConcurrencyRequest(CamelModel):
    concurrency: int


@router.put("/concurrency")
async def update_concurrency(
    data: ConcurrencyRequest,
    admin: User = Depends(require_admin),
):
    """Set pipeline concurrency target."""
    if data.concurrency < 1 or data.concurrency > 50:
        raise HTTPException(status_code=400, detail="concurrency must be 1-50")

    redis = await get_redis()
    prev = await q.get_concurrency(redis)
    await q.set_concurrency(redis, data.concurrency)

    return {"concurrency": data.concurrency, "previous": prev}


@router.put("/pause")
async def pause_pipeline(admin: User = Depends(require_admin)):
    """Pause the pipeline. In-flight articles will complete."""
    redis = await get_redis()
    await q.set_paused(redis, True)
    return {"paused": True}


@router.put("/resume")
async def resume_pipeline(admin: User = Depends(require_admin)):
    """Resume the pipeline."""
    redis = await get_redis()
    await q.set_paused(redis, False)
    return {"paused": False}


@router.get("/circuit-breaker")
async def circuit_breaker_status(admin: User = Depends(require_admin)):
    """Get circuit breaker state."""
    redis = await get_redis()
    data = await redis.hgetall("nf:pipeline:circuit_breaker")
    if not data:
        return {"state": "closed", "consecutiveFailures": 0, "failureThreshold": 5, "recoveryTimeout": 60}
    return {
        "state": data.get("state", "closed"),
        "consecutiveFailures": int(data.get("consecutive_failures", 0)),
        "lastFailureTime": float(data.get("last_failure_time", 0)),
        "updatedAt": data.get("updated_at"),
    }


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker(admin: User = Depends(require_admin)):
    """Manually reset the circuit breaker."""
    from app.pipeline.circuit_breaker import CircuitBreaker
    redis = await get_redis()
    cb = CircuitBreaker(redis)
    await cb.reset()
    return {"state": "closed", "message": "Circuit breaker reset"}


class StoryBatchSizeRequest(CamelModel):
    batch_size: int


@router.get("/story-batch-size")
async def get_story_batch_size(admin: User = Depends(require_admin)):
    """Get current story batch size setting."""
    from app.core.config import load_pipeline_config

    redis = await get_redis()
    val = await redis.get("nf:pipeline:story_batch_size")
    config = load_pipeline_config()
    default = config.get("consumer", {}).get("story_batch_size", 8)

    return {"current": int(val) if val else default, "default": default}


@router.put("/story-batch-size")
async def update_story_batch_size(
    data: StoryBatchSizeRequest,
    admin: User = Depends(require_admin),
):
    """Set story batch size (how many articles before triggering story clustering)."""
    if data.batch_size < 1 or data.batch_size > 50:
        raise HTTPException(status_code=400, detail="batch_size must be 1-50")

    redis = await get_redis()
    prev = await redis.get("nf:pipeline:story_batch_size")
    await redis.set("nf:pipeline:story_batch_size", str(data.batch_size))

    return {"batch_size": data.batch_size, "previous": int(prev) if prev else None}


@router.get("/agent-queue")
async def get_agent_queue(
    limit: int = 20,
    admin: User = Depends(require_admin),
):
    """Peek at the agent queue without consuming."""
    from app.pipeline import agent_queue as aq

    redis = await get_redis()
    items = await aq.peek_queue(redis, limit=min(limit, 50))
    queue_len = await aq.get_queue_length(redis)

    return {"queue_length": queue_len, "items": items}

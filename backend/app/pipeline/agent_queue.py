"""Unified agent queue — all agent LLM calls go through one queue.

Agent groups (all agents for one article) are submitted as a single unit
and executed sequentially by the worker to maximize LLM prefix cache hits.
"""

from __future__ import annotations

import json
import logging
import time
import uuid

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Queue keys
AGENT_QUEUE = "nf:agent:queue"
AGENT_QUEUE_HEALTH = "nf:agent:health"
AGENT_QUEUE_METRICS = "nf:agent:metrics"
AGENT_QUEUE_CONCURRENCY = "nf:agent:concurrency"


async def submit_agent_group(
    redis: aioredis.Redis,
    group_type: str,  # "article", "story", or "system"
    context_data: dict,
    agents: list[str],
    prior_results: dict | None = None,
    display_info: dict | None = None,
    fire_and_forget: bool = False,
) -> tuple[str, str]:
    """Submit an agent group to the unified queue.

    Returns (group_id, result_key) — caller should await wait_results(result_key).
    When ``fire_and_forget=True``, no caller waits on the result; the worker
    self-finalizes DB writes and the result_key gets a short TTL.
    """
    group_id = str(uuid.uuid4())
    result_key = f"nf:agent:result:{group_id}"

    payload = {
        "group_id": group_id,
        "group_type": group_type,
        "context_data": context_data,
        "agents": agents,
        "prior_results": prior_results or {},
        "display_info": display_info or {},
        "result_key": result_key,
        "submitted_at": time.time(),
        "fire_and_forget": fire_and_forget,
    }

    await redis.rpush(AGENT_QUEUE, json.dumps(payload))

    logger.debug(
        "Agent group submitted: %s type=%s agents=%s fire_and_forget=%s",
        group_id[:8], group_type, agents, fire_and_forget,
    )
    return group_id, result_key


async def dequeue_agent_group(redis: aioredis.Redis, timeout: int = 2) -> dict | None:
    """Dequeue an agent group (blocking pop)."""
    result = await redis.blpop(AGENT_QUEUE, timeout=timeout)
    if result is None:
        return None
    _, raw_json = result
    try:
        return json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        logger.error("Malformed agent group payload, dropping: %s", raw_json[:200])
        return None


async def post_results(redis: aioredis.Redis, result_key: str, results: dict) -> None:
    """Post agent group results for the orchestrator to pick up."""
    await redis.rpush(result_key, json.dumps(results))
    # Set expiry so orphaned result keys don't leak
    await redis.expire(result_key, 600)  # 10 min TTL
    logger.debug("Agent results posted to %s (%d agents)", result_key, len(results))


async def wait_results(redis: aioredis.Redis, result_key: str, timeout: int = 0) -> dict | None:
    """Wait for agent group results (blocking pop on result key).

    Worker always posts a result (success or error), so timeout=0 (infinite)
    is the default. The only timeout in the system is in the worker.

    Returns dict of {agent_id: serialized_result} or None on timeout.
    """
    result = await redis.blpop(result_key, timeout=timeout)
    if result is None:
        logger.warning("Agent group result not received: %s", result_key)
        return None
    _, raw_json = result
    # Clean up the key
    await redis.delete(result_key)
    return json.loads(raw_json)


async def get_queue_length(redis: aioredis.Redis) -> int:
    """Get the number of pending agent groups in the queue."""
    return await redis.llen(AGENT_QUEUE)


async def get_concurrency(redis: aioredis.Redis) -> int | None:
    """Get target concurrency from Redis. Returns None if not set."""
    val = await redis.get(AGENT_QUEUE_CONCURRENCY)
    if val is None:
        return None
    return int(val)


async def set_concurrency(redis: aioredis.Redis, value: int) -> None:
    """Set target concurrency for the agent worker."""
    await redis.set(AGENT_QUEUE_CONCURRENCY, str(value))


async def update_health(redis: aioredis.Redis, **kwargs) -> None:
    """Update agent worker health metrics."""
    await redis.hset(AGENT_QUEUE_HEALTH, mapping={k: str(v) for k, v in kwargs.items()})
    await redis.expire(AGENT_QUEUE_HEALTH, 120)  # 2 min TTL


async def increment_metrics(redis: aioredis.Redis, field: str, amount: int = 1) -> None:
    """Increment an agent metrics counter."""
    await redis.hincrby(AGENT_QUEUE_METRICS, field, amount)


async def peek_queue(redis: aioredis.Redis, limit: int = 20) -> list[dict]:
    """Peek at the queue without consuming. Returns display info for each group."""
    raw_items = await redis.lrange(AGENT_QUEUE, 0, limit - 1)
    items = []
    for raw in raw_items:
        try:
            payload = json.loads(raw)
            group_type = payload.get("group_type", "article")
            agents = payload.get("agents", [])

            if group_type == "story":
                display_info = payload.get("display_info", {})
                label = display_info.get("label", "故事线归类")
                items.append({
                    "group_id": payload.get("group_id", ""),
                    "group_type": "story",
                    "label": label,
                    "agents": agents,
                })
            else:
                title = payload.get("context_data", {}).get("title", "")
                items.append({
                    "group_id": payload.get("group_id", ""),
                    "group_type": "article",
                    "label": title[:60] if title else "(unknown)",
                    "agents": agents,
                })
        except (json.JSONDecodeError, TypeError):
            continue
    return items

"""Per-purpose circuit breaker for the LLM pipeline.

State is fully Redis-backed (no in-process state) so the consumer process and
the agent worker process share the same view. Each "purpose" — typically an
agent_id (summarizer, entity, finance_analyzer, translator, ...) or a system
purpose (classifier, cleaner) — has its own independent state.

Two states (no HALF_OPEN):
- CLOSED: failures < threshold; requests flow.
- OPEN:   any one purpose >= threshold consecutive LLM failures; the consumer
          stops dequeueing entirely. A background probe task in the consumer
          periodically sends a 1-token "Hi" through gateway.chat(purpose=X)
          for each OPEN purpose. All probes succeed -> all CLOSED.

Recording:
- record_failure(redis, purpose) is called only for *LLM* failures (not parse
  errors, DB errors, business logic). Detection: gateway raises LLMCallError;
  agent_worker / consumer translate that into a record_failure call.
- record_success(redis, purpose) is called whenever a purpose's LLM call
  succeeds (any successful agent execution counts the agent's purpose).

Storage layout:
- Hash  ``nf:pipeline:circuit_breaker:state``  field=purpose -> JSON state
- String ``nf:pipeline:circuit_breaker:global_open``  "1" if any purpose OPEN
"""

from __future__ import annotations

import json
import logging
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

CB_STATE_HASH = "nf:pipeline:circuit_breaker:state"
CB_GLOBAL_OPEN = "nf:pipeline:circuit_breaker:global_open"
CB_EVENT_STREAM_KEY = "type"  # used by emit_event

CLOSED = "closed"
OPEN = "open"

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_TIMEOUT = 60  # seconds between probe attempts when OPEN


def _empty_state() -> dict:
    return {
        "state": CLOSED,
        "consecutive_failures": 0,
        "last_failure_time": 0.0,
        "last_probe_time": 0.0,
        "last_success_time": 0.0,
        "updated_at": 0.0,
    }


def _decode_state(raw: str | bytes | None) -> dict:
    if not raw:
        return _empty_state()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return _empty_state()
    merged = _empty_state()
    merged.update(data)
    return merged


async def _save_state(redis: aioredis.Redis, purpose: str, state: dict) -> None:
    state["updated_at"] = time.time()
    await redis.hset(CB_STATE_HASH, purpose, json.dumps(state))


async def _refresh_global_open(redis: aioredis.Redis) -> bool:
    """Recompute the global-open flag from per-purpose states. Returns new value."""
    raw_states = await redis.hgetall(CB_STATE_HASH)
    has_open = False
    if raw_states:
        for _, raw in raw_states.items():
            s = _decode_state(raw)
            if s.get("state") == OPEN:
                has_open = True
                break
    await redis.set(CB_GLOBAL_OPEN, "1" if has_open else "0")
    return has_open


async def is_globally_open(redis: aioredis.Redis) -> bool:
    """Fast check: is any purpose OPEN? Used by consumer's dequeue gate."""
    val = await redis.get(CB_GLOBAL_OPEN)
    if val is None:
        # No flag yet — recompute (lazy init)
        return await _refresh_global_open(redis)
    if isinstance(val, bytes):
        val = val.decode("utf-8", errors="replace")
    return val == "1"


async def get_state(redis: aioredis.Redis, purpose: str) -> dict:
    raw = await redis.hget(CB_STATE_HASH, purpose)
    return _decode_state(raw)


async def get_all_states(redis: aioredis.Redis) -> dict[str, dict]:
    raw_states = await redis.hgetall(CB_STATE_HASH)
    if not raw_states:
        return {}
    out: dict[str, dict] = {}
    for k, v in raw_states.items():
        key = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else k
        out[key] = _decode_state(v)
    return out


async def get_open_purposes(redis: aioredis.Redis) -> list[str]:
    states = await get_all_states(redis)
    return [p for p, s in states.items() if s.get("state") == OPEN]


async def record_failure(
    redis: aioredis.Redis,
    purpose: str,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
) -> dict:
    """Record an LLM failure for a purpose. Trips OPEN at threshold.

    Returns the new state dict. Also emits an SSE event on transition.
    """
    state = await get_state(redis, purpose)
    state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
    state["last_failure_time"] = time.time()

    transitioned = False
    if state.get("state") == CLOSED and state["consecutive_failures"] >= failure_threshold:
        state["state"] = OPEN
        transitioned = True

    await _save_state(redis, purpose, state)

    if transitioned:
        await _refresh_global_open(redis)
        logger.warning(
            "Circuit breaker OPEN: purpose=%s after %d consecutive failures (threshold=%d)",
            purpose, state["consecutive_failures"], failure_threshold,
        )
        await _emit_event(redis, "circuit_breaker_open", purpose, state)
    else:
        logger.info(
            "Circuit breaker: purpose=%s failure %d/%d",
            purpose, state["consecutive_failures"], failure_threshold,
        )

    return state


async def record_success(redis: aioredis.Redis, purpose: str) -> dict:
    """Record a successful LLM call. Resets to CLOSED if currently OPEN."""
    state = await get_state(redis, purpose)
    prev = state.get("state", CLOSED)
    state["consecutive_failures"] = 0
    state["last_success_time"] = time.time()
    state["state"] = CLOSED

    await _save_state(redis, purpose, state)

    if prev == OPEN:
        had_open = await _refresh_global_open(redis)
        logger.info(
            "Circuit breaker CLOSED: purpose=%s recovered (any others open=%s)",
            purpose, had_open,
        )
        await _emit_event(redis, "circuit_breaker_closed", purpose, state)
        # If no other purposes are still open, requeue dead letters.
        if not had_open:
            try:
                from app.pipeline.queue import requeue_dead_letters
                requeued = await requeue_dead_letters(redis)
                if requeued:
                    logger.info(
                        "Auto-requeued %d dead-letter articles after CB fully recovered",
                        requeued,
                    )
            except Exception:
                logger.warning("Failed to auto-requeue dead-letter articles", exc_info=True)

    return state


async def reset(redis: aioredis.Redis, purpose: str | None = None) -> None:
    """Manually reset all (or one) purpose to CLOSED."""
    if purpose is None:
        await redis.delete(CB_STATE_HASH)
        await redis.set(CB_GLOBAL_OPEN, "0")
        logger.info("Circuit breaker manually reset (all purposes)")
        await _emit_event(redis, "circuit_breaker_reset", None, None)
    else:
        await redis.hdel(CB_STATE_HASH, purpose)
        await _refresh_global_open(redis)
        logger.info("Circuit breaker manually reset: purpose=%s", purpose)
        await _emit_event(redis, "circuit_breaker_reset", purpose, None)


async def mark_probe_attempt(redis: aioredis.Redis, purpose: str) -> dict:
    """Record that we just attempted a probe for this purpose. Used to throttle."""
    state = await get_state(redis, purpose)
    state["last_probe_time"] = time.time()
    await _save_state(redis, purpose, state)
    return state


async def should_probe(
    redis: aioredis.Redis,
    purpose: str,
    recovery_timeout: int = DEFAULT_RECOVERY_TIMEOUT,
) -> bool:
    """Return True if enough time has passed since last probe to try again."""
    state = await get_state(redis, purpose)
    if state.get("state") != OPEN:
        return False
    last = float(state.get("last_probe_time", 0) or state.get("last_failure_time", 0))
    return (time.time() - last) >= recovery_timeout


async def _emit_event(
    redis: aioredis.Redis,
    event_type: str,
    purpose: str | None,
    state: dict | None,
) -> None:
    """Emit SSE event for state changes (best-effort)."""
    try:
        from app.pipeline.queue import QUEUE_STREAM
        payload = {"type": event_type}
        if purpose is not None:
            payload["purpose"] = purpose
        if state is not None:
            payload["state"] = state.get("state", "")
            payload["consecutive_failures"] = str(state.get("consecutive_failures", 0))
        await redis.xadd(QUEUE_STREAM, payload, maxlen=500, approximate=True)
    except Exception:
        logger.warning("Failed to emit circuit breaker event: %s", event_type, exc_info=True)

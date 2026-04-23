"""Circuit breaker for pipeline consumer — prevents queue drain during LLM outages.

Three states:
- CLOSED: Normal operation, requests flow through
- OPEN: Failures exceeded threshold, requests blocked, periodic probing
- HALF_OPEN: Probing after recovery timeout, single request allowed
"""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Redis keys
CB_STATE_KEY = "nf:pipeline:circuit_breaker"

# States
CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitBreaker:
    """Async circuit breaker with Redis-persisted state."""

    def __init__(
        self,
        redis: aioredis.Redis,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ):
        self._redis = redis
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

        self._state = CLOSED
        self._consecutive_failures = 0
        self._last_failure_time = 0.0
        self._last_probe_time = 0.0

    async def load_state(self) -> None:
        """Load persisted state from Redis (call on startup)."""
        data = await self._redis.hgetall(CB_STATE_KEY)
        if data:
            self._state = data.get("state", CLOSED)
            self._consecutive_failures = int(data.get("consecutive_failures", 0))
            self._last_failure_time = float(data.get("last_failure_time", 0))
            self._last_probe_time = float(data.get("last_probe_time", 0))
            logger.info(
                "Circuit breaker loaded: state=%s failures=%d",
                self._state, self._consecutive_failures,
            )

    async def _persist_state(self) -> None:
        """Persist current state to Redis."""
        try:
            await self._redis.hset(CB_STATE_KEY, mapping={
                "state": self._state,
                "consecutive_failures": str(self._consecutive_failures),
                "last_failure_time": str(self._last_failure_time),
                "last_probe_time": str(self._last_probe_time),
                "updated_at": str(time.time()),
            })
        except Exception:
            logger.warning("Failed to persist circuit breaker state to Redis", exc_info=True)

    @property
    def state(self) -> str:
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    async def on_dequeue_attempt(self) -> bool:
        """Called before dequeue. Returns True if request should proceed.

        Handles OPEN -> HALF_OPEN transition when recovery timeout elapses.
        """
        if self._state == CLOSED:
            return True

        if self._state == OPEN:
            if time.time() - self._last_failure_time >= self._recovery_timeout:
                self._state = HALF_OPEN
                self._last_probe_time = time.time()
                await self._persist_state()
                logger.info("Circuit breaker HALF_OPEN (probing after %ds)", self._recovery_timeout)
                await self._emit_event("circuit_breaker_half_open")
                return True
            return False

        if self._state == HALF_OPEN:
            # Allow a re-probe if recovery timeout elapsed since last probe —
            # handles consumer restart while a probe was in-flight (state stuck
            # as half_open in Redis with no active probe to resolve it).
            if time.time() - self._last_probe_time >= self._recovery_timeout:
                self._last_probe_time = time.time()
                await self._persist_state()
                logger.info("Circuit breaker HALF_OPEN re-probe (no active probe, recovery timeout elapsed)")
                return True
            return False

        return True

    async def record_success(self) -> None:
        """Record a successful processing completion."""
        prev_state = self._state
        self._state = CLOSED
        self._consecutive_failures = 0
        await self._persist_state()

        if prev_state != CLOSED:
            logger.info("Circuit breaker CLOSED (recovered from %s)", prev_state)
            await self._emit_event("circuit_breaker_closed")
            # Auto-requeue dead-letter articles on recovery so they get retried
            # now that the LLM is back.
            try:
                from app.pipeline.queue import requeue_dead_letters
                requeued = await requeue_dead_letters(self._redis)
                if requeued:
                    logger.info("Auto-requeued %d dead-letter articles after circuit breaker recovery", requeued)
            except Exception:
                logger.warning("Failed to auto-requeue dead-letter articles on CB recovery", exc_info=True)

    async def record_failure(self) -> None:
        """Record a processing failure."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

        if self._state == HALF_OPEN:
            self._state = OPEN
            await self._persist_state()
            logger.warning(
                "Circuit breaker OPEN (probe failed, failures=%d)",
                self._consecutive_failures,
            )
            await self._emit_event("circuit_breaker_open")
            return

        if self._state == CLOSED and self._consecutive_failures >= self._failure_threshold:
            self._state = OPEN
            await self._persist_state()
            logger.warning(
                "Circuit breaker OPEN (threshold=%d reached after %d consecutive failures)",
                self._failure_threshold, self._consecutive_failures,
            )
            await self._emit_event("circuit_breaker_open")
            return

        await self._persist_state()

        if self._state == CLOSED:
            logger.info(
                "Circuit breaker: failure %d/%d recorded",
                self._consecutive_failures, self._failure_threshold,
            )

    async def reset(self) -> None:
        """Manually reset circuit breaker (admin action)."""
        self._state = CLOSED
        self._consecutive_failures = 0
        await self._persist_state()
        logger.info("Circuit breaker manually reset")
        await self._emit_event("circuit_breaker_reset")

    async def get_status(self) -> dict:
        """Get current status for admin API."""
        return {
            "state": self._state,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self._failure_threshold,
            "recovery_timeout": self._recovery_timeout,
            "last_failure_time": self._last_failure_time,
            "time_until_probe": max(
                0,
                self._recovery_timeout - (time.time() - self._last_failure_time),
            ) if self._state == OPEN else 0,
        }

    async def _emit_event(self, event_type: str) -> None:
        """Emit SSE event for state changes."""
        try:
            from app.pipeline.queue import QUEUE_STREAM
            await self._redis.xadd(
                QUEUE_STREAM,
                {
                    "type": event_type,
                    "state": self._state,
                    "consecutive_failures": str(self._consecutive_failures),
                },
                maxlen=500,
                approximate=True,
            )
        except Exception:
            logger.warning("Failed to emit circuit breaker event: %s", event_type, exc_info=True)

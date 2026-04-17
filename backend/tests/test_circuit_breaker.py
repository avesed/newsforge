"""Circuit breaker tests — reproduces the HALF_OPEN deadlock bug and verifies the fix.

Bug scenario:
  1. Failures exceed threshold → OPEN
  2. Recovery timeout elapses → OPEN→HALF_OPEN, one probe allowed
  3. Consumer restarts mid-probe (or probe result lost)
  4. New consumer loads HALF_OPEN from Redis
  5. OLD CODE: on_dequeue_attempt() returns False forever → deadlock
  6. FIX: after recovery_timeout elapses again, a re-probe is allowed
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.pipeline.circuit_breaker import (
    CB_STATE_KEY,
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
)


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def cb(redis):
    return CircuitBreaker(redis, failure_threshold=3, recovery_timeout=10)


def _patch_time(ts: float):
    return patch("app.pipeline.circuit_breaker.time.time", return_value=ts)


def _patch_emit():
    return patch.object(CircuitBreaker, "_emit_event", new_callable=AsyncMock)


# ── Basic lifecycle ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_closed_allows_requests(cb):
    assert cb.state == CLOSED
    assert await cb.on_dequeue_attempt() is True


@pytest.mark.asyncio
async def test_failures_open_breaker(cb):
    """3 consecutive failures → OPEN."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()
    assert cb.state == OPEN


@pytest.mark.asyncio
async def test_open_blocks_requests(cb, redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()

    # Still within recovery_timeout (t=1005 < 1000+10)
    with _patch_time(1005.0):
        assert await cb.on_dequeue_attempt() is False


@pytest.mark.asyncio
async def test_open_to_half_open_probe(cb, redis):
    """After recovery_timeout, OPEN → HALF_OPEN and one probe is allowed."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()

    with _patch_emit(), _patch_time(1011.0):
        assert await cb.on_dequeue_attempt() is True
        assert cb.state == HALF_OPEN
        # Second call in HALF_OPEN should block (probe in flight)
        assert await cb.on_dequeue_attempt() is False


@pytest.mark.asyncio
async def test_half_open_probe_success_closes(cb):
    """Successful probe in HALF_OPEN → CLOSED."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()

    with _patch_emit(), _patch_time(1011.0):
        await cb.on_dequeue_attempt()  # → HALF_OPEN
        await cb.record_success()
        assert cb.state == CLOSED
        assert cb.consecutive_failures == 0


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens(cb):
    """Failed probe in HALF_OPEN → back to OPEN."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()

    with _patch_emit(), _patch_time(1011.0):
        await cb.on_dequeue_attempt()  # → HALF_OPEN

    with _patch_emit(), _patch_time(1012.0):
        await cb.record_failure()
        assert cb.state == OPEN


# ── Bug reproduction: HALF_OPEN deadlock after consumer restart ──

@pytest.mark.asyncio
async def test_half_open_deadlock_after_restart(redis):
    """REPRODUCTION: Consumer restart with HALF_OPEN in Redis → stuck forever (old bug).

    This test verifies the fix: after recovery_timeout elapses, a re-probe
    is allowed even when the state was loaded as HALF_OPEN.
    """
    # Phase 1: First consumer trips the breaker and transitions to HALF_OPEN
    cb1 = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=10)
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb1.record_failure()
    assert cb1.state == OPEN

    with _patch_emit(), _patch_time(1011.0):
        allowed = await cb1.on_dequeue_attempt()
        assert allowed is True
        assert cb1.state == HALF_OPEN

    # Phase 2: Consumer "restarts" — new instance loads state from Redis
    cb2 = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=10)
    await cb2.load_state()
    assert cb2.state == HALF_OPEN, "Loaded HALF_OPEN from Redis"

    # Immediately after restart: should still block (within recovery_timeout of probe)
    # last_probe_time was ~1011 when HALF_OPEN entered, recovery_timeout=10
    with _patch_time(1015.0):
        assert await cb2.on_dequeue_attempt() is False, \
            "Should block within recovery_timeout of last probe"

    # After recovery_timeout from probe time: FIX allows re-probe
    with _patch_time(1025.0):
        result = await cb2.on_dequeue_attempt()
        assert result is True, \
            "FIX: should allow re-probe after recovery_timeout elapses in HALF_OPEN"

    # And that re-probe succeeding should close the breaker
    with _patch_emit():
        await cb2.record_success()
    assert cb2.state == CLOSED


@pytest.mark.asyncio
async def test_half_open_reprobe_on_failure_cycles(redis):
    """After restart in HALF_OPEN, failed re-probes cycle OPEN→HALF_OPEN→OPEN...
    until one succeeds.
    """
    # Setup: stuck in HALF_OPEN
    cb = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=10)
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()

    with _patch_emit(), _patch_time(1011.0):
        await cb.on_dequeue_attempt()  # → HALF_OPEN

    # Simulate restart
    cb2 = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=10)
    await cb2.load_state()
    assert cb2.state == HALF_OPEN

    # Re-probe allowed after timeout, but probe fails → back to OPEN
    with _patch_emit(), _patch_time(1022.0):
        assert await cb2.on_dequeue_attempt() is True

    with _patch_emit(), _patch_time(1023.0):
        await cb2.record_failure()
        assert cb2.state == OPEN

    # Next cycle: OPEN → timeout → HALF_OPEN → probe allowed
    with _patch_emit(), _patch_time(1034.0):
        assert await cb2.on_dequeue_attempt() is True
        assert cb2.state == HALF_OPEN

    # This time probe succeeds
    with _patch_emit():
        await cb2.record_success()
    assert cb2.state == CLOSED


# ── Redis persistence ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_persisted_to_redis(cb, redis):
    """State changes are persisted and loadable by a new instance."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()

    data = await redis.hgetall(CB_STATE_KEY)
    assert data["state"] == OPEN
    assert data["consecutive_failures"] == "3"

    cb2 = CircuitBreaker(redis, failure_threshold=3, recovery_timeout=10)
    await cb2.load_state()
    assert cb2.state == OPEN
    assert cb2.consecutive_failures == 3


@pytest.mark.asyncio
async def test_manual_reset(cb, redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure()
    assert cb.state == OPEN

    with _patch_emit():
        await cb.reset()
    assert cb.state == CLOSED
    assert cb.consecutive_failures == 0

    data = await redis.hgetall(CB_STATE_KEY)
    assert data["state"] == CLOSED


@pytest.mark.asyncio
async def test_success_resets_failure_count(cb):
    """Successes in CLOSED state reset the consecutive failure counter."""
    with _patch_emit(), _patch_time(1000.0):
        await cb.record_failure()
        await cb.record_failure()
    assert cb.consecutive_failures == 2

    await cb.record_success()
    assert cb.consecutive_failures == 0
    assert cb.state == CLOSED

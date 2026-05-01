"""Per-purpose circuit breaker tests.

The cb is now Redis-backed and stateless (no class), with per-purpose state
keyed by agent_id / system purpose. Probe-based recovery is driven by an
external probe task in the consumer (not tested here — that test belongs
with the consumer).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.pipeline import circuit_breaker as cb


@pytest.fixture
def redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _patch_emit():
    return patch.object(cb, "_emit_event", new_callable=AsyncMock)


def _patch_time(ts: float):
    return patch("app.pipeline.circuit_breaker.time.time", return_value=ts)


# ── Per-purpose lifecycle ───────────────────────────────────────


@pytest.mark.asyncio
async def test_initial_state_closed(redis):
    state = await cb.get_state(redis, "summarizer")
    assert state["state"] == cb.CLOSED
    assert state["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_failures_open_breaker_for_purpose(redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "summarizer", failure_threshold=3)
    state = await cb.get_state(redis, "summarizer")
    assert state["state"] == cb.OPEN
    assert state["consecutive_failures"] == 3


@pytest.mark.asyncio
async def test_failures_only_affect_named_purpose(redis):
    """summarizer failures must NOT trip translator's cb."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(5):
            await cb.record_failure(redis, "summarizer", failure_threshold=3)

    sum_state = await cb.get_state(redis, "summarizer")
    tr_state = await cb.get_state(redis, "translator")
    assert sum_state["state"] == cb.OPEN
    assert tr_state["state"] == cb.CLOSED


@pytest.mark.asyncio
async def test_global_open_when_any_purpose_open(redis):
    assert await cb.is_globally_open(redis) is False

    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "entity", failure_threshold=3)

    assert await cb.is_globally_open(redis) is True


@pytest.mark.asyncio
async def test_global_clears_when_last_purpose_recovers(redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "entity", failure_threshold=3)
        for _ in range(3):
            await cb.record_failure(redis, "summarizer", failure_threshold=3)

    assert await cb.is_globally_open(redis) is True

    with _patch_emit():
        await cb.record_success(redis, "entity")
    # summarizer still OPEN -> still globally open
    assert await cb.is_globally_open(redis) is True

    with _patch_emit():
        await cb.record_success(redis, "summarizer")
    # both CLOSED -> globally CLOSED
    assert await cb.is_globally_open(redis) is False


@pytest.mark.asyncio
async def test_success_resets_consecutive_failures(redis):
    with _patch_emit(), _patch_time(1000.0):
        await cb.record_failure(redis, "translator", failure_threshold=5)
        await cb.record_failure(redis, "translator", failure_threshold=5)
    state = await cb.get_state(redis, "translator")
    assert state["consecutive_failures"] == 2
    assert state["state"] == cb.CLOSED  # below threshold

    with _patch_emit():
        await cb.record_success(redis, "translator")
    state = await cb.get_state(redis, "translator")
    assert state["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_success_recovers_open_purpose(redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "finance_analyzer", failure_threshold=3)
    assert (await cb.get_state(redis, "finance_analyzer"))["state"] == cb.OPEN

    with _patch_emit():
        await cb.record_success(redis, "finance_analyzer")
    state = await cb.get_state(redis, "finance_analyzer")
    assert state["state"] == cb.CLOSED


@pytest.mark.asyncio
async def test_should_probe_throttle(redis):
    """should_probe() returns False until recovery_timeout elapses."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "classifier", failure_threshold=3)

    # Within recovery window
    with _patch_time(1005.0):
        assert await cb.should_probe(redis, "classifier", recovery_timeout=10) is False

    # Past recovery window — first probe allowed
    with _patch_time(1015.0):
        assert await cb.should_probe(redis, "classifier", recovery_timeout=10) is True

    # mark probe attempt — next call within window blocks again
    with _patch_time(1015.0):
        await cb.mark_probe_attempt(redis, "classifier")

    with _patch_time(1020.0):
        assert await cb.should_probe(redis, "classifier", recovery_timeout=10) is False

    with _patch_time(1030.0):
        assert await cb.should_probe(redis, "classifier", recovery_timeout=10) is True


@pytest.mark.asyncio
async def test_should_probe_only_open(redis):
    """CLOSED purposes are never probed."""
    with _patch_time(1000.0):
        assert await cb.should_probe(redis, "summarizer", recovery_timeout=10) is False


@pytest.mark.asyncio
async def test_get_open_purposes(redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "entity", failure_threshold=3)
        await cb.record_failure(redis, "summarizer", failure_threshold=3)  # 1 failure, CLOSED

    open_p = await cb.get_open_purposes(redis)
    assert open_p == ["entity"]


@pytest.mark.asyncio
async def test_reset_single_purpose(redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "entity", failure_threshold=3)
        for _ in range(3):
            await cb.record_failure(redis, "translator", failure_threshold=3)

    with _patch_emit(), patch("app.pipeline.queue.requeue_dead_letters",
                              new_callable=AsyncMock, return_value=0):
        await cb.reset(redis, purpose="entity")

    assert (await cb.get_state(redis, "entity"))["state"] == cb.CLOSED
    assert (await cb.get_state(redis, "translator"))["state"] == cb.OPEN
    assert await cb.is_globally_open(redis) is True


@pytest.mark.asyncio
async def test_reset_all_purposes(redis):
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "entity", failure_threshold=3)
        for _ in range(3):
            await cb.record_failure(redis, "translator", failure_threshold=3)

    with _patch_emit():
        await cb.reset(redis)

    states = await cb.get_all_states(redis)
    assert states == {}
    assert await cb.is_globally_open(redis) is False


# ── Redis persistence ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_survives_process_restart(redis):
    """Redis is the source of truth — a fresh process sees prior state."""
    with _patch_emit(), _patch_time(1000.0):
        for _ in range(3):
            await cb.record_failure(redis, "summarizer", failure_threshold=3)

    # Simulate restart: nothing to do — state lives entirely in Redis
    state = await cb.get_state(redis, "summarizer")
    assert state["state"] == cb.OPEN
    assert state["consecutive_failures"] == 3
    assert await cb.is_globally_open(redis) is True

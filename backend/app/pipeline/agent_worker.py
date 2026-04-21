"""Agent worker — processes agent groups from the unified queue.

Mirrors PipelineConsumer's pattern (BLPOP loop, counter-based concurrency,
graceful shutdown) but processes agent groups instead of articles.

Key design: agents within a group execute SEQUENTIALLY (not parallel) to
maximize LLM prefix cache hit rate — all agents for one article share the
same system prompt + article block prefix.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from app.core.config import load_pipeline_config
from app.db.redis import get_redis
from app.pipeline import agent_queue as aq
from app.pipeline.agents.base import AgentContext, AgentResult
from app.pipeline.agents.registry import get_agent_registry
from app.pipeline.events import record_event
from app.pipeline.queue import QUEUE_STREAM

logger = logging.getLogger(__name__)


def _serialize_agent_result(result: AgentResult) -> dict:
    """Serialize an AgentResult for transport."""
    return {
        "success": result.success,
        "duration_ms": round(result.duration_ms, 1),
        "tokens_used": result.tokens_used,
        "error": result.error,
        "data": result.data,
    }


async def _persist_and_emit(redis, article_id: str, agent_id: str, serialized: dict) -> None:
    """Per-agent: DB write + SSE event + Redis checkpoint. All best-effort."""
    # 1. Write agent-specific columns to DB
    from app.pipeline.agent_db_writer import write_agent_result

    try:
        await write_agent_result(article_id, agent_id, serialized)
    except Exception:
        logger.warning("Per-agent DB write failed: %s:%s", article_id[:8], agent_id, exc_info=True)

    # 2. Emit SSE stream event (agent_complete)
    try:
        await redis.xadd(
            QUEUE_STREAM,
            {
                "type": "agent_complete",
                "article_id": article_id,
                "agent_id": agent_id,
                "success": "1" if serialized.get("success") else "0",
                "duration_ms": str(round(serialized.get("duration_ms", 0))),
                "tokens_used": str(serialized.get("tokens_used", 0)),
                "error": (serialized.get("error") or "")[:200],
            },
            maxlen=500,
            approximate=True,
        )
    except Exception:
        logger.debug("SSE emit failed for %s:%s", article_id[:8], agent_id)

    # 3. Update per-agent checkpoint in Redis Hash
    try:
        checkpoint_key = f"nf:agent:checkpoint:{article_id}"
        await redis.hset(checkpoint_key, agent_id, json.dumps(serialized))
        await redis.expire(checkpoint_key, 7200)
    except Exception:
        logger.debug("Checkpoint write failed for %s:%s", article_id[:8], agent_id)


async def _emit_agent_start(redis, article_id: str, agent_id: str) -> None:
    """Emit agent_start SSE event. Best-effort."""
    try:
        await redis.xadd(
            QUEUE_STREAM,
            {"type": "agent_start", "article_id": article_id, "agent_id": agent_id},
            maxlen=500,
            approximate=True,
        )
    except Exception:
        logger.debug("SSE agent_start emit failed: %s:%s", article_id[:8], agent_id, exc_info=True)


class AgentWorker:
    """Processes agent groups from the unified agent queue."""

    def __init__(self):
        config = load_pipeline_config()
        worker_config = config.get("agent_worker", {})

        self._concurrency = worker_config.get("concurrency", 6)
        self._per_group_timeout = worker_config.get("per_group_timeout_seconds", 300)

        self._active_count = 0
        self._concurrency_target = self._concurrency
        self._shutdown = False
        self._processed = 0
        self._start_time = time.time()
        self._tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        """Main worker loop."""
        logger.info(
            "Agent worker starting (concurrency=%d, timeout=%ds)",
            self._concurrency_target, self._per_group_timeout,
        )

        # Note: signal handlers are NOT registered here because the worker
        # runs in the same process as PipelineConsumer (via run_consumer).
        # The consumer's signal handler triggers shutdown; the worker detects
        # it via CancelledError when the task is cancelled.

        redis = await get_redis()

        # Sync concurrency from Redis
        target = await aq.get_concurrency(redis)
        if target is not None:
            self._concurrency_target = target

        # Start background concurrency poller
        config_task = asyncio.create_task(self._config_poller(redis))

        try:
            while not self._shutdown:
                # Capacity check (counter-based, no semaphore)
                if self._active_count >= self._concurrency_target:
                    await asyncio.sleep(0.1)
                    continue

                group = await aq.dequeue_agent_group(redis, timeout=2)
                if group is None:
                    continue

                self._active_count += 1
                task = asyncio.create_task(self._execute_group_safe(redis, group))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

                # Periodic health update
                await aq.update_health(
                    redis,
                    active=self._active_count,
                    concurrency=self._concurrency_target,
                    processed=self._processed,
                    uptime=int(time.time() - self._start_time),
                )

        except asyncio.CancelledError:
            logger.info("Agent worker cancelled")
        finally:
            config_task.cancel()
            # Wait for in-flight tasks
            if self._tasks:
                logger.info("Waiting for %d in-flight agent groups...", len(self._tasks))
                await asyncio.wait(self._tasks, timeout=45)
            logger.info("Agent worker stopped (processed=%d)", self._processed)

    async def _execute_group_safe(self, redis, group: dict) -> None:
        """Execute an agent group with timeout and error handling."""
        group_id = group.get("group_id", "?")
        result_key = group.get("result_key")

        if not result_key:
            logger.error("Agent group %s missing result_key, dropping", group_id[:8])
            self._active_count -= 1
            return

        try:
            results = await asyncio.wait_for(
                self._execute_group(redis, group),
                timeout=self._per_group_timeout,
            )
            await aq.post_results(redis, result_key, results)
            self._processed += 1
            await aq.increment_metrics(redis, "completed", 1)

        except asyncio.TimeoutError:
            logger.error(
                "Agent group %s timed out after %ds",
                group_id[:8], self._per_group_timeout,
            )
            await aq.post_results(redis, result_key, {"_error": "timeout"})
            await aq.increment_metrics(redis, "timeouts", 1)

        except Exception:
            logger.exception("Agent group %s failed", group_id[:8])
            try:
                await aq.post_results(redis, result_key, {"_error": "worker_error"})
            except Exception:
                logger.warning("Failed to post error result for group %s", group_id[:8])
            await aq.increment_metrics(redis, "errors", 1)

        finally:
            self._active_count -= 1

    async def _execute_group(self, redis, group: dict) -> dict:
        """Execute all agents in a group sequentially for prefix cache optimization."""
        group_type = group.get("group_type", "article")

        # Story groups have their own execution path
        if group_type == "story":
            return await self._execute_story_group(group)

        registry = get_agent_registry()
        context_data = group["context_data"]
        agent_ids = group["agents"]
        prior_results = group.get("prior_results", {})

        group_start = time.monotonic()

        # Build context
        context = AgentContext(
            article_id=context_data.get("article_id", ""),
            title=context_data.get("title", ""),
            summary=context_data.get("summary"),
            full_text=context_data.get("full_text"),
            language=context_data.get("language"),
            categories=context_data.get("categories", []),
            has_market_impact=context_data.get("has_market_impact", False),
            value_score=context_data.get("value_score", 0),
            url=context_data.get("url"),
            source_name=context_data.get("source_name"),
        )

        # Restore prior results (from checkpoint) into context
        for agent_id, result_data in prior_results.items():
            context.agent_results[agent_id] = AgentResult(
                agent_id=agent_id,
                success=result_data.get("success", False),
                data=result_data.get("data", {}),
                duration_ms=result_data.get("duration_ms", 0),
                tokens_used=result_data.get("tokens_used", 0),
            )

        # Resolve agents and group by phase
        agents_by_phase: dict[int, list] = {}
        for agent_id in agent_ids:
            agent = registry.get_agent(agent_id)
            if agent is None:
                logger.warning("Unknown agent_id in group: %s", agent_id)
                continue
            agents_by_phase.setdefault(agent.phase, []).append(agent)

        # Execute agents by phase.
        # Within a phase: agents with no unmet deps run in PARALLEL for speed,
        # but requests are staggered slightly so vLLM prefix cache prefill
        # can match against the shared system+article prefix.
        # Agents with unmet deps wait for deps, then run.
        results: dict[str, dict] = {}

        for phase_num in sorted(agents_by_phase.keys()):
            phase_agents = agents_by_phase[phase_num]

            # Split into ready (deps satisfied) and waiting (deps pending)
            ready = []
            waiting = []
            for agent in phase_agents:
                # Skip if already completed (from prior_results)
                if agent.agent_id in prior_results:
                    pr = prior_results[agent.agent_id]
                    if pr.get("success", False):
                        results[agent.agent_id] = pr
                        continue

                missing_deps = [
                    dep for dep in agent.requires
                    if dep not in context.agent_results
                ]
                if missing_deps:
                    waiting.append(agent)
                else:
                    ready.append(agent)

            # Run ready agents in parallel (prefix cache hits on prefill)
            if ready:
                async def _run_one(agent):
                    await _emit_agent_start(redis, context.article_id, agent.agent_id)
                    res = await agent.safe_execute(context)
                    if isinstance(res, Exception):
                        # This shouldn't happen since safe_execute catches, but just in case
                        res = AgentResult(
                            agent_id=agent.agent_id, success=False, data={},
                            duration_ms=0, error=str(res)[:500],
                        )
                    context.agent_results[res.agent_id] = res
                    serialized = _serialize_agent_result(res)
                    results[res.agent_id] = serialized
                    # Per-agent persist + emit
                    await _persist_and_emit(redis, context.article_id, res.agent_id, serialized)
                    # Record pipeline event (existing)
                    try:
                        await record_event(
                            context.article_id,
                            f"agent:{res.agent_id}",
                            "success" if res.success else "error",
                            duration_ms=res.duration_ms,
                            metadata={"tokens": res.tokens_used},
                            error=res.error,
                        )
                    except Exception:
                        logger.debug("Failed to record event for agent %s", res.agent_id)
                    return res

                parallel_results = await asyncio.gather(
                    *[_run_one(agent) for agent in ready],
                    return_exceptions=True,
                )
                # Handle any unexpected exceptions from _run_one itself
                for agent, res in zip(ready, parallel_results):
                    if isinstance(res, Exception):
                        logger.exception("Agent wrapper %s raised error", agent.agent_id)
                        err_result = AgentResult(
                            agent_id=agent.agent_id, success=False, data={},
                            duration_ms=0, error=str(res)[:500],
                        )
                        context.agent_results[err_result.agent_id] = err_result
                        serialized = _serialize_agent_result(err_result)
                        results[err_result.agent_id] = serialized
                        await _persist_and_emit(redis, context.article_id, err_result.agent_id, serialized)

            # Run waiting agents sequentially (deps now available)
            for agent in waiting:
                failed_deps = [
                    dep for dep in agent.requires
                    if dep in context.agent_results and not context.agent_results[dep].success
                ]
                if failed_deps:
                    logger.warning(
                        "Agent %s running with failed dependencies: %s",
                        agent.agent_id, failed_deps,
                    )

                await _emit_agent_start(redis, context.article_id, agent.agent_id)
                result = await agent.safe_execute(context)
                context.agent_results[result.agent_id] = result
                serialized = _serialize_agent_result(result)
                results[result.agent_id] = serialized
                await _persist_and_emit(redis, context.article_id, result.agent_id, serialized)

                # Record pipeline event (best-effort)
                try:
                    await record_event(
                        context.article_id,
                        f"agent:{result.agent_id}",
                        "success" if result.success else "error",
                        duration_ms=result.duration_ms,
                        metadata={"tokens": result.tokens_used},
                        error=result.error,
                    )
                except Exception:
                    logger.debug("Failed to record event for agent %s", result.agent_id)

        group_duration = (time.monotonic() - group_start) * 1000
        total_tokens = sum(
            r.get("tokens_used", 0) for r in results.values() if r.get("success")
        )
        logger.info(
            "Agent group complete: %s | type=%s | %d agents | %d tokens | %.0fms",
            context.article_id[:8] if context.article_id else "system",
            group_type,
            len(results),
            total_tokens,
            group_duration,
        )

        return results

    async def _execute_story_group(self, group: dict) -> dict:
        """Execute a story clustering group."""
        from app.pipeline.agents.story_matcher import BatchStoryMatcher

        article_ids = group.get("context_data", {}).get("article_ids", [])
        if not article_ids:
            logger.warning("Story group has no article_ids")
            return {"story_matcher": {"success": False, "error": "no article_ids"}}

        matcher = BatchStoryMatcher()
        result = await matcher.execute(article_ids)

        logger.info(
            "Story group complete: %d articles | matched=%d created=%d skipped=%d",
            len(article_ids),
            result.get("matched", 0),
            result.get("created", 0),
            result.get("skipped", 0),
        )

        return {"story_matcher": result}

    async def _config_poller(self, redis) -> None:
        """Poll Redis for concurrency target changes."""
        while not self._shutdown:
            try:
                target = await aq.get_concurrency(redis)
                if target is not None and target != self._concurrency_target:
                    logger.info(
                        "Agent worker concurrency changed: %d -> %d",
                        self._concurrency_target, target,
                    )
                    self._concurrency_target = target
            except Exception:
                logger.debug("Config poll error", exc_info=True)
            await asyncio.sleep(5)


async def run_agent_worker() -> None:
    """Entry point for the agent worker process."""
    worker = AgentWorker()
    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [agent-worker] %(levelname)s %(message)s",
    )
    asyncio.run(run_agent_worker())

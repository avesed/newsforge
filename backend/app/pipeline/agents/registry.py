"""Agent registry — singleton that manages agent definitions and trigger resolution.

Trigger types:
1. always: Run for every high-value article
2. category_triggered: Run when article matches specific categories
3. condition_triggered: Run when custom conditions are met

The registry loads trigger configuration from pipeline.yml and resolves
which agents to run for a given article based on its classification.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import load_pipeline_config
from app.pipeline.agents.base import AgentDefinition

logger = logging.getLogger(__name__)

_registry: AgentRegistry | None = None
_priority_override: dict | None = None


def set_priority_override(config: dict | None) -> None:
    """Set in-process priority override (called by admin API)."""
    global _priority_override
    _priority_override = config


async def load_priority_override_from_redis() -> None:
    """Load priority override from Redis on startup. Called once."""
    global _priority_override
    try:
        from app.db.redis import get_redis
        redis = await get_redis()
        raw = await redis.get("nf:pipeline:agent_priority")
        if raw:
            import json
            _priority_override = json.loads(raw)
            logger.info("Loaded agent priority override from Redis: %s", _priority_override)
    except Exception:
        logger.debug("No agent priority override in Redis")


class AgentRegistry:
    """Singleton registry for pipeline agent definitions."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._triggers: dict[str, Any] = {}
        self._routing_rules: dict[str, Any] = {}
        self._priority_config: dict[str, Any] = {}
        self._load_triggers()

    def _load_triggers(self) -> None:
        """Load agent trigger configuration from pipeline.yml."""
        config = load_pipeline_config()
        self._triggers = config.get("agent_triggers", {})
        self._routing_rules = config.get("routing_rules", {})
        # Use runtime override if set, else fall back to pipeline.yml
        if _priority_override is not None:
            self._priority_config = _priority_override
        else:
            self._priority_config = config.get("agent_priority", {})

    def register(self, agent: AgentDefinition) -> None:
        """Register an agent definition."""
        if agent.agent_id in self._agents:
            logger.warning("Agent %s already registered, overwriting", agent.agent_id)
        self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id: str) -> AgentDefinition | None:
        """Get a registered agent by ID."""
        return self._agents.get(agent_id)

    def all_agents(self) -> dict[str, AgentDefinition]:
        """Return all registered agents."""
        return dict(self._agents)

    def resolve_agents(
        self,
        categories: list[str],
        value_score: int,
        has_market_impact: bool,
        source_categories: list[str] | None = None,
    ) -> dict[int, list[AgentDefinition]]:
        """Resolve which agents to run based on article classification.

        Returns {phase: [agents]} grouped by execution phase, sorted.
        """
        high_threshold = self._routing_rules.get("high_value_threshold", 60)
        medium_threshold = self._routing_rules.get("medium_value_threshold", 30)
        market_upgrades = self._routing_rules.get("market_impact_upgrades_to_high", True)

        # Determine processing tier
        effective_score = value_score
        if has_market_impact and market_upgrades:
            effective_score = max(effective_score, high_threshold)

        lightweight_threshold = self._routing_rules.get("lightweight_threshold", 15)
        lightweight_agent_ids = self._routing_rules.get("lightweight_agents", [])

        if effective_score < lightweight_threshold:
            # Very low value: no agents
            return {}

        if effective_score < medium_threshold:
            # Lightweight: basic entity/tag extraction only
            agent_ids = list(lightweight_agent_ids)
        elif effective_score < high_threshold:
            # Medium value: limited agents
            agent_ids = list(self._routing_rules.get("medium_value_agents", []))
        else:
            # High value: full agent resolution
            agent_ids = list(self._triggers.get("always", []))

            # Category-triggered agents
            cat_triggers = self._triggers.get("category_triggered", {})
            for cat in categories:
                if cat in cat_triggers:
                    agent_ids.extend(cat_triggers[cat])

            # Condition-triggered agents
            cond_triggers = self._triggers.get("condition_triggered", [])
            for trigger in cond_triggers:
                condition = trigger.get("condition", "")
                agents = trigger.get("agents", [])
                if self._evaluate_condition(condition, categories, has_market_impact, value_score):
                    agent_ids.extend(agents)

        # --- finance_analyzer: conditional trigger ---
        # Runs when ANY of: (1) article category matches, (2) has_market_impact,
        # (3) source/feed pre-tagged as finance
        if "finance_analyzer" not in agent_ids and "finance_analyzer" in self._agents:
            fa_cats = set(self._triggers.get("finance_analyzer_categories", []))
            source_cats = set(source_categories or [])
            should_run = (
                has_market_impact
                or bool(fa_cats & set(categories))
                or "finance" in source_cats
            )
            if should_run:
                agent_ids.append("finance_analyzer")

        return self._collect_agents(set(agent_ids))

    def resolve_agents_tiered(
        self,
        categories: list[str],
        value_score: int,
        has_market_impact: bool,
        source_categories: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Resolve agents split into P1 (high priority) and P2 (low priority).

        P1 agents are user-facing (summarizer, translator, entity).
        P2 agents are analytical (finance_analyzer, embedder) and can
        be disabled via ``agent_priority.p2_enabled: false`` for standalone
        deployments (except embedder, which always runs).

        Returns ``(p1_agent_ids, p2_agent_ids)`` preserving execution order.
        If priority config is absent, all agents are returned as P1 (backward
        compatible).
        """
        all_phases = self.resolve_agents(
            categories, value_score, has_market_impact, source_categories
        )
        if not all_phases:
            return [], []

        # Flatten to ordered list of agent IDs (phase order, then alphabetical)
        all_ids: list[str] = []
        for phase_num in sorted(all_phases.keys()):
            for agent in all_phases[phase_num]:
                all_ids.append(agent.agent_id)

        p1_set = set(self._priority_config.get("p1_agents", []))
        p2_enabled = self._priority_config.get("p2_enabled", True)

        # No priority config → everything is P1 (backward compatible)
        if not p1_set:
            return all_ids, []

        # Classify: agents in p1_set are P1; the rest are P2.
        # Dependency rule: if an agent requires any P2 agent, it must be P2.
        p2_ids_set: set[str] = set()
        for aid in all_ids:
            if aid not in p1_set:
                p2_ids_set.add(aid)

        # Enforce dependency constraint: P1 agent requiring a P2 agent → move to P2
        changed = True
        while changed:
            changed = False
            for aid in list(all_ids):
                if aid in p2_ids_set:
                    continue
                agent = self._agents.get(aid)
                if agent and any(dep in p2_ids_set for dep in agent.requires):
                    p2_ids_set.add(aid)
                    changed = True
                    logger.info(
                        "Agent '%s' moved to P2 (depends on P2 agent)", aid
                    )

        p1_ids = [aid for aid in all_ids if aid not in p2_ids_set]
        p2_ids = [aid for aid in all_ids if aid in p2_ids_set]

        if not p2_enabled:
            # When P2 is disabled, keep embedder — move it to P1 tail
            kept = [aid for aid in p2_ids if aid == "embedder"]
            dropped = [aid for aid in p2_ids if aid != "embedder"]
            if dropped:
                logger.debug("P2 agents disabled by config, dropping: %s", dropped)
            if kept:
                logger.debug("P2 disabled but keeping embedder in P1: %s", kept)
                p1_ids = p1_ids + kept
            p2_ids = []

        return p1_ids, p2_ids

    def _collect_agents(
        self, agent_ids: set[str] | list[str]
    ) -> dict[int, list[AgentDefinition]]:
        """Collect agent definitions and group by phase."""
        phases: dict[int, list[AgentDefinition]] = {}

        for aid in agent_ids:
            agent = self._agents.get(aid)
            if agent is None:
                logger.warning("Agent '%s' referenced in config but not registered", aid)
                continue
            phase = agent.phase
            if phase not in phases:
                phases[phase] = []
            phases[phase].append(agent)

        # Sort phases and agents within each phase by agent_id for determinism
        return {
            k: sorted(v, key=lambda a: a.agent_id)
            for k, v in sorted(phases.items())
        }

    @staticmethod
    def _evaluate_condition(
        condition: str,
        categories: list[str],
        has_market_impact: bool,
        value_score: int,
    ) -> bool:
        """Evaluate a trigger condition expression.

        Supported variables: categories, has_market_impact, value_score.
        Uses safe eval with restricted namespace.
        """
        if not condition:
            return False
        try:
            result = eval(  # noqa: S307
                condition,
                {"__builtins__": {}},
                {
                    "categories": categories,
                    "has_market_impact": has_market_impact,
                    "value_score": value_score,
                    "any": any,
                    "all": all,
                    "len": len,
                },
            )
            return bool(result)
        except Exception:
            logger.warning("Failed to evaluate trigger condition: %s", condition)
            return False


def get_agent_registry() -> AgentRegistry:
    """Get or create the agent registry singleton."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
        _register_all_agents(_registry)
    return _registry


def reset_agent_registry() -> None:
    """Reset the registry (e.g., after config reload)."""
    global _registry
    _registry = None


def _register_all_agents(registry: AgentRegistry) -> None:
    """Register all built-in agents."""
    from app.pipeline.agents.summarizer import UnifiedSummarizerAgent
    from app.pipeline.agents.entity import UnifiedEntityAgent
    from app.pipeline.agents.finance_analyzer import FinanceAnalyzerAgent
    from app.pipeline.agents.embedder import EmbedderAgent
    from app.pipeline.agents.translator import TranslatorAgent

    agents: list[AgentDefinition] = [
        UnifiedSummarizerAgent(),
        UnifiedEntityAgent(),
        FinanceAnalyzerAgent(),
        EmbedderAgent(),
        TranslatorAgent(),
    ]

    for agent in agents:
        registry.register(agent)

    logger.info("Registered %d pipeline agents", len(agents))

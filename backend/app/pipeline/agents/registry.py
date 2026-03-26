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


class AgentRegistry:
    """Singleton registry for pipeline agent definitions."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._triggers: dict[str, Any] = {}
        self._routing_rules: dict[str, Any] = {}
        self._load_triggers()

    def _load_triggers(self) -> None:
        """Load agent trigger configuration from pipeline.yml."""
        config = load_pipeline_config()
        self._triggers = config.get("agent_triggers", {})
        self._routing_rules = config.get("routing_rules", {})

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

        if effective_score < medium_threshold:
            # Low value: no agents
            return {}

        if effective_score < high_threshold:
            # Medium value: limited agents
            medium_agent_ids = self._routing_rules.get("medium_value_agents", [])
            return self._collect_agents(medium_agent_ids)

        # High value: full agent resolution
        agent_ids: set[str] = set()

        # Always-run agents
        always_agents = self._triggers.get("always", [])
        agent_ids.update(always_agents)

        # Category-triggered agents
        cat_triggers = self._triggers.get("category_triggered", {})
        for cat in categories:
            if cat in cat_triggers:
                agent_ids.update(cat_triggers[cat])

        # Condition-triggered agents
        cond_triggers = self._triggers.get("condition_triggered", [])
        for trigger in cond_triggers:
            condition = trigger.get("condition", "")
            agents = trigger.get("agents", [])
            if self._evaluate_condition(condition, categories, has_market_impact, value_score):
                agent_ids.update(agents)

        return self._collect_agents(agent_ids)

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
    from app.pipeline.agents.sentiment import UnifiedSentimentAgent
    from app.pipeline.agents.tagger import UnifiedTaggerAgent
    from app.pipeline.agents.scorer import ImpactScorerAgent
    from app.pipeline.agents.domain_specific import PoliticsImpactAgent, TechTrendAgent
    from app.pipeline.agents.deep_reporter import DeepReporterAgent
    from app.pipeline.agents.embedder import EmbedderAgent
    from app.pipeline.agents.story_matcher import StoryMatcherAgent

    agents: list[AgentDefinition] = [
        UnifiedSummarizerAgent(),
        UnifiedEntityAgent(),
        UnifiedSentimentAgent(),
        UnifiedTaggerAgent(),
        ImpactScorerAgent(),
        PoliticsImpactAgent(),
        TechTrendAgent(),
        DeepReporterAgent(),
        EmbedderAgent(),
        StoryMatcherAgent(),
    ]

    for agent in agents:
        registry.register(agent)

    logger.info("Registered %d pipeline agents", len(agents))

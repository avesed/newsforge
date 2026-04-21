"""Per-agent incremental DB writer.

Each agent writes its own dedicated columns immediately after execution,
rather than waiting for all agents to complete. Merged fields (entities,
finance_metadata) are finalized once all agents are done.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import update as sql_update

logger = logging.getLogger(__name__)


# Map agent_id -> lambda(result_data) -> dict of column values.
# Only agents with dedicated columns are listed here.
# Agents that contribute to merged fields (entity, tagger) are handled by finalize_merged_fields.
AGENT_COLUMN_MAP: dict[str, Any] = {
    "summarizer": lambda d: {
        k: v
        for k, v in {
            "ai_summary": d.get("ai_summary"),
            "detailed_summary": d.get("detailed_summary"),
        }.items()
        if v is not None
    },
    "translator": lambda d: {
        k: v
        for k, v in {
            "title_zh": d.get("title_zh"),
            "full_text_zh": d.get("full_text_zh"),
        }.items()
        if v is not None
    },
    "sentiment": lambda d: {
        k: v
        for k, v in {
            "sentiment_score": d.get("sentiment_score"),
            "sentiment_label": d.get("sentiment_label"),
        }.items()
        if v is not None
    },
    "finance_analyzer": lambda d: {
        k: v
        for k, v in {
            "sentiment_score": d.get("sentiment_score"),
            "sentiment_label": d.get("sentiment_label"),
            "ai_analysis": d.get("analysis_report"),
        }.items()
        if v is not None
    },
}


async def write_agent_result(article_id: str, agent_id: str, serialized: dict) -> None:
    """Write agent-specific columns to DB immediately after agent execution.

    Best-effort: logs warnings on failure, never raises.
    """
    if agent_id not in AGENT_COLUMN_MAP:
        return
    if not serialized.get("success"):
        return

    data = serialized.get("data", {})
    if not data:
        return

    extractor = AGENT_COLUMN_MAP[agent_id]
    columns = extractor(data)
    if not columns:
        return

    try:
        from app.db.database import get_session_factory
        from app.models.article import Article

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                sql_update(Article)
                .where(Article.id == article_id)
                .values(**columns)
            )
            await session.commit()
        logger.debug(
            "Per-agent DB write OK: %s:%s cols=%s",
            article_id[:8], agent_id, list(columns.keys()),
        )
    except Exception:
        logger.warning(
            "Per-agent DB write failed: %s:%s",
            article_id[:8], agent_id, exc_info=True,
        )


async def finalize_merged_fields(
    article_id: str, agent_data: dict, session,
    classification: dict | None = None,
) -> dict:
    """Extract and merge entity + finance_metadata fields from all agents.

    Takes the full agent_data dict, an existing DB session, and optionally
    the classification result dict (which now contains industry_tags and
    event_tags after the tagger-merger).
    Returns a dict of column values to merge into the consumer's update_values.
    """
    from app.models.article import Article

    update_values: dict[str, Any] = {}

    # --- Collect entity results (unified "entity" agent or legacy "entity_*" agents) ---
    all_entities: list[dict] = []
    for aid, agent_result in agent_data.items():
        if (aid == "entity" or aid.startswith("entity_")) and agent_result.get("success"):
            entities = agent_result.get("data", {}).get("entities", [])
            all_entities.extend(entities)

    _CONF_MAP = {"high": 0.9, "medium": 0.5, "low": 0.1}
    if all_entities:
        update_values["entities"] = all_entities
        # Primary entity = highest confidence
        best = max(
            all_entities,
            key=lambda e: e.get("confidence", 0)
            if isinstance(e.get("confidence"), (int, float))
            else _CONF_MAP.get(str(e.get("confidence", "")), 0),
        )
        update_values["primary_entity"] = best.get("name")
        update_values["primary_entity_type"] = best.get("type")

    # --- Finance metadata (WebStock compatible) ---
    # Preserve existing finance_metadata (e.g., ingested_by from ingest endpoint).
    # READ COMMITTED isolation is sufficient here because worker writes (via
    # write_agent_result with independent sessions) complete before consumer
    # calls finalize_merged_fields — timing guaranteed by orchestrator await.
    try:
        existing_article = await session.get(Article, article_id)
    except Exception:
        logger.warning(
            "finalize_merged_fields: failed to read existing article %s, "
            "skipping finance_metadata merge", article_id[:8], exc_info=True,
        )
        existing_article = None
    finance_meta = (
        dict(existing_article.finance_metadata)
        if existing_article and existing_article.finance_metadata
        else {}
    )

    # Finance analyzer (merged sentiment + deep_reporter) or legacy sentiment agent
    fa_result = agent_data.get("finance_analyzer") or agent_data.get("sentiment") or {}
    if fa_result.get("success"):
        fd = fa_result.get("data", {})
        if fd.get("finance_sentiment"):
            finance_meta["sentiment_tag"] = fd["finance_sentiment"]
        if fd.get("investment_summary"):
            finance_meta["investment_summary"] = fd["investment_summary"]
        if fd.get("financial_entities"):
            finance_meta["financial_entities"] = fd["financial_entities"]
        if fd.get("sectors"):
            finance_meta["sectors"] = fd["sectors"]
        if fd.get("policy_analysis"):
            finance_meta["policy_analysis"] = fd["policy_analysis"]

    # industry_tags and event_tags now come from classifier (merged from former tagger agent)
    if classification:
        if classification.get("industry_tags"):
            finance_meta["industry_tags"] = classification["industry_tags"]
        if classification.get("event_tags"):
            finance_meta["event_tags"] = classification["event_tags"]

    # Note: stock/index entity types removed — symbol resolution now handled
    # externally. finance_metadata["symbols"] may still be set by ingest endpoint.

    # Set market from entity agent primary_market
    entity_result = agent_data.get("entity", {})
    if entity_result.get("success"):
        ed = entity_result.get("data", {})
        if ed.get("primary_market"):
            finance_meta["market"] = ed["primary_market"]

    if finance_meta:
        update_values["finance_metadata"] = finance_meta

    if update_values:
        logger.debug(
            "finalize_merged_fields %s: fields=%s entities=%d finance_keys=%s",
            article_id[:8],
            list(update_values.keys()),
            len(all_entities),
            list(finance_meta.keys()) if finance_meta else [],
        )

    return update_values


async def finalize_p2_merged_fields(
    article_id: str,
    agent_data: dict,
    successful_ids: list[str],
    session,
) -> None:
    """Merge P2 (low-priority) agent results into an already-finalized article.

    Unlike ``finalize_merged_fields`` (called by consumer for P1 agents), this:
    - Reads existing ``finance_metadata`` and merges additively (not replaces)
    - Appends P2 agent IDs to ``agents_executed``
    - Uses ``SELECT ... FOR UPDATE`` to prevent race conditions
    - Per-agent columns (sentiment_score, sentiment_label) are already written
      by ``_persist_and_emit`` during execution, so only merged fields need handling.
    """
    from sqlalchemy import select as sql_select, update as sql_update
    from app.models.article import Article

    # Read existing article with lock
    result = await session.execute(
        sql_select(Article).where(Article.id == article_id).with_for_update()
    )
    article = result.scalar_one_or_none()
    if not article:
        logger.warning("P2 finalize: article %s not found", article_id[:8])
        return

    # --- Merge finance_metadata contributions from P2 agents ---
    finance_meta = dict(article.finance_metadata) if article.finance_metadata else {}

    fa_result = agent_data.get("finance_analyzer") or agent_data.get("sentiment") or {}
    if isinstance(fa_result, dict) and fa_result.get("success"):
        fd = fa_result.get("data", {})
        if fd.get("finance_sentiment"):
            finance_meta["sentiment_tag"] = fd["finance_sentiment"]
        if fd.get("investment_summary"):
            finance_meta["investment_summary"] = fd["investment_summary"]
        if fd.get("financial_entities"):
            finance_meta["financial_entities"] = fd["financial_entities"]
        if fd.get("sectors"):
            finance_meta["sectors"] = fd["sectors"]
        if fd.get("policy_analysis"):
            finance_meta["policy_analysis"] = fd["policy_analysis"]

    # Build update dict
    update_values: dict[str, Any] = {}

    if finance_meta:
        update_values["finance_metadata"] = finance_meta

    # Append P2 agent IDs to agents_executed
    existing_agents = list(article.agents_executed or [])
    new_agents = [aid for aid in successful_ids if aid not in existing_agents]
    if new_agents:
        update_values["agents_executed"] = existing_agents + new_agents

    # Update pipeline_metadata with P2 agent data
    pipeline_meta = dict(article.pipeline_metadata) if article.pipeline_metadata else {}
    p2_agents_meta = {}
    for aid, result_data in agent_data.items():
        if isinstance(result_data, dict):
            p2_agents_meta[aid] = result_data
    if p2_agents_meta:
        agents_meta = pipeline_meta.get("agents", {})
        agents_meta.update(p2_agents_meta)
        pipeline_meta["agents"] = agents_meta
        update_values["pipeline_metadata"] = pipeline_meta

    if update_values:
        await session.execute(
            sql_update(Article)
            .where(Article.id == article_id)
            .values(**update_values)
        )
        logger.debug(
            "finalize_p2_merged_fields %s: fields=%s new_agents=%s",
            article_id[:8],
            list(update_values.keys()),
            new_agents,
        )

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
    article_id: str, agent_data: dict, session
) -> dict:
    """Extract and merge entity + finance_metadata fields from all agents.

    Takes the full agent_data dict and an existing DB session.
    Returns a dict of column values to merge into the consumer's update_values.

    This consolidates logic previously inline in consumer._process_article
    (entities from entity/entity_* agents, finance_metadata from sentiment +
    tagger + entity agents).
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

    sentiment_result = agent_data.get("sentiment", {})
    if sentiment_result.get("success"):
        sd = sentiment_result.get("data", {})
        if sd.get("finance_sentiment"):
            finance_meta["sentiment_tag"] = sd["finance_sentiment"]
        if sd.get("investment_summary"):
            finance_meta["investment_summary"] = sd["investment_summary"]

    tagger_result = agent_data.get("tagger", {})
    if tagger_result.get("success"):
        td = tagger_result.get("data", {})
        if td.get("industry_tags"):
            finance_meta["industry_tags"] = td["industry_tags"]
        if td.get("event_tags"):
            finance_meta["event_tags"] = td["event_tags"]

    # Extract stock symbols from entity results
    stock_entities = [e for e in all_entities if e.get("type") in ("stock", "index")]
    if stock_entities:
        symbols = []
        for e in stock_entities:
            sym = e.get("symbol") or e.get("name", "")
            if sym:
                symbols.append(sym)
        finance_meta["symbols"] = symbols

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

"""Pipeline event recording — writes key events to pipeline_events table.

Used for observability: track classification, content fetch, agent execution,
and errors through the admin pipeline monitor.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def record_event(
    article_id: str,
    stage: str,
    status: str,
    duration_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Record a pipeline event to the database.

    Args:
        article_id: The article being processed.
        stage: Pipeline stage (classify, fetch, agent, embed, etc.).
        status: Outcome (success, error, skip, warning).
        duration_ms: How long this stage took.
        metadata: Additional context (model, tokens, categories, etc.).
        error: Error message if status is error/warning.
    """
    try:
        from app.db.database import get_session_factory
        from app.models.pipeline_event import PipelineEvent

        factory = get_session_factory()
        async with factory() as session:
            event = PipelineEvent(
                article_id=article_id,
                stage=stage,
                status=status,
                duration_ms=duration_ms,
                metadata_=metadata,
                error=error,
            )
            session.add(event)
            await session.commit()
    except Exception as e:
        # Never let event recording break the pipeline
        logger.warning("Failed to record pipeline event: %s", e)

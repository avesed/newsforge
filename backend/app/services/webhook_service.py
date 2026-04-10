"""Webhook service — trigger webhooks on events, async fire-and-forget."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook import Webhook

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT = 10.0  # seconds
_MAX_CONSECUTIVE_FAILURES = 10


async def trigger_webhooks(
    db: AsyncSession,
    event_type: str,
    payload: dict,
) -> None:
    """Find matching webhooks and fire them asynchronously.

    Does not block the caller — launches tasks in the background.
    """
    # Find active webhooks subscribed to this event
    query = (
        select(Webhook)
        .where(
            Webhook.is_active.is_(True),
            Webhook.events.any(event_type),
        )
    )
    result = await db.execute(query)
    webhooks = result.scalars().all()

    if not webhooks:
        return

    # Build the full event payload
    event_payload = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }

    # Apply filters and fire in background
    for webhook in webhooks:
        if not _matches_filters(webhook, payload):
            continue
        asyncio.create_task(
            _deliver_webhook(
                webhook_id=webhook.id,
                webhook_url=webhook.url,
                webhook_secret=webhook.secret,
                webhook_consecutive_failures=webhook.consecutive_failures,
                events=webhook.events,
                event_type=event_type,
                event_payload=event_payload,
            )
        )


def _matches_filters(webhook: Webhook, payload: dict) -> bool:
    """Check if the payload matches the webhook's optional filters."""
    if not webhook.filters:
        return True

    filters = webhook.filters

    # Category filter
    if "categories" in filters:
        article_categories = payload.get("categories", [])
        primary = payload.get("primary_category")
        all_cats = set(article_categories or [])
        if primary:
            all_cats.add(primary)
        if not all_cats.intersection(set(filters["categories"])):
            return False

    # Minimum value score filter
    if "min_value_score" in filters:
        score = payload.get("value_score")
        if score is None or score < filters["min_value_score"]:
            return False

    # Filter by ingested_by (for WebStock integration)
    ingested_by = filters.get("ingested_by")
    if ingested_by:
        article_meta = payload.get("finance_metadata") or {}
        if article_meta.get("ingested_by") != ingested_by:
            return False

    return True


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature of payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


async def _deliver_webhook(
    webhook_id: str,
    webhook_url: str,
    webhook_secret: str,
    webhook_consecutive_failures: int,
    events: list[str],
    event_type: str,
    event_payload: dict,
) -> None:
    """Send HTTP POST to webhook URL with HMAC signature.

    Creates its own DB session to avoid sharing a session across concurrent tasks.
    """
    from app.db.database import get_session_factory

    payload_bytes = json.dumps(event_payload, default=str).encode("utf-8")
    signature = _sign_payload(payload_bytes, webhook_secret)

    headers = {
        "Content-Type": "application/json",
        "X-NewsForge-Signature": f"sha256={signature}",
        "X-NewsForge-Event": event_payload["event"],
    }

    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
            response = await client.post(
                webhook_url,
                content=payload_bytes,
                headers=headers,
            )

        factory = get_session_factory()
        async with factory() as session:
            if response.status_code < 400:
                # Success — reset failure counter
                await session.execute(
                    update(Webhook)
                    .where(Webhook.id == webhook_id)
                    .values(
                        consecutive_failures=0,
                        last_triggered_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                logger.debug("Webhook %s delivered: %s %d", webhook_id, webhook_url, response.status_code)
            else:
                await _record_failure(session, webhook_id, webhook_consecutive_failures, f"HTTP {response.status_code}")

    except httpx.TimeoutException:
        await _record_failure_standalone(webhook_id, webhook_consecutive_failures, "Timeout")
    except Exception as exc:
        await _record_failure_standalone(webhook_id, webhook_consecutive_failures, str(exc)[:200])


async def _record_failure(
    db: AsyncSession,
    webhook_id: str,
    consecutive_failures: int,
    reason: str,
) -> None:
    """Increment failure counter; disable webhook after too many consecutive failures.

    Expects a session that the caller manages (commit/close).
    """
    new_count = consecutive_failures + 1
    values: dict = {
        "consecutive_failures": new_count,
        "last_triggered_at": datetime.now(timezone.utc),
    }

    if new_count >= _MAX_CONSECUTIVE_FAILURES:
        values["is_active"] = False
        logger.warning(
            "Webhook %s disabled after %d consecutive failures (last: %s)",
            webhook_id,
            new_count,
            reason,
        )
    else:
        logger.info("Webhook %s delivery failed (%d/%d): %s", webhook_id, new_count, _MAX_CONSECUTIVE_FAILURES, reason)

    await db.execute(
        update(Webhook).where(Webhook.id == webhook_id).values(**values)
    )
    await db.commit()


async def _record_failure_standalone(
    webhook_id: str,
    consecutive_failures: int,
    reason: str,
) -> None:
    """Record failure with its own DB session (for use outside a session context)."""
    from app.db.database import get_session_factory

    try:
        factory = get_session_factory()
        async with factory() as session:
            await _record_failure(session, webhook_id, consecutive_failures, reason)
    except Exception:
        logger.exception("Failed to record webhook failure for %s", webhook_id)


async def send_test_event(db: AsyncSession, webhook: Webhook) -> dict:
    """Send a test event to a webhook and return the result."""
    test_payload = {
        "event": "test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "message": "This is a test event from NewsForge.",
            "webhook_id": str(webhook.id),
        },
    }

    payload_bytes = json.dumps(test_payload, default=str).encode("utf-8")
    signature = _sign_payload(payload_bytes, webhook.secret)

    headers = {
        "Content-Type": "application/json",
        "X-NewsForge-Signature": f"sha256={signature}",
        "X-NewsForge-Event": "test",
    }

    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
            response = await client.post(
                webhook.url,
                content=payload_bytes,
                headers=headers,
            )
        return {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "response_body": response.text[:500],
        }
    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout"}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:200]}

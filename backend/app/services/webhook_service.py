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
    tasks = []
    for webhook in webhooks:
        if not _matches_filters(webhook, payload):
            continue
        tasks.append(_deliver_webhook(db, webhook, event_payload))

    if tasks:
        # Fire-and-forget: don't await completion
        asyncio.gather(*tasks, return_exceptions=True)


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

    return True


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature of payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


async def _deliver_webhook(
    db: AsyncSession,
    webhook: Webhook,
    event_payload: dict,
) -> None:
    """Send HTTP POST to webhook URL with HMAC signature."""
    payload_bytes = json.dumps(event_payload, default=str).encode("utf-8")
    signature = _sign_payload(payload_bytes, webhook.secret)

    headers = {
        "Content-Type": "application/json",
        "X-NewsForge-Signature": f"sha256={signature}",
        "X-NewsForge-Event": event_payload["event"],
    }

    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT) as client:
            response = await client.post(
                webhook.url,
                content=payload_bytes,
                headers=headers,
            )

        if response.status_code < 400:
            # Success — reset failure counter
            await db.execute(
                update(Webhook)
                .where(Webhook.id == webhook.id)
                .values(
                    consecutive_failures=0,
                    last_triggered_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()
            logger.debug("Webhook %s delivered: %s %d", webhook.id, webhook.url, response.status_code)
        else:
            await _record_failure(db, webhook, f"HTTP {response.status_code}")

    except httpx.TimeoutException:
        await _record_failure(db, webhook, "Timeout")
    except Exception as exc:
        await _record_failure(db, webhook, str(exc)[:200])


async def _record_failure(db: AsyncSession, webhook: Webhook, reason: str) -> None:
    """Increment failure counter; disable webhook after too many consecutive failures."""
    new_count = webhook.consecutive_failures + 1
    values: dict = {
        "consecutive_failures": new_count,
        "last_triggered_at": datetime.now(timezone.utc),
    }

    if new_count >= _MAX_CONSECUTIVE_FAILURES:
        values["is_active"] = False
        logger.warning(
            "Webhook %s disabled after %d consecutive failures (last: %s)",
            webhook.id,
            new_count,
            reason,
        )
    else:
        logger.info("Webhook %s delivery failed (%d/%d): %s", webhook.id, new_count, _MAX_CONSECUTIVE_FAILURES, reason)

    await db.execute(
        update(Webhook).where(Webhook.id == webhook.id).values(**values)
    )
    await db.commit()


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

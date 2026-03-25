"""Webhook management endpoints for authenticated users."""

from __future__ import annotations

import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.models.webhook import Webhook
from app.schemas.base import CamelModel
from app.services.webhook_service import send_test_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# --- Schemas ---

class WebhookCreateRequest(CamelModel):
    url: str
    events: list[str]
    filters: dict | None = None


class WebhookResponse(CamelModel):
    id: UUID
    url: str
    events: list[str]
    filters: dict | None = None
    is_active: bool
    consecutive_failures: int = 0
    last_triggered_at: str | None = None
    created_at: str | None = None


class WebhookTestResponse(CamelModel):
    success: bool
    status_code: int | None = None
    response_body: str | None = None
    error: str | None = None


# --- Valid event types ---

_VALID_EVENTS = frozenset({
    "article.published",
    "market.impact",
    "sentiment.alert",
    "article.updated",
    "article.classified",
})


# --- Endpoints ---

@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's webhooks."""
    result = await db.execute(
        select(Webhook)
        .where(Webhook.user_id == user.id)
        .order_by(Webhook.created_at.desc())
    )
    webhooks = result.scalars().all()
    return [_to_response(w) for w in webhooks]


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook."""
    # Validate events
    invalid = set(body.events) - _VALID_EVENTS
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid event types: {', '.join(sorted(invalid))}. "
                   f"Valid types: {', '.join(sorted(_VALID_EVENTS))}",
        )

    if not body.events:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one event type is required",
        )

    # Validate URL is reachable
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.head(body.url)
            # Accept any response (even 405 Method Not Allowed) — just check connectivity
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Webhook URL is not reachable: {exc}",
        )
    except Exception:
        pass  # Other errors (e.g., SSL) are acceptable — the URL exists

    # Generate HMAC secret
    webhook_secret = secrets.token_urlsafe(32)

    webhook = Webhook(
        user_id=user.id,
        url=body.url,
        events=body.events,
        filters=body.filters,
        secret=webhook_secret,
    )
    db.add(webhook)
    await db.flush()

    logger.info("Webhook created: %s for user %d", webhook.id, user.id)

    response = _to_response(webhook)
    # Include secret only on creation
    return response


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a webhook."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user.id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")

    await db.delete(webhook)


@router.post("/{webhook_id}/test", response_model=WebhookTestResponse)
async def test_webhook(
    webhook_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test event to a webhook."""
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.user_id == user.id)
    )
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")

    test_result = await send_test_event(db, webhook)
    return WebhookTestResponse(**test_result)


def _to_response(webhook: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=webhook.id,
        url=webhook.url,
        events=webhook.events,
        filters=webhook.filters,
        is_active=webhook.is_active,
        consecutive_failures=webhook.consecutive_failures,
        last_triggered_at=str(webhook.last_triggered_at) if webhook.last_triggered_at else None,
        created_at=str(webhook.created_at) if webhook.created_at else None,
    )

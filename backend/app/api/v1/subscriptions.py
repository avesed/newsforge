"""Subscription endpoints — user subscriptions to categories/keywords."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.base import CamelModel

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class SubscriptionResponse(CamelModel):
    id: UUID
    type: str
    target_id: str | None = None
    keywords: list[str] | None = None
    is_active: bool


class SubscriptionCreateRequest(CamelModel):
    type: str  # category, keyword, source, feed
    target_id: str | None = None
    keywords: list[str] | None = None


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    body: SubscriptionCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.type not in ("category", "keyword", "source", "feed"):
        raise HTTPException(status_code=400, detail="Invalid subscription type")

    sub = Subscription(
        user_id=user.id,
        type=body.type,
        target_id=body.target_id,
        keywords=body.keywords,
    )
    db.add(sub)
    await db.flush()
    return sub


@router.delete("/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    sub_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user.id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    await db.delete(sub)

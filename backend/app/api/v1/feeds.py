"""Feed management endpoints — add/list/delete RSS feeds."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.feed import Feed
from app.models.user import User
from app.schemas.base import CamelModel

router = APIRouter(prefix="/feeds", tags=["feeds"])


class FeedCreateRequest(CamelModel):
    url: str
    title: str | None = None
    feed_type: str = "native_rss"  # native_rss, rsshub
    rsshub_route: str | None = None
    category_id: UUID | None = None
    poll_interval_minutes: int = 15


class FeedResponse(CamelModel):
    id: UUID
    url: str
    title: str | None = None
    feed_type: str
    rsshub_route: str | None = None
    category_id: UUID | None = None
    poll_interval_minutes: int
    is_enabled: bool
    article_count: int
    consecutive_errors: int
    last_error: str | None = None


@router.get("", response_model=list[FeedResponse])
async def list_feeds(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's RSS feeds."""
    result = await db.execute(
        select(Feed).where(Feed.user_id == user.id).order_by(Feed.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
async def create_feed(
    body: FeedCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a custom RSS feed."""
    # Check duplicate
    existing = await db.execute(select(Feed).where(Feed.url == body.url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Feed URL already exists")

    feed = Feed(
        url=body.url,
        title=body.title,
        feed_type=body.feed_type,
        rsshub_route=body.rsshub_route,
        category_id=body.category_id,
        poll_interval_minutes=max(5, body.poll_interval_minutes),
        user_id=user.id,
    )
    db.add(feed)
    await db.flush()
    return feed


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(
    feed_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user's RSS feed."""
    result = await db.execute(
        select(Feed).where(Feed.id == feed_id, Feed.user_id == user.id)
    )
    feed = result.scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    await db.delete(feed)

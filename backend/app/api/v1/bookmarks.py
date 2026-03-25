"""Bookmark endpoints — favorites / read later."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.database import get_db
from app.models.article import Article
from app.models.bookmark import Bookmark
from app.models.user import User
from app.schemas.base import CamelModel

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


class BookmarkResponse(CamelModel):
    id: UUID
    article_id: UUID
    article_title: str | None = None
    article_url: str | None = None
    article_primary_category: str | None = None
    note: str | None = None
    created_at: str | None = None


class BookmarkCreateRequest(CamelModel):
    article_id: UUID
    note: str | None = None


@router.get("", response_model=list[BookmarkResponse])
async def list_bookmarks(
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List user's bookmarks with article info."""
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Bookmark, Article.title, Article.url, Article.primary_category)
        .join(Article, Bookmark.article_id == Article.id)
        .where(Bookmark.user_id == user.id)
        .order_by(Bookmark.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    bookmarks = []
    for row in result.all():
        bm = row[0]
        bookmarks.append(BookmarkResponse(
            id=bm.id,
            article_id=bm.article_id,
            article_title=row[1],
            article_url=row[2],
            article_primary_category=row[3],
            note=bm.note,
            created_at=str(bm.created_at) if bm.created_at else None,
        ))
    return bookmarks


@router.post("", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark(
    body: BookmarkCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add article to bookmarks."""
    # Check article exists
    article = await db.execute(select(Article).where(Article.id == body.article_id))
    if article.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Article not found")

    # Check duplicate
    existing = await db.execute(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.article_id == body.article_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Already bookmarked")

    bm = Bookmark(user_id=user.id, article_id=body.article_id, note=body.note)
    db.add(bm)
    await db.flush()

    return BookmarkResponse(id=bm.id, article_id=bm.article_id, note=bm.note)


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == user.id)
    )
    bm = result.scalar_one_or_none()
    if bm is None:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    await db.delete(bm)

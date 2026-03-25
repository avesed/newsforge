"""Category endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.category import Category
from app.schemas.article import CategoryResponse
from app.services.cache_service import cache

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryResponse])
async def list_categories(db: AsyncSession = Depends(get_db)):
    """List all active categories with article counts."""
    cached = await cache.get("categories")
    if cached:
        return [CategoryResponse(**c) for c in cached]

    result = await db.execute(
        select(Category)
        .where(Category.is_active == True)  # noqa: E712
        .order_by(Category.sort_order)
    )
    categories = result.scalars().all()

    await cache.set(
        "categories",
        [CategoryResponse.model_validate(c).model_dump(mode="json") for c in categories],
        ttl_seconds=600,
    )
    return categories

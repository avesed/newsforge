"""Admin source and feed management endpoints."""

from __future__ import annotations

import logging
from uuid import UUID

import feedparser
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.models.category import Category
from app.models.feed import Feed
from app.models.source import Source
from app.models.user import User
from app.schemas.base import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/sources", tags=["admin"])


# ---------------------------------------------------------------------------
# Source schemas
# ---------------------------------------------------------------------------

class SourceResponse(CamelModel):
    id: UUID
    name: str
    source_type: str
    provider: str
    categories: list[str] | None = None
    markets: list[str] | None = None
    is_enabled: bool
    health_status: str
    consecutive_errors: int
    article_count: int


class SourceCreateRequest(CamelModel):
    name: str
    source_type: str
    provider: str
    config: dict | None = None
    categories: list[str] | None = None
    markets: list[str] | None = None


class SourceUpdateRequest(CamelModel):
    is_enabled: bool | None = None
    name: str | None = None
    config: dict | None = None


# ---------------------------------------------------------------------------
# Feed schemas
# ---------------------------------------------------------------------------

class FeedCreateRequest(CamelModel):
    url: str
    title: str | None = None
    feed_type: str = "native_rss"
    rsshub_route: str | None = None
    source_id: str | None = None
    category_slug: str | None = None
    poll_interval_minutes: int = 15
    fulltext_mode: bool = False


class FeedUpdateRequest(CamelModel):
    title: str | None = None
    is_enabled: bool | None = None
    poll_interval_minutes: int | None = None
    fulltext_mode: bool | None = None
    category_slug: str | None = None


class FeedResponse(CamelModel):
    id: str
    url: str
    title: str | None
    feed_type: str
    rsshub_route: str | None
    source_id: str | None
    category_id: str | None
    category_slug: str | None
    poll_interval_minutes: int
    fulltext_mode: bool
    is_enabled: bool
    last_polled_at: str | None
    consecutive_errors: int
    article_count: int
    last_error: str | None
    user_id: int | None


class FeedTestResponse(CamelModel):
    success: bool
    message: str
    article_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_category_slug(db: AsyncSession, slug: str) -> UUID:
    """Look up category by slug, raise 404 if not found."""
    result = await db.execute(select(Category).where(Category.slug == slug))
    cat = result.scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail=f"Category '{slug}' not found")
    return cat.id


async def _feed_to_response(feed: Feed, db: AsyncSession) -> dict:
    """Convert a Feed ORM object to a FeedResponse-compatible dict."""
    category_slug: str | None = None
    if feed.category_id is not None:
        result = await db.execute(select(Category.slug).where(Category.id == feed.category_id))
        category_slug = result.scalar_one_or_none()

    return {
        "id": str(feed.id),
        "url": feed.url,
        "title": feed.title,
        "feed_type": feed.feed_type,
        "rsshub_route": feed.rsshub_route,
        "source_id": str(feed.source_id) if feed.source_id else None,
        "category_id": str(feed.category_id) if feed.category_id else None,
        "category_slug": category_slug,
        "poll_interval_minutes": feed.poll_interval_minutes,
        "fulltext_mode": feed.fulltext_mode,
        "is_enabled": feed.is_enabled,
        "last_polled_at": feed.last_polled_at.isoformat() if feed.last_polled_at else None,
        "consecutive_errors": feed.consecutive_errors,
        "article_count": feed.article_count,
        "last_error": feed.last_error,
        "user_id": feed.user_id,
    }


# ---------------------------------------------------------------------------
# Source endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SourceResponse])
async def list_sources(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Source).order_by(Source.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    source = Source(
        name=body.name,
        source_type=body.source_type,
        provider=body.provider,
        config=body.config or {},
        categories=body.categories,
        markets=body.markets,
    )
    db.add(source)
    await db.flush()
    return source


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: UUID,
    body: SourceUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a source (e.g., enable/disable toggle)."""
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if body.is_enabled is not None:
        source.is_enabled = body.is_enabled
    if body.name is not None:
        source.name = body.name
    if body.config is not None:
        source.config = body.config

    await db.flush()
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    await db.delete(source)


# ---------------------------------------------------------------------------
# Feed endpoints
# ---------------------------------------------------------------------------

@router.get("/feeds", response_model=list[FeedResponse])
async def list_all_feeds(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all feeds (system + user) for admin, with category slug."""
    result = await db.execute(select(Feed).order_by(Feed.created_at.desc()))
    feeds = result.scalars().all()

    # Batch-load category slugs to avoid N+1
    category_ids = {f.category_id for f in feeds if f.category_id is not None}
    slug_map: dict[UUID, str] = {}
    if category_ids:
        cat_result = await db.execute(
            select(Category.id, Category.slug).where(Category.id.in_(category_ids))
        )
        slug_map = {row.id: row.slug for row in cat_result}

    return [
        {
            "id": str(f.id),
            "url": f.url,
            "title": f.title,
            "feed_type": f.feed_type,
            "rsshub_route": f.rsshub_route,
            "source_id": str(f.source_id) if f.source_id else None,
            "category_id": str(f.category_id) if f.category_id else None,
            "category_slug": slug_map.get(f.category_id) if f.category_id else None,
            "poll_interval_minutes": f.poll_interval_minutes,
            "fulltext_mode": f.fulltext_mode,
            "is_enabled": f.is_enabled,
            "last_polled_at": f.last_polled_at.isoformat() if f.last_polled_at else None,
            "consecutive_errors": f.consecutive_errors,
            "article_count": f.article_count,
            "last_error": f.last_error,
            "user_id": f.user_id,
        }
        for f in feeds
    ]


@router.post("/feeds", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
async def create_feed(
    body: FeedCreateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new system feed."""
    # Check for duplicate URL
    existing = await db.execute(select(Feed.id).where(Feed.url == body.url))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A feed with this URL already exists",
        )

    # Resolve category slug -> id
    category_id: UUID | None = None
    if body.category_slug:
        category_id = await _resolve_category_slug(db, body.category_slug)

    # Validate source_id if provided
    source_id: UUID | None = None
    if body.source_id:
        source_id = UUID(body.source_id)
        src = await db.execute(select(Source.id).where(Source.id == source_id))
        if src.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Source not found")

    feed = Feed(
        url=body.url,
        title=body.title,
        feed_type=body.feed_type,
        rsshub_route=body.rsshub_route,
        source_id=source_id,
        category_id=category_id,
        poll_interval_minutes=body.poll_interval_minutes,
        fulltext_mode=body.fulltext_mode,
        user_id=None,  # System feed
    )
    db.add(feed)
    await db.flush()
    await db.refresh(feed)

    return await _feed_to_response(feed, db)


@router.patch("/feeds/{feed_id}", response_model=FeedResponse)
async def update_feed(
    feed_id: UUID,
    body: FeedUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Partially update a feed."""
    result = await db.execute(select(Feed).where(Feed.id == feed_id))
    feed = result.scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    if body.title is not None:
        feed.title = body.title
    if body.is_enabled is not None:
        feed.is_enabled = body.is_enabled
    if body.poll_interval_minutes is not None:
        feed.poll_interval_minutes = body.poll_interval_minutes
    if body.fulltext_mode is not None:
        feed.fulltext_mode = body.fulltext_mode
    if body.category_slug is not None:
        feed.category_id = await _resolve_category_slug(db, body.category_slug)

    await db.flush()
    return await _feed_to_response(feed, db)


@router.delete("/feeds/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_feed(
    feed_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a feed."""
    result = await db.execute(select(Feed).where(Feed.id == feed_id))
    feed = result.scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    await db.delete(feed)


@router.post("/feeds/{feed_id}/test", response_model=FeedTestResponse)
async def test_feed(
    feed_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Test a feed by fetching its URL and counting parseable articles."""
    result = await db.execute(select(Feed).where(Feed.id == feed_id))
    feed = result.scalar_one_or_none()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(feed.url, follow_redirects=True)
            resp.raise_for_status()

        parsed = feedparser.parse(resp.text)

        if parsed.bozo and not parsed.entries:
            return FeedTestResponse(
                success=False,
                message=f"Feed parse error: {parsed.bozo_exception}",
                article_count=0,
            )

        count = len(parsed.entries)
        feed_title = parsed.feed.get("title", "")
        return FeedTestResponse(
            success=True,
            message=f"Successfully parsed feed '{feed_title}' with {count} article(s)",
            article_count=count,
        )

    except httpx.HTTPStatusError as exc:
        return FeedTestResponse(
            success=False,
            message=f"HTTP {exc.response.status_code} from feed URL",
            article_count=0,
        )
    except httpx.RequestError as exc:
        return FeedTestResponse(
            success=False,
            message=f"Connection error: {exc}",
            article_count=0,
        )
    except Exception as exc:
        logger.exception("Unexpected error testing feed %s", feed_id)
        return FeedTestResponse(
            success=False,
            message=f"Unexpected error: {exc}",
            article_count=0,
        )


# ---------------------------------------------------------------------------
# Google News feed builder
# ---------------------------------------------------------------------------

@router.get("/google-news/options")
async def google_news_options(admin: User = Depends(require_admin)):
    """Return available Google News topics and locales for the feed builder UI."""
    from app.sources.rss.google_news import (
        TOPIC_MIDS, TOPIC_TO_CATEGORY, LOCALES,
        build_topic_url, build_top_stories_url,
    )

    topics = [
        {"id": "top_stories", "label_en": "Top Stories", "label_zh": "头条", "category": None},
    ]
    for topic_id, mid in TOPIC_MIDS.items():
        category = TOPIC_TO_CATEGORY.get(topic_id)
        # Human-readable labels
        labels = {
            "world": ("World", "国际"),
            "business": ("Business", "商业/财经"),
            "technology": ("Technology", "科技"),
            "entertainment": ("Entertainment", "娱乐"),
            "sports": ("Sports", "体育"),
            "science": ("Science", "科学"),
            "health": ("Health", "健康"),
        }
        en, zh = labels.get(topic_id, (topic_id.title(), topic_id))
        topics.append({"id": topic_id, "label_en": en, "label_zh": zh, "category": category})

    locales = [
        {"id": "zh-CN", "label_en": "China (Simplified Chinese)", "label_zh": "中国 (简体中文)"},
        {"id": "zh-TW", "label_en": "Taiwan (Traditional Chinese)", "label_zh": "台湾 (繁体中文)"},
        {"id": "zh-HK", "label_en": "Hong Kong (Traditional Chinese)", "label_zh": "香港 (繁体中文)"},
        {"id": "en-US", "label_en": "United States (English)", "label_zh": "美国 (英文)"},
        {"id": "en-GB", "label_en": "United Kingdom (English)", "label_zh": "英国 (英文)"},
        {"id": "en-AU", "label_en": "Australia (English)", "label_zh": "澳大利亚 (英文)"},
        {"id": "en-IN", "label_en": "India (English)", "label_zh": "印度 (英文)"},
        {"id": "ja-JP", "label_en": "Japan (Japanese)", "label_zh": "日本 (日文)"},
        {"id": "ko-KR", "label_en": "Korea (Korean)", "label_zh": "韩国 (韩文)"},
    ]

    return {"topics": topics, "locales": locales}


@router.post("/google-news/build-url")
async def google_news_build_url(
    body: dict,
    admin: User = Depends(require_admin),
):
    """Generate a Google News RSS URL from topic + locale selection."""
    from app.sources.rss.google_news import (
        build_topic_url, build_top_stories_url, TOPIC_TO_CATEGORY,
    )

    topic = body.get("topic", "top_stories")
    locale = body.get("locale", "zh-CN")

    if topic == "top_stories":
        url = build_top_stories_url(locale)
        category = None
    else:
        url = build_topic_url(topic, locale)
        category = TOPIC_TO_CATEGORY.get(topic)

    # Build a nice title
    locale_names = {"zh-CN": "ZH-CN", "zh-TW": "ZH-TW", "zh-HK": "ZH-HK", "en-US": "EN-US", "en-GB": "EN-GB", "en-AU": "EN-AU", "en-IN": "EN-IN", "ja-JP": "JA-JP", "ko-KR": "KO-KR"}
    topic_names = {"top_stories": "头条", "world": "国际", "business": "商业", "technology": "科技", "entertainment": "娱乐", "sports": "体育", "science": "科学", "health": "健康"}

    title = f"Google News {topic_names.get(topic, topic)} ({locale_names.get(locale, locale)})"

    return {"url": url, "title": title, "category": category}

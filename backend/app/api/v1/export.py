"""RSS/Atom export endpoints — generate feed XML from articles."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.article import Article

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])

_SITE_TITLE = "NewsForge"
_SITE_LINK = "https://newsforge.app"
_SITE_DESCRIPTION = "Universal news aggregation and analysis platform"


def _build_article_query(
    category: str | None,
    tags: str | None,
    language: str | None,
    limit: int,
):
    """Build common article query with filters."""
    query = (
        select(Article)
        .where(Article.content_status.in_(["processed", "embedded", "fetched"]))
        .order_by(Article.published_at.desc().nullslast())
        .limit(limit)
    )
    if category:
        query = query.where(Article.primary_category == category)
    if language:
        query = query.where(Article.language == language)
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_list:
            query = query.where(Article.tags.overlap(tag_list))
    return query


def _format_rfc822(dt: datetime | None) -> str:
    """Format datetime as RFC 822 for RSS."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def _format_rfc3339(dt: datetime | None) -> str:
    """Format datetime as RFC 3339 for Atom."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("/rss")
async def rss_feed(
    category: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    language: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate RSS 2.0 XML feed."""
    query = _build_article_query(category, tags, language, limit)
    result = await db.execute(query)
    articles = result.scalars().all()

    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")

    title_text = _SITE_TITLE
    if category:
        title_text = f"{_SITE_TITLE} - {category}"

    SubElement(channel, "title").text = title_text
    SubElement(channel, "link").text = _SITE_LINK
    SubElement(channel, "description").text = _SITE_DESCRIPTION
    SubElement(channel, "language").text = language or "en"
    SubElement(channel, "lastBuildDate").text = _format_rfc822(datetime.now(timezone.utc))

    for article in articles:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = article.title
        SubElement(item, "link").text = article.url
        SubElement(item, "guid", isPermaLink="true").text = article.url

        # Description: prefer ai_summary, fall back to summary
        description = article.ai_summary or article.summary or ""
        SubElement(item, "description").text = description

        if article.published_at:
            SubElement(item, "pubDate").text = _format_rfc822(article.published_at)

        if article.primary_category:
            SubElement(item, "category").text = article.primary_category

        # Add additional categories
        if article.categories:
            for cat in article.categories:
                if cat != article.primary_category:
                    SubElement(item, "category").text = cat

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="unicode").encode("utf-8")

    return Response(
        content=xml_bytes,
        media_type="application/rss+xml; charset=utf-8",
    )


@router.get("/atom")
async def atom_feed(
    category: str | None = Query(None),
    tags: str | None = Query(None, description="Comma-separated tags"),
    language: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Generate Atom 1.0 XML feed."""
    query = _build_article_query(category, tags, language, limit)
    result = await db.execute(query)
    articles = result.scalars().all()

    atom_ns = "http://www.w3.org/2005/Atom"
    feed = Element("feed", xmlns=atom_ns)

    title_text = _SITE_TITLE
    if category:
        title_text = f"{_SITE_TITLE} - {category}"

    SubElement(feed, "title").text = title_text
    SubElement(feed, "id").text = _SITE_LINK
    SubElement(feed, "updated").text = _format_rfc3339(datetime.now(timezone.utc))

    link_self = SubElement(feed, "link")
    link_self.set("rel", "self")
    link_self.set("href", f"{_SITE_LINK}/api/v1/export/atom")

    link_alt = SubElement(feed, "link")
    link_alt.set("rel", "alternate")
    link_alt.set("href", _SITE_LINK)

    SubElement(feed, "subtitle").text = _SITE_DESCRIPTION

    author = SubElement(feed, "author")
    SubElement(author, "name").text = _SITE_TITLE

    for article in articles:
        entry = SubElement(feed, "entry")
        SubElement(entry, "title").text = article.title
        SubElement(entry, "id").text = article.url

        link_el = SubElement(entry, "link")
        link_el.set("rel", "alternate")
        link_el.set("href", article.url)

        # Summary
        summary_text = article.ai_summary or article.summary or ""
        summary_el = SubElement(entry, "summary")
        summary_el.set("type", "text")
        summary_el.text = summary_text

        if article.published_at:
            SubElement(entry, "published").text = _format_rfc3339(article.published_at)
            SubElement(entry, "updated").text = _format_rfc3339(article.published_at)

        if article.primary_category:
            cat_el = SubElement(entry, "category")
            cat_el.set("term", article.primary_category)

        if article.categories:
            for cat in article.categories:
                if cat != article.primary_category:
                    cat_el = SubElement(entry, "category")
                    cat_el.set("term", cat)

    xml_bytes = b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(feed, encoding="unicode").encode("utf-8")

    return Response(
        content=xml_bytes,
        media_type="application/atom+xml; charset=utf-8",
    )

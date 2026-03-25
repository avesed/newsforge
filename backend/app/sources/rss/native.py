"""Native RSS/Atom parser — direct subscription without RSSHub.

This is the primary RSS source for NewsForge (user requirement #1).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.sources.base import FetchParams, HealthStatus, RawArticle

logger = logging.getLogger(__name__)


class NativeRSSSource:
    """Fetch and parse standard RSS/Atom feeds directly."""

    source_id: str = "native_rss"
    source_type: str = "rss"
    supported_categories: list[str] = []  # All categories

    async def fetch_feed(self, feed_url: str, max_articles: int = 100) -> list[RawArticle]:
        """Fetch articles from a single RSS/Atom feed URL."""
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(feed_url, headers={
                    "User-Agent": "NewsForge/1.0 (RSS Reader)",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                })
                response.raise_for_status()

            parsed = feedparser.parse(response.text)

            if parsed.bozo and not parsed.entries:
                logger.warning("Feed parse error for %s: %s", feed_url, parsed.bozo_exception)
                return []

            articles = []
            for entry in parsed.entries[:max_articles]:
                article = self._entry_to_article(entry, feed_url)
                if article:
                    articles.append(article)

            logger.info("Fetched %d articles from RSS feed: %s", len(articles), feed_url)
            return articles

        except httpx.HTTPStatusError as e:
            logger.warning("HTTP error fetching feed %s: %s", feed_url, e)
            return []
        except Exception:
            logger.exception("Failed to fetch RSS feed: %s", feed_url)
            return []

    async def fetch(self, params: FetchParams) -> list[RawArticle]:
        """Protocol method — not used directly (feeds are fetched individually)."""
        return []

    async def health_check(self) -> HealthStatus:
        return HealthStatus(is_healthy=True, message="Native RSS parser is always available")

    def _entry_to_article(self, entry: dict, feed_url: str) -> RawArticle | None:
        """Convert a feedparser entry to RawArticle."""
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()

        if not title or not link:
            return None

        # Parse published date
        published = None
        for date_field in ("published", "updated", "created"):
            date_str = entry.get(date_field)
            if date_str:
                published = self._parse_date(date_str)
                if published:
                    break

        # Extract summary
        summary = None
        if entry.get("summary"):
            summary = self._strip_html(entry["summary"])
        elif entry.get("description"):
            summary = self._strip_html(entry["description"])

        # Extract authors
        authors = None
        if entry.get("author"):
            authors = [entry["author"]]
        elif entry.get("authors"):
            authors = [a.get("name", "") for a in entry["authors"] if a.get("name")]

        # Extract top image
        top_image = None
        for link_item in entry.get("links", []):
            if link_item.get("type", "").startswith("image/"):
                top_image = link_item.get("href")
                break
        if not top_image and entry.get("media_content"):
            for media in entry["media_content"]:
                if media.get("medium") == "image" or media.get("type", "").startswith("image/"):
                    top_image = media.get("url")
                    break

        # Language
        language = entry.get("language") or entry.get("content", [{}])[0].get("language") if entry.get("content") else None

        return RawArticle(
            title=title,
            url=link,
            summary=summary[:1000] if summary else None,
            published_at=published,
            source_name=feed_url,
            authors=authors,
            language=language,
            external_id=entry.get("id"),
            top_image=top_image,
        )

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse various date formats from RSS feeds."""
        try:
            # feedparser sometimes pre-parses
            if hasattr(date_str, "tm_year"):
                import calendar
                return datetime.fromtimestamp(calendar.timegm(date_str), tz=timezone.utc)
            return parsedate_to_datetime(date_str)
        except (ValueError, TypeError):
            pass
        try:
            from datetime import datetime as dt
            return dt.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _strip_html(html: str) -> str:
        """Simple HTML tag stripping."""
        import re
        text = re.sub(r"<[^>]+>", "", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

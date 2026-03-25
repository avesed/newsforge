"""Google News RSS source — topic/keyword/locale-based news discovery.

Architecture:
  1. encode_topic_id() generates Google News topic URLs from Knowledge Graph MIDs
  2. RSS fetch returns articles with news.google.com redirect URLs
  3. resolve_google_news_url() uses Playwright to follow JS redirect → real URL
  4. Real URLs are stored on the article for Crawl4AI full-text fetching later

Google News RSS endpoint formats:
  Top stories: /rss?hl={lang}&gl={country}&ceid={country}:{lang}
  By topic:    /rss/topics/{topic_id}?hl={lang}&gl={country}&ceid={country}:{lang}
  By search:   /rss/search?q={keyword}&hl={lang}&gl={country}&ceid={country}:{lang}

Topic IDs are protobuf-encoded: outer(field1=0, field5(field1=10, field4=base64(inner), field10=1))
Inner protobuf: field1=16, field2(field1=MID, field2=lang, field3=country), field5=0
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import feedparser
import httpx

from app.sources.base import FetchParams, HealthStatus, RawArticle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Google Knowledge Graph MIDs → topic categories
# ---------------------------------------------------------------------------

TOPIC_MIDS: dict[str, str] = {
    "world": "/m/09nm_",
    "business": "/m/09s1f",
    "technology": "/m/07c1v",
    "entertainment": "/m/02jjt",
    "sports": "/m/06ntj",
    "science": "/m/06mq7",
    "health": "/m/0kt51",
}

# Map Google News topics to NewsForge categories
TOPIC_TO_CATEGORY: dict[str, str] = {
    "world": "world",
    "business": "finance",
    "technology": "tech",
    "entertainment": "entertainment",
    "sports": "sports",
    "science": "science",
    "health": "health",
}

# Supported locales: (hl, gl, ceid)
LOCALES: dict[str, tuple[str, str, str]] = {
    "en-US": ("en", "US", "US:en"),
    "zh-CN": ("zh-CN", "CN", "CN:zh-Hans"),
    "zh-TW": ("zh-TW", "TW", "TW:zh-Hant"),
    "zh-HK": ("zh-HK", "HK", "HK:zh-Hant"),
    "ja-JP": ("ja", "JP", "JP:ja"),
    "ko-KR": ("ko", "KR", "KR:ko"),
    "en-GB": ("en-GB", "GB", "GB:en"),
    "en-AU": ("en-AU", "AU", "AU:en"),
    "en-IN": ("en-IN", "IN", "IN:en"),
}

BASE_URL = "https://news.google.com"


# ---------------------------------------------------------------------------
# Topic ID encoding (protobuf → base64url)
# ---------------------------------------------------------------------------

def encode_topic_id(mid: str, lang: str, country: str) -> str:
    """Encode a Google Knowledge Graph MID + locale into a Google News topic ID.

    The encoding is a two-layer protobuf structure:
      Inner: {field1=16, field2={field1=MID, field2=lang, field3=country}, field5=0}
      Outer: {field1=0, field5={field1=10, field4=base64(inner), field10=1}}
    """
    # --- Inner protobuf ---
    nested = b""
    nested += b"\x0a" + bytes([len(mid)]) + mid.encode()           # field 1: MID
    nested += b"\x12" + bytes([len(lang)]) + lang.encode()          # field 2: lang
    nested += b"\x1a" + bytes([len(country)]) + country.encode()    # field 3: country

    inner = b""
    inner += b"\x08\x10"                                            # field 1: varint 16
    inner += b"\x12" + bytes([len(nested)]) + nested                # field 2: nested message
    inner += b"\x28\x00"                                            # field 5: varint 0

    inner_b64 = base64.urlsafe_b64encode(inner).rstrip(b"=")

    # --- Outer protobuf ---
    field5_content = b""
    field5_content += b"\x08\x0a"                                              # sub-field 1: varint 10
    field5_content += b"\x22" + bytes([len(inner_b64)]) + inner_b64            # sub-field 4: base64
    field5_content += b"\x50\x01"                                              # sub-field 10: varint 1

    outer = b""
    outer += b"\x08\x00"                                                       # field 1: varint 0
    outer += b"\x2a" + bytes([len(field5_content)]) + field5_content           # field 5: nested

    return base64.urlsafe_b64encode(outer).rstrip(b"=").decode()


def build_topic_url(topic: str, locale: str = "en-US") -> str:
    """Build a Google News RSS URL for a topic + locale."""
    mid = TOPIC_MIDS.get(topic)
    if not mid:
        raise ValueError(f"Unknown topic: {topic}. Available: {list(TOPIC_MIDS.keys())}")

    hl, gl, ceid = LOCALES.get(locale, LOCALES["en-US"])

    # For topic IDs, the lang in protobuf uses the ceid lang part
    proto_lang = ceid.split(":")[-1]  # e.g., "zh-Hans" from "CN:zh-Hans"
    topic_id = encode_topic_id(mid, proto_lang, gl)

    return f"{BASE_URL}/rss/topics/{topic_id}?hl={hl}&gl={gl}&ceid={ceid}"


def build_search_url(keyword: str, locale: str = "en-US") -> str:
    """Build a Google News RSS URL for a keyword search."""
    hl, gl, ceid = LOCALES.get(locale, LOCALES["en-US"])
    from urllib.parse import quote
    return f"{BASE_URL}/rss/search?q={quote(keyword)}&hl={hl}&gl={gl}&ceid={ceid}"


def build_top_stories_url(locale: str = "en-US") -> str:
    """Build a Google News RSS URL for top stories."""
    hl, gl, ceid = LOCALES.get(locale, LOCALES["en-US"])
    return f"{BASE_URL}/rss?hl={hl}&gl={gl}&ceid={ceid}"


# ---------------------------------------------------------------------------
# Google News URL resolution (encrypted redirect → real URL)
# ---------------------------------------------------------------------------

async def resolve_google_news_url(google_url: str, timeout_ms: int = 15000) -> str | None:
    """Resolve a Google News article URL to the real source URL.

    Google News encodes article URLs with server-side encryption (since 2024).
    The only way to get the real URL is to follow the JS redirect chain:
      1. Google returns a SPA shell (200)
      2. SPA calls batchexecute RPC to server (server decrypts article ID)
      3. Server returns real URL
      4. JS does window.location redirect

    We use Playwright to follow this chain.
    """
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(google_url, wait_until="domcontentloaded", timeout=timeout_ms)

                # Poll until URL changes away from news.google.com (max ~10s)
                for _ in range(20):
                    await page.wait_for_timeout(500)
                    current = page.url
                    if "news.google.com" not in current:
                        return current

                logger.warning("Google News URL did not redirect within timeout: %s", google_url[:80])
                return None
            finally:
                await browser.close()

    except ImportError:
        logger.error("Playwright not installed — cannot resolve Google News URLs")
        return None
    except Exception:
        logger.exception("Failed to resolve Google News URL: %s", google_url[:80])
        return None


async def resolve_urls_batch(
    google_urls: list[str],
    concurrency: int = 5,
    timeout_ms: int = 15000,
) -> dict[str, str | None]:
    """Resolve multiple Google News URLs concurrently, sharing one browser.

    Returns a dict of {google_url: real_url | None}.
    """
    results: dict[str, str | None] = {}

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("Playwright not installed")
        return {url: None for url in google_urls}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(concurrency)

        async def _resolve_one(url: str) -> None:
            async with semaphore:
                try:
                    page = await browser.new_page()
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        for _ in range(20):
                            await page.wait_for_timeout(500)
                            current = page.url
                            if "news.google.com" not in current:
                                results[url] = current
                                return
                        results[url] = None
                    finally:
                        await page.close()
                except Exception:
                    logger.exception("Failed to resolve: %s", url[:80])
                    results[url] = None

        await asyncio.gather(*[_resolve_one(url) for url in google_urls])
        await browser.close()

    resolved_count = sum(1 for v in results.values() if v is not None)
    logger.info("Resolved %d/%d Google News URLs", resolved_count, len(google_urls))
    return results


# ---------------------------------------------------------------------------
# Google News Source (implements NewsSource protocol)
# ---------------------------------------------------------------------------

@dataclass
class GoogleNewsConfig:
    """Configuration for a Google News source instance."""

    topics: list[str] = field(default_factory=lambda: ["world", "business", "technology"])
    keywords: list[str] = field(default_factory=list)
    locale: str = "en-US"
    include_top_stories: bool = True
    resolve_urls: bool = True  # Whether to resolve redirects (needs Playwright)
    resolve_concurrency: int = 5
    max_articles_per_feed: int = 50


class GoogleNewsSource:
    """Google News RSS-based news source.

    Fetches articles via Google News RSS feeds (topics, keywords, top stories),
    then optionally resolves encrypted redirect URLs to real source URLs.

    Usage:
        source = GoogleNewsSource(config=GoogleNewsConfig(
            topics=["technology", "business"],
            keywords=["人工智能"],
            locale="zh-CN",
        ))
        articles = await source.fetch(FetchParams())
    """

    source_id: str = "google_news"
    source_type: str = "rss"
    supported_categories: list[str] = list(TOPIC_TO_CATEGORY.values())

    def __init__(self, config: GoogleNewsConfig | None = None):
        self.config = config or GoogleNewsConfig()

    async def fetch(self, params: FetchParams) -> list[RawArticle]:
        """Fetch articles from all configured Google News feeds."""
        # Build list of feed URLs
        feed_urls: list[tuple[str, str | None]] = []  # (url, category_hint)

        if self.config.include_top_stories:
            feed_urls.append((build_top_stories_url(self.config.locale), None))

        for topic in self.config.topics:
            try:
                url = build_topic_url(topic, self.config.locale)
                category = TOPIC_TO_CATEGORY.get(topic)
                feed_urls.append((url, category))
            except ValueError:
                logger.warning("Skipping unknown topic: %s", topic)

        for keyword in self.config.keywords:
            url = build_search_url(keyword, self.config.locale)
            feed_urls.append((url, None))

        if params.keywords:
            for keyword in params.keywords:
                url = build_search_url(keyword, self.config.locale)
                feed_urls.append((url, None))

        # Fetch all feeds concurrently
        all_articles: list[RawArticle] = []
        max_per = params.max_articles or self.config.max_articles_per_feed

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            tasks = [self._fetch_feed(client, url, cat, max_per) for url, cat in feed_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
            elif isinstance(result, Exception):
                logger.warning("Feed fetch error: %s", result)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_articles: list[RawArticle] = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique_articles.append(article)

        logger.info(
            "Google News: %d unique articles from %d feeds (%s)",
            len(unique_articles), len(feed_urls), self.config.locale,
        )

        # Resolve Google News redirect URLs → real source URLs
        if self.config.resolve_urls and unique_articles:
            google_urls = [a.url for a in unique_articles]
            resolved = await resolve_urls_batch(
                google_urls,
                concurrency=self.config.resolve_concurrency,
            )
            for article in unique_articles:
                real_url = resolved.get(article.url)
                if real_url:
                    # Store original Google URL in extra, replace with real URL
                    article.extra = article.extra or {}
                    article.extra["google_news_url"] = article.url
                    article.url = real_url
                else:
                    # Mark as unresolved — pipeline can skip content fetch
                    article.extra = article.extra or {}
                    article.extra["url_unresolved"] = True

        return unique_articles

    async def health_check(self) -> HealthStatus:
        """Check if Google News RSS is accessible."""
        try:
            url = build_top_stories_url(self.config.locale)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers={"User-Agent": "NewsForge/1.0"})
                if resp.status_code == 200 and "<item>" in resp.text:
                    return HealthStatus(is_healthy=True, message="Google News RSS accessible")
            return HealthStatus(is_healthy=False, message=f"HTTP {resp.status_code}")
        except Exception as e:
            return HealthStatus(is_healthy=False, message=str(e))

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        feed_url: str,
        category_hint: str | None,
        max_articles: int,
    ) -> list[RawArticle]:
        """Fetch and parse a single Google News RSS feed."""
        try:
            response = await client.get(feed_url, headers={
                "User-Agent": "NewsForge/1.0 (RSS Reader)",
                "Accept": "application/rss+xml, application/xml, text/xml",
            })
            response.raise_for_status()
        except Exception:
            logger.exception("Failed to fetch Google News feed: %s", feed_url[:80])
            return []

        parsed = feedparser.parse(response.text)
        if parsed.bozo and not parsed.entries:
            logger.warning("Feed parse error: %s", parsed.bozo_exception)
            return []

        articles: list[RawArticle] = []
        for entry in parsed.entries[:max_articles]:
            article = self._entry_to_article(entry, category_hint)
            if article:
                articles.append(article)

        return articles

    @staticmethod
    def _entry_to_article(entry: dict, category_hint: str | None) -> RawArticle | None:
        """Convert a feedparser entry from Google News RSS to RawArticle."""
        title_raw = entry.get("title", "").strip()
        link = entry.get("link", "").strip()

        if not title_raw or not link:
            return None

        # Google News title format: "Article Title - Source Name"
        # Split to extract source name
        source_name = ""
        title = title_raw
        if " - " in title_raw:
            parts = title_raw.rsplit(" - ", 1)
            title = parts[0].strip()
            source_name = parts[1].strip()

        # Also available in <source> tag
        if not source_name:
            source_name = entry.get("source", {}).get("title", "")

        # Parse published date
        published = None
        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                published = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                pass

        # Summary: Google News wraps it in HTML with a link
        summary = None
        if entry.get("summary"):
            # Strip HTML tags from summary
            summary = re.sub(r"<[^>]+>", "", entry["summary"]).strip()

        return RawArticle(
            title=title,
            url=link,  # Still the Google News redirect URL at this point
            summary=summary[:500] if summary else None,
            published_at=published,
            source_name=source_name,
            language=None,  # Pipeline will detect
            category_hint=category_hint,
            external_id=entry.get("id"),
            extra={"google_source": source_name},
        )

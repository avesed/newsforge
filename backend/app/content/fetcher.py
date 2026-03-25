"""Content fetcher — unified entry point for article full-text extraction.

Fallback chain: RSS full text (pass-through) -> Crawl4AI (primary) -> Tavily (optional).
Crawl4AI handles JS rendering + anti-bot natively (magic mode), replacing trafilatura + Playwright.
Google News URLs are decoded via Google's batchexecute RPC before content fetch.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MIN_CONTENT_LENGTH = 200
MAX_CONTENT_LENGTH = 50_000
FETCH_TIMEOUT = 30

# Singleton Crawl4AI crawler instance
_crawler = None
_crawler_lock = asyncio.Lock()


@dataclass
class FetchResult:
    full_text: str
    language: str | None = None
    authors: list[str] | None = None
    title: str | None = None
    provider: str = "crawl4ai"
    word_count: int = 0


async def _get_crawler():
    """Get or create the singleton Crawl4AI crawler instance.

    Reuses the same browser across all requests to avoid startup overhead.
    """
    global _crawler
    if _crawler is not None:
        return _crawler

    async with _crawler_lock:
        # Double-check after acquiring lock
        if _crawler is not None:
            return _crawler

        from crawl4ai import AsyncWebCrawler, BrowserConfig, UndetectedAdapter
        from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy

        browser_cfg = BrowserConfig(
            headless=True,
            enable_stealth=True,
            user_agent_mode="random",
        )
        adapter = UndetectedAdapter()
        strategy = AsyncPlaywrightCrawlerStrategy(
            browser_config=browser_cfg,
            browser_adapter=adapter,
        )
        crawler = AsyncWebCrawler(crawler_strategy=strategy)
        await crawler.__aenter__()
        _crawler = crawler
        logger.info("Crawl4AI crawler initialized (singleton)")
        return _crawler


async def shutdown_crawler() -> None:
    """Shutdown the singleton crawler. Call on application shutdown."""
    global _crawler
    if _crawler is not None:
        try:
            await _crawler.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error during crawler shutdown", exc_info=True)
        _crawler = None
        logger.info("Crawl4AI crawler shut down")


async def fetch_content(
    url: str,
    rss_full_text: str | None = None,
    rss_language: str | None = None,
    rss_authors: list[str] | None = None,
    rss_title: str | None = None,
) -> FetchResult | None:
    """Fetch and extract article content from URL.

    Layer 0: Resolve Google News redirect URLs to real article URLs.
    Layer 1: If RSS provided full text (>= MIN_CONTENT_LENGTH), use it directly.
    Layer 2: Crawl4AI with magic mode — handles JS + anti-bot, extracts clean markdown.
    Layer 3: Tavily API (optional fallback if configured).

    Returns None if all providers fail or content is too short.
    """
    # Layer 0: Resolve Google News encrypted redirect URLs
    if "news.google.com/rss/articles/" in url:
        real_url = await _resolve_google_news_url(url)
        if real_url:
            logger.info("Resolved Google News URL → %s", real_url[:100])
            url = real_url
        else:
            logger.warning("Failed to resolve Google News URL: %s", url[:80])
            return None

    # Layer 1: RSS pass-through
    if rss_full_text and len(rss_full_text) >= MIN_CONTENT_LENGTH:
        text = rss_full_text[:MAX_CONTENT_LENGTH]
        logger.debug("Using RSS full text for %s (%d chars)", url[:60], len(text))
        return FetchResult(
            full_text=text,
            language=rss_language,
            authors=rss_authors,
            title=rss_title,
            provider="rss",
            word_count=len(text.split()),
        )

    # Layer 2: Crawl4AI (primary)
    result = await _fetch_crawl4ai(url)
    if result:
        return result

    # Layer 3: Plain HTTP fallback (some sites block headless browsers but allow normal requests)
    result = await _fetch_httpx(url)
    if result:
        return result

    # Layer 4: Tavily API (optional fallback)
    settings = get_settings()
    if settings.tavily_api_key:
        result = await _fetch_tavily(url, settings.tavily_api_key)
        if result:
            return result

    logger.warning("All content providers failed for URL: %s", url[:100])
    return None


async def _resolve_google_news_url(google_url: str) -> str | None:
    """Resolve a Google News encrypted URL to the real article URL.

    Two-step HTTP decode via Google's batchexecute RPC:
    1. GET the article page to extract signature (data-n-a-sg) and timestamp (data-n-a-ts).
    2. POST to DotsSplashUi/data/batchexecute with Fbv4je RPC to get the real URL.

    No browser needed — pure HTTP requests.
    """
    parsed = urlparse(google_url)
    path_parts = parsed.path.split("/")
    if len(path_parts) < 2 or path_parts[-2] not in ("articles", "read"):
        return None
    base64_str = path_parts[-1]

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Step 1: fetch article page to get decoding params
            signature, timestamp = await _get_gnews_decode_params(client, base64_str)
            if not signature or not timestamp:
                return None

            # Step 2: call batchexecute RPC to decode
            return await _gnews_batch_decode(client, base64_str, signature, timestamp)
    except Exception:
        logger.warning("Google News URL decode failed: %s", google_url[:80], exc_info=True)
        return None


async def _get_gnews_decode_params(
    client: httpx.AsyncClient, base64_str: str
) -> tuple[str | None, str | None]:
    """Fetch signature and timestamp from the Google News article page."""
    from selectolax.parser import HTMLParser

    for prefix in ("articles", "rss/articles"):
        url = f"https://news.google.com/{prefix}/{base64_str}"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            continue

        tree = HTMLParser(resp.text)
        el = tree.css_first("c-wiz > div[jscontroller]")
        if el is None:
            continue
        sig = el.attributes.get("data-n-a-sg")
        ts = el.attributes.get("data-n-a-ts")
        if sig and ts:
            return sig, ts

    logger.warning("Could not extract decode params for %s", base64_str[:40])
    return None, None


async def _gnews_batch_decode(
    client: httpx.AsyncClient,
    base64_str: str,
    signature: str,
    timestamp: str,
) -> str | None:
    """Call Google's Fbv4je batchexecute RPC to decode a Google News URL."""
    payload = [
        "Fbv4je",
        f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{base64_str}",{timestamp},"{signature}"]',
    ]
    body = f"f.req={quote(json.dumps([[payload]]))}"
    resp = await client.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
        },
        content=body,
    )
    resp.raise_for_status()

    parsed = json.loads(resp.text.split("\n\n")[1])[:-2]
    decoded_url = json.loads(parsed[0][2])[1]
    if decoded_url and "news.google.com" not in decoded_url:
        return decoded_url
    return None


async def _fetch_crawl4ai(url: str) -> FetchResult | None:
    """Fetch content using Crawl4AI with magic mode (primary provider).

    Magic mode enables anti-bot bypass (DataDome, Cloudflare, etc.),
    user simulation, and navigator override for stealth crawling.
    """
    try:
        from crawl4ai import CrawlerRunConfig, CacheMode

        crawler = await _get_crawler()

        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            magic=True,
            page_timeout=FETCH_TIMEOUT * 1000,  # ms
        )

        result = await asyncio.wait_for(
            crawler.arun(url=url, config=config),
            timeout=FETCH_TIMEOUT + 10,
        )

        if not result.success:
            logger.warning(
                "Crawl4AI failed for %s: status=%s error=%s",
                url[:60], result.status_code, result.error_message,
            )
            return None

        # Prefer markdown output (clean, structured)
        text = result.markdown or ""

        if len(text) < MIN_CONTENT_LENGTH:
            # Fallback to cleaned_html if markdown is too short
            text = result.cleaned_html or ""

        if len(text) < MIN_CONTENT_LENGTH:
            logger.warning(
                "Crawl4AI content too short for %s (%d chars, status=%s)",
                url[:60], len(text), result.status_code,
            )
            return None

        text = text[:MAX_CONTENT_LENGTH]

        # Extract metadata from result
        title = None
        language = None
        if hasattr(result, "metadata") and result.metadata:
            title = result.metadata.get("title")
            language = result.metadata.get("language")
            if language:
                language = language[:2].lower()

        word_count = len(text.split())
        logger.info(
            "Crawl4AI fetched %s: %d words, status=%s",
            url[:60], word_count, result.status_code,
        )

        return FetchResult(
            full_text=text,
            language=language,
            authors=None,
            title=title,
            provider="crawl4ai",
            word_count=word_count,
        )
    except asyncio.TimeoutError:
        logger.warning("Crawl4AI timed out for %s", url[:60])
        return None
    except Exception:
        logger.warning("Crawl4AI failed for %s", url[:60], exc_info=True)
        return None


_ARTICLE_SELECTORS = (
    "article", "[role='article']", ".post-content", ".entry-content",
    ".article-body", ".article-content", ".story-body", "main",
)


async def _fetch_httpx(url: str) -> FetchResult | None:
    """Plain HTTP GET + selectolax extraction.

    Fallback for sites that block headless browsers but serve full HTML
    to normal HTTP clients (e.g. nytimes.com/athletic).
    """
    try:
        from selectolax.parser import HTMLParser

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        if "text/html" not in resp.headers.get("content-type", ""):
            return None

        tree = HTMLParser(resp.text)
        for tag in tree.css("script, style, nav, footer, header, aside, iframe, noscript"):
            tag.decompose()

        text = ""
        for sel in _ARTICLE_SELECTORS:
            el = tree.css_first(sel)
            if el:
                text = el.text(separator="\n", strip=True)
                if len(text) >= MIN_CONTENT_LENGTH:
                    break

        if len(text) < MIN_CONTENT_LENGTH:
            return None

        text = text[:MAX_CONTENT_LENGTH]
        title = None
        language = None
        title_el = tree.css_first("title")
        if title_el:
            title = title_el.text(strip=True)
        html_el = tree.css_first("html")
        if html_el:
            language = (html_el.attributes.get("lang") or "")[:2].lower() or None

        word_count = len(text.split())
        logger.info("httpx fetched %s: %d words", url[:60], word_count)
        return FetchResult(
            full_text=text, language=language, title=title,
            provider="httpx", word_count=word_count,
        )
    except Exception:
        logger.debug("httpx failed for %s", url[:60], exc_info=True)
        return None


async def _fetch_tavily(url: str, api_key: str) -> FetchResult | None:
    """Fetch content using Tavily Extract API (fallback)."""
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            response = await client.post(
                "https://api.tavily.com/extract",
                json={"urls": [url]},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            return None

        text = results[0].get("raw_content", "") or results[0].get("text", "")
        if len(text) < MIN_CONTENT_LENGTH:
            return None

        text = text[:MAX_CONTENT_LENGTH]
        return FetchResult(
            full_text=text,
            provider="tavily",
            word_count=len(text.split()),
        )
    except Exception:
        logger.debug("Tavily failed for %s", url[:60], exc_info=True)
        return None

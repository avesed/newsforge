"""Finnhub news source adapter — company news and general market news.

Uses the Finnhub REST API directly via httpx (no finnhub Python client dependency).
Implements the NewsSource protocol for integration into the NewsForge pipeline.

Endpoints:
  Company news: https://finnhub.io/api/v1/company-news?symbol={}&from={}&to={}&token={}
  General news: https://finnhub.io/api/v1/news?category=general&token={}
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.sources.base import FetchParams, HealthStatus, RawArticle

logger = logging.getLogger(__name__)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

# Finnhub API base URL
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"

# Per-request article limits
MAX_COMPANY_NEWS = 50
MAX_GENERAL_NEWS = 30

# Default symbols to fetch when no specific symbols are requested
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]


def _sanitize_text(text: str | None) -> str | None:
    """Strip HTML tags and normalize whitespace."""
    if not text:
        return None
    text = _HTML_TAG_PATTERN.sub("", text)
    text = html.unescape(text)
    text = " ".join(text.split())
    return text.strip() or None


@dataclass
class FinnhubConfig:
    """Configuration for the Finnhub news source."""

    api_key: str | None = None
    default_symbols: list[str] = field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    include_general_news: bool = True
    company_news_lookback_days: int = 7
    request_timeout: float = 30.0


class FinnhubNewsSource:
    """Finnhub news source — US stock company news and general market news.

    Implements the NewsSource protocol. Fetches news from Finnhub REST API
    and maps responses to RawArticle format for the pipeline.

    Usage:
        source = FinnhubNewsSource(config=FinnhubConfig(api_key="your_key"))
        articles = await source.fetch(FetchParams(symbols=["AAPL", "NVDA"]))
    """

    source_id: str = "finnhub"
    source_type: str = "api"
    supported_categories: list[str] = ["finance"]

    def __init__(self, config: FinnhubConfig | None = None):
        self.config = config or FinnhubConfig()

    def _get_api_key(self) -> str | None:
        """Get Finnhub API key from config or environment."""
        if self.config.api_key:
            return self.config.api_key
        # Fallback to app settings
        from app.core.config import get_settings
        return get_settings().finnhub_api_key

    async def fetch(self, params: FetchParams) -> list[RawArticle]:
        """Fetch articles from Finnhub — company news for symbols + general news."""
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("FINNHUB_API_KEY not configured, skipping Finnhub source")
            return []

        all_articles: list[RawArticle] = []

        # Determine symbols to fetch
        symbols = params.symbols or self.config.default_symbols

        async with httpx.AsyncClient(timeout=self.config.request_timeout) as client:
            # Fetch company news for each symbol
            for symbol in symbols:
                articles = await self._fetch_company_news(client, api_key, symbol, params.since)
                all_articles.extend(articles)

            # Fetch general market news
            if self.config.include_general_news:
                general = await self._fetch_general_news(client, api_key)
                all_articles.extend(general)

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique: list[RawArticle] = []
        for article in all_articles:
            if article.url not in seen_urls:
                seen_urls.add(article.url)
                unique.append(article)

        logger.info(
            "Finnhub: %d unique articles (%d symbols, general=%s)",
            len(unique), len(symbols), self.config.include_general_news,
        )
        return unique

    async def health_check(self) -> HealthStatus:
        """Check if Finnhub API is accessible."""
        api_key = self._get_api_key()
        if not api_key:
            return HealthStatus(is_healthy=False, message="FINNHUB_API_KEY not configured")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{FINNHUB_BASE_URL}/news",
                    params={"category": "general", "token": api_key},
                )
                if resp.status_code == 200:
                    return HealthStatus(is_healthy=True, message="Finnhub API accessible")
                return HealthStatus(
                    is_healthy=False,
                    message=f"Finnhub API returned HTTP {resp.status_code}",
                )
        except Exception as e:
            return HealthStatus(is_healthy=False, message=str(e))

    async def _fetch_company_news(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        symbol: str,
        since: datetime | None = None,
    ) -> list[RawArticle]:
        """Fetch company news for a single symbol from Finnhub."""
        from_date = (since or datetime.now(timezone.utc) - timedelta(
            days=self.config.company_news_lookback_days
        )).strftime("%Y-%m-%d")
        to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            resp = await client.get(
                f"{FINNHUB_BASE_URL}/company-news",
                params={
                    "symbol": symbol,
                    "from": from_date,
                    "to": to_date,
                    "token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                logger.warning("Finnhub rate limit exceeded for symbol %s", symbol)
            elif status in (401, 403):
                logger.error("Finnhub auth error for symbol %s: HTTP %d", symbol, status)
            else:
                logger.error("Finnhub company news HTTP %d for %s", status, symbol)
            return []
        except Exception:
            logger.exception("Finnhub company news error for %s", symbol)
            return []

        articles: list[RawArticle] = []
        for item in data[:MAX_COMPANY_NEWS]:
            article = self._parse_item(item, symbol=symbol)
            if article:
                articles.append(article)

        logger.debug("Finnhub: %d company news for %s", len(articles), symbol)
        return articles

    async def _fetch_general_news(
        self,
        client: httpx.AsyncClient,
        api_key: str,
    ) -> list[RawArticle]:
        """Fetch general market news from Finnhub."""
        try:
            resp = await client.get(
                f"{FINNHUB_BASE_URL}/news",
                params={"category": "general", "token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 429:
                logger.warning("Finnhub rate limit exceeded for general news")
            elif status in (401, 403):
                logger.error("Finnhub auth error for general news: HTTP %d", status)
            else:
                logger.error("Finnhub general news HTTP %d", status)
            return []
        except Exception:
            logger.exception("Finnhub general news error")
            return []

        articles: list[RawArticle] = []
        for item in data[:MAX_GENERAL_NEWS]:
            article = self._parse_item(item, symbol=None)
            if article:
                articles.append(article)

        logger.debug("Finnhub: %d general news articles", len(articles))
        return articles

    @staticmethod
    def _parse_item(item: dict, symbol: str | None = None) -> RawArticle | None:
        """Parse a single Finnhub news item into a RawArticle."""
        url = item.get("url", "").strip()
        headline = _sanitize_text(item.get("headline", ""))
        if not url or not headline:
            return None

        # Parse timestamp (Finnhub uses Unix epoch seconds)
        published = None
        ts = item.get("datetime")
        if ts:
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (ValueError, OSError):
                pass

        summary = _sanitize_text(item.get("summary"))
        source_name = item.get("source", "finnhub")
        image_url = item.get("image") or None

        # Build extra metadata for the pipeline
        extra: dict = {
            "provider": "finnhub",
            "finnhub_id": item.get("id"),
            "finnhub_category": item.get("category"),
            "market": "us",
        }
        if symbol:
            extra["symbols"] = [symbol]

        return RawArticle(
            title=headline,
            url=url,
            summary=summary[:500] if summary else None,
            published_at=published,
            source_name=source_name,
            language="en",
            category_hint="finance",
            external_id=str(item.get("id", "")),
            top_image=image_url,
            extra=extra,
        )

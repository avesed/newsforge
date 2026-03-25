"""NewsSource protocol — unified interface for all news source adapters.

New sources only need to implement this protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class RawArticle:
    """Article as returned from a news source — pipeline entry point."""

    title: str
    url: str
    summary: str | None = None
    published_at: datetime | None = None
    source_name: str = ""
    authors: list[str] | None = None
    language: str | None = None  # Source-provided (may be inaccurate, pipeline re-detects)
    category_hint: str | None = None  # Source-provided classification hint
    external_id: str | None = None
    top_image: str | None = None
    extra: dict | None = None  # Source-specific metadata


@dataclass
class FetchParams:
    """Parameters for fetching articles from a source."""

    symbols: list[str] | None = None  # For finance sources
    keywords: list[str] | None = None
    categories: list[str] | None = None
    max_articles: int = 100
    since: datetime | None = None


@dataclass
class HealthStatus:
    is_healthy: bool
    message: str = ""
    last_check: datetime | None = None


@runtime_checkable
class NewsSource(Protocol):
    """Protocol that all news sources must implement."""

    source_id: str
    source_type: str  # 'rss', 'api', 'scraper'
    supported_categories: list[str]

    async def fetch(self, params: FetchParams) -> list[RawArticle]:
        """Fetch articles from this source."""
        ...

    async def health_check(self) -> HealthStatus:
        """Check if this source is operational."""
        ...

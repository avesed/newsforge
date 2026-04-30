"""Source registry — manages available news source adapters."""

from __future__ import annotations

import logging
from typing import Any

from app.sources.base import HealthStatus, NewsSource

logger = logging.getLogger(__name__)


class SourceRegistry:
    """Singleton registry for news source adapters."""

    def __init__(self):
        self._sources: dict[str, NewsSource] = {}

    def register(self, source: NewsSource) -> None:
        """Register a news source adapter."""
        self._sources[source.source_id] = source
        logger.info("Registered news source: %s (type=%s)", source.source_id, source.source_type)

    def get(self, source_id: str) -> NewsSource | None:
        """Get a source by ID."""
        return self._sources.get(source_id)

    def list_sources(self) -> list[NewsSource]:
        """List all registered sources."""
        return list(self._sources.values())

    async def health_check_all(self) -> dict[str, HealthStatus]:
        """Run health check on all sources."""
        results = {}
        for source_id, source in self._sources.items():
            try:
                results[source_id] = await source.health_check()
            except Exception as e:
                results[source_id] = HealthStatus(is_healthy=False, message=str(e))
        return results


_registry: SourceRegistry | None = None


def get_source_registry() -> SourceRegistry:
    """Get or create the source registry singleton with built-in sources."""
    global _registry
    if _registry is None:
        _registry = SourceRegistry()
        _register_builtin_sources(_registry)
    return _registry


def _register_builtin_sources(registry: SourceRegistry) -> None:
    """Register all built-in news source adapters."""
    from app.sources.rss.native import NativeRSSSource
    from app.sources.rss.google_news import GoogleNewsSource, GoogleNewsConfig
    from app.sources.api.finnhub import FinnhubNewsSource
    from app.sources.api.stockpulse import StockPulseSource

    registry.register(NativeRSSSource())

    # Finnhub — US stock company news + general market news
    registry.register(FinnhubNewsSource())

    # StockPulse — fan-out aggregator (yfinance + akshare + finnhub + tiingo + ...)
    # driven by watched_symbols table, not the generic poll_api_sources path.
    registry.register(StockPulseSource.from_settings())

    # Default Google News instances: EN-US + ZH-CN
    registry.register(GoogleNewsSource(config=GoogleNewsConfig(
        topics=["world", "business", "technology", "entertainment", "sports", "science"],
        locale="en-US",
    )))
    # Chinese locale as a separate source instance
    cn_source = GoogleNewsSource(config=GoogleNewsConfig(
        topics=["world", "business", "technology", "entertainment", "sports", "science"],
        locale="zh-CN",
    ))
    cn_source.source_id = "google_news_cn"
    registry.register(cn_source)

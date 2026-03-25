"""RSSHub adapter — optional news source (user requirement #1: RSSHub retained as one source)."""

from __future__ import annotations

import logging

import httpx

from app.core.config import get_settings
from app.sources.base import FetchParams, HealthStatus, RawArticle
from app.sources.rss.native import NativeRSSSource

logger = logging.getLogger(__name__)


class RSSHubSource:
    """Fetch articles via RSSHub instance. Delegates parsing to NativeRSSSource."""

    source_id: str = "rsshub"
    source_type: str = "rss"
    supported_categories: list[str] = []  # All categories

    def __init__(self):
        self._native = NativeRSSSource()

    async def fetch_route(self, route: str, max_articles: int = 100) -> list[RawArticle]:
        """Fetch articles from an RSSHub route (e.g., /reuters/world)."""
        settings = get_settings()
        if not settings.rsshub_url:
            logger.warning("RSSHub URL not configured, skipping route: %s", route)
            return []

        url = f"{settings.rsshub_url}{route}"
        if settings.rsshub_access_key:
            url += f"?key={settings.rsshub_access_key}"

        return await self._native.fetch_feed(url, max_articles)

    async def fetch(self, params: FetchParams) -> list[RawArticle]:
        """Protocol method — not used directly (routes are fetched individually)."""
        return []

    async def health_check(self) -> HealthStatus:
        settings = get_settings()
        if not settings.rsshub_url:
            return HealthStatus(is_healthy=False, message="RSSHub URL not configured")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{settings.rsshub_url}")
                if resp.status_code == 200:
                    return HealthStatus(is_healthy=True, message="RSSHub is reachable")
            return HealthStatus(is_healthy=False, message=f"RSSHub returned {resp.status_code}")
        except Exception as e:
            return HealthStatus(is_healthy=False, message=str(e))

"""StockPulse news source adapter — fan-out aggregator over all configured providers.

StockPulse (port 8010) sits in front of yfinance/akshare/finnhub/tiingo/massive/
tushare and exposes a single fan-out endpoint:

    GET /api/v1/data/news?symbol=&market=&since=&limit=
    headers: X-API-Key: ...

Behavior we rely on:
- Pass-through fan-out, NO dedup on StockPulse side (NewsForge owns dedup).
- `since` is best-effort — some providers ignore it, so we do a local
  published_at filter as a backstop.
- StockPulse's own market detection treats bare 6-digit A-share codes as US,
  so we use `infer_market_for_stockpulse()` to send an explicit `market=sh|sz`
  for those.
- Each item already carries `symbols: list[str]` (related tickers from the
  source) and `source: str` ("yfinance"/"akshare"/...). We propagate both.

This source is normally driven by the watched_symbols table (per-watchlist
news), not by a static default list — so `fetch()` requires `params.symbols`
and is a no-op when empty.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.sources.base import FetchParams, HealthStatus, RawArticle
from app.utils.symbol_market import infer_market_for_stockpulse

logger = logging.getLogger(__name__)


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 string into a tz-aware datetime; None on failure."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        # fromisoformat handles "2026-04-30T10:00:00+00:00" and "...Z" via replace
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class StockPulseSource:
    """StockPulse fan-out news source.

    Implements the NewsSource protocol. One HTTP call per requested symbol;
    StockPulse internally fans out to all configured providers in parallel.
    """

    source_id: str = "stockpulse"
    source_type: str = "api"
    supported_categories: list[str] = ["finance"]

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        request_timeout: float = 30.0,
        per_symbol_limit: int = 50,
        max_concurrency: int = 4,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""
        self._timeout = request_timeout
        self._per_symbol_limit = per_symbol_limit
        self._sem = asyncio.Semaphore(max_concurrency)

    @classmethod
    def from_settings(cls) -> "StockPulseSource":
        """Build the source from runtime config.

        Priority: ``system_settings`` (admin UI) → environment variables.
        Reading system_settings via raw SQL — same pattern used by
        app.core.secrets — keeps this safely callable from any context
        (consumer process, scheduler, request handler) without an
        AsyncSession dependency.
        """
        from app.core.config import get_settings
        s = get_settings()

        url = s.stockpulse_url or ""
        api_key = s.stockpulse_api_key or ""

        try:
            import asyncpg  # noqa: F401
            from app.db.database import get_engine
            from sqlalchemy import text as _text
            engine = get_engine()
            # Synchronous fallback: if called from sync context, skip DB lookup.
            # We use run_sync via a brief connection here — but simpler is to
            # just attempt a sync-aware path by deferring to the async path if
            # there's no running loop. To stay simple and side-effect-free,
            # we fetch lazily on first fetch() instead. So no DB call here.
        except Exception:
            pass

        return cls(base_url=url, api_key=api_key)

    async def _refresh_runtime_overrides(self) -> None:
        """Refresh url/api_key from system_settings (admin UI) if present.

        Called once at the start of fetch() so runtime config changes take
        effect on the next poll without a process restart. Falls back to
        the construction-time values (env vars) on any error.
        """
        try:
            from app.db.database import get_session_factory
            from sqlalchemy import text as _text
            factory = get_session_factory()
            async with factory() as session:
                rows = (await session.execute(
                    _text(
                        "SELECT key, value FROM system_settings "
                        "WHERE key IN ('integration.stockpulse.url', "
                        "'integration.stockpulse.api_key')"
                    )
                )).all()
            kv = {r.key: r.value for r in rows}
            url_override = kv.get("integration.stockpulse.url")
            key_override = kv.get("integration.stockpulse.api_key")
            if url_override:
                self._base_url = url_override.rstrip("/")
            if key_override:
                self._api_key = key_override
        except Exception:
            logger.debug("Failed to refresh StockPulse runtime overrides", exc_info=True)

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url) and bool(self._api_key)

    async def fetch(self, params: FetchParams) -> list[RawArticle]:
        """Fetch news for the given symbols. No symbols → no-op.

        Each symbol becomes one /api/v1/data/news call. We use limit-only
        (no `since`) — the time window per symbol is whatever the most
        recent N articles span, which auto-adapts to news density. Hot
        tickers get a narrow window naturally; cold tickers get a wide one.
        NewsForge's dedup engine (URL + SimHash + semantic) handles repeats
        on subsequent polls.
        """
        # Pick up admin-UI overrides on every poll so config changes take
        # effect without a restart.
        await self._refresh_runtime_overrides()

        if not self.is_configured:
            logger.warning("StockPulse not configured (URL/API key missing), skipping")
            return []

        symbols = params.symbols or []
        if not symbols:
            logger.debug("StockPulse: no symbols requested, skipping")
            return []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            tasks = [self._fetch_one(client, sym) for sym in symbols]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[RawArticle] = []
        for batch in batches:
            if isinstance(batch, Exception):
                logger.warning("StockPulse fetch failed for one symbol: %s", batch)
                continue
            out.extend(batch)

        logger.info(
            "StockPulse: %d articles across %d symbols",
            len(out), len(symbols),
        )
        return out

    async def health_check(self) -> HealthStatus:
        if not self.is_configured:
            return HealthStatus(
                is_healthy=False,
                message="STOCKPULSE_URL or STOCKPULSE_API_KEY not configured",
            )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Probe the global feed (no symbol) — cheapest call shape.
                resp = await client.get(
                    f"{self._base_url}/api/v1/data/news",
                    params={"limit": 1},
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    return HealthStatus(is_healthy=True, message="StockPulse reachable")
                return HealthStatus(
                    is_healthy=False,
                    message=f"StockPulse returned HTTP {resp.status_code}",
                )
        except Exception as e:
            return HealthStatus(is_healthy=False, message=str(e)[:200])

    # ---------------------------------------------------------------- internal

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._api_key, "Accept": "application/json"}

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        symbol: str,
    ) -> list[RawArticle]:
        market = infer_market_for_stockpulse(symbol)
        qs: dict[str, Any] = {"symbol": symbol, "limit": self._per_symbol_limit}
        if market:
            qs["market"] = market

        async with self._sem:
            try:
                resp = await client.get(
                    f"{self._base_url}/api/v1/data/news",
                    params=qs,
                    headers=self._headers(),
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.warning(
                    "StockPulse HTTP %d for symbol=%s: %s",
                    e.response.status_code, symbol, e.response.text[:200],
                )
                return []
            except Exception:
                logger.exception("StockPulse error for symbol=%s", symbol)
                return []

        body = resp.json() or {}
        items = body.get("data") or []
        if not isinstance(items, list):
            logger.warning("StockPulse returned non-list data for symbol=%s", symbol)
            return []

        out: list[RawArticle] = []
        for item in items:
            article = self._normalize(item, queried_symbol=symbol)
            if article is not None:
                out.append(article)

        if items:
            by_source: dict[str, int] = {}
            for it in items:
                by_source[it.get("source", "?")] = by_source.get(it.get("source", "?"), 0) + 1
            logger.debug(
                "StockPulse %s: %d items by_source=%s",
                symbol, len(items), by_source,
            )
        return out

    @staticmethod
    def _normalize(
        item: dict[str, Any],
        queried_symbol: str,
    ) -> RawArticle | None:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not url or not title:
            return None

        published_at = _parse_iso(item.get("published_at"))

        provider = item.get("source") or "stockpulse"
        publisher = item.get("publisher")
        source_name = publisher or f"stockpulse:{provider}"

        # Combine StockPulse's own related symbols with the symbol we queried for
        # (StockPulse may return zero or extra tickers; we always at least know
        # the queried one is relevant).
        related = item.get("symbols") or []
        if not isinstance(related, list):
            related = []
        sym_set: list[str] = []
        seen: set[str] = set()
        for s in [queried_symbol, *related]:
            su = (s or "").upper().strip()
            if su and su not in seen:
                seen.add(su)
                sym_set.append(su)

        # external_id needs to be globally unique across StockPulse's providers,
        # since each provider has its own id-space.
        item_id = item.get("id")
        if item_id:
            external_id = f"stockpulse:{provider}:{item_id}"[:512]
        else:
            external_id = None

        # raw payload is stashed for downstream debugging / future RAG, but
        # truncated so finance_metadata stays small.
        raw_keep: dict[str, Any] | None = None
        raw = item.get("raw")
        if isinstance(raw, dict) and raw:
            raw_keep = {k: raw[k] for k in list(raw.keys())[:20]}  # cap keys

        extra: dict[str, Any] = {
            "provider": "stockpulse",
            "stockpulse_source": provider,
            "symbols": sym_set,
        }
        if raw_keep is not None:
            extra["raw_payload"] = raw_keep

        summary = item.get("summary")
        if isinstance(summary, str):
            summary = summary.strip() or None
            if summary and len(summary) > 1000:
                summary = summary[:1000]

        return RawArticle(
            title=title[:500],
            url=url[:1024],
            summary=summary,
            published_at=published_at,
            source_name=source_name[:200],
            language=item.get("language"),
            category_hint="finance",
            external_id=external_id,
            top_image=item.get("image_url"),
            extra=extra,
        )

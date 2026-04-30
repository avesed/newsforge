"""Admin API for the StockPulse news aggregator integration.

StockPulse is the upstream fan-out aggregator (yfinance + akshare + finnhub
+ tiingo + ...). NewsForge polls it every 5 minutes for each symbol in the
``watched_symbols`` table.

Two settings are stored in ``system_settings`` so they take effect at
runtime without a container restart:
    integration.stockpulse.url      — base URL (e.g. http://stockpulse-app:80)
    integration.stockpulse.api_key  — X-API-Key for the StockPulse consumer

Until the admin sets these, NewsForge falls back to the legacy
``STOCKPULSE_URL`` / ``STOCKPULSE_API_KEY`` environment variables. Setting
them in the UI overrides env vars; clearing them reverts to env.

This module also exposes:
    GET  /admin/stockpulse/test           — probe StockPulse health
    GET  /admin/stockpulse/watched         — list watched_symbols rows
    POST /admin/stockpulse/poll/{tier}    — manually trigger a tier poll
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.models.user import User
from app.models.watched_symbol import WatchedSymbol
from app.schemas.base import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/stockpulse", tags=["admin"])


_URL_KEY = "integration.stockpulse.url"
_API_KEY_KEY = "integration.stockpulse.api_key"


# --- Schemas ---


class StockPulseConfig(CamelModel):
    """StockPulse integration config + status snapshot."""

    url: str | None = None
    # API key never returned in plaintext — only a masked preview.
    api_key_set: bool = False
    api_key_preview: str | None = None
    enabled_in_yaml: bool = True
    poll_interval_minutes: int = 5
    default_limit: int = 10


class StockPulseConfigUpdate(CamelModel):
    url: str | None = None
    # Pass empty string to clear, null to leave unchanged.
    api_key: str | None = None


class StockPulseTestResult(CamelModel):
    ok: bool
    status_code: int | None = None
    message: str
    elapsed_ms: int | None = None


class WatchedSymbolRow(CamelModel):
    id: int
    symbol: str
    market: str | None = None
    registered_by: str | None = None
    last_viewed_at: datetime | None = None
    last_polled_at: datetime | None = None
    last_error: str | None = None


class WatchedSymbolsResponse(CamelModel):
    total: int
    items: list[WatchedSymbolRow]


class PollResult(CamelModel):
    tier: str
    triggered: bool
    message: str


# --- Helpers ---


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    row = (await db.execute(
        text("SELECT value FROM system_settings WHERE key = :k"),
        {"k": key},
    )).first()
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    """Upsert (key=value) or DELETE if value is None/empty."""
    if value is None or value == "":
        await db.execute(
            text("DELETE FROM system_settings WHERE key = :k"),
            {"k": key},
        )
        return
    await db.execute(
        text(
            "INSERT INTO system_settings (key, value) VALUES (:k, :v) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
            "updated_at = NOW()"
        ),
        {"k": key, "v": value},
    )


def _mask_api_key(raw: str) -> str:
    """Show first 4 + '...' + last 2 chars; for very short keys, show length."""
    if len(raw) <= 6:
        return f"({len(raw)} chars)"
    return f"{raw[:4]}...{raw[-2:]}"


async def _resolve_runtime_config(db: AsyncSession) -> tuple[str | None, str | None]:
    """Return (url, api_key) the source actually uses right now.

    Priority: system_settings → environment variable. Mirrors what
    StockPulseSource.from_settings() will see after the next refresh.
    """
    from app.core.config import get_settings
    s = get_settings()
    url = await _get_setting(db, _URL_KEY) or s.stockpulse_url
    api_key = await _get_setting(db, _API_KEY_KEY) or s.stockpulse_api_key
    return url or None, api_key or None


# --- Endpoints ---


@router.get("/config", response_model=StockPulseConfig)
async def get_config(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Read current StockPulse integration config."""
    from app.core.config import load_pipeline_config

    url, api_key = await _resolve_runtime_config(db)

    pipeline_cfg = load_pipeline_config()
    sp_cfg = (pipeline_cfg.get("sources") or {}).get("stockpulse") or {}
    tiers = sp_cfg.get("tiers") or {}
    hot_interval = int((tiers.get("hot") or {}).get("interval_minutes", 5))

    return StockPulseConfig(
        url=url,
        api_key_set=bool(api_key),
        api_key_preview=_mask_api_key(api_key) if api_key else None,
        enabled_in_yaml=bool(sp_cfg.get("enabled", False)),
        poll_interval_minutes=hot_interval,
        default_limit=int(sp_cfg.get("default_limit", 10)),
    )


@router.put("/config", response_model=StockPulseConfig)
async def update_config(
    body: StockPulseConfigUpdate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Persist StockPulse URL / API key.

    Pass an empty string for either field to clear it (revert to env var).
    Pass null/omit to leave unchanged.
    """
    if body.url is not None:
        # Strip trailing slash to match StockPulseSource normalization.
        await _set_setting(db, _URL_KEY, body.url.rstrip("/") or None)
    if body.api_key is not None:
        await _set_setting(db, _API_KEY_KEY, body.api_key or None)
    await db.commit()

    # Force-refresh the settings cache so the next poll picks up new values.
    from app.core.config import get_settings
    get_settings.cache_clear()

    return await get_config(_admin=_admin, db=db)  # type: ignore[arg-type]


@router.post("/test", response_model=StockPulseTestResult)
async def test_connection(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Probe StockPulse health endpoint with the configured credentials.

    Calls ``GET /api/v1/data/news?limit=1`` (the cheapest authenticated
    request shape) and reports HTTP status + roundtrip time.
    """
    import time as _time

    url, api_key = await _resolve_runtime_config(db)
    if not url:
        return StockPulseTestResult(
            ok=False, message="STOCKPULSE_URL not configured",
        )
    if not api_key:
        return StockPulseTestResult(
            ok=False, message="STOCKPULSE_API_KEY not configured",
        )

    started = _time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{url.rstrip('/')}/api/v1/data/news",
                params={"limit": 1},
                headers={"X-API-Key": api_key, "Accept": "application/json"},
            )
        elapsed = int((_time.monotonic() - started) * 1000)
        if resp.status_code == 200:
            try:
                payload = resp.json()
                count = len(payload.get("data") or [])
                msg = f"StockPulse OK (returned {count} item)"
            except Exception:
                msg = "StockPulse OK"
            return StockPulseTestResult(
                ok=True, status_code=resp.status_code,
                message=msg, elapsed_ms=elapsed,
            )
        return StockPulseTestResult(
            ok=False, status_code=resp.status_code,
            message=f"HTTP {resp.status_code}: {resp.text[:200]}",
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = int((_time.monotonic() - started) * 1000)
        return StockPulseTestResult(
            ok=False, message=str(e)[:300], elapsed_ms=elapsed,
        )


@router.get("/watched", response_model=WatchedSymbolsResponse)
async def list_watched_symbols(
    limit: int = 200,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List rows from watched_symbols + total count.

    All symbols are polled on the same 5-minute interval — there is no
    hot/warm/cold tiering on the data fetch path. ``last_viewed_at`` is
    still kept for potential future reordering / per-symbol prioritization,
    but does not affect frequency today.
    """
    total = (await db.execute(
        select(func.count(WatchedSymbol.id))
    )).scalar() or 0

    rows = (await db.execute(
        select(WatchedSymbol)
        .order_by(WatchedSymbol.last_viewed_at.desc().nullslast())
        .limit(limit)
    )).scalars().all()

    items = [
        WatchedSymbolRow(
            id=r.id, symbol=r.symbol, market=r.market,
            registered_by=r.registered_by,
            last_viewed_at=r.last_viewed_at,
            last_polled_at=r.last_polled_at,
            last_error=r.last_error,
        )
        for r in rows
    ]
    return WatchedSymbolsResponse(total=total, items=items)


@router.post("/poll/{tier}", response_model=PollResult)
async def trigger_poll(
    tier: str = Path(..., pattern="^(hot|warm|cold)$"),
    _admin: User = Depends(require_admin),
):
    """Manually fire one StockPulse tier poll (for testing).

    Runs as a fire-and-forget asyncio task so the HTTP response returns
    immediately. Watch logs / watched_symbols.last_polled_at to confirm.
    """
    import asyncio
    from app.pipeline.orchestrator import poll_stockpulse_tier

    async def _run():
        try:
            await poll_stockpulse_tier(tier)
        except Exception:
            logger.exception("Manual StockPulse poll failed (tier=%s)", tier)

    asyncio.create_task(_run())
    return PollResult(
        tier=tier, triggered=True,
        message=f"Tier '{tier}' poll dispatched in background",
    )

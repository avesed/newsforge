"""Market inference for StockPulse queries.

StockPulse's `detect_market()` does NOT recognize bare 6-digit A-share codes
(e.g. `600519`) — it falls through to US, which means akshare/tushare
providers won't run. We must explicitly send `market=sh|sz` for those.

For symbols that StockPulse can detect itself (`.HK`, `.SS`, `.SZ` suffixes,
plain US tickers, precious metals like `GC=F`), we pass `market=None` and
let StockPulse decide.
"""

from __future__ import annotations

import re

_BARE_A_SHARE = re.compile(r"^\d{6}$")


def infer_market_for_stockpulse(symbol: str) -> str | None:
    """Return explicit market hint for StockPulse, or None to let it auto-detect.

    Rules:
    - Bare 6-digit codes starting with 6 → 'sh' (Shanghai main board)
    - Bare 6-digit codes starting with 0/3 → 'sz' (Shenzhen main + ChiNext)
    - Anything else → None (suffix-bearing or US-style — StockPulse handles)
    """
    s = symbol.upper().strip()
    if not _BARE_A_SHARE.match(s):
        return None
    if s.startswith("6"):
        return "sh"
    if s.startswith(("0", "3")):
        return "sz"
    return None

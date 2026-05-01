"""WatchedSymbol — symbols that downstream consumers (e.g. WebStock) want
news for, used to drive StockPulse polling.

Each row is a (symbol, market) pair. `last_viewed_at` tracks the most recent
time any user looked at this symbol on any consumer; the scheduler uses it
for hot/warm/cold tiering. `last_polled_at` and `last_error` track the most
recent StockPulse fetch for this symbol.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class WatchedSymbol(Base):
    __tablename__ = "watched_symbols"

    __table_args__ = (
        UniqueConstraint("symbol", "market", "registered_by", name="uq_watched_symbols_sym_mkt_consumer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Symbol as registered (e.g. "AAPL", "600519", "0700.HK"). Bare 6-digit
    # A-share codes MUST come with an explicit market hint from the caller.
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Market hint used when calling StockPulse: 'sh' | 'sz' | 'hk' | 'us' |
    # 'metal' | '' (empty = let StockPulse auto-detect).
    # NOT NULL + default '' so the unique constraint works (NULL ≠ NULL in PG).
    market: Mapped[str] = mapped_column(String(8), nullable=False, default="", server_default="")

    # Source of the registration (e.g. "webstock"). Each consumer gets its
    # own rows so unsubscribing one consumer doesn't affect others.
    # NOT NULL + default '' for the same NULL-uniqueness reason.
    registered_by: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)

    # Most recent time any user viewed this symbol on the registering consumer.
    # Drives the scheduler's hot/warm/cold tier classification.
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    # Most recent successful StockPulse poll.
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Last error text from StockPulse poll, truncated to 500 chars.
    last_error: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

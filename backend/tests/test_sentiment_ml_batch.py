"""Tests for POST /api/internal/sentiment/ml-batch endpoint.

Three test categories:
1. Functional — correct aggregation, field values, filtering
2. Edge cases — empty inputs, no matches, bad dates, boundary conditions
3. Stability — large payloads, concurrent requests, idempotency
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.article import Article

URL = "/api/internal/sentiment/ml-batch"


# ── Helpers ────────────────────────────────────────────────────────


async def _insert_article(
    db: AsyncSession,
    *,
    symbol: str = "AAPL",
    market: str = "us",
    published_at: datetime | None = None,
    sentiment_score: float | None = 0.5,
    sentiment_tag: str | None = "bullish",
    value_score: int | None = 75,
    extra_symbols: list[str] | None = None,
) -> Article:
    symbols = [symbol]
    if extra_symbols:
        symbols.extend(extra_symbols)

    fm: dict = {"symbols": symbols, "market": market}
    if sentiment_tag:
        fm["sentiment_tag"] = sentiment_tag

    article = Article(
        id=uuid.uuid4(),
        title=f"Test article {symbol}",
        url=f"https://example.com/{uuid.uuid4().hex}",
        published_at=published_at or datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc),
        sentiment_score=sentiment_score,
        value_score=value_score,
        finance_metadata=fm,
        content_status="processed",
    )
    db.add(article)
    await db.flush()
    return article


# ══════════════════════════════════════════════════════════════════
# 1. FUNCTIONAL TESTS
# ══════════════════════════════════════════════════════════════════


class TestFunctionalMlBatch:
    """Core functionality — aggregation logic, field values, filtering."""

    async def test_single_symbol_single_day(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        await _insert_article(
            db_session,
            symbol="TEST1",
            published_at=datetime(2025, 3, 10, 10, 0, tzinfo=timezone.utc),
            sentiment_score=0.8,
            sentiment_tag="bullish",
            value_score=90,
        )
        resp = await client.post(
            URL,
            json={"symbols": ["TEST1"], "start_date": "2025-03-10", "end_date": "2025-03-10"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        row = data[0]
        assert row["symbol"] == "TEST1"
        assert row["date"] == "2025-03-10"
        assert row["sentiment_avg"] == 0.8
        assert row["article_count"] == 1
        assert row["bullish_ratio"] == 1.0
        assert row["content_score_avg"] == 90.0

    async def test_multiple_articles_same_day_aggregation(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 4, 1, 8, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="AGG1", published_at=dt, sentiment_score=0.6, sentiment_tag="bullish", value_score=80)
        await _insert_article(db_session, symbol="AGG1", published_at=dt + timedelta(hours=2), sentiment_score=-0.2, sentiment_tag="bearish", value_score=60)
        await _insert_article(db_session, symbol="AGG1", published_at=dt + timedelta(hours=4), sentiment_score=0.1, sentiment_tag="neutral", value_score=70)

        resp = await client.post(
            URL,
            json={"symbols": ["AGG1"], "start_date": "2025-04-01", "end_date": "2025-04-01"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert len(data) == 1
        row = data[0]
        assert row["article_count"] == 3
        assert abs(row["sentiment_avg"] - round((0.6 - 0.2 + 0.1) / 3, 4)) < 0.001
        assert abs(row["bullish_ratio"] - round(1 / 3, 4)) < 0.001
        assert abs(row["content_score_avg"] - 70.0) < 0.1

    async def test_multiple_symbols_multiple_days(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        for sym, day, score in [
            ("SYM_A", 5, 0.3),
            ("SYM_A", 6, 0.7),
            ("SYM_B", 5, -0.5),
        ]:
            await _insert_article(
                db_session,
                symbol=sym,
                published_at=datetime(2025, 2, day, 12, 0, tzinfo=timezone.utc),
                sentiment_score=score,
                sentiment_tag="bullish" if score > 0 else "bearish",
                value_score=50,
            )

        resp = await client.post(
            URL,
            json={"symbols": ["SYM_A", "SYM_B"], "start_date": "2025-02-01", "end_date": "2025-02-28"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        symbols_dates = [(r["symbol"], r["date"]) for r in data]
        assert ("SYM_A", "2025-02-05") in symbols_dates
        assert ("SYM_A", "2025-02-06") in symbols_dates
        assert ("SYM_B", "2025-02-05") in symbols_dates
        assert len(data) == 3

    async def test_market_filter(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 5, 1, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="MKT1", market="us", published_at=dt, sentiment_score=0.5)
        await _insert_article(db_session, symbol="MKT1", market="cn", published_at=dt, sentiment_score=-0.3)

        resp = await client.post(
            URL,
            json={"symbols": ["MKT1"], "market": "us", "start_date": "2025-05-01", "end_date": "2025-05-01"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["sentiment_avg"] == 0.5

    async def test_no_market_filter_returns_all(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 5, 2, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="ALL1", market="us", published_at=dt, sentiment_score=0.4)
        await _insert_article(db_session, symbol="ALL1", market="hk", published_at=dt, sentiment_score=0.6)

        resp = await client.post(
            URL,
            json={"symbols": ["ALL1"], "start_date": "2025-05-02", "end_date": "2025-05-02"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["article_count"] == 2
        assert abs(data[0]["sentiment_avg"] - 0.5) < 0.001

    async def test_article_with_multiple_symbols_counted_for_each(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 7, 1, 12, 0, tzinfo=timezone.utc)
        await _insert_article(
            db_session,
            symbol="MULTI_A",
            extra_symbols=["MULTI_B"],
            published_at=dt,
            sentiment_score=0.9,
            sentiment_tag="bullish",
            value_score=80,
        )

        resp = await client.post(
            URL,
            json={"symbols": ["MULTI_A", "MULTI_B"], "start_date": "2025-07-01", "end_date": "2025-07-01"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        syms = {r["symbol"] for r in data}
        assert "MULTI_A" in syms
        assert "MULTI_B" in syms

    async def test_result_ordering_by_symbol_then_date(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        for sym, day in [("ORD_B", 2), ("ORD_A", 3), ("ORD_A", 1), ("ORD_B", 1)]:
            await _insert_article(
                db_session,
                symbol=sym,
                published_at=datetime(2025, 8, day, 12, 0, tzinfo=timezone.utc),
                sentiment_score=0.1,
            )

        resp = await client.post(
            URL,
            json={"symbols": ["ORD_A", "ORD_B"], "start_date": "2025-08-01", "end_date": "2025-08-05"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        pairs = [(r["symbol"], r["date"]) for r in data]
        assert pairs == sorted(pairs)

    async def test_bullish_ratio_zero_when_all_bearish(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 9, 1, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="BEAR1", published_at=dt, sentiment_tag="bearish")
        await _insert_article(db_session, symbol="BEAR1", published_at=dt + timedelta(hours=1), sentiment_tag="neutral")

        resp = await client.post(
            URL,
            json={"symbols": ["BEAR1"], "start_date": "2025-09-01", "end_date": "2025-09-01"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert data[0]["bullish_ratio"] == 0.0

    async def test_null_sentiment_score_excluded(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 9, 5, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="NULLS1", published_at=dt, sentiment_score=None, sentiment_tag="bullish", value_score=None)
        await _insert_article(db_session, symbol="NULLS1", published_at=dt + timedelta(hours=1), sentiment_score=0.4, sentiment_tag="bearish", value_score=60)

        resp = await client.post(
            URL,
            json={"symbols": ["NULLS1"], "start_date": "2025-09-05", "end_date": "2025-09-05"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert data[0]["article_count"] == 1
        assert data[0]["sentiment_avg"] == 0.4
        assert data[0]["bullish_ratio"] == 0.0

    async def test_rounding_precision(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        dt = datetime(2025, 10, 1, 12, 0, tzinfo=timezone.utc)
        for i in range(7):
            await _insert_article(
                db_session,
                symbol="PREC1",
                published_at=dt + timedelta(minutes=i),
                sentiment_score=0.1 * i - 0.3,
                sentiment_tag="bullish" if i % 2 == 0 else "bearish",
                value_score=60 + i,
            )

        resp = await client.post(
            URL,
            json={"symbols": ["PREC1"], "start_date": "2025-10-01", "end_date": "2025-10-01"},
            headers=api_headers,
        )
        row = resp.json()["data"][0]
        # Verify 4-decimal rounding for sentiment_avg and bullish_ratio
        assert isinstance(row["sentiment_avg"], float)
        s = str(row["sentiment_avg"])
        if "." in s:
            assert len(s.split(".")[1]) <= 4
        # content_score_avg rounds to 1 decimal
        s2 = str(row["content_score_avg"])
        if "." in s2:
            assert len(s2.split(".")[1]) <= 1


# ══════════════════════════════════════════════════════════════════
# 2. EDGE CASE TESTS
# ══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions, invalid inputs, empty results."""

    async def test_empty_symbols_list(self, client: AsyncClient, api_headers: dict):
        resp = await client.post(
            URL,
            json={"symbols": [], "start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_no_matching_data(self, client: AsyncClient, api_headers: dict):
        resp = await client.post(
            URL,
            json={"symbols": ["ZZZZZZ_NONEXIST"], "start_date": "2099-01-01", "end_date": "2099-12-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_invalid_date_format(self, client: AsyncClient, api_headers: dict):
        resp = await client.post(
            URL,
            json={"symbols": ["AAPL"], "start_date": "not-a-date", "end_date": "2025-01-31"},
            headers=api_headers,
        )
        assert resp.status_code == 422

    async def test_start_after_end(self, client: AsyncClient, api_headers: dict):
        resp = await client.post(
            URL,
            json={"symbols": ["AAPL"], "start_date": "2025-03-01", "end_date": "2025-01-01"},
            headers=api_headers,
        )
        assert resp.status_code == 422

    async def test_same_start_and_end_date(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        await _insert_article(
            db_session,
            symbol="SAMEDAY",
            published_at=datetime(2025, 6, 1, 23, 59, 59, tzinfo=timezone.utc),
            sentiment_score=0.1,
        )
        resp = await client.post(
            URL,
            json={"symbols": ["SAMEDAY"], "start_date": "2025-06-01", "end_date": "2025-06-01"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1

    async def test_missing_required_fields(self, client: AsyncClient, api_headers: dict):
        resp = await client.post(URL, json={"symbols": ["AAPL"]}, headers=api_headers)
        assert resp.status_code == 422

    async def test_no_api_key(self, client: AsyncClient):
        resp = await client.post(
            URL,
            json={"symbols": ["AAPL"], "start_date": "2025-01-01", "end_date": "2025-01-31"},
        )
        assert resp.status_code == 401

    async def test_invalid_api_key(self, client: AsyncClient):
        resp = await client.post(
            URL,
            json={"symbols": ["AAPL"], "start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers={"X-API-Key": "totally-bogus-key"},
        )
        assert resp.status_code == 401

    async def test_whitespace_and_case_in_symbols(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        await _insert_article(
            db_session,
            symbol="CASE1",
            published_at=datetime(2025, 7, 10, 12, 0, tzinfo=timezone.utc),
            sentiment_score=0.5,
        )
        resp = await client.post(
            URL,
            json={"symbols": [" case1 ", "  CASE1"], "start_date": "2025-07-10", "end_date": "2025-07-10"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["symbol"] == "CASE1"

    async def test_symbols_with_empty_strings_filtered(
        self, client: AsyncClient, api_headers: dict
    ):
        resp = await client.post(
            URL,
            json={"symbols": ["", "  ", ""], "start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_article_without_finance_metadata_symbols(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Articles with no symbols in finance_metadata shouldn't break the query."""
        article = Article(
            id=uuid.uuid4(),
            title="No symbols article",
            url=f"https://example.com/{uuid.uuid4().hex}",
            published_at=datetime(2025, 11, 1, 12, 0, tzinfo=timezone.utc),
            sentiment_score=0.5,
            finance_metadata={},
            content_status="processed",
        )
        db_session.add(article)
        await db_session.flush()

        resp = await client.post(
            URL,
            json={"symbols": ["NOSYM"], "start_date": "2025-11-01", "end_date": "2025-11-01"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_article_without_sentiment_tag(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        await _insert_article(
            db_session,
            symbol="NOTAG1",
            published_at=datetime(2025, 11, 5, 12, 0, tzinfo=timezone.utc),
            sentiment_score=0.3,
            sentiment_tag=None,
            value_score=50,
        )
        resp = await client.post(
            URL,
            json={"symbols": ["NOTAG1"], "start_date": "2025-11-05", "end_date": "2025-11-05"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["bullish_ratio"] is None
        assert data[0]["sentiment_avg"] == 0.3

    async def test_invalid_market_rejected(self, client: AsyncClient, api_headers: dict):
        resp = await client.post(
            URL,
            json={"symbols": ["AAPL"], "market": "xyz", "start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers=api_headers,
        )
        assert resp.status_code == 422

    async def test_very_long_date_range(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """A year-long range should still work."""
        await _insert_article(
            db_session,
            symbol="LONG1",
            published_at=datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc),
        )
        resp = await client.post(
            URL,
            json={"symbols": ["LONG1"], "start_date": "2025-01-01", "end_date": "2025-12-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    async def test_over_2000_symbols_returns_empty(
        self, client: AsyncClient, api_headers: dict
    ):
        symbols = [f"S{i:05d}" for i in range(2001)]
        resp = await client.post(
            URL,
            json={"symbols": symbols, "start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    async def test_date_boundary_inclusive(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Articles at start-of-day and end-of-day should both be included."""
        await _insert_article(
            db_session,
            symbol="BOUND1",
            published_at=datetime(2025, 3, 15, 0, 0, 0, tzinfo=timezone.utc),
            sentiment_score=0.1,
        )
        await _insert_article(
            db_session,
            symbol="BOUND1",
            published_at=datetime(2025, 3, 15, 23, 59, 58, tzinfo=timezone.utc),
            sentiment_score=0.9,
        )

        resp = await client.post(
            URL,
            json={"symbols": ["BOUND1"], "start_date": "2025-03-15", "end_date": "2025-03-15"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert data[0]["article_count"] == 2


# ══════════════════════════════════════════════════════════════════
# 3. STABILITY TESTS
# ══════════════════════════════════════════════════════════════════


class TestStability:
    """Large payloads, concurrent requests, idempotency."""

    async def test_many_symbols_query(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Query with 500 symbols should complete without error."""
        dt = datetime(2025, 12, 1, 12, 0, tzinfo=timezone.utc)
        for i in range(10):
            await _insert_article(
                db_session,
                symbol=f"BULK{i:03d}",
                published_at=dt,
                sentiment_score=0.1 * i,
            )

        symbols = [f"BULK{i:03d}" for i in range(500)]
        resp = await client.post(
            URL,
            json={"symbols": symbols, "start_date": "2025-12-01", "end_date": "2025-12-01"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 10

    async def test_rapid_sequential_requests(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Many rapid sequential requests should all succeed consistently."""
        dt = datetime(2025, 12, 5, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="CONC1", published_at=dt, sentiment_score=0.5)

        body = {"symbols": ["CONC1"], "start_date": "2025-12-05", "end_date": "2025-12-05"}
        for _ in range(10):
            resp = await client.post(URL, json=body, headers=api_headers)
            assert resp.status_code == 200
            assert len(resp.json()["data"]) == 1

    async def test_idempotent_results(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Same request twice should return identical results."""
        dt = datetime(2025, 12, 10, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="IDEM1", published_at=dt, sentiment_score=0.33)

        body = {"symbols": ["IDEM1"], "start_date": "2025-12-10", "end_date": "2025-12-10"}
        r1 = await client.post(URL, json=body, headers=api_headers)
        r2 = await client.post(URL, json=body, headers=api_headers)
        assert r1.json() == r2.json()

    async def test_many_articles_per_day(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """100 articles for one symbol on one day should aggregate correctly."""
        dt = datetime(2025, 12, 15, 0, 0, tzinfo=timezone.utc)
        total_score = 0.0
        bullish_count = 0
        total_value = 0
        n = 100

        for i in range(n):
            score = -1.0 + (2.0 * i / (n - 1))
            tag = "bullish" if score > 0.3 else ("bearish" if score < -0.3 else "neutral")
            vs = 50 + (i % 50)
            total_score += score
            if tag == "bullish":
                bullish_count += 1
            total_value += vs
            await _insert_article(
                db_session,
                symbol="HEAVY1",
                published_at=dt + timedelta(minutes=i),
                sentiment_score=round(score, 4),
                sentiment_tag=tag,
                value_score=vs,
            )

        resp = await client.post(
            URL,
            json={"symbols": ["HEAVY1"], "start_date": "2025-12-15", "end_date": "2025-12-15"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert len(data) == 1
        row = data[0]
        assert row["article_count"] == n
        assert abs(row["sentiment_avg"] - round(total_score / n, 4)) < 0.01
        assert abs(row["bullish_ratio"] - round(bullish_count / n, 4)) < 0.01
        assert abs(row["content_score_avg"] - round(total_value / n, 1)) < 1.0

    async def test_wide_date_range_many_days(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Articles spread across 30 days should return 30 rows."""
        base = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        for d in range(30):
            await _insert_article(
                db_session,
                symbol="WIDE1",
                published_at=base + timedelta(days=d),
                sentiment_score=0.1,
            )

        resp = await client.post(
            URL,
            json={"symbols": ["WIDE1"], "start_date": "2025-01-01", "end_date": "2025-01-31"},
            headers=api_headers,
        )
        data = resp.json()["data"]
        assert len(data) == 30

    async def test_response_structure_consistency(
        self, client: AsyncClient, db_session: AsyncSession, api_headers: dict
    ):
        """Every row must have exactly the expected keys."""
        dt = datetime(2025, 12, 20, 12, 0, tzinfo=timezone.utc)
        await _insert_article(db_session, symbol="STRUCT1", published_at=dt)

        resp = await client.post(
            URL,
            json={"symbols": ["STRUCT1"], "start_date": "2025-12-20", "end_date": "2025-12-20"},
            headers=api_headers,
        )
        row = resp.json()["data"][0]
        expected_keys = {"symbol", "date", "sentiment_avg", "article_count", "bullish_ratio", "content_score_avg"}
        assert set(row.keys()) == expected_keys

    async def test_with_real_data_aapl(
        self, client: AsyncClient, api_headers: dict
    ):
        """Smoke test against real AAPL data in the database.

        This validates the query runs correctly against production-shaped data
        with real JSONB contents, not just our test fixtures.
        """
        resp = await client.post(
            URL,
            json={"symbols": ["AAPL"], "start_date": "2025-01-01", "end_date": "2025-12-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        for row in data:
            assert row["symbol"] == "AAPL"
            assert row["article_count"] >= 1
            if row["sentiment_avg"] is not None:
                assert -1.0 <= row["sentiment_avg"] <= 1.0
            if row["bullish_ratio"] is not None:
                assert 0.0 <= row["bullish_ratio"] <= 1.0

    async def test_with_real_data_nvda(
        self, client: AsyncClient, api_headers: dict
    ):
        """Smoke test against real NVDA data."""
        resp = await client.post(
            URL,
            json={"symbols": ["NVDA"], "market": "us", "start_date": "2025-01-01", "end_date": "2025-12-31"},
            headers=api_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        for row in data:
            assert row["symbol"] == "NVDA"

"""Tests for app.services.screener orchestration layer.

Covers the bug where _execute_tql_count was being passed the LIMIT bind
even though it strips the LIMIT ? from the SQL — sqlite3 would raise
"Incorrect number of bindings supplied".

These tests use a tempfile-backed SQLite so the seeded data is shared
across the multiple connections that screener.py opens internally.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def shared_db(monkeypatch, tmp_path):
    """A tempfile SQLite with the snapshot + ticker_scores tables seeded.

    screener.py opens its own connections via sqlite3.connect(settings.db_path)
    and we point that path at our tempfile so all the connections share the
    same on-disk data.
    """
    db_path = tmp_path / "screener_test.db"
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE ticker_screener_snapshot (
            symbol TEXT PRIMARY KEY,
            last_date TEXT, compute_date TEXT, computed_at TEXT,
            last_close REAL, last_volume INTEGER, last_open REAL,
            last_high REAL, last_low REAL,
            sector TEXT, industry TEXT, pe REAL, market_cap REAL, fair_value REAL,
            high_52w REAL, low_52w REAL, pct_from_52w_high REAL, pct_from_52w_low REAL,
            rsi_1d REAL, macd_1d REAL, macd_signal_1d REAL, macd_histogram_1d REAL,
            bb_middle_1d REAL, bb_upper_1d REAL, bb_lower_1d REAL, bb_width_1d REAL,
            bb_squeeze_1d TEXT, atr_1d REAL, atr_percent_1d REAL, vwma_20_1d REAL,
            hv_20 REAL, hv_60 REAL, sharpe_60 REAL, sharpe_126 REAL
        );
        CREATE TABLE ticker_scores (
            symbol TEXT PRIMARY KEY,
            return_1w REAL, return_1m REAL, return_3m REAL,
            return_6m REAL, return_1y REAL,
            momentum_score REAL, momentum_rank INTEGER, volume_ratio_20d REAL
        );
    """)
    rows = [
        ("HDFCBANK", 105.0, 100.0, "Banks", 18.0, 70.0, 1.0),
        ("INFY",     105.0, 100.0, "IT",     25.0, 55.0, 1.0),
        ("TATAMOTORS", 95.0, 100.0, "Auto",  12.0, 45.0, 1.0),
    ]
    for sym, last_close, last_open, sector, pe, rsi, ratio in rows:
        con.execute(
            """INSERT INTO ticker_screener_snapshot
               (symbol, last_date, compute_date, computed_at, last_close, last_volume,
                last_open, last_high, last_low, sector, industry, pe,
                rsi_1d, bb_squeeze_1d, atr_percent_1d)
               VALUES (?, '2025-06-04', '2025-06-04', '2025-06-04 10:00:00',
                       ?, 1000000, ?, ?, ?, ?, '', ?, ?, 'N', 1.0)""",
            (sym, last_close, last_open, last_close + 1, last_close - 1,
             sector, pe, rsi),
        )
        con.execute(
            """INSERT INTO ticker_scores
               (symbol, return_1w, return_1m, return_3m, return_6m, return_1y,
                momentum_score, momentum_rank, volume_ratio_20d)
               VALUES (?, 1.0, 2.0, 3.0, 4.0, 5.0, 50.0, 1, ?)""",
            (sym, ratio),
        )
    con.commit()
    con.close()

    from app.config import settings
    from app.services import screener

    monkeypatch.setattr(settings, "db_path", str(db_path))
    screener.invalidate_snapshot_check_cache()
    return db_path


class TestCountBindBugRegression:
    """Regression: COUNT must not include the LIMIT bind in its parameters."""

    def test_run_screener_tql_no_bind_mismatch(self, shared_db):
        from app.services.screener import run_screener_tql
        result = run_screener_tql("RSI > 50", limit=10)
        # HDFCBANK (RSI=70) and INFY (RSI=55) match; TATAMOTORS (RSI=45) doesn't
        assert result["count"] == 2
        assert result["returned"] == 2
        symbols = sorted(r["symbol"] for r in result["results"])
        assert symbols == ["HDFCBANK", "INFY"]

    def test_run_screener_tql_zero_results(self, shared_db):
        from app.services.screener import run_screener_tql
        result = run_screener_tql('Sector = "Nonexistent"', limit=5)
        assert result["count"] == 0
        assert result["returned"] == 0
        assert result["results"] == []

    def test_run_screener_legacy_no_bind_mismatch(self, shared_db):
        from app.services.screener import run_screener
        result = run_screener({"rsi_min": 50}, limit=10)
        # Same match: HDFCBANK + INFY
        assert result["count"] == 2
        assert result["returned"] == 2
        symbols = sorted(r["symbol"] for r in result["results"])
        assert symbols == ["HDFCBANK", "INFY"]

    def test_count_equals_total_when_limit_above_match_count(self, shared_db):
        """When limit > matches, count == returned."""
        from app.services.screener import run_screener_tql
        result = run_screener_tql("RSI > 0", limit=100)
        assert result["count"] == 3
        assert result["returned"] == 3

    def test_count_above_returned_when_limit_caps(self, shared_db):
        """When limit < matches, count > returned."""
        from app.services.screener import run_screener_tql
        result = run_screener_tql("RSI > 0", limit=1)
        assert result["count"] == 3
        assert result["returned"] == 1

    def test_hv_filter_uses_bare_column(self, shared_db):
        """Regression: HV20/HV60/Sharpe60/Sharpe126 are stored without _1d suffix."""
        from app.services.screener import run_screener_tql
        # All three have hv_20=NULL by default; set one to 0.5 so the
        # filter has at least one match
        import sqlite3 as _sq
        con = _sq.connect(str(shared_db))
        con.execute("UPDATE ticker_screener_snapshot SET hv_20 = 0.5 WHERE symbol = 'HDFCBANK'")
        con.commit(); con.close()
        result = run_screener_tql("HV20 > 0.3", limit=10)
        assert result["count"] == 1
        assert result["results"][0]["symbol"] == "HDFCBANK"

    def test_sharpe_filter_uses_bare_column(self, shared_db):
        from app.services.screener import run_screener_tql
        import sqlite3 as _sq
        con = _sq.connect(str(shared_db))
        con.execute("UPDATE ticker_screener_snapshot SET sharpe_60 = 2.0 WHERE symbol = 'INFY'")
        con.commit(); con.close()
        result = run_screener_tql("Sharpe60 > 1.0", limit=10)
        assert result["count"] == 1
        assert result["results"][0]["symbol"] == "INFY"

    def test_1h_hv_uses_suffixed_column(self, shared_db):
        """1h:HV20 still works because the snapshot has hv_20_1h."""
        from app.services.screener import run_screener_tql
        import sqlite3 as _sq
        con = _sq.connect(str(shared_db))
        # The schema doesn't include hv_20_1h in our test fixture; we add it
        # to confirm the transpiler emits snap.hv_20_1h (not snap.hv_20_1d).
        con.execute("ALTER TABLE ticker_screener_snapshot ADD COLUMN hv_20_1h REAL")
        con.execute("UPDATE ticker_screener_snapshot SET hv_20_1h = 0.4 WHERE symbol = 'TATAMOTORS'")
        con.commit(); con.close()
        # This should not raise OperationalError about a missing column.
        result = run_screener_tql("1h:HV20 > 0.3", limit=10)
        assert result["count"] == 1
        assert result["results"][0]["symbol"] == "TATAMOTORS"

def test_screener_html_cache_eviction():
    from app.services.screener_client import _HTML_CACHE
    _HTML_CACHE.clear()
    for i in range(600):
        _HTML_CACHE[f"key_{i}"] = f"html_{i}"
    assert len(_HTML_CACHE) <= 500

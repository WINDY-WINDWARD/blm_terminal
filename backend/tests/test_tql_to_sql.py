"""Tests for the TQL → SQL transpiler (app.services.tql_to_sql).

Covers:
- AST node → SQL rendering (each node type)
- Interval-prefixed field resolution (1h:RSI, W:ATR, M:MACD)
- Lateral-join generation when non-1d intervals are referenced
- BBSqueeze bare-boolean shorthand
- IN with mixed-type values
- Legacy filter dict → SQL
- Sort field whitelist
- _row_to_dict hydration (output shape parity with legacy in-memory result)
- Integration: parse + render + execute against an in-memory SQLite fixture
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tql_parser import (  # noqa: E402
    AndNode,
    CompareNode,
    InNode,
    NotNode,
    OrNode,
    parse_tql,
    TQLSyntaxError,
)
from app.services.tql_to_sql import (  # noqa: E402
    _FALLBACK_COLUMN,
    _INDICATOR_COLUMNS,
    _node_to_where,
    _row_to_dict,
    _sort_sql,
    _split_field,
    build_legacy_query,
    build_snapshot_legacy_query,
    build_snapshot_tql_query,
    build_tql_query,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _render(tql: str, default_interval: str = "1d"):
    """Parse TQL and render the WHERE fragment, returning (sql_fragment, intervals, binds)."""
    ast = parse_tql(tql)
    intervals: set[str] = set()
    binds: list = []
    fragment = _node_to_where(ast, default_interval, intervals, binds)
    return fragment, intervals, binds


# ─── Token / field split ────────────────────────────────────────────────────

class TestSplitField:
    def test_plain_field(self):
        iv, name = _split_field("RSI")
        assert iv is None
        assert name == "RSI"

    def test_1h_prefix(self):
        iv, name = _split_field("1h:RSI")
        assert iv == "1h"
        assert name == "RSI"

    def test_W_prefix(self):
        iv, name = _split_field("W:ATR")
        assert iv == "W"
        assert name == "ATR"

    def test_M_prefix(self):
        iv, name = _split_field("M:MACD")
        assert iv == "M"
        assert name == "MACD"

    def test_1d_prefix(self):
        iv, name = _split_field("1d:BBWidth")
        assert iv == "1d"
        assert name == "BBWidth"


# ─── AST node rendering ─────────────────────────────────────────────────────

class TestNodeToWhere:
    def test_compare_numeric_gt(self):
        frag, ints, binds = _render("RSI > 60")
        assert "td.rsi_14" in frag
        assert ">" in frag
        assert binds == [60]
        assert ints == set()

    def test_compare_string_eq(self):
        frag, ints, binds = _render('Sector = "Banks"')
        assert "su.sector" in frag
        assert "=" in frag
        assert binds == ["Banks"]
        assert ints == set()

    def test_compare_lt(self):
        _, _, binds = _render("PE < 30")
        assert binds == [30]

    def test_compare_le(self):
        frag, _, binds = _render("PE <= 30")
        assert "<=" in frag
        assert binds == [30]

    def test_compare_ne(self):
        frag, _, binds = _render('Sector != "Banks"')
        assert "!=" in frag
        assert binds == ["Banks"]

    def test_in_clause_strings(self):
        frag, _, binds = _render('Sector IN ("Banks", "IT", "Auto")')
        assert "IN" in frag
        assert "su.sector" in frag
        assert binds == ["Banks", "IT", "Auto"]

    def test_in_clause_numbers(self):
        frag, _, binds = _render("Return1w IN (1, 5, 10)")
        assert "ts.return_1w" in frag
        assert binds == [1, 5, 10]

    def test_and(self):
        frag, _, binds = _render('RSI > 60 AND Sector = "Banks"')
        assert "AND" in frag
        assert "td.rsi_14" in frag
        assert "su.sector" in frag
        assert binds == [60, "Banks"]

    def test_or(self):
        frag, _, binds = _render('Sector = "Banks" OR Sector = "IT"')
        assert "OR" in frag
        assert binds == ["Banks", "IT"]

    def test_not(self):
        frag, _, _ = _render("NOT BBSqueeze")
        # bare BBSqueeze expands to (IS NOT NULL AND = 'Y'); NOT inverts
        assert "NOT" in frag
        assert "bb_squeeze" in frag
        assert "= 'Y'" in frag
        assert "IS NOT NULL" in frag

    def test_parens(self):
        frag, _, _ = _render("(RSI > 60 AND Volume > 2) OR PE < 20")
        assert frag.count("(") >= 2
        assert "OR" in frag
        assert "AND" in frag

    def test_bbsqueeze_bare(self):
        # BBSqueeze alone is shorthand for BBSqueeze = 1 (i.e. squeeze active)
        frag, _, _ = _render("BBSqueeze")
        assert "bb_squeeze" in frag
        assert "= 'Y'" in frag
        assert "IS NOT NULL" in frag
        assert "IS NOT NULL" in frag

    def test_parens(self):
        frag, _, _ = _render("(RSI > 60 AND Volume > 2) OR PE < 20")
        assert frag.count("(") >= 2
        assert "OR" in frag
        assert "AND" in frag

    def test_bbsqueeze_bare(self):
        # BBSqueeze alone is shorthand for BBSqueeze = 1 (i.e. squeeze active)
        frag, _, _ = _render("BBSqueeze")
        assert "bb_squeeze" in frag
        assert "= 'Y'" in frag
        assert "IS NOT NULL" in frag

    def test_unknown_field_raises(self):
        with pytest.raises(TQLSyntaxError):
            parse_tql("NotARealField > 5")

    def test_unknown_interval_raises(self):
        with pytest.raises(TQLSyntaxError):
            parse_tql("5m:RSI > 60")


# ─── Interval lateral join generation ───────────────────────────────────────

class TestLateralJoins:
    def test_1h_prefix_adds_lateral(self):
        _, ints, _ = _render("1h:RSI > 60")
        assert "1h" in ints

    def test_W_prefix_adds_lateral(self):
        _, ints, _ = _render("W:ATR < 3")
        assert "w" in ints  # normalized

    def test_M_prefix_adds_lateral(self):
        _, ints, _ = _render("M:MACD > 0")
        assert "m" in ints

    def test_1d_prefix_does_not_add_lateral(self):
        _, ints, _ = _render("1d:RSI > 60")
        # 1d comes from td_latest, no lateral needed
        assert ints == set()

    def test_mixed_intervals(self):
        _, ints, _ = _render("1h:RSI > 60 AND W:BBWidth < 0.1 AND 1d:ATR < 5")
        assert "1h" in ints
        assert "w" in ints
        # 1d not in lateral set
        assert "1d" not in ints


# ─── Legacy filter translation ──────────────────────────────────────────────

class TestLegacyQuery:
    def test_empty_filters(self):
        sql, binds = build_legacy_query({})
        assert "1=1" in sql
        assert binds[:-1] == []  # last bind is the LIMIT

    def test_rsi_min(self):
        sql, binds = build_legacy_query({"rsi_min": 60.0})
        assert "td.rsi_14 >=" in sql
        assert 60.0 in binds

    def test_pe_range(self):
        sql, binds = build_legacy_query({"pe_min": 5.0, "pe_max": 30.0})
        assert "su.symbol_pe >=" in sql
        assert "su.symbol_pe <=" in sql
        assert 5.0 in binds
        assert 30.0 in binds

    def test_sector_filter(self):
        sql, binds = build_legacy_query({"sector": "Banks"})
        assert "LOWER(su.sector) = LOWER(?)" in sql
        assert "Banks" in binds

    def test_industry_partial_match(self):
        sql, binds = build_legacy_query({"industry": "Software"})
        assert "LIKE" in sql
        assert any("%Software%" in str(b) for b in binds)

    def test_bbsqueeze_true(self):
        sql, binds = build_legacy_query({"bb_squeeze": True})
        assert "td.bb_squeeze = 'Y'" in sql

    def test_bbsqueeze_false(self):
        sql, binds = build_legacy_query({"bb_squeeze": False})
        assert "!= 'Y'" in sql

    def test_above_sma50(self):
        sql, _ = build_legacy_query({"above_sma50": True})
        assert "td.close > td.bb_middle" in sql

    def test_momentum_score_min(self):
        sql, binds = build_legacy_query({"momentum_score_min": 70.0})
        assert "ts.momentum_score >=" in sql
        assert 70.0 in binds

    def test_pct_change_window(self):
        sql, binds = build_legacy_query({
            "pct_change_today_min": 2.0,
            "pct_change_1w_min": 1.0,
        })
        assert "pct_change_today" in sql or "change_today" in sql
        assert "ts.return_1w >=" in sql
        assert 2.0 in binds
        assert 1.0 in binds

    def test_limit_is_appended(self):
        sql, binds = build_legacy_query({"rsi_min": 60.0}, limit=25)
        assert "LIMIT ?" in sql
        assert binds[-1] == 25


# ─── Sort field whitelist ───────────────────────────────────────────────────

class TestSortSql:
    def test_symbol_default(self):
        assert "td.symbol" in _sort_sql("symbol", "asc")
        assert "ASC" in _sort_sql("symbol", "asc")

    def test_desc(self):
        assert "DESC" in _sort_sql("rsi", "desc")

    def test_unknown_field_falls_back(self):
        sql = _sort_sql("nonexistent", "asc")
        assert "td.symbol" in sql  # fallback

    def test_change_today(self):
        assert "change_today" in _sort_sql("change_today", "desc")


# ─── build_tql_query integration ────────────────────────────────────────────

class TestBuildTqlQuery:
    def test_simple_query_shape(self):
        sql, binds = build_tql_query("RSI > 60", limit=10)
        assert "WITH td_latest AS" in sql
        assert "ticker_scores" in sql
        assert "stock_universe" in sql
        assert "td_latest.rn = 1" in sql
        assert "ORDER BY" in sql
        assert "LIMIT ?" in sql
        assert binds[-1] == 10

    def test_no_lateral_for_1d(self):
        sql, _ = build_tql_query("RSI > 60")
        assert "ticker_intraday" not in sql

    def test_lateral_for_1h(self):
        sql, _ = build_tql_query("1h:RSI > 60")
        assert "ticker_intraday" in sql
        assert "ti_1h" in sql

    def test_lateral_for_W(self):
        sql, _ = build_tql_query("W:BBWidth < 0.1")
        assert "ticker_intraday" in sql
        assert "ti_w" in sql  # normalized

    def test_combined_query(self):
        sql, binds = build_tql_query(
            'RSI > 60 AND 1h:MACD > 0 AND Sector = "Banks"',
            sort_by="rsi", order="desc", limit=20
        )
        assert "td.rsi_14" in sql
        assert "ti_1h" in sql
        assert "su.sector" in sql
        assert "DESC" in sql
        assert binds[-1] == 20

    def test_syntax_error_raises(self):
        with pytest.raises(TQLSyntaxError):
            build_tql_query("RSI >>> 60")


# ─── _row_to_dict output shape ─────────────────────────────────────────────

class TestRowToDict:
    def _sample_row(self):
        return {
            "symbol": "HDFCBANK",
            "date": "2025-06-04",
            "open": 100.0,
            "close": 105.0,
            "change_today": 5.0,
            "return_1w": 3.0,
            "return_1m": 8.0,
            "return_3m": 12.0,
            "return_6m": None,
            "return_1y": 25.0,
            "momentum_score": 78.5,
            "momentum_rank": 42,
            "volume_ratio_20d": 1.8,
            "rsi_14": 65.4,
            "atr_percent": 2.1,
            "macd": 1.5,
            "macd_signal": 1.2,
            "macd_histogram": 0.3,
            "bb_middle": 102.0,
            "bb_upper": 110.0,
            "bb_lower": 95.0,
            "bb_width": 14.7,
            "bb_squeeze": "Y",
            "atr_14": 2.5,
            "vwma_20": 103.0,
            "hv_20": 18.0,
            "hv_60": 22.0,
            "sharpe_60": 0.8,
            "sharpe_126": 0.65,
            "sector": "Banks",
            "industry": "Private Banks",
            "pe": 18.5,
            "fair_value": 110.0,
            "high_52w": 110.0,
            "low_52w": 90.0,
        }

    def test_basic_shape(self):
        d = _row_to_dict(self._sample_row())
        assert d["symbol"] == "HDFCBANK"
        assert d["close"] == 105.0
        assert d["change_today"] == 5.0

    def test_returns_dict(self):
        d = _row_to_dict(self._sample_row())
        assert d["returns"]["1w"] == 3.0
        assert d["returns"]["1m"] == 8.0
        assert d["returns"]["6m"] is None

    def test_indicators_dict(self):
        d = _row_to_dict(self._sample_row())
        assert d["indicators"]["rsi_14"] == 65.4
        assert d["indicators"]["bb_squeeze"] is True  # "Y" → True

    def test_indicators_by_interval_has_1d(self):
        d = _row_to_dict(self._sample_row())
        assert "1d" in d["indicators_by_interval"]
        assert d["indicators_by_interval"]["1d"]["rsi_14"] == 65.4

    def test_pos_52w_computed(self):
        d = _row_to_dict(self._sample_row())
        # (105 - 110) / 110 * 100 = -4.55
        assert d["pos_52w"]["pct_from_52w_high"] == -4.55
        # (105 - 90) / 90 * 100 = 16.67
        assert d["pos_52w"]["pct_from_52w_low"] == 16.67

    def test_sector_industry_pe(self):
        d = _row_to_dict(self._sample_row())
        assert d["sector"] == "Banks"
        assert d["industry"] == "Private Banks"
        assert d["pe"] == 18.5
        assert d["fair_value"] == 110.0

    def test_volume_ratio_renamed(self):
        d = _row_to_dict(self._sample_row())
        assert d["volume_ratio"] == 1.8

    def test_momentum_score(self):
        d = _row_to_dict(self._sample_row())
        assert d["momentum_score"] == 78.5

    def test_no_high_52w(self):
        row = self._sample_row()
        row["high_52w"] = None
        row["low_52w"] = None
        d = _row_to_dict(row)
        assert d["pos_52w"]["pct_from_52w_high"] is None
        assert d["pos_52w"]["pct_from_52w_low"] is None

    def test_bb_squeeze_N(self):
        row = self._sample_row()
        row["bb_squeeze"] = "N"
        d = _row_to_dict(row)
        assert d["indicators"]["bb_squeeze"] is False

    def test_bb_squeeze_null(self):
        row = self._sample_row()
        row["bb_squeeze"] = None
        d = _row_to_dict(row)
        assert d["indicators"]["bb_squeeze"] is False


# ─── SQLite integration test ────────────────────────────────────────────────

@pytest.fixture
def in_memory_db():
    """In-memory SQLite with the minimum schema needed to run a TQL query."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE ticker_daily (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            series TEXT NOT NULL DEFAULT 'EQ',
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume INTEGER NOT NULL,
            rsi_14 REAL,
            macd REAL,
            macd_signal REAL,
            macd_histogram REAL,
            bb_middle REAL,
            bb_upper REAL,
            bb_lower REAL,
            bb_width REAL,
            bb_squeeze TEXT,
            atr_14 REAL,
            atr_percent REAL,
            vwma_20 REAL,
            hv_20 REAL,
            hv_60 REAL,
            sharpe_60 REAL,
            sharpe_126 REAL
        );

        CREATE TABLE ticker_scores (
            symbol TEXT PRIMARY KEY,
            return_1w REAL,
            return_1m REAL,
            return_3m REAL,
            return_6m REAL,
            return_1y REAL,
            momentum_score REAL,
            momentum_rank INTEGER,
            volume_ratio_20d REAL
        );

        CREATE TABLE stock_universe (
            symbol TEXT PRIMARY KEY,
            sector TEXT,
            industry TEXT,
            symbol_pe REAL,
            fair_value REAL,
            high_52w REAL,
            low_52w REAL
        );

        CREATE TABLE ticker_intraday (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            interval TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            rsi_14 REAL, macd REAL, atr_percent REAL
        );
    """)
    # Seed 3 symbols with daily history
    for sym, sector, rsi, pe in [
        ("HDFCBANK", "Banks", 70.0, 18.0),
        ("INFY",     "IT",    55.0, 25.0),
        ("TATAMOTORS", "Auto", 45.0, 12.0),
    ]:
        # 2 days of history
        for d, c, o in [("2025-06-03", 100.0, 99.0), ("2025-06-04", 105.0, 100.0)]:
            con.execute(
                "INSERT INTO ticker_daily (symbol, date, open, high, low, close, volume, rsi_14) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sym, d, o, c + 1, o - 1, c, 1_000_000, rsi),
            )
        con.execute(
            "INSERT INTO ticker_scores (symbol, return_1w, return_1m, momentum_score) "
            "VALUES (?, ?, ?, ?)",
            (sym, 5.0, 10.0, 75.0 if rsi > 60 else 45.0),
        )
        con.execute(
            "INSERT INTO stock_universe (symbol, sector, industry, symbol_pe, high_52w, low_52w) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sym, sector, sector + "-Industry", pe, 110.0, 90.0),
        )
    con.commit()
    return con


class TestSqliteIntegration:
    def test_basic_RSI_filter(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("app.services.screener.settings.db_path", ":memory:")
        # We can't easily redirect settings; use sqlite3 directly with the same query
        sql, binds = build_tql_query("RSI > 60", limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = [r["symbol"] for r in rows]
        assert "HDFCBANK" in symbols
        assert "INFY" not in symbols
        assert "TATAMOTORS" not in symbols

    def test_sector_filter(self, in_memory_db):
        sql, binds = build_tql_query('Sector = "Banks"', limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "HDFCBANK"

    def test_combined_AND(self, in_memory_db):
        sql, binds = build_tql_query('RSI > 60 AND Sector = "Banks"', limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "HDFCBANK"

    def test_bbsqueeze_no_match(self, in_memory_db):
        # No rows have bb_squeeze='Y' in our seed data
        sql, binds = build_tql_query("BBSqueeze", limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 0

    def test_in_clause(self, in_memory_db):
        sql, binds = build_tql_query('Sector IN ("Banks", "IT")', limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = {r["symbol"] for r in rows}
        assert symbols == {"HDFCBANK", "INFY"}

    def test_sort_desc(self, in_memory_db):
        sql, binds = build_tql_query('Sector IN ("Banks", "IT", "Auto")', sort_by="rsi", order="desc", limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = [r["symbol"] for r in rows]
        # HDFCBANK RSI=70, INFY=55, TATAMOTORS=45 → desc order
        assert symbols[0] == "HDFCBANK"
        assert symbols[-1] == "TATAMOTORS"

    def test_limit_respected(self, in_memory_db):
        sql, binds = build_tql_query('Sector IN ("Banks", "IT", "Auto")', limit=2)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 2

    def test_legacy_filter_equivalence(self, in_memory_db):
        # rsi_min=60 should match TQL "RSI > 60"
        sql, binds = build_legacy_query({"rsi_min": 60}, limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = {r["symbol"] for r in rows}
        assert "HDFCBANK" in symbols
        assert "INFY" not in symbols

    def test_legacy_pe_filter(self, in_memory_db):
        sql, binds = build_legacy_query({"pe_max": 20}, limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = {r["symbol"] for r in rows}
        # HDFCBANK pe=18, TATAMOTORS pe=12 → match; INFY pe=25 → no
        assert "HDFCBANK" in symbols
        assert "TATAMOTORS" in symbols
        assert "INFY" not in symbols

    def test_legacy_above_sma50(self, in_memory_db):
        # bb_middle was not seeded → all rows excluded (close > NULL is NULL → fails WHERE)
        sql, binds = build_legacy_query({"above_sma50": True}, limit=50)
        cur = in_memory_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 0


# ─── Phase B: snapshot-backed query tests ───────────────────────────────────

_SNAPSHOT_SCHEMA = """
    CREATE TABLE ticker_screener_snapshot (
        symbol TEXT PRIMARY KEY,
        last_date TEXT NOT NULL,
        compute_date TEXT NOT NULL,
        computed_at TEXT NOT NULL,
        last_close REAL NOT NULL,
        last_volume INTEGER NOT NULL,
        last_open REAL NOT NULL,
        last_high REAL NOT NULL,
        last_low REAL NOT NULL,
        rsi_1d REAL, macd_1d REAL, macd_signal_1d REAL, macd_histogram_1d REAL,
        bb_middle_1d REAL, bb_upper_1d REAL, bb_lower_1d REAL, bb_width_1d REAL,
        bb_squeeze_1d TEXT, atr_1d REAL, atr_percent_1d REAL, vwma_20_1d REAL,
        hv_20 REAL, hv_60 REAL, sharpe_60 REAL, sharpe_126 REAL,
        high_52w REAL, low_52w REAL,
        pct_from_52w_high REAL, pct_from_52w_low REAL,
        sector TEXT, industry TEXT, pe REAL, market_cap REAL, fair_value REAL,
        intraday_close_1h REAL, rsi_1h REAL, macd_1h REAL, macd_signal_1h REAL,
        macd_histogram_1h REAL, bb_middle_1h REAL, bb_upper_1h REAL, bb_lower_1h REAL,
        bb_width_1h REAL, bb_squeeze_1h TEXT, atr_1h REAL, atr_percent_1h REAL,
        vwma_20_1h REAL, hv_20_1h REAL, hv_60_1h REAL, sharpe_60_1h REAL, sharpe_126_1h REAL,
        intraday_close_W REAL, rsi_W REAL, macd_W REAL, macd_signal_W REAL,
        macd_histogram_W REAL, bb_middle_W REAL, bb_upper_W REAL, bb_lower_W REAL,
        bb_width_W REAL, bb_squeeze_W TEXT, atr_W REAL, atr_percent_W REAL,
        vwma_20_W REAL, hv_20_W REAL, hv_60_W REAL, sharpe_60_W REAL, sharpe_126_W REAL,
        intraday_close_M REAL, rsi_M REAL, macd_M REAL, macd_signal_M REAL,
        macd_histogram_M REAL, bb_middle_M REAL, bb_upper_M REAL, bb_lower_M REAL,
        bb_width_M REAL, bb_squeeze_M TEXT, atr_M REAL, atr_percent_M REAL,
        vwma_20_M REAL, hv_20_M REAL, hv_60_M REAL, sharpe_60_M REAL, sharpe_126_M REAL
    );
"""


@pytest.fixture
def snapshot_db():
    """In-memory SQLite with ticker_screener_snapshot + ticker_scores seeded."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(_SNAPSHOT_SCHEMA + """
        CREATE TABLE ticker_scores (
            symbol TEXT PRIMARY KEY,
            return_1w REAL, return_1m REAL, return_3m REAL,
            return_6m REAL, return_1y REAL,
            momentum_score REAL, momentum_rank INTEGER, volume_ratio_20d REAL
        );
    """)
    # 3 symbols: HDFCBANK high RSI, INFY mid, TATAMOTORS low
    snapshot_rows = [
        # HDFCBANK: sector=Banks, pe=18, RSI=70, near 52w high
        ("HDFCBANK", 105.0, 100.0, 110.0, 90.0, 70.0, "Banks", "Banking", 18.0,
         1.05, 90.0, "Y", 80.0),
        # INFY: sector=IT, pe=25, RSI=55
        ("INFY", 105.0, 100.0, 110.0, 90.0, 55.0, "IT", "Software", 25.0,
         1.0, 50.0, None, 60.0),
        # TATAMOTORS: sector=Auto, pe=12, RSI=45, near 52w low
        ("TATAMOTORS", 95.0, 100.0, 110.0, 90.0, 45.0, "Auto", "Auto", 12.0,
         0.9, 0.0, "N", 30.0),
    ]
    for sym, last_close, last_open, high_52w, low_52w, rsi, sector, industry, pe, \
        ratio, pct_hi, bb, mom in snapshot_rows:
        last_date = "2025-06-04"
        pct_lo = round(((last_close - low_52w) / low_52w) * 100, 2)
        pct_hi_r = round(((last_close - high_52w) / high_52w) * 100, 2)
        con.execute(
            """
            INSERT INTO ticker_screener_snapshot (
                symbol, last_date, compute_date, computed_at,
                last_close, last_volume, last_open, last_high, last_low,
                rsi_1d, bb_squeeze_1d,
                high_52w, low_52w, pct_from_52w_high, pct_from_52w_low,
                sector, industry, pe
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sym, last_date, last_date, "2025-06-04 10:00:00",
             last_close, 1_000_000, last_open, last_close + 1, last_close - 1,
             rsi, bb, high_52w, low_52w, pct_hi_r, pct_lo,
             sector, industry, pe),
        )
        con.execute(
            "INSERT INTO ticker_scores (symbol, return_1w, return_1m, momentum_score, volume_ratio_20d) "
            "VALUES (?, ?, ?, ?, ?)",
            (sym, 5.0, 10.0, mom, ratio),
        )
    con.commit()
    return con


class TestSnapshotQuery:
    """Phase B: read directly from ticker_screener_snapshot."""

    def test_snapshot_query_shape(self, snapshot_db):
        sql, binds = build_snapshot_tql_query("RSI > 60", limit=10)
        assert "ticker_screener_snapshot" in sql
        assert "ticker_scores" in sql
        assert "WITH td_latest" not in sql  # no CTE
        assert "LEFT JOIN LATERAL" not in sql  # no lateral joins

    def test_snapshot_RSI_filter(self, snapshot_db):
        sql, binds = build_snapshot_tql_query("RSI > 60", limit=50)
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = {r["symbol"] for r in rows}
        assert "HDFCBANK" in symbols
        assert "INFY" not in symbols
        assert "TATAMOTORS" not in symbols

    def test_snapshot_sector_filter(self, snapshot_db):
        sql, binds = build_snapshot_tql_query('Sector = "Banks"', limit=50)
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "HDFCBANK"

    def test_snapshot_interval_1h_no_lateral(self, snapshot_db):
        # Even with 1h:RSI, no lateral join needed (snapshot has it inline)
        sql, binds = build_snapshot_tql_query("1h:RSI > 60", limit=50)
        assert "LEFT JOIN LATERAL" not in sql
        cur = snapshot_db.execute(sql, binds)
        # rsi_1h not seeded in this fixture → no rows match
        rows = cur.fetchall()
        assert len(rows) == 0

    def test_snapshot_pct_from_52w_low_filter(self, snapshot_db):
        sql, binds = build_snapshot_tql_query("From52wLow > 10", limit=50)
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        # HDFCBANK pct_lo=16.67, INFY=16.67, TATAMOTORS=5.56 → 2 match
        assert len(rows) == 2

    def test_snapshot_legacy_pe_filter(self, snapshot_db):
        sql, binds = build_snapshot_legacy_query({"pe_max": 20}, limit=50)
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        symbols = {r["symbol"] for r in rows}
        assert "HDFCBANK" in symbols
        assert "TATAMOTORS" in symbols
        assert "INFY" not in symbols

    def test_snapshot_legacy_bb_squeeze(self, snapshot_db):
        # Only HDFCBANK has bb_squeeze_1d='Y'
        sql, binds = build_snapshot_legacy_query({"bb_squeeze": True}, limit=50)
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "HDFCBANK"

    def test_snapshot_legacy_above_sma50(self, snapshot_db):
        # bb_middle_1d is NULL for all rows in this fixture
        sql, binds = build_snapshot_legacy_query({"above_sma50": True}, limit=50)
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        assert len(rows) == 0

    def test_snapshot_sort_desc(self, snapshot_db):
        sql, binds = build_snapshot_tql_query(
            "RSI > 0", sort_by="rsi", order="desc", limit=50
        )
        cur = snapshot_db.execute(sql, binds)
        rows = cur.fetchall()
        # Sorted by RSI desc: HDFCBANK(70) → INFY(55) → TATAMOTORS(45)
        assert [r["symbol"] for r in rows] == ["HDFCBANK", "INFY", "TATAMOTORS"]

    def test_snapshot_row_shape_matches_legacy(self, snapshot_db):
        """_row_to_dict works on snapshot rows (no CTE-specific columns)."""
        sql, binds = build_snapshot_tql_query("RSI > 60", limit=10)
        cur = snapshot_db.execute(sql, binds)
        row = dict(cur.fetchone())
        result = _row_to_dict(row)
        # Same shape as the CTE variant
        for k in ("symbol", "close", "change_today", "returns", "pos_52w",
                  "indicators", "indicators_by_interval", "sector", "industry",
                  "pe", "momentum_score"):
            assert k in result, f"missing {k}"
        assert result["symbol"] == "HDFCBANK"
        assert result["sector"] == "Banks"
        assert result["pe"] == 18.0
        assert result["indicators"]["rsi_14"] == 70.0

"""Screener service — TQL and legacy filter → SQL → results.

This module is now a thin orchestration layer over ``tql_to_sql.py``. It
parses the input (TQL string or legacy filter dict), dispatches to the
appropriate SQL builder, executes against the SQLite warehouse, and
rehydrates rows into the result dict shape that the API, AI tool, and
MCP tool all expect.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from app.services.tql_to_sql import (
    _row_to_dict,
    build_legacy_query,
    build_snapshot_legacy_query,
    build_snapshot_tql_query,
    build_tql_query,
)
from app.services.tql_parser import TQLSyntaxError
from app.config import settings


# ─── SQL execution helpers ───────────────────────────────────────────────────

def _execute_sql(sql: str, binds: list) -> list[dict]:
    """Execute a parameterised SQL statement and return hydrated result dicts.

    Uses a sync sqlite3 connection (same DB as SQLAlchemy uses for ``_SyncSessionLocal``)
    so the entire WHERE-clause evaluation happens in SQLite, not Python.
    """
    with sqlite3.connect(settings.db_path, timeout=60) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute(sql, binds)
        rows = cur.fetchall()

    return [_row_to_dict(dict(r)) for r in rows]


def _execute_tql_count(sql_no_limit: str, binds: list) -> int:
    """Count query for the same TQL — replaces LIMIT with COUNT(*).

    Used to report ``count`` (total matching) separately from ``returned``
    (the page). The COUNT re-uses the same CTE + WHERE.
    """
    # Strip the trailing "LIMIT ?" to get the full filtered set
    sql_count = sql_no_limit.rsplit("LIMIT", 1)[0]
    # Add a derived wrapper to count rows
    sql_count = f"SELECT COUNT(*) AS n FROM ({sql_count})"
    with sqlite3.connect(settings.db_path, timeout=60) as con:
        row = con.execute(sql_count, binds).fetchone()
    return int(row[0])


# ─── Phase B: snapshot availability cache ────────────────────────────────────
# ticker_screener_snapshot is populated nightly by _ticker_scores_sync().
# We auto-prefer the snapshot-backed query when it has rows; otherwise fall
# back to the CTE-based query (which is also fast, just less optimized).
import time as _time
_snapshot_check_ttl_s = 30.0
_snapshot_check_last_ts = 0.0
_snapshot_check_last_val = False


def _snapshot_has_rows() -> bool:
    """Return True iff ticker_screener_snapshot has at least one row.

    Cached for ``_snapshot_check_ttl_s`` seconds to avoid hammering the DB.
    """
    global _snapshot_check_last_ts, _snapshot_check_last_val
    now = _time.time()
    if now - _snapshot_check_last_ts < _snapshot_check_ttl_s:
        return _snapshot_check_last_val
    try:
        with sqlite3.connect(settings.db_path, timeout=10) as con:
            row = con.execute("SELECT COUNT(*) FROM ticker_screener_snapshot").fetchone()
            has = int(row[0]) > 0
    except Exception:
        has = False
    _snapshot_check_last_ts = now
    _snapshot_check_last_val = has
    return has


def invalidate_snapshot_check_cache() -> None:
    """Reset the snapshot-availability cache (e.g. after a fresh sync)."""
    global _snapshot_check_last_ts, _snapshot_check_last_val
    _snapshot_check_last_ts = 0.0
    _snapshot_check_last_val = False


# ─── Public entry points ─────────────────────────────────────────────────────

def run_screener_tql(
    tql: str,
    default_interval: str = "1d",
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
    use_cache: bool = True,  # kept for API compatibility, ignored (SQL is the cache)
) -> dict:
    """Run screener using a TQL (Ticker Query Language) query string.

    Translates the TQL AST into a single parameterised SQL statement,
    executes it, and rehydrates the result rows.

    Args:
        tql: TQL query e.g. ``RSI > 60 AND Sector = "Banks"``
        default_interval: Interval used for un-prefixed indicator fields (1d / 1h / W / M)
        sort_by: Field to sort by
        order: asc or desc
        limit: Max results

    Returns:
        Dict with count, returned, filters_applied, results.
    """
    try:
        if _snapshot_has_rows():
            sql, binds = build_snapshot_tql_query(tql, default_interval, sort_by, order, limit)
        else:
            sql, binds = build_tql_query(tql, default_interval, sort_by, order, limit)
    except TQLSyntaxError as e:
        raise ValueError(f"TQL syntax error: {e}") from e

    count = _execute_tql_count(sql, binds)
    rows = _execute_sql(sql, binds)

    return {
        "count": count,
        "returned": len(rows),
        "filters_applied": [f"tql:{tql[:60]}"],
        "results": rows,
    }


def run_screener(
    filters: Optional[dict] = None,
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
    use_cache: bool = True,  # ignored
) -> dict:
    """Run screener with legacy filter dict.

    Translates each key in ``filters`` to a SQL WHERE fragment and executes.
    Output shape matches the TQL path.
    """
    if filters is None:
        filters = {}
    if _snapshot_has_rows():
        sql, binds = build_snapshot_legacy_query(filters, sort_by, order, limit)
    else:
        sql, binds = build_legacy_query(filters, sort_by, order, limit)
    count = _execute_tql_count(sql, binds)
    rows = _execute_sql(sql, binds)
    return {
        "count": count,
        "returned": len(rows),
        "filters_applied": list(filters.keys()),
        "results": rows,
    }


def get_screener_sectors(use_cache: bool = True) -> list[str]:
    """Return sorted list of distinct sector values from the snapshot (or stock_universe).

    Phase B: prefer ticker_screener_snapshot since it's pre-computed. Falls
    back to stock_universe if the snapshot hasn't been built yet.
    """
    table = "ticker_screener_snapshot" if _snapshot_has_rows() else "stock_universe"
    with sqlite3.connect(settings.db_path, timeout=60) as con:
        rows = con.execute(
            f"SELECT DISTINCT sector FROM {table} "
            "WHERE sector IS NOT NULL AND sector != '' ORDER BY sector"
        ).fetchall()
    return [r[0] for r in rows]

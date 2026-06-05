"""TQL → SQL transpiler.

Converts a Ticker Query Language AST (parsed by ``tql_parser.py``) into a single
parameterised SQL statement that runs against the ticker warehouse tables.
This eliminates the N+1 pattern of the legacy in-memory screener and reduces
a typical 30+ second query to <100ms.

Two output modes
----------------
1. ``build_tql_query(tql, default_interval, sort_by, order, limit)`` — TQL
   AST → SQL. Operates on a single denormalised view built from
   ``ticker_daily`` (latest candle per symbol) joined to ``ticker_scores``,
   ``ticker_intraday`` (latest 1h/W/M per symbol), and ``stock_universe``.

2. ``build_legacy_query(filters, sort_by, order, limit)`` — translate the
   legacy dict-of-filters form (e.g. ``{"rsi_min": 60}``) into the same SQL.

Both produce the same row shape so the response can be sorted/paginated
identically.

Field source map
----------------
A TQL field name is resolved to a (table, column) pair.  Indicator fields
may carry an interval prefix (``1h:RSI``, ``W:ATR``) — the transpiler
inserts the right lateral join when an interval other than ``1d`` is needed.
"""

from __future__ import annotations

import functools
from typing import Any, Optional

from app.services.tql_parser import (
    AndNode,
    CompareNode,
    InNode,
    NotNode,
    OrNode,
    parse_tql,
)


# ─── Field → SQL column map ───────────────────────────────────────────────────
#
# Lowercased TQL field name → (sql_column, is_numeric)
# - Indicator fields are looked up dynamically by interval.
# - "return" fields come from ticker_scores.
# - "pos52w" / "pe" / "sector" / "industry" / "fair_value" come from
#   stock_universe.
# - "top" fields come from ticker_daily (latest per symbol).

VALID_INTERVALS = {"1d", "1h", "w", "m"}
INTERVAL_NORMALIZE = {"W": "w", "M": "m", "1d": "1d", "1h": "1h"}


def _norm_interval(iv: str) -> str:
    return INTERVAL_NORMALIZE.get(iv, iv.lower())


# Indicator columns live in ticker_daily for 1d and ticker_intraday for 1h/W/M
_INDICATOR_COLUMNS = {
    "rsi":         "rsi_14",
    "atr":         "atr_percent",
    "macd":        "macd",
    "macdsignal":  "macd_signal",
    "macdhist":    "macd_histogram",
    "bbwidth":     "bb_width",
    "bbsqueeze":   "bb_squeeze",   # Y/N
    "hv20":        "hv_20",
    "hv60":        "hv_60",
    "sharpe60":    "sharpe_60",
    "sharpe126":   "sharpe_126",
}


# Snapshot column bases: maps the ticker_daily/intraday column name to the
# base name used in ticker_screener_snapshot. The snapshot has columns like
# ``rsi_1d``, ``rsi_1h``, ``rsi_W``, ``rsi_M`` (no trailing ``_14``), so we
# need an explicit table-driven mapping rather than a string-suffix strip.
# Any indicator added to _INDICATOR_COLUMNS must also appear here.
_SNAPSHOT_INDICATOR_BASES: dict[str, str] = {
    "rsi_14":         "rsi",
    "atr_percent":    "atr_percent",
    "macd":           "macd",
    "macd_signal":    "macd_signal",
    "macd_histogram": "macd_histogram",
    "bb_middle":      "bb_middle",
    "bb_upper":       "bb_upper",
    "bb_lower":       "bb_lower",
    "bb_width":       "bb_width",
    "bb_squeeze":     "bb_squeeze",
    "atr_14":         "atr",
    "vwma_20":        "vwma_20",
    "hv_20":          "hv_20",
    "hv_60":          "hv_60",
    "sharpe_60":      "sharpe_60",
    "sharpe_126":     "sharpe_126",
}

# These four indicators are stored WITHOUT a ``_1d`` suffix in the snapshot
# (because they are only computed daily, not for 1h/W/M), but WITH the
# ``_1h`` / ``_W`` / ``_M`` suffix for the other intervals. Asymmetric
# schema — special-case the 1d lookup so we use the bare column name.
_SNAPSHOT_BARE_FOR_1D: frozenset[str] = frozenset(
    {"hv_20", "hv_60", "sharpe_60", "sharpe_126"}
)


def _field_sql_name(field: str) -> str:
    """Return SQL column name for a TQL field (no interval prefix)."""
    f = field.lower()
    if f in _INDICATOR_COLUMNS:
        return _INDICATOR_COLUMNS[f]
    return f


# Default column for an unprefixed field (when no interval is given)
_FALLBACK_COLUMN = {
    "change":       "change_today",
    "volume":       "volume_ratio_20d",   # from ticker_scores
    "close":        "close",
    "sector":       "sector",              # from stock_universe
    "industry":     "industry",            # from stock_universe
    "pe":           "symbol_pe",           # from stock_universe
    "momentumscore":"momentum_score",      # from ticker_scores
    "return1w":     "return_1w",           # from ticker_scores
    "return1m":     "return_1m",
    "return3m":     "return_3m",
    "return6m":     "return_6m",
    "return1y":     "return_1y",
    "from52whigh":  "from_52w_high",       # from ticker_screener_snapshot (Phase B)
    "from52wlow":   "from_52w_low",        # from ticker_screener_snapshot (Phase B)
    "symbol":       "symbol",
}


def _split_field(field: str) -> tuple[Optional[str], str]:
    """Split ``1h:RSI`` → (``1h``, ``RSI``); ``RSI`` → (None, ``RSI``)."""
    if ":" in field:
        iv, name = field.split(":", 1)
        if iv.lower() in VALID_INTERVALS or iv in ("W", "M", "1d", "1h"):
            return iv, name
    return None, field


# ─── WHERE fragment builder ───────────────────────────────────────────────────

_OPS_NUMERIC = {">", "<", ">=", "<=", "=", "==", "!="}
_OPS_STRING  = {"=", "==", "!="}


def _field_sql_expression(field: str, default_interval: str) -> tuple[str, set[str]]:
    """Return (sql_expr, set_of_intervals_needed_for_lateral_joins).

    The expression references a fully-qualified column. If the field needs a
    non-1d interval via a lateral join, the interval is added to the returned
    set so the caller can build the right JOIN clauses.
    """
    iv_prefix, name = _split_field(field)
    interval = _norm_interval(iv_prefix) if iv_prefix else _norm_interval(default_interval)
    name_lower = name.lower()

    if name_lower in _INDICATOR_COLUMNS:
        col = _INDICATOR_COLUMNS[name_lower]
        if interval == "1d":
            return f"td.{col}", set()
        # Need a lateral join for 1h/W/M
        return f"ti_{interval}.{col}", {interval}

    if name_lower in _FALLBACK_COLUMN:
        col = _FALLBACK_COLUMN[name_lower]
        # Where does this column live?
        if name_lower in {"change", "close"}:
            return f"td.{col}", set()
        if name_lower == "volume":
            return f"ts.{col}", set()
        if name_lower in {"sector", "industry", "pe"}:
            return f"su.{col if col != 'symbol_pe' else 'symbol_pe'}", set()
        if name_lower == "momentumscore":
            return f"ts.momentum_score", set()
        if name_lower.startswith("return"):
            return f"ts.{col}", set()
        if name_lower in {"from52whigh", "from52wlow"}:
            # snapshot columns (Phase B)
            return f"snap.{col}", set()
        if name_lower == "symbol":
            return "td.symbol", set()

    raise ValueError(f"Unknown TQL field: {field!r}")


def _literal_sql(value: Any) -> tuple[str, list[Any]]:
    """Convert a Python value into a SQL literal + bind list."""
    if isinstance(value, bool):
        return ("1" if value else "0"), []
    if isinstance(value, (int, float)):
        return "?", [value]
    if isinstance(value, str):
        return "?", [value]
    raise ValueError(f"Unsupported literal type: {type(value).__name__}")


def _node_to_where(node: Any, default_interval: str, intervals: set[str], binds: list[Any]) -> str:
    """Recursively render an AST node as a SQL WHERE fragment with ``?`` binds.

    Mutates ``intervals`` (adds lateral-join intervals) and ``binds`` (adds values).
    """
    if isinstance(node, AndNode):
        l = _node_to_where(node.left, default_interval, intervals, binds)
        r = _node_to_where(node.right, default_interval, intervals, binds)
        return f"({l} AND {r})"

    if isinstance(node, OrNode):
        l = _node_to_where(node.left, default_interval, intervals, binds)
        r = _node_to_where(node.right, default_interval, intervals, binds)
        return f"({l} OR {r})"

    if isinstance(node, NotNode):
        return f"(NOT {_node_to_where(node.expr, default_interval, intervals, binds)})"

    if isinstance(node, CompareNode):
        # Bare-boolean shorthand: BBSqueeze alone is treated as ``BBSqueeze = 1``.
        # We expand it to (bbsqueeze IS NOT NULL AND bbsqueeze = 'Y') so that
        # NOT BBSqueeze correctly matches both NULL and explicit 'N'.
        if node.field.lower() == "bbsqueeze" and node.op == "=":
            sql, ints = _field_sql_expression(node.field, default_interval)
            intervals.update(ints)
            if node.value is True:
                return f"({sql} IS NOT NULL AND {sql} = 'Y')"
            if node.value is False:
                return f"({sql} IS NULL OR {sql} != 'Y')"
        sql, ints = _field_sql_expression(node.field, default_interval)
        intervals.update(ints)
        lit, vals = _literal_sql(node.value)
        binds.extend(vals)
        return f"({sql} {node.op} {lit})"

    if isinstance(node, InNode):
        sql, ints = _field_sql_expression(node.field, default_interval)
        intervals.update(ints)
        parts: list[str] = []
        for v in node.values:
            lit, vals = _literal_sql(v)
            binds.extend(vals)
            parts.append(lit)
        return f"({sql} IN ({', '.join(parts)}))"

    raise ValueError(f"Unknown AST node: {type(node).__name__}")


# ─── Order/sort helpers ───────────────────────────────────────────────────────

# Whitelist of sortable fields mapped to a SQL expression.
_SORT_FIELD_SQL: dict[str, str] = {
    "symbol":            "td.symbol",
    "close":             "td.close",
    "change_today":      "td.change_today",
    "pct_change_1w":     "ts.return_1w",
    "pct_change_1m":     "ts.return_1m",
    "pct_change_3m":     "ts.return_3m",
    "pct_change_6m":     "ts.return_6m",
    "pct_change_1y":     "ts.return_1y",
    "volume_ratio":      "ts.volume_ratio_20d",
    "pct_from_52w_high": "snap.from_52w_high",
    "pct_from_52w_low":  "snap.from_52w_low",
    "atr_percent":       "td.atr_percent",
    "rsi":               "td.rsi_14",
    "momentum_score":    "ts.momentum_score",
}


def _sort_sql(sort_by: str, order: str) -> str:
    expr = _SORT_FIELD_SQL.get(sort_by, "td.symbol")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    return f"{expr} {direction} NULLS LAST, td.symbol ASC"


# ─── Top-level builders ───────────────────────────────────────────────────────

_BASE_CTE = """
WITH td_latest AS (
    SELECT
        symbol,
        date,
        open,
        high,
        low,
        close,
        volume,
        rsi_14,
        macd,
        macd_signal,
        macd_histogram,
        bb_middle,
        bb_upper,
        bb_lower,
        bb_width,
        bb_squeeze,
        atr_14,
        atr_percent,
        vwma_20,
        hv_20,
        hv_60,
        sharpe_60,
        sharpe_126,
        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
    FROM ticker_daily
),
td AS (SELECT * FROM td_latest WHERE rn = 1)
"""


def _lateral_joins(intervals: set[str]) -> str:
    """Build LEFT JOIN LATERAL for each non-1d interval needed by the WHERE."""
    parts: list[str] = []
    for iv in sorted(intervals):
        if iv == "1d":
            continue
        parts.append(f"""
LEFT JOIN LATERAL (
    SELECT rsi_14, macd, macd_signal, macd_histogram, bb_middle, bb_upper, bb_lower,
           bb_width, bb_squeeze, atr_14, atr_percent, vwma_20, hv_20, hv_60,
           sharpe_60, sharpe_126
    FROM ticker_intraday
    WHERE ticker_intraday.symbol = td.symbol
      AND ticker_intraday.interval = '{iv}'
    ORDER BY timestamp DESC
    LIMIT 1
) AS ti_{iv} ON 1=1""")
    return "\n".join(parts)


def _hashable_filters(filters: dict) -> tuple[tuple[str, Any], ...]:
    """Convert a legacy-filter dict to a hashable key for lru_cache.

    Items are sorted by key so that ``{"a": 1, "b": 2}`` and
    ``{"b": 2, "a": 1}`` produce the same cache key.
    """
    return tuple(sorted(filters.items()))


def build_tql_query(
    tql: str,
    default_interval: str = "1d",
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
) -> tuple[str, list[Any]]:
    """Parse a TQL string and return (sql, bind_values).

    The SQL is a single CTE-based statement that runs in O(1) queries
    against ticker_daily, ticker_intraday (lateral), ticker_scores,
    stock_universe, and ticker_screener_snapshot (Phase B).

    Cached via ``functools.lru_cache(maxsize=256)`` (on the private
    ``_build_tql_query_cached`` helper) — the (sql, binds) tuple is a
    deterministic function of these args, and the typical screener request
    flow issues the same TQL with the same sort/limit repeatedly.
    """
    return _build_tql_query_cached(tql, default_interval, sort_by, order, limit)


@functools.lru_cache(maxsize=256)
def _build_tql_query_cached(
    tql: str,
    default_interval: str,
    sort_by: str,
    order: str,
    limit: int,
) -> tuple[str, list[Any]]:
    ast = parse_tql(tql)
    intervals: set[str] = set()
    binds: list[Any] = []
    where = _node_to_where(ast, default_interval, intervals, binds)

    lateral = _lateral_joins(intervals)
    sort_expr = _sort_sql(sort_by, order)

    # change_today = (close - open) / open * 100, computed inline
    sql = f"""
{_BASE_CTE}
SELECT
    td.symbol,
    td.date,
    td.open,
    td.close,
    ROUND((td.close - td.open) / NULLIF(td.open, 0) * 100, 2) AS change_today,
    ts.return_1w, ts.return_1m, ts.return_3m, ts.return_6m, ts.return_1y,
    ts.momentum_score, ts.momentum_rank, ts.volume_ratio_20d,
    td.rsi_14, td.atr_percent, td.macd, td.macd_signal,
    td.macd_histogram, td.bb_middle, td.bb_upper, td.bb_lower,
    td.bb_width, td.bb_squeeze, td.atr_14, td.vwma_20,
    td.hv_20, td.hv_60, td.sharpe_60, td.sharpe_126,
    su.sector, su.industry, su.symbol_pe AS pe, su.fair_value,
    su.high_52w, su.low_52w
FROM td
INNER JOIN ticker_scores ts ON ts.symbol = td.symbol
LEFT JOIN stock_universe su ON su.symbol = td.symbol
{lateral}
WHERE {where}
ORDER BY {sort_expr}
LIMIT ?
"""
    binds.append(limit)
    return sql, binds


# ─── Phase B: snapshot-based builders ──────────────────────────────────────────
#
# When ticker_screener_snapshot is populated, TQL/legacy queries can read
# from a single small denormalized table instead of joining 4 tables +
# lateral subqueries.  The result row shape is identical to build_tql_query
# so callers don't need to change.
#
# Snapshot columns are aliased to match the CTE query's row shape:
#   snap.last_close AS close, snap.rsi_1d AS rsi_14, etc.

# Map snapshot column name → alias used in result row (must match CTE variant)
_SNAP_ALIASES = {
    "last_date": "date",
    "last_open": "open",
    "last_close": "close",
    "rsi_1d": "rsi_14",
    "atr_percent_1d": "atr_percent",
    "macd_1d": "macd",
    "macd_signal_1d": "macd_signal",
    "macd_histogram_1d": "macd_histogram",
    "bb_middle_1d": "bb_middle",
    "bb_upper_1d": "bb_upper",
    "bb_lower_1d": "bb_lower",
    "bb_width_1d": "bb_width",
    "bb_squeeze_1d": "bb_squeeze",
    "atr_1d": "atr_14",
    "vwma_20_1d": "vwma_20",
    "pct_from_52w_high": "from_52w_high",
    "pct_from_52w_low": "from_52w_low",
}


def _snapshot_select_clause() -> str:
    """Build the SELECT clause for a snapshot-based query.

    Aliases snapshot columns to match the CTE-based query's row shape so
    ``_row_to_dict`` works unchanged.
    """
    return """
    snap.symbol,
    snap.last_date AS date,
    snap.last_open AS open,
    snap.last_close AS close,
    ROUND((snap.last_close - snap.last_open) / NULLIF(snap.last_open, 0) * 100, 2) AS change_today,
    ts.return_1w, ts.return_1m, ts.return_3m, ts.return_6m, ts.return_1y,
    ts.momentum_score, ts.momentum_rank, ts.volume_ratio_20d,
    snap.rsi_1d AS rsi_14, snap.atr_percent_1d AS atr_percent,
    snap.macd_1d AS macd, snap.macd_signal_1d AS macd_signal,
    snap.macd_histogram_1d AS macd_histogram,
    snap.bb_middle_1d AS bb_middle, snap.bb_upper_1d AS bb_upper,
    snap.bb_lower_1d AS bb_lower, snap.bb_width_1d AS bb_width,
    snap.bb_squeeze_1d AS bb_squeeze, snap.atr_1d AS atr_14,
    snap.vwma_20_1d AS vwma_20,
    snap.hv_20, snap.hv_60, snap.sharpe_60, snap.sharpe_126,
    snap.sector, snap.industry, snap.pe, snap.fair_value,
    snap.high_52w, snap.low_52w,
    snap.pct_from_52w_high AS from_52w_high,
    snap.pct_from_52w_low AS from_52w_low
"""


def _snapshot_field_sql_expression(field: str, default_interval: str) -> tuple[str, set[str]]:
    """Like _field_sql_expression, but reads from `snap` (and interval columns).

    For 1h/W/M indicator fields, the snapshot already has them inline as
    ``rsi_1h``, ``rsi_W``, etc. — no lateral join needed.
    """
    iv_prefix, name = _split_field(field)
    interval = _norm_interval(iv_prefix) if iv_prefix else _norm_interval(default_interval)
    name_lower = name.lower()

    if name_lower in _INDICATOR_COLUMNS:
        col = _INDICATOR_COLUMNS[name_lower]
        # snapshot column names are {rsi, atr, macd, ...}_{1d, 1h, W, M}.
        # _INDICATOR_COLUMNS maps TQL name → ticker_daily/intraday column name
        # (e.g. "rsi" → "rsi_14").  Use the explicit _SNAPSHOT_INDICATOR_BASES
        # map to find the snapshot base; assert it exists so a future indicator
        # with an unfamiliar column name fails loud at parse time, not at SQL
        # execution.
        short = _SNAPSHOT_INDICATOR_BASES.get(col)
        if short is None:
            raise ValueError(
                f"Snapshot base unknown for indicator column {col!r} "
                f"(TQL field {field!r}). Add an entry to _SNAPSHOT_INDICATOR_BASES."
            )
        if interval == "1d":
            # hv_20 / hv_60 / sharpe_60 / sharpe_126 live at the bare column
            # in the snapshot (no _1d suffix). Everything else is _1d.
            if col in _SNAPSHOT_BARE_FOR_1D:
                return f"snap.{short}", set()
            return f"snap.{short}_1d", set()
        if interval == "1h":
            return f"snap.{short}_1h", set()
        if interval == "w":
            return f"snap.{short}_W", set()
        if interval == "m":
            return f"snap.{short}_M", set()
        raise ValueError(f"Unknown interval: {interval!r}")

    if name_lower in _FALLBACK_COLUMN:
        col = _FALLBACK_COLUMN[name_lower]
        if name_lower in {"change", "close"}:
            return "snap.last_close", set()  # change_today is computed in SELECT
        if name_lower == "volume":
            return "ts.volume_ratio_20d", set()
        if name_lower in {"sector", "industry"}:
            return f"snap.{col}", set()
        if name_lower == "pe":
            return "snap.pe", set()
        if name_lower == "momentumscore":
            return "ts.momentum_score", set()
        if name_lower.startswith("return"):
            return f"ts.{col}", set()
        if name_lower in {"from52whigh", "from52wlow"}:
            return f"snap.pct_{col}", set()
        if name_lower == "symbol":
            return "snap.symbol", set()

    raise ValueError(f"Unknown TQL field: {field!r}")


def _snapshot_node_to_where(
    node: Any, default_interval: str, intervals: set[str], binds: list[Any]
) -> str:
    """Recursive AST → SQL for snapshot-based queries.  Mirrors _node_to_where."""
    if isinstance(node, AndNode):
        l = _snapshot_node_to_where(node.left, default_interval, intervals, binds)
        r = _snapshot_node_to_where(node.right, default_interval, intervals, binds)
        return f"({l} AND {r})"

    if isinstance(node, OrNode):
        l = _snapshot_node_to_where(node.left, default_interval, intervals, binds)
        r = _snapshot_node_to_where(node.right, default_interval, intervals, binds)
        return f"({l} OR {r})"

    if isinstance(node, NotNode):
        return f"(NOT {_snapshot_node_to_where(node.expr, default_interval, intervals, binds)})"

    if isinstance(node, CompareNode):
        if node.field.lower() == "bbsqueeze" and node.op == "=":
            sql, ints = _snapshot_field_sql_expression(node.field, default_interval)
            intervals.update(ints)
            if node.value is True:
                return f"({sql} IS NOT NULL AND {sql} = 'Y')"
            if node.value is False:
                return f"({sql} IS NULL OR {sql} != 'Y')"
        sql, ints = _snapshot_field_sql_expression(node.field, default_interval)
        intervals.update(ints)
        lit, vals = _literal_sql(node.value)
        binds.extend(vals)
        return f"({sql} {node.op} {lit})"

    if isinstance(node, InNode):
        sql, ints = _snapshot_field_sql_expression(node.field, default_interval)
        intervals.update(ints)
        parts: list[str] = []
        for v in node.values:
            lit, vals = _literal_sql(v)
            binds.extend(vals)
            parts.append(lit)
        return f"({sql} IN ({', '.join(parts)}))"

    raise ValueError(f"Unknown AST node: {type(node).__name__}")


def _snapshot_sort_sql(sort_by: str, order: str) -> str:
    """Snapshot-aware sort: same field whitelist but read from snap instead of td."""
    snap_sort: dict[str, str] = {
        "symbol":            "snap.symbol",
        "close":             "snap.last_close",
        "change_today":      "change_today",  # alias in SELECT
        "pct_change_1w":     "ts.return_1w",
        "pct_change_1m":     "ts.return_1m",
        "pct_change_3m":     "ts.return_3m",
        "pct_change_6m":     "ts.return_6m",
        "pct_change_1y":     "ts.return_1y",
        "volume_ratio":      "ts.volume_ratio_20d",
        "pct_from_52w_high": "snap.pct_from_52w_high",
        "pct_from_52w_low":  "snap.pct_from_52w_low",
        "atr_percent":       "snap.atr_percent_1d",
        "rsi":               "snap.rsi_1d",
        "momentum_score":    "ts.momentum_score",
    }
    expr = snap_sort.get(sort_by, "snap.symbol")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    return f"{expr} {direction} NULLS LAST, snap.symbol ASC"


def build_snapshot_tql_query(
    tql: str,
    default_interval: str = "1d",
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
) -> tuple[str, list[Any]]:
    """Phase B: read directly from ticker_screener_snapshot.

    Cached via ``functools.lru_cache(maxsize=256)`` on
    ``_build_snapshot_tql_query_cached``.
    """
    return _build_snapshot_tql_query_cached(tql, default_interval, sort_by, order, limit)


@functools.lru_cache(maxsize=256)
def _build_snapshot_tql_query_cached(
    tql: str,
    default_interval: str,
    sort_by: str,
    order: str,
    limit: int,
) -> tuple[str, list[Any]]:
    """Phase B: read directly from ticker_screener_snapshot.

    Faster than ``build_tql_query`` (no window functions, no lateral joins,
    no stock_universe JOIN) when the snapshot is populated.  Returns the
    same row shape so callers can use it as a drop-in replacement.
    """
    ast = parse_tql(tql)
    intervals: set[str] = set()
    binds: list[Any] = []
    where = _snapshot_node_to_where(ast, default_interval, intervals, binds)
    sort_expr = _snapshot_sort_sql(sort_by, order)
    select = _snapshot_select_clause()
    sql = f"""
SELECT
{select}
FROM ticker_screener_snapshot snap
INNER JOIN ticker_scores ts ON ts.symbol = snap.symbol
WHERE {where}
ORDER BY {sort_expr}
LIMIT ?
"""
    binds.append(limit)
    return sql, binds


def build_snapshot_legacy_query(
    filters: dict,
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
) -> tuple[str, list[Any]]:
    """Phase B: legacy-filter variant of build_snapshot_tql_query.

    Cached via ``functools.lru_cache(maxsize=256)`` on
    ``_build_snapshot_legacy_query_cached`` — the dict is hashed via
    ``_hashable_filters`` so the same filter dict (regardless of insertion
    order) produces the same cache key.
    """
    return _build_snapshot_legacy_query_cached(
        _hashable_filters(filters), sort_by, order, limit
    )


@functools.lru_cache(maxsize=256)
def _build_snapshot_legacy_query_cached(
    filters_hashable: tuple,
    sort_by: str,
    order: str,
    limit: int,
) -> tuple[str, list[Any]]:
    """Phase B: legacy-filter variant of build_snapshot_tql_query (cached)."""
    filters = dict(filters_hashable)
    where, binds = _legacy_where_snapshot(filters)
    sort_expr = _snapshot_sort_sql(sort_by, order)
    select = _snapshot_select_clause()
    sql = f"""
SELECT
{select}
FROM ticker_screener_snapshot snap
INNER JOIN ticker_scores ts ON ts.symbol = snap.symbol
WHERE {where}
ORDER BY {sort_expr}
LIMIT ?
"""
    binds.append(limit)
    return sql, binds


def _legacy_where_snapshot(filters: dict) -> tuple[str, list[Any]]:
    """Legacy filter → WHERE for snapshot-based queries.

    Same filters as ``_legacy_where`` but every column reference is rewritten
    to the snapshot alias (``snap.last_close`` instead of ``td.close``, etc.).
    """
    parts: list[str] = []
    binds: list[Any] = []

    if "pct_change_today_min" in filters:
        parts.append("(snap.last_close - snap.last_open) / NULLIF(snap.last_open, 0) * 100 >= ?")
        binds.append(filters["pct_change_today_min"])
    if "pct_change_today_max" in filters:
        parts.append("(snap.last_close - snap.last_open) / NULLIF(snap.last_open, 0) * 100 <= ?")
        binds.append(filters["pct_change_today_max"])
    if "pct_change_1w_min" in filters:
        parts.append("ts.return_1w >= ?"); binds.append(filters["pct_change_1w_min"])
    if "pct_change_1w_max" in filters:
        parts.append("ts.return_1w <= ?"); binds.append(filters["pct_change_1w_max"])
    if "pct_change_1m_min" in filters:
        parts.append("ts.return_1m >= ?"); binds.append(filters["pct_change_1m_min"])
    if "pct_change_1m_max" in filters:
        parts.append("ts.return_1m <= ?"); binds.append(filters["pct_change_1m_max"])
    if "pct_change_3m_min" in filters:
        parts.append("ts.return_3m >= ?"); binds.append(filters["pct_change_3m_min"])
    if "pct_change_3m_max" in filters:
        parts.append("ts.return_3m <= ?"); binds.append(filters["pct_change_3m_max"])
    if "pct_change_6m_min" in filters:
        parts.append("ts.return_6m >= ?"); binds.append(filters["pct_change_6m_min"])
    if "pct_change_6m_max" in filters:
        parts.append("ts.return_6m <= ?"); binds.append(filters["pct_change_6m_max"])
    if "pct_change_1y_min" in filters:
        parts.append("ts.return_1y >= ?"); binds.append(filters["pct_change_1y_min"])
    if "pct_change_1y_max" in filters:
        parts.append("ts.return_1y <= ?"); binds.append(filters["pct_change_1y_max"])
    if "volume_ratio_min" in filters:
        parts.append("ts.volume_ratio_20d >= ?"); binds.append(filters["volume_ratio_min"])
    if "volume_ratio_max" in filters:
        parts.append("ts.volume_ratio_20d <= ?"); binds.append(filters["volume_ratio_max"])
    if "pct_from_52w_high_max" in filters:
        parts.append("snap.pct_from_52w_high <= ?")
        binds.append(filters["pct_from_52w_high_max"])
    if "pct_from_52w_high_min" in filters:
        parts.append("snap.pct_from_52w_high >= ?")
        binds.append(filters["pct_from_52w_high_min"])
    if "pct_from_52w_low_min" in filters:
        parts.append("snap.pct_from_52w_low >= ?")
        binds.append(filters["pct_from_52w_low_min"])
    if "pct_from_52w_low_max" in filters:
        parts.append("snap.pct_from_52w_low <= ?")
        binds.append(filters["pct_from_52w_low_max"])
    if "is_52w_high" in filters:
        v = filters["is_52w_high"]
        if v:
            parts.append("snap.high_52w IS NOT NULL AND snap.pct_from_52w_high >= -0.5")
        else:
            parts.append("snap.high_52w IS NULL OR snap.pct_from_52w_high < -0.5")
    if "is_52w_low" in filters:
        v = filters["is_52w_low"]
        if v:
            parts.append("snap.low_52w IS NOT NULL AND snap.pct_from_52w_low <= 0.5")
        else:
            parts.append("snap.low_52w IS NULL OR snap.pct_from_52w_low > 0.5")
    if "atr_pct_max" in filters or "atr_pct_min" in filters:
        if "atr_pct_max" in filters:
            parts.append("snap.atr_percent_1d <= ?"); binds.append(filters["atr_pct_max"])
        if "atr_pct_min" in filters:
            parts.append("snap.atr_percent_1d >= ?"); binds.append(filters["atr_pct_min"])
    if "rsi_min" in filters:
        parts.append("snap.rsi_1d >= ?"); binds.append(filters["rsi_min"])
    if "rsi_max" in filters:
        parts.append("snap.rsi_1d <= ?"); binds.append(filters["rsi_max"])
    if "bb_squeeze" in filters:
        if filters["bb_squeeze"]:
            parts.append("snap.bb_squeeze_1d = 'Y'")
        else:
            parts.append("(snap.bb_squeeze_1d IS NULL OR snap.bb_squeeze_1d != 'Y')")
    if "pe_min" in filters:
        parts.append("snap.pe >= ?"); binds.append(filters["pe_min"])
    if "pe_max" in filters:
        parts.append("snap.pe <= ?"); binds.append(filters["pe_max"])
    if "sector" in filters:
        parts.append("LOWER(snap.sector) = LOWER(?)"); binds.append(filters["sector"])
    if "industry" in filters:
        parts.append("LOWER(snap.industry) LIKE LOWER(?)"); binds.append(f"%{filters['industry']}%")
    if "above_sma50" in filters:
        v = filters["above_sma50"]
        if v:
            parts.append("snap.last_close > snap.bb_middle_1d")
        else:
            parts.append("snap.last_close <= snap.bb_middle_1d")
    if "momentum_score_min" in filters:
        parts.append("ts.momentum_score >= ?"); binds.append(filters["momentum_score_min"])

    if not parts:
        return "1=1", []
    return " AND ".join(parts), binds


# ─── Legacy filter transpiler ─────────────────────────────────────────────────

# Map legacy filter key → (sql_expr, op, value) or special handlers.
def _legacy_where(filters: dict) -> tuple[str, list[Any]]:
    """Translate legacy filter dict to a WHERE fragment."""
    parts: list[str] = []
    binds: list[Any] = []

    if "pct_change_today_min" in filters:
        parts.append("(td.close - td.open) / NULLIF(td.open, 0) * 100 >= ?")
        binds.append(filters["pct_change_today_min"])
    if "pct_change_today_max" in filters:
        parts.append("(td.close - td.open) / NULLIF(td.open, 0) * 100 <= ?")
        binds.append(filters["pct_change_today_max"])
    if "pct_change_1w_min" in filters:
        parts.append("ts.return_1w >= ?"); binds.append(filters["pct_change_1w_min"])
    if "pct_change_1w_max" in filters:
        parts.append("ts.return_1w <= ?"); binds.append(filters["pct_change_1w_max"])
    if "pct_change_1m_min" in filters:
        parts.append("ts.return_1m >= ?"); binds.append(filters["pct_change_1m_min"])
    if "pct_change_1m_max" in filters:
        parts.append("ts.return_1m <= ?"); binds.append(filters["pct_change_1m_max"])
    if "pct_change_3m_min" in filters:
        parts.append("ts.return_3m >= ?"); binds.append(filters["pct_change_3m_min"])
    if "pct_change_3m_max" in filters:
        parts.append("ts.return_3m <= ?"); binds.append(filters["pct_change_3m_max"])
    if "pct_change_6m_min" in filters:
        parts.append("ts.return_6m >= ?"); binds.append(filters["pct_change_6m_min"])
    if "pct_change_6m_max" in filters:
        parts.append("ts.return_6m <= ?"); binds.append(filters["pct_change_6m_max"])
    if "pct_change_1y_min" in filters:
        parts.append("ts.return_1y >= ?"); binds.append(filters["pct_change_1y_min"])
    if "pct_change_1y_max" in filters:
        parts.append("ts.return_1y <= ?"); binds.append(filters["pct_change_1y_max"])
    if "volume_ratio_min" in filters:
        parts.append("ts.volume_ratio_20d >= ?"); binds.append(filters["volume_ratio_min"])
    if "volume_ratio_max" in filters:
        parts.append("ts.volume_ratio_20d <= ?"); binds.append(filters["volume_ratio_max"])
    if "pct_from_52w_high_max" in filters:
        # Approximate: derived from high_52w (stock_universe) + close
        parts.append("CASE WHEN su.high_52w IS NULL OR su.high_52w = 0 THEN NULL ELSE (td.close - su.high_52w) / su.high_52w * 100 END <= ?")
        binds.append(filters["pct_from_52w_high_max"])
    if "pct_from_52w_high_min" in filters:
        parts.append("CASE WHEN su.high_52w IS NULL OR su.high_52w = 0 THEN NULL ELSE (td.close - su.high_52w) / su.high_52w * 100 END >= ?")
        binds.append(filters["pct_from_52w_high_min"])
    if "pct_from_52w_low_min" in filters:
        parts.append("CASE WHEN su.low_52w IS NULL OR su.low_52w = 0 THEN NULL ELSE (td.close - su.low_52w) / su.low_52w * 100 END >= ?")
        binds.append(filters["pct_from_52w_low_min"])
    if "pct_from_52w_low_max" in filters:
        parts.append("CASE WHEN su.low_52w IS NULL OR su.low_52w = 0 THEN NULL ELSE (td.close - su.low_52w) / su.low_52w * 100 END <= ?")
        binds.append(filters["pct_from_52w_low_max"])
    if "is_52w_high" in filters:
        v = filters["is_52w_high"]
        if v:
            parts.append("su.high_52w IS NOT NULL AND ABS(td.close - su.high_52w) / NULLIF(su.high_52w, 0) < 0.005")
        else:
            parts.append("su.high_52w IS NULL OR ABS(td.close - su.high_52w) / NULLIF(su.high_52w, 0) >= 0.005")
    if "is_52w_low" in filters:
        v = filters["is_52w_low"]
        if v:
            parts.append("su.low_52w IS NOT NULL AND ABS(td.close - su.low_52w) / NULLIF(su.low_52w, 0) < 0.005")
        else:
            parts.append("su.low_52w IS NULL OR ABS(td.close - su.low_52w) / NULLIF(su.low_52w, 0) >= 0.005")
    if "atr_pct_max" in filters or "atr_pct_min" in filters:
        if "atr_pct_max" in filters:
            parts.append("td.atr_percent <= ?"); binds.append(filters["atr_pct_max"])
        if "atr_pct_min" in filters:
            parts.append("td.atr_percent >= ?"); binds.append(filters["atr_pct_min"])
    if "rsi_min" in filters:
        parts.append("td.rsi_14 >= ?"); binds.append(filters["rsi_min"])
    if "rsi_max" in filters:
        parts.append("td.rsi_14 <= ?"); binds.append(filters["rsi_max"])
    if "bb_squeeze" in filters:
        if filters["bb_squeeze"]:
            parts.append("td.bb_squeeze = 'Y'")
        else:
            parts.append("(td.bb_squeeze IS NULL OR td.bb_squeeze != 'Y')")
    if "pe_min" in filters:
        parts.append("su.symbol_pe >= ?"); binds.append(filters["pe_min"])
    if "pe_max" in filters:
        parts.append("su.symbol_pe <= ?"); binds.append(filters["pe_max"])
    if "sector" in filters:
        parts.append("LOWER(su.sector) = LOWER(?)"); binds.append(filters["sector"])
    if "industry" in filters:
        parts.append("LOWER(su.industry) LIKE LOWER(?)"); binds.append(f"%{filters['industry']}%")
    if "above_sma50" in filters:
        v = filters["above_sma50"]
        if v:
            parts.append("td.close > td.bb_middle")
        else:
            parts.append("td.close <= td.bb_middle")
    if "momentum_score_min" in filters:
        parts.append("ts.momentum_score >= ?"); binds.append(filters["momentum_score_min"])

    if not parts:
        return "1=1", []
    return " AND ".join(parts), binds


def build_legacy_query(
    filters: dict,
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
) -> tuple[str, list[Any]]:
    """Translate legacy filter dict to a parameterised SQL statement.

    Cached via ``functools.lru_cache(maxsize=256)`` on
    ``_build_legacy_query_cached`` — the dict is hashed via
    ``_hashable_filters`` so the same filter dict (regardless of insertion
    order) produces the same cache key.
    """
    return _build_legacy_query_cached(
        _hashable_filters(filters), sort_by, order, limit
    )


@functools.lru_cache(maxsize=256)
def _build_legacy_query_cached(
    filters_hashable: tuple,
    sort_by: str,
    order: str,
    limit: int,
) -> tuple[str, list[Any]]:
    """Translate legacy filter dict to a parameterised SQL statement (cached)."""
    filters = dict(filters_hashable)
    where, binds = _legacy_where(filters)
    sort_expr = _sort_sql(sort_by, order)
    sql = f"""
{_BASE_CTE}
SELECT
    td.symbol,
    td.date,
    td.open,
    td.close,
    ROUND((td.close - td.open) / NULLIF(td.open, 0) * 100, 2) AS change_today,
    ts.return_1w, ts.return_1m, ts.return_3m, ts.return_6m, ts.return_1y,
    ts.momentum_score, ts.momentum_rank, ts.volume_ratio_20d,
    td.rsi_14, td.atr_percent, td.macd, td.macd_signal,
    td.macd_histogram, td.bb_middle, td.bb_upper, td.bb_lower,
    td.bb_width, td.bb_squeeze, td.atr_14, td.vwma_20,
    td.hv_20, td.hv_60, td.sharpe_60, td.sharpe_126,
    su.sector, su.industry, su.symbol_pe AS pe, su.fair_value,
    su.high_52w, su.low_52w
FROM td
INNER JOIN ticker_scores ts ON ts.symbol = td.symbol
LEFT JOIN stock_universe su ON su.symbol = td.symbol
WHERE {where}
ORDER BY {sort_expr}
LIMIT ?
"""
    binds.append(limit)
    return sql, binds


# ─── Row → result dict (response shape) ───────────────────────────────────────

def _row_to_dict(row: Any) -> dict:
    """Convert a SQLAlchemy row (or sqlite3 Row) into the screener result dict.

    Output shape matches the legacy in-memory result shape so callers (route
    handlers, AI/MCP tools) don't need to change.
    """
    # Accept any mapping (Row, dict)
    get = row.get if hasattr(row, "get") else None
    if get is None:
        get = lambda k: row[k]

    symbol = get("symbol")
    close = get("close")
    change_today = get("change_today")

    indicators = {
        "rsi_14":         get("rsi_14"),
        "atr_percent":    get("atr_percent"),
        "macd":           get("macd"),
        "macd_signal":    get("macd_signal"),
        "macd_histogram": get("macd_histogram"),
        "bb_middle":      get("bb_middle"),
        "bb_upper":       get("bb_upper"),
        "bb_lower":       get("bb_lower"),
        "bb_width":       get("bb_width"),
        "bb_squeeze":     (get("bb_squeeze") == "Y") if get("bb_squeeze") is not None else False,
        "atr_14":         get("atr_14"),
        "vwma_20":        get("vwma_20"),
        "hv_20":          get("hv_20"),
        "hv_60":          get("hv_60"),
        "sharpe_60":      get("sharpe_60"),
        "sharpe_126":     get("sharpe_126"),
    }

    indicators_by_interval = {"1d": indicators}

    high_52w = get("high_52w")
    low_52w  = get("low_52w")
    pos_52w = {
        "pct_from_52w_high": (
            round(((close - high_52w) / high_52w) * 100, 2) if high_52w else None
        ),
        "pct_from_52w_low": (
            round(((close - low_52w) / low_52w) * 100, 2) if low_52w else None
        ),
    }

    return {
        "symbol": symbol,
        "close": close,
        "change_today": change_today,
        "returns": {
            "1w": get("return_1w"),
            "1m": get("return_1m"),
            "3m": get("return_3m"),
            "6m": get("return_6m"),
            "1y": get("return_1y"),
        },
        "pos_52w": pos_52w,
        "volume_ratio": get("volume_ratio_20d"),
        "indicators": indicators,
        "indicators_by_interval": indicators_by_interval,
        "sector": get("sector"),
        "industry": get("industry"),
        "pe": get("pe"),
        "fair_value": get("fair_value"),
        "momentum_score": get("momentum_score"),
    }

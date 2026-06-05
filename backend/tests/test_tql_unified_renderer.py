"""Tier 2 parity tests for the unified TQL transpiler helpers (audit B.9).

Goal: prove that the legacy and snapshot AST→WHERE renderers (and sort
helpers) produce STRUCTURALLY equivalent SQL for the same input, modulo
the field substitution.  This is the safety net that lets us delete
~200 LOC of mechanical duplicate code while keeping a guarantee that
the two backends stay in lock-step on operator/paren/bind shape.

What is parity
--------------
Same TQL string
    → legacy path and snapshot path produce the same number of bind
      placeholders (?)
    → same operator chars (=, !=, <, <=, >, >=, IN, AND, OR, NOT)
    → same paren nesting depth
    → same interval set (lateral join keys)

Same sort_by / order
    → legacy and snapshot both produce ASC or DESC
    → both append a tie-breaker column at the end
    → both emit NULLS LAST on the primary

Why is this useful
------------------
If a future change to the AST renderer forgets to update the snapshot
side, these tests fail with a structural diff (different bind count,
different operator, different paren shape) — the exact failure mode
that motivated B.9.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tql_parser import parse_tql  # noqa: E402
from app.services.tql_to_sql import (  # noqa: E402
    _node_to_where,
    _render_node_to_where,
    _render_sort_sql,
    _snapshot_node_to_where,
    _snapshot_sort_sql,
    _sort_sql,
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _strip_column_refs(sql: str) -> str:
    """Replace any ``schema.column`` or ``schema.column_alias`` reference
    with a placeholder so we can compare structural shape without being
    sensitive to ``td`` vs ``snap`` vs ``ts``.

    We also normalise ``%s`` binds (used in psycopg-style) to ``?`` (used
    in sqlite/sqlalchemy bindparam).  Currently this codebase only uses
    ``?`` but if that changes the test would still be valid.
    """
    import re
    # Replace patterns like ``td.rsi_14`` / ``snap.last_close`` / ``ts.return_1w``
    out = re.sub(r"\b[a-z_]+\.[a-z_0-9]+", "<COL>", sql)
    out = out.replace("%s", "?")
    return out


def _paren_depth(sql: str) -> int:
    """Return the maximum nesting depth of ``(`` parens (ignoring parens
    inside string literals, which is good enough for our test inputs)."""
    depth = 0
    max_depth = 0
    for ch in sql:
        if ch == "(":
            depth += 1
            if depth > max_depth:
                max_depth = depth
        elif ch == ")":
            depth -= 1
    return max_depth


def _count_binds(sql: str) -> int:
    return sql.count("?")


def _op_set(sql: str) -> set[str]:
    """Return the set of distinct SQL operators used in this fragment."""
    ops = set()
    for op in ("=", "!=", "<=", ">=", "<", ">", " IN ", " AND ", " OR ", " NOT "):
        if op in sql:
            ops.add(op)
    return ops


def _ast_render_pair(tql: str, default_interval: str = "1d"):
    """Render the same TQL through both the legacy and snapshot paths.

    Returns a 5-tuple of (legacy_sql, snapshot_sql, intervals, legacy_binds,
    snapshot_binds).
    """
    ast = parse_tql(tql)
    leg_intervals: set[str] = set()
    leg_binds: list = []
    leg_sql = _node_to_where(ast, default_interval, leg_intervals, leg_binds)

    snap_intervals: set[str] = set()
    snap_binds: list = []
    snap_sql = _snapshot_node_to_where(ast, default_interval, snap_intervals, snap_binds)

    return leg_sql, snap_sql, leg_intervals, snap_intervals, leg_binds, snap_binds


# ─── Tests ──────────────────────────────────────────────────────────────────


class TestNodeToWhereParity:
    """Same TQL → structurally equivalent SQL from both renderers."""

    @pytest.mark.parametrize(
        "tql",
        [
            "RSI > 60",
            "PE < 30",
            "PE <= 30",
            "RSI >= 50",
            'Sector = "Banks"',
            'Sector != "IT"',
            "1h:RSI > 70",
            "W:ATR > 5",
            "M:MACD > 0",
            "BBSqueeze = true",
            "BBSqueeze = false",
            "BBSqueeze",
            'Sector IN ("Banks", "IT")',
            "RSI > 60 AND PE < 30",
            "RSI > 60 OR PE < 30",
            "NOT RSI > 60",
            "(RSI > 60 AND PE < 30) OR ATR > 5",
        ],
    )
    def test_same_bind_count(self, tql: str):
        _, _, _, _, leg_binds, snap_binds = _ast_render_pair(tql)
        assert len(leg_binds) == len(snap_binds), (
            f"bind-count drift on TQL {tql!r}: legacy={len(leg_binds)} "
            f"snapshot={len(snap_binds)}"
        )

    @pytest.mark.parametrize(
        "tql",
        [
            "RSI > 60",
            "PE < 30",
            'Sector = "Banks"',
            'Sector IN ("Banks", "IT")',
            "RSI > 60 AND PE < 30",
            "RSI > 60 OR PE < 30",
            "NOT RSI > 60",
            "(RSI > 60 AND PE < 30) OR ATR > 5",
            "BBSqueeze",
        ],
    )
    def test_same_paren_depth(self, tql: str):
        leg_sql, snap_sql, _, _, _, _ = _ast_render_pair(tql)
        assert _paren_depth(leg_sql) == _paren_depth(snap_sql), (
            f"paren-depth drift on TQL {tql!r}: "
            f"legacy={_paren_depth(leg_sql)} snap={_paren_depth(snap_sql)}\n"
            f"  legacy: {leg_sql}\n  snap:   {snap_sql}"
        )

    @pytest.mark.parametrize(
        "tql",
        [
            "RSI > 60",
            "PE < 30",
            "PE <= 30",
            'Sector = "Banks"',
            'Sector != "IT"',
            'Sector IN ("Banks", "IT")',
            "RSI > 60 AND PE < 30",
            "RSI > 60 OR PE < 30",
            "NOT RSI > 60",
            "BBSqueeze = true",
        ],
    )
    def test_same_operator_set(self, tql: str):
        leg_sql, snap_sql, _, _, _, _ = _ast_render_pair(tql)
        assert _op_set(leg_sql) == _op_set(snap_sql), (
            f"operator drift on TQL {tql!r}: "
            f"legacy={_op_set(leg_sql)} snap={_op_set(snap_sql)}"
        )

    @pytest.mark.parametrize(
        "tql",
        [
            "1h:RSI > 70",
            "W:ATR > 5",
            "M:MACD > 0",
        ],
    )
    def test_snapshot_resolves_inline_indicators(self, tql: str):
        """For non-1d interval prefixes, the snapshot already stores the
        indicator value inline (``snap.rsi_1h``, ``snap.atr_W``, …) so the
        snapshot resolver returns an empty interval set (no lateral join
        needed) — the legacy path requires a lateral join into
        ``ticker_1h`` / ``ticker_weekly`` / ``ticker_monthly`` and
        therefore returns a populated interval set.

        This is a structural, intentional asymmetry: the snapshot
        precomputes the indicator at every interval.  The parity test
        below documents it explicitly so a future change to either
        resolver is forced to think about this.
        """
        _, _, leg_intervals, snap_intervals, _, _ = _ast_render_pair(tql)
        # The legacy path needs at least one interval (lateral join target)
        assert leg_intervals, (
            f"legacy should require a lateral join for {tql!r}, got {leg_intervals!r}"
        )
        # The snapshot path resolves inline (no lateral join)
        assert not snap_intervals, (
            f"snapshot should resolve inline for {tql!r}, got intervals {snap_intervals!r}"
        )

    @pytest.mark.parametrize(
        "tql",
        [
            "RSI > 60",
            "PE < 30",
            "1d:RSI > 60",  # explicit 1d prefix
        ],
    )
    def test_same_interval_set_for_1d(self, tql: str):
        """For 1d-only TQLs, both renderers should produce an empty
        interval set (no lateral joins)."""
        _, _, leg_intervals, snap_intervals, _, _ = _ast_render_pair(tql)
        assert leg_intervals == snap_intervals, (
            f"interval drift on TQL {tql!r}: "
            f"legacy={leg_intervals} snap={snap_intervals}"
        )

    def test_column_substitutions_match(self):
        """For each field used, both renderers emit ONE column reference."""
        leg_sql, snap_sql, _, _, _, _ = _ast_render_pair(
            "RSI > 60 AND PE < 30 AND BBSqueeze"
        )
        # Strip column refs — the result should be identical (modulo bind values)
        leg_norm = _strip_column_refs(leg_sql)
        snap_norm = _strip_column_refs(snap_sql)
        assert leg_norm == snap_norm, (
            f"shape drift (after stripping column refs):\n"
            f"  legacy: {leg_norm}\n  snap:   {snap_norm}"
        )

    def test_both_renderers_use_field_resolver(self):
        """The unified _render_node_to_where with the legacy field resolver
        must produce the same SQL as the legacy _node_to_where wrapper.
        """
        ast = parse_tql("RSI > 60")
        intervals: set[str] = set()
        binds: list = []
        unified_sql = _render_node_to_where(ast, "1d", intervals, binds, _legacy_resolver)
        legacy_sql = _node_to_where(ast, "1d", set(), [])
        # The legacy resolver must use ``td.rsi_14`` because that's what
        # the legacy _field_sql_expression returns.
        assert "td.rsi_14" in unified_sql
        # And the unified path with the legacy resolver must match the
        # legacy wrapper byte-for-byte.
        assert unified_sql == legacy_sql

    def test_both_renderers_snap_field_resolver(self):
        """The unified _render_node_to_where with the snapshot field
        resolver must produce the same SQL as _snapshot_node_to_where.
        """
        ast = parse_tql("RSI > 60")
        intervals: set[str] = set()
        binds: list = []
        unified_sql = _render_node_to_where(ast, "1d", intervals, binds, _snapshot_resolver)
        snap_sql = _snapshot_node_to_where(ast, "1d", set(), [])
        assert "snap.rsi_1d" in unified_sql
        assert unified_sql == snap_sql


class TestSortSqlParity:
    """Same sort_by/order → structurally equivalent ORDER BY from both."""

    @pytest.mark.parametrize(
        "sort_by,order",
        [
            ("symbol", "asc"),
            ("symbol", "desc"),
            ("close", "asc"),
            ("rsi", "desc"),
            ("pct_change_1w", "asc"),
            ("momentum_score", "desc"),
            ("volume_ratio", "asc"),
        ],
    )
    def test_both_emit_asc_or_desc(self, sort_by, order):
        leg = _sort_sql(sort_by, order)
        snap = _snapshot_sort_sql(sort_by, order)
        expected_dir = "DESC" if order.lower() == "desc" else "ASC"
        assert expected_dir in leg, f"legacy missing {expected_dir}: {leg}"
        assert expected_dir in snap, f"snap missing {expected_dir}: {snap}"

    @pytest.mark.parametrize(
        "sort_by",
        ["symbol", "close", "rsi", "pct_change_1w", "momentum_score"],
    )
    def test_both_emit_nulls_last(self, sort_by):
        leg = _sort_sql(sort_by, "desc")
        snap = _snapshot_sort_sql(sort_by, "desc")
        assert "NULLS LAST" in leg, f"legacy missing NULLS LAST: {leg}"
        assert "NULLS LAST" in snap, f"snap missing NULLS LAST: {snap}"

    def test_both_append_tiebreaker(self):
        """Both should append a tiebreaker column at the end (the table
        alias may differ; we just check the structure)."""
        leg = _sort_sql("rsi", "desc")
        snap = _snapshot_sort_sql("rsi", "desc")
        leg_norm = _strip_column_refs(leg)
        snap_norm = _strip_column_refs(snap)
        assert leg_norm == snap_norm, (
            f"ORDER BY shape drift:\n  legacy: {leg_norm}\n  snap:   {snap_norm}"
        )

    def test_unified_sort_helper_legacy(self):
        """_render_sort_sql with the legacy table defaults must match
        _sort_sql byte-for-byte for a representative sort key.
        """
        from app.services.tql_to_sql import _SORT_FIELD_SQL
        unified = _render_sort_sql("rsi", "desc", _SORT_FIELD_SQL, "td.symbol", "td.symbol")
        legacy = _sort_sql("rsi", "desc")
        assert unified == legacy

    def test_unified_sort_helper_snap(self):
        from app.services.tql_to_sql import _SNAPSHOT_SORT_FIELD_SQL
        unified = _render_sort_sql("rsi", "desc", _SNAPSHOT_SORT_FIELD_SQL, "snap.symbol", "snap.symbol")
        snap = _snapshot_sort_sql("rsi", "desc")
        assert unified == snap


# ─── Resolvers for the unified-renderer tests ───────────────────────────────

# We import the resolvers lazily so that if the tql_to_sql module is
# restructured the tests still load (they'll surface a clear ImportError
# at the call site, not at collection time).


def _legacy_resolver(field: str, default_interval: str):
    """Wrapper that delegates to the legacy ``_field_sql_expression``."""
    from app.services.tql_to_sql import _field_sql_expression
    return _field_sql_expression(field, default_interval)


def _snapshot_resolver(field: str, default_interval: str):
    """Wrapper that delegates to ``_snapshot_field_sql_expression``."""
    from app.services.tql_to_sql import _snapshot_field_sql_expression
    return _snapshot_field_sql_expression(field, default_interval)

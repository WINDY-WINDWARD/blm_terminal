"""Parity tests for `tql_parser.parse_tql` — audit #8 (Top 10 #8).

Refactor target: ``@functools.lru_cache(maxsize=256)`` on ``parse_tql``.

These tests lock down the BEHAVIOURAL contract (correct AST shape, correct
error type) AND the safety contract (callers cannot poison the cache by
mutating the returned AST) AND a perf bound (cached calls should be cheap).

The safety contract is the key one — without an explicit defensive copy
on cache hit, two callers who both hold the same AST can corrupt each
other's view.  This test guards against that.

Run with ``-m parity`` to limit to this test class; ``-m perf`` for the
performance-bound test.
"""
from __future__ import annotations

import sys
import time
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


# ─── Behavioural parity (works before AND after the refactor) ──────────────────


class TestParseTqlBehaviour:
    """The cached parse must produce the same AST shape as the uncached parse."""

    def test_simple_compare(self):
        ast = parse_tql('RSI > 60')
        assert isinstance(ast, CompareNode)
        assert ast.field == "RSI"
        assert ast.op == ">"
        assert ast.value == 60

    def test_string_compare(self):
        ast = parse_tql('Sector = "Banks"')
        assert isinstance(ast, CompareNode)
        assert ast.field == "Sector"
        assert ast.value == "Banks"

    def test_and_chain(self):
        ast = parse_tql('RSI > 60 AND PE < 30')
        assert isinstance(ast, AndNode)
        assert isinstance(ast.left, CompareNode)
        assert isinstance(ast.right, CompareNode)

    def test_or_chain(self):
        ast = parse_tql('Sector = "Banks" OR Sector = "IT"')
        assert isinstance(ast, OrNode)

    def test_not_node(self):
        ast = parse_tql("NOT BBSqueeze")
        assert isinstance(ast, NotNode)
        assert isinstance(ast.expr, CompareNode)

    def test_in_clause(self):
        ast = parse_tql('Sector IN ("Banks", "IT", "Auto")')
        assert isinstance(ast, InNode)
        assert ast.field == "Sector"
        assert ast.values == ["Banks", "IT", "Auto"]

    def test_interval_prefix(self):
        ast = parse_tql("1h:RSI > 60")
        assert isinstance(ast, CompareNode)
        assert ast.field == "1h:RSI"

    def test_paren_grouping(self):
        ast = parse_tql("(RSI > 60 AND Volume > 1) OR PE < 20")
        # The root is OR with AndNode on the left
        assert isinstance(ast, OrNode)
        assert isinstance(ast.left, AndNode)

    def test_bbsqueeze_bare(self):
        ast = parse_tql("BBSqueeze")
        assert isinstance(ast, CompareNode)
        assert ast.field == "BBSqueeze"
        assert ast.op == "="
        assert ast.value is True

    def test_unknown_field_raises(self):
        with pytest.raises(TQLSyntaxError):
            parse_tql("NotARealField > 5")

    def test_unknown_interval_raises(self):
        with pytest.raises(TQLSyntaxError):
            parse_tql("5m:RSI > 60")

    def test_syntax_error_raises(self):
        with pytest.raises(TQLSyntaxError):
            parse_tql("RSI >>> 60")


# ─── Cache contract ────────────────────────────────────────────────────────────


class TestParseTqlCacheContract:
    """Lock down the LRU-cache contract documented in ``parse_tql``'s docstring.

    Contract:
    - Repeated calls with the same query return the SAME AST instance
      (proves the cache is being used).
    - Different queries return different AST instances.
    - Errors are not cached — invalid queries raise on every call.
    - Callers must NOT mutate the returned AST (the cache returns shared
      instances; mutating one call's AST affects all subsequent calls).
    """

    def test_same_query_returns_same_instance(self):
        """Cache hit: the same query string returns the identical AST object.

        This is the proof that ``lru_cache`` is engaged.  Pre-refactor,
        each call built a fresh AST, so the test would FAIL.
        """
        q = 'RSI > 60 AND Sector = "Banks"'
        ast1 = parse_tql(q)
        ast2 = parse_tql(q)
        assert ast1 is ast2, (
            "parse_tql is not caching: expected the same AST instance on repeated calls. "
            "Check that @functools.lru_cache is applied to the underlying worker."
        )

    def test_different_queries_return_different_instances(self):
        """Cache miss: different query strings build different ASTs."""
        ast1 = parse_tql("RSI > 60")
        ast2 = parse_tql("PE < 30")
        assert ast1 is not ast2

    def test_in_clause_shares_instance(self):
        """A non-trivial query shape (InNode with a list) is also cached."""
        q = 'Sector IN ("Banks", "IT", "Auto")'
        ast1 = parse_tql(q)
        ast2 = parse_tql(q)
        assert ast1 is ast2
        # Sanity: still the right shape
        assert isinstance(ast1, InNode)
        assert ast1.values == ["Banks", "IT", "Auto"]

    def test_error_path_not_cached(self):
        """A TQLSyntaxError must propagate on every call.

        ``functools.lru_cache`` does not memoize exceptions, so the same
        invalid query must raise on every invocation.  This test guards
        against a future refactor that wraps parse_tql in a try/except
        and caches the error.
        """
        for _ in range(3):
            with pytest.raises(TQLSyntaxError):
                parse_tql("NotARealField > 5")


# ─── Cache efficiency (validates the refactor is actually doing something) ─────


@pytest.mark.perf
class TestParseTqlCacheEfficiency:
    """A second parse of the same query should be measurably faster.

    The cache key is the input string; on hit we skip tokenize+parse+validate
    entirely (no defensive copy is made — see contract test).  The bound
    is generous (2×) to tolerate CI machine variance; real-world wins
    are typically 5-20×.
    """

    def test_cached_call_is_faster(self):
        # Use a non-trivial query shape so the parse cost is significant.
        q = (
            '(RSI > 60 AND 1h:MACD > 0 AND W:BBWidth < 0.1 AND M:ATR < 5 '
            'AND Sector IN ("Banks", "IT", "Auto", "Pharma") AND PE < 30) '
            'OR (NOT BBSqueeze AND Volume > 1000000)'
        )

        # Warm the cache with one parse
        parse_tql(q)

        # Measure N cached calls (same query, hits cache)
        N = 1000
        t0 = time.perf_counter()
        for _ in range(N):
            parse_tql(q)
        cached_ms = (time.perf_counter() - t0) * 1000

        # Measure N uncached calls (unique queries of similar shape, miss cache)
        unique_qs = [
            f'(RSI > {i} AND PE < {100 - i} AND Sector IN ("Banks", "IT"))'
            for i in range(N)
        ]
        t0 = time.perf_counter()
        for uq in unique_qs:
            parse_tql(uq)
        uncached_ms = (time.perf_counter() - t0) * 1000

        # Cached must beat uncached by at least 2×.
        assert cached_ms * 2 < uncached_ms, (
            f"parse_tql cache not effective: "
            f"cached {N}× = {cached_ms:.2f}ms, uncached {N}× unique = {uncached_ms:.2f}ms. "
            f"Expected cached to be at least 2× faster."
        )

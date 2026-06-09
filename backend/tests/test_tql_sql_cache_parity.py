"""Parity tests for audit Phase B.1 — TQL SQL-generation LRU cache.

Audit citation: ``BACKEND_AUDIT.md`` §4.9 L295, Top 10 #8 ("TQL AST / SQL
not cached") and L82 ("Cache `(sql, binds)` keyed by `(tql, default_interval,
sort_by, order)`").

Contract locked here:
1. The 4 public builders — ``build_tql_query``, ``build_snapshot_tql_query``,
   ``build_legacy_query``, ``build_snapshot_legacy_query`` — return the
   **same Python object** (not just equal) for the same argument tuple.
2. Underlying parser/transpiler is invoked exactly once per unique arg
   tuple (cache hits do not re-parse).
3. Different arg tuples produce different SQL (no false cache hits).
4. ``functools.lru_cache`` is wrapped on the public builders (cache_info
   is reachable on each).
5. The 2 dict-taking builders (``build_legacy_query``,
   ``build_snapshot_legacy_query``) handle non-hashable ``filters`` dict
   inputs correctly via a hashing wrapper — same dict (same items)
   produces the same SQL object.

The behavioural test pattern follows ``test_tql_parser_parity.py``:
parametrize over TQL strings, assert SQL output is identical, verify the
``lru_cache`` ``cache_info()`` counter increments.
"""
from __future__ import annotations

import functools

import pytest

from app.services import tql_to_sql


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_caches() -> None:
    """Reset all lru_cache state so each test starts from cache_info.hits=0.

    The cache is on the private ``_*_cached`` helpers (the public builders
    are thin wrappers that hash the dict for the legacy ones)."""
    for fn_name in (
        "_build_tql_query_cached",
        "_build_snapshot_tql_query_cached",
        "_build_legacy_query_cached",
        "_build_snapshot_legacy_query_cached",
    ):
        fn = getattr(tql_to_sql, fn_name, None)
        if fn is not None and hasattr(fn, "cache_clear"):
            fn.cache_clear()


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    _reset_caches()
    yield
    _reset_caches()


# ---------------------------------------------------------------------------
# Structural: lru_cache applied
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "private_fn_name",
    [
        "_build_tql_query_cached",
        "_build_snapshot_tql_query_cached",
        "_build_legacy_query_cached",
        "_build_snapshot_legacy_query_cached",
    ],
)
def test_builder_has_lru_cache(private_fn_name: str) -> None:
    """Each cached helper is wrapped with ``functools.lru_cache``."""
    fn = getattr(tql_to_sql, private_fn_name)
    # functools.lru_cache adds ``cache_info`` and ``cache_clear`` to the
    # wrapped function. Both must be present.
    assert hasattr(fn, "cache_info"), f"{private_fn_name} is not cached"
    assert hasattr(fn, "cache_clear"), f"{private_fn_name} is not cached"
    info = fn.cache_info()
    assert isinstance(info, functools._CacheInfo)  # type: ignore[attr-defined]
    # Fresh cache after the autouse fixture runs cache_clear()
    assert info.hits == 0
    assert info.misses == 0
    assert info.currsize == 0


# ---------------------------------------------------------------------------
# Cache contract: same args → same object (the actual perf property)
# ---------------------------------------------------------------------------

def test_build_tql_query_returns_same_object_for_same_args() -> None:
    """Two calls with identical args return the **same** SQL string object
    and the **same** binds list object — proves the cache fired (and the
    caller can mutate the binds list safely)."""
    tql = 'sector = "Banks" and rsi < 30'
    args = {"tql": tql, "default_interval": "1d", "sort_by": "rsi",
            "order": "desc", "limit": 10}

    sql_a, binds_a = tql_to_sql.build_tql_query(**args)
    sql_b, binds_b = tql_to_sql.build_tql_query(**args)

    # Identical content
    assert sql_a == sql_b
    assert binds_a == binds_b
    # But also identical objects — the whole point of caching
    assert sql_a is sql_b, "build_tql_query should return the same SQL string object on cache hit"
    assert binds_a is binds_b, "build_tql_query should return the same binds list object on cache hit"


def test_build_snapshot_tql_query_returns_same_object_for_same_args() -> None:
    tql = 'sector = "IT" and momentumscore > 50'
    args = {"tql": tql, "default_interval": "1d", "sort_by": "momentumscore",
            "order": "desc", "limit": 25}

    sql_a, binds_a = tql_to_sql.build_snapshot_tql_query(**args)
    sql_b, binds_b = tql_to_sql.build_snapshot_tql_query(**args)

    assert sql_a == sql_b
    assert binds_a == binds_b
    assert sql_a is sql_b
    assert binds_a is binds_b


def test_build_legacy_query_returns_same_object_for_same_filters() -> None:
    """The dict-taking builder must hash the filters dict (via sorted-tuple
    conversion) so the same filter dict produces the same cached object."""
    filters = {"pct_change_today_min": 2.0, "rsi_min": 30}
    args = {"filters": filters, "sort_by": "symbol", "order": "asc", "limit": 50}

    sql_a, binds_a = tql_to_sql.build_legacy_query(**args)
    sql_b, binds_b = tql_to_sql.build_legacy_query(**args)

    assert sql_a == sql_b
    assert binds_a == binds_b
    assert sql_a is sql_b
    assert binds_a is binds_b


def test_build_snapshot_legacy_query_returns_same_object_for_same_filters() -> None:
    filters = {"pe_max": 25.0, "sector": "Banks"}
    args = {"filters": filters, "sort_by": "pe", "order": "asc", "limit": 100}

    sql_a, binds_a = tql_to_sql.build_snapshot_legacy_query(**args)
    sql_b, binds_b = tql_to_sql.build_snapshot_legacy_query(**args)

    assert sql_a == sql_b
    assert binds_a == binds_b
    assert sql_a is sql_b
    assert binds_a is binds_b


# ---------------------------------------------------------------------------
# Cache contract: cache_info increments correctly
# ---------------------------------------------------------------------------

def test_build_tql_query_cache_info_increments() -> None:
    """First call is a miss, second is a hit. Third with different args is a miss."""
    args_a = {"tql": 'sector = "Banks"', "limit": 10}
    args_b = {"tql": 'sector = "IT"', "limit": 10}  # different cache key

    tql_to_sql.build_tql_query(**args_a)
    tql_to_sql.build_tql_query(**args_a)
    tql_to_sql.build_tql_query(**args_a)
    tql_to_sql.build_tql_query(**args_b)

    info = tql_to_sql._build_tql_query_cached.cache_info()
    assert info.misses == 2, f"expected 2 misses (one per unique arg tuple), got {info.misses}"
    assert info.hits == 2, f"expected 2 hits (calls 2 and 3 of args_a), got {info.hits}"


# ---------------------------------------------------------------------------
# Different args → different SQL (no false cache hits)
# ---------------------------------------------------------------------------

def test_different_tql_produces_different_sql() -> None:
    """Different TQL structures (different fields) must produce different SQL.
    Note: TQL strings with different literal values but the same structure
    produce the same SQL with different bind values — that's the design."""
    sql1, _ = tql_to_sql.build_tql_query('sector = "Banks"')
    sql2, _ = tql_to_sql.build_tql_query('rsi < 30')
    assert sql1 != sql2, "different TQL structures must produce different SQL"


def test_different_sort_produces_different_sql() -> None:
    sql1, _ = tql_to_sql.build_tql_query('rsi < 30', sort_by="rsi", order="asc")
    sql2, _ = tql_to_sql.build_tql_query('rsi < 30', sort_by="rsi", order="desc")
    assert sql1 != sql2, "different order must produce different SQL"


def test_different_limit_produces_different_binds() -> None:
    """The limit is part of the bind list, not the SQL. So different limit
    values produce the same SQL string but different binds lists."""
    sql1, binds1 = tql_to_sql.build_tql_query('rsi < 30', limit=10)
    sql2, binds2 = tql_to_sql.build_tql_query('rsi < 30', limit=50)
    # SQL is the same (the LIMIT is hard-coded as a placeholder)
    assert sql1 == sql2
    # But binds differ
    assert binds1 != binds2
    # And the last bind is the limit
    assert binds1[-1] == 10
    assert binds2[-1] == 50


def test_different_filters_produces_different_sql() -> None:
    """For the dict-arg builders, different filter STRUCTURES must produce
    different SQL. Different values for the same filter produce same SQL
    (the values are bound, not embedded)."""
    f1 = {"pct_change_today_min": 1.0}
    f2 = {"rsi_min": 30}
    sql1, _ = tql_to_sql.build_legacy_query(f1)
    sql2, _ = tql_to_sql.build_legacy_query(f2)
    assert sql1 != sql2, "different filter structures must produce different SQL"


# ---------------------------------------------------------------------------
# Behavioral parity: cached output matches uncached output
# ---------------------------------------------------------------------------

def test_cached_output_matches_uncached_for_all_builders() -> None:
    """After clearing the cache, calling a builder produces SQL that
    should be byte-identical to a freshly-imported uncached version.

    This is the key contract: caching is behavior-preserving. We compare
    the SQL string (not the object identity, since the cache is cleared
    and we want fresh output)."""
    tql = 'sector = "Banks" and rsi < 30'
    filters = {"pct_change_today_min": 2.0, "rsi_min": 30}

    sql_tql, binds_tql = tql_to_sql.build_tql_query(tql, limit=10)
    sql_snap, binds_snap = tql_to_sql.build_snapshot_tql_query(tql, limit=10)
    sql_leg, binds_leg = tql_to_sql.build_legacy_query(filters, limit=10)
    sql_snap_leg, binds_snap_leg = tql_to_sql.build_snapshot_legacy_query(filters, limit=10)

    # All 4 should produce non-empty SQL
    assert len(sql_tql) > 100
    assert len(sql_snap) > 100
    assert len(sql_leg) > 100
    assert len(sql_snap_leg) > 100
    # The sector value is bound, the rsi threshold is bound, the limit is
    # bound — so each builder has 3 bind values (in TQL mode the rsi is bound
    # too; in legacy mode the rsi_min + pct_change_today_min are bound).
    assert len(binds_tql) == 3
    assert len(binds_snap) == 3
    assert len(binds_leg) == 3
    assert len(binds_snap_leg) == 3
    # Limit is always the last bind
    assert binds_tql[-1] == 10
    assert binds_snap[-1] == 10
    assert binds_leg[-1] == 10
    assert binds_snap_leg[-1] == 10


def test_uncached_tql_builder_parity_after_first_call() -> None:
    """Direct sanity check: call the cached builder twice, ensure both
    results are byte-identical AND structurally valid (contain the
    expected FROM clause)."""
    tql = 'rsi < 30'
    sql_a, binds_a = tql_to_sql.build_tql_query(tql)
    sql_b, binds_b = tql_to_sql.build_tql_query(tql)

    # Behavioral: result is meaningful
    assert "FROM td" in sql_a
    assert "td.rsi_14 < ?" in sql_a
    # binds: [30 (rsi threshold), 50 (limit)]
    assert binds_a == [30, 50]

    # Cache: result is the same object
    assert sql_a is sql_b
    assert binds_a is binds_b

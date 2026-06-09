"""Parity tests for cache unification: 3 routers -> cache.nse_cache.

Audit Phase A: routers/valuation.py:33-45, portfolio.py:30-43, and
screener.py:26-43 each implemented their own ad-hoc dict+TTL cache. The
audit recommended unifying them onto the shared `nse_cache` from
`app.services.cache` (which uses `cachetools.TTLCache` for thread-safety,
auto-eviction, and LRU semantics).

This test file pins the unification:

  1. **Structural** — each router must import `nse_cache` from
     `app.services.cache` and must NOT define its own private
     `_cache` / `_CACHE` dict or `_cache_get` / `_cache_set` helpers.
  2. **Behavioral** — calling each router's route handler with the same
     args must populate `nse_cache` with the expected cache key, and a
     second call with the same args must not re-invoke the underlying
     data fetcher (proves a cache hit).
  3. **Keying** — different inputs must produce different cache entries
     (no collisions).

Note: this unification changes the effective TTL for the three routers
from {valuation: 1800s, portfolio: 900s, screener.search: 60s,
screener.{company,trades,quarterly}: 900s} to nse_cache's canonical
600s. That is intentional — it is the unification contract specified
in BACKEND_AUDIT.md line 180.
"""
from __future__ import annotations

import inspect

import pytest

from app.routers import portfolio, screener, valuation
from app.services import cache as cache_mod


# --- helpers ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_nse_cache() -> None:
    """Clear nse_cache before and after each test so cache state doesn't leak."""
    cache_mod.nse_cache.clear()
    yield
    cache_mod.nse_cache.clear()


def _has_private_cache_primitives(module) -> list[str]:
    """Return names of any private cache primitives found on the module."""
    found = []
    for name in ("_cache", "_CACHE", "_cache_get", "_cache_set", "_CACHE_TTL"):
        if hasattr(module, name):
            found.append(name)
    return found


# --- structural tests: valuation --------------------------------------------


def test_valuation_imports_nse_cache_from_app_services_cache() -> None:
    """valuation.py must import nse_cache from app.services.cache."""
    src = inspect.getsource(valuation)
    assert "from app.services.cache import nse_cache" in src, (
        "valuation.py must import nse_cache from app.services.cache for the "
        "unification (BACKEND_AUDIT.md line 180)."
    )


def test_valuation_drops_private_cache_primitives() -> None:
    """valuation.py must NOT define its own _cache/_CACHE dict or _cache_get/_cache_set."""
    found = _has_private_cache_primitives(valuation)
    assert found == [], (
        f"valuation.py must drop its private cache primitives (audit line 180). "
        f"Found: {found}. Replace with nse_cache.get(key) / nse_cache[key] = value."
    )


# --- structural tests: portfolio --------------------------------------------


def test_portfolio_imports_nse_cache_from_app_services_cache() -> None:
    src = inspect.getsource(portfolio)
    assert "from app.services.cache import nse_cache" in src, (
        "portfolio.py must import nse_cache from app.services.cache for the "
        "unification (BACKEND_AUDIT.md line 180)."
    )


def test_portfolio_drops_private_cache_primitives() -> None:
    found = _has_private_cache_primitives(portfolio)
    assert found == [], (
        f"portfolio.py must drop its private cache primitives (audit line 180). "
        f"Found: {found}. Replace with nse_cache.get(key) / nse_cache[key] = value."
    )


# --- structural tests: screener ---------------------------------------------


def test_screener_imports_nse_cache_from_app_services_cache() -> None:
    src = inspect.getsource(screener)
    assert "from app.services.cache import nse_cache" in src, (
        "screener.py must import nse_cache from app.services.cache for the "
        "unification (BACKEND_AUDIT.md line 180)."
    )


def test_screener_drops_private_cache_primitives() -> None:
    found = _has_private_cache_primitives(screener)
    assert found == [], (
        f"screener.py must drop its private cache primitives (audit line 180). "
        f"Found: {found}. Replace with nse_cache.get(key) / nse_cache[key] = value."
    )


# --- behavioral tests: valuation --------------------------------------------


@pytest.mark.asyncio
async def test_valuation_get_valuation_populates_nse_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_valuation must write its result to nse_cache and serve a hit on the 2nd call."""
    sentinel_data = {
        "cmp": 100.0, "eps": 5.0, "book_value": 50.0,
        "dividend_rate": None, "dividend_yield": 1.5,
        "earnings_growth": 0.10, "revenue_growth": 0.10,
        "forward_eps": None, "shares_outstanding": 1000.0,
        "ebitda": 50.0, "total_debt": 0.0, "total_cash": 0.0,
        "fcf_per_share": None, "graham_precomputed": None,
        "evebitda_ratio": None, "source": "test",
    }
    call_count = {"n": 0}

    async def fake_fetch(symbol: str) -> dict:
        call_count["n"] += 1
        return sentinel_data

    monkeypatch.setattr(valuation, "_fetch_valuation_data", fake_fetch)

    # First call: must invoke the fetcher and populate the cache
    result1 = await valuation.get_valuation("RELIANCE", 0.12, 0.05, None)
    assert call_count["n"] == 1, "first call must invoke _fetch_valuation_data"

    cache_key = "RELIANCE:0.12:0.05:None"
    assert cache_key in cache_mod.nse_cache, (
        f"valuation.get_valuation must populate nse_cache with the computed "
        f"cache_key {cache_key!r}"
    )
    assert cache_mod.nse_cache.get(cache_key) is result1, (
        "the value stored in nse_cache must be the same object returned to the caller"
    )

    # Second call with identical args: must be a cache hit (no second fetch)
    result2 = await valuation.get_valuation("RELIANCE", 0.12, 0.05, None)
    assert call_count["n"] == 1, (
        "second call with the same args must be a cache hit — "
        "_fetch_valuation_data must not be re-invoked"
    )
    assert result2 is result1 or result1.model_dump() == result2.model_dump()


@pytest.mark.asyncio
async def test_valuation_different_args_yield_different_cache_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Different wacc/terminal_growth must produce different cache keys."""
    async def fake_fetch(symbol: str) -> dict:
        return {
            "cmp": 100.0, "eps": 5.0, "book_value": 50.0,
            "dividend_rate": None, "dividend_yield": 1.5,
            "earnings_growth": 0.10, "revenue_growth": 0.10,
            "forward_eps": None, "shares_outstanding": 1000.0,
            "ebitda": 50.0, "total_debt": 0.0, "total_cash": 0.0,
            "fcf_per_share": None, "graham_precomputed": None,
            "evebitda_ratio": None, "source": "test",
        }

    monkeypatch.setattr(valuation, "_fetch_valuation_data", fake_fetch)

    await valuation.get_valuation("RELIANCE", 0.12, 0.05, None)
    await valuation.get_valuation("RELIANCE", 0.15, 0.05, None)
    await valuation.get_valuation("TCS", 0.12, 0.05, None)

    assert "RELIANCE:0.12:0.05:None" in cache_mod.nse_cache
    assert "RELIANCE:0.15:0.05:None" in cache_mod.nse_cache
    assert "TCS:0.12:0.05:None" in cache_mod.nse_cache
    assert len(cache_mod.nse_cache) == 3, "three distinct calls must produce 3 entries"


# --- behavioral tests: portfolio --------------------------------------------


@pytest.mark.asyncio
async def test_portfolio_optimize_populates_nse_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """optimize_portfolio must write its result to nse_cache and serve a hit on the 2nd call."""
    from app.routers.portfolio import (
        PortfolioOptimizeRequest,
        PortfolioOptimizeResult,
        IndividualStats,
    )

    sentinel = PortfolioOptimizeResult(
        weights={"A": 0.4, "B": 0.3, "C": 0.3},
        expected_annual_return=0.10,
        expected_annual_volatility=0.20,
        sharpe_ratio=0.5,
        correlation_matrix={
            "A": {"A": 1.0, "B": 0.3, "C": 0.2},
            "B": {"A": 0.3, "B": 1.0, "C": 0.4},
            "C": {"A": 0.2, "B": 0.4, "C": 1.0},
        },
        individual_stats={
            "A": IndividualStats(annual_return=0.10, annual_volatility=0.20, sharpe=0.5),
            "B": IndividualStats(annual_return=0.08, annual_volatility=0.15, sharpe=0.4),
            "C": IndividualStats(annual_return=0.12, annual_volatility=0.25, sharpe=0.5),
        },
        period_used="1y",
        objective_used="max_sharpe",
        symbols_used=["A", "B", "C"],
        symbols_failed=[],
        computed_at="2026-06-05T00:00:00+00:00",
    )
    call_count = {"n": 0}

    def fake_run(request: PortfolioOptimizeRequest) -> PortfolioOptimizeResult:
        call_count["n"] += 1
        return sentinel

    monkeypatch.setattr(portfolio, "_run_optimization_sync", fake_run)

    request = PortfolioOptimizeRequest(
        symbols=["A", "B", "C"],
        period="1y",
        objective="max_sharpe",
        risk_free_rate=0.06,
    )

    # First call: must invoke the runner and populate the cache
    result1 = await portfolio.optimize_portfolio(request)
    assert call_count["n"] == 1, "first call must invoke _run_optimization_sync"

    cache_key = "A,B,C:1y:max_sharpe:0.06"
    assert cache_key in cache_mod.nse_cache, (
        f"portfolio.optimize_portfolio must populate nse_cache with the "
        f"computed cache_key {cache_key!r}"
    )

    # Second call: must be a cache hit
    result2 = await portfolio.optimize_portfolio(request)
    assert call_count["n"] == 1, (
        "second call with the same request must be a cache hit — "
        "_run_optimization_sync must not be re-invoked"
    )
    assert result2 is result1 or result1.model_dump() == result2.model_dump()


# --- behavioral tests: screener ---------------------------------------------


@pytest.mark.asyncio
async def test_screener_search_populates_nse_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """screener_search must write its result to nse_cache and serve a hit on the 2nd call."""
    from app.services.screener_client import screener_client

    sentinel = [{"symbol": "RELIANCE", "name": "Reliance Industries", "url": "/company/RELIANCE/"}]
    call_count = {"n": 0}

    async def fake_search(q: str):
        call_count["n"] += 1
        return sentinel

    monkeypatch.setattr(screener_client, "search", fake_search)

    # First call: must invoke the search and populate the cache
    result1 = await screener.screener_search("reliance")
    assert call_count["n"] == 1, "first call must invoke screener_client.search"

    cache_key = "screener:search:reliance"
    assert cache_key in cache_mod.nse_cache, (
        f"screener.screener_search must populate nse_cache with the computed "
        f"cache_key {cache_key!r}"
    )

    # Second call: must be a cache hit
    result2 = await screener.screener_search("reliance")
    assert call_count["n"] == 1, "second call must be a cache hit"
    assert result1 == result2 == sentinel


@pytest.mark.asyncio
async def test_screener_search_normalizes_query_for_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """screener_search must normalize the query to lowercase for the cache key."""
    from app.services.screener_client import screener_client

    sentinel = [{"symbol": "RELIANCE", "name": "Reliance"}]
    call_count = {"n": 0}

    async def fake_search(q: str):
        call_count["n"] += 1
        return sentinel

    monkeypatch.setattr(screener_client, "search", fake_search)

    await screener.screener_search("RELIANCE")
    assert call_count["n"] == 1
    assert "screener:search:reliance" in cache_mod.nse_cache, (
        "cache key must use the lowercased query (parity with the original behavior)"
    )

    # Different-case query must hit the same cache entry
    await screener.screener_search("Reliance")
    assert call_count["n"] == 1, (
        "RELIANCE and Reliance must share the same cache entry (q.lower() normalization)"
    )

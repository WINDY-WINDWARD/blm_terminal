"""Unit tests for the NSE change-ranges / symbol-data helpers and REST routes.

Covers:
  - app.services.market_data.fetch_change_ranges_batch / fetch_symbol_data_batch
  - app.routers.markets.get_change_ranges / get_symbol_data
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_nse_cache():
    """Clear the in-process NSE cache between tests so stubs aren't masked."""
    from app.services.cache import nse_cache

    nse_cache.clear()
    yield
    nse_cache.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_active_client(monkeypatch, *, change_ranges=None, symbol_data=None, raise_exc=None):
    """Patch the NSE client methods that market_data calls.

    `_active_client` is bound at import time (sync or async variant), so we
    monkeypatch the `get_change_ranges` / `get_symbol_data` attributes on
    whichever object was selected.
    """
    from app.services import market_data

    client = market_data._active_client

    def _change_ranges(sym):
        if raise_exc is not None:
            raise raise_exc
        return change_ranges

    def _symbol_data(sym):
        if raise_exc is not None:
            raise raise_exc
        return symbol_data

    monkeypatch.setattr(client, "get_change_ranges", _change_ranges)
    monkeypatch.setattr(client, "get_symbol_data", _symbol_data)


# ---------------------------------------------------------------------------
# fetch_change_ranges_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_change_ranges_batch_returns_mapping(monkeypatch):
    from app.services import market_data

    expected = {
        "oneDayPercent": 0.1,
        "oneWeekPercent": 1.2,
        "oneMonthPercent": 3.4,
    }
    _patch_active_client(monkeypatch, change_ranges=expected)

    out = await market_data.fetch_change_ranges_batch(["RELIANCE"])
    assert out == {"RELIANCE": expected}


@pytest.mark.asyncio
async def test_fetch_change_ranges_batch_handles_failure(monkeypatch):
    from app.services import market_data

    _patch_active_client(monkeypatch, raise_exc=RuntimeError("nse down"))

    out = await market_data.fetch_change_ranges_batch(["RELIANCE"])
    # Exception is caught and turned into None for that symbol
    assert out == {"RELIANCE": None}


@pytest.mark.asyncio
async def test_fetch_change_ranges_batch_empty():
    from app.services import market_data

    assert await market_data.fetch_change_ranges_batch([]) == {}
    assert await market_data.fetch_change_ranges_batch(None) == {}


# ---------------------------------------------------------------------------
# fetch_symbol_data_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_symbol_data_batch_returns_mapping(monkeypatch):
    from app.services import market_data

    expected = {
        "equityResponse": [
            {
                "orderBook": {"lastPrice": 1234.5},
                "metaData": {"pChange": 1.23},
                "priceInfo": {"yearHigh": 1300, "yearLow": 1100},
            }
        ]
    }
    _patch_active_client(monkeypatch, symbol_data=expected)

    out = await market_data.fetch_symbol_data_batch(["RELIANCE"])
    assert out == {"RELIANCE": expected}


@pytest.mark.asyncio
async def test_fetch_symbol_data_batch_handles_failure(monkeypatch):
    from app.services import market_data

    _patch_active_client(monkeypatch, raise_exc=RuntimeError("nse down"))

    out = await market_data.fetch_symbol_data_batch(["RELIANCE"])
    assert out == {"RELIANCE": None}


# ---------------------------------------------------------------------------
# Cache reuse: second call within TTL should not hit NSE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_ranges_cache_hit(monkeypatch):
    from app.services import market_data

    call_count = {"n": 0}

    def _change_ranges(sym):
        call_count["n"] += 1
        return {"oneDayPercent": 1.0}

    monkeypatch.setattr(market_data._active_client, "get_change_ranges", _change_ranges)

    # First call populates cache
    first = await market_data.fetch_change_ranges_batch(["TCS"])
    assert first["TCS"] == {"oneDayPercent": 1.0}
    # Second call should be served from cache
    second = await market_data.fetch_change_ranges_batch(["TCS"])
    assert second["TCS"] == {"oneDayPercent": 1.0}
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# HTTP route param binding (REST fallback used by the Next.js proxy)
# ---------------------------------------------------------------------------


def test_symbol_data_route_binds_single_query_param(monkeypatch):
    """`/api/markets/symbol-data?symbol=X` must bind to the `symbol` list param.

    The Next.js proxy at src/app/api/nse/symbol-data/route.ts hits this
    route with a single `?symbol=X` query string when the NSE upstream
    circuit is open. A binding regression (e.g. someone changing the
    param to a path segment) would silently break the fallback.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import markets as markets_router_module
    from app.services import market_data

    captured: list[list[str]] = []

    async def _fake(symbols):
        captured.append(list(symbols))
        return {symbols[0].upper(): {"ltp": 100.0, "pChange": 0.5, "yearHigh": 110, "yearLow": 90}}

    # The router does `from app.services.market_data import fetch_symbol_data_batch`
    # at module load, so we have to patch both the module attribute and the
    # name the route closure already captured.
    monkeypatch.setattr(market_data, "fetch_symbol_data_batch", _fake)
    monkeypatch.setattr(markets_router_module, "fetch_symbol_data_batch", _fake)

    app = FastAPI()
    app.include_router(markets_router_module.router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/markets/symbol-data?symbol=RELIANCE")

    assert resp.status_code == 200, resp.text
    assert captured == [["RELIANCE"]], captured
    assert resp.json() == {
        "data": {
            "RELIANCE": {
                "ltp": 100.0,
                "pChange": 0.5,
                "yearHigh": 110,
                "yearLow": 90,
            }
        }
    }


def test_symbol_data_route_binds_repeated_query_params(monkeypatch):
    """`?symbol=A&symbol=B` must bind both values to the `symbol` list param."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import markets as markets_router_module
    from app.services import market_data

    captured: list[list[str]] = []

    async def _fake(symbols):
        captured.append(list(symbols))
        out = {}
        for s in symbols:
            out[s.upper()] = {"ltp": 100.0, "pChange": 0.5}
        return out

    monkeypatch.setattr(market_data, "fetch_symbol_data_batch", _fake)
    monkeypatch.setattr(markets_router_module, "fetch_symbol_data_batch", _fake)

    app = FastAPI()
    app.include_router(markets_router_module.router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/markets/symbol-data?symbol=RELIANCE&symbol=TCS")

    assert resp.status_code == 200, resp.text
    assert captured == [["RELIANCE", "TCS"]], captured

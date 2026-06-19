"""Tests for /api/stockuniverse/{symbol}/ratios — the FDM screener-fallback endpoint.

This endpoint returns live NSE ratios (P/E, sector P/E, 52W high/low) for a
symbol. The FDM widget uses it when screener.in returns 503, so the widget
isn't completely empty for the user.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Build a fresh FastAPI app with the stockuniverse router."""
    from app.routers.stockuniverse import router as stockuniverse_router
    app = FastAPI()
    app.include_router(stockuniverse_router, prefix="/api")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _fake_stock_metadata(**overrides) -> MagicMock:
    """Build a fake StockUniverse ORM-like object with the NSE fields we use."""
    defaults = {
        "symbol": "RELIANCE",
        "companyName": "Reliance Industries Limited",
        "isin": "INE002A01018",
        "symbolPE": 18.86,
        "sectorPE": 18.86,
        "industry": "Refineries & Marketing",
        "high_52w": 1611.8,
        "low_52w": 1253.2,
        "high_52w_date": datetime(2026, 1, 5),
        "low_52w_date": datetime(2026, 6, 11),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestGetMarketRatios:
    def test_returns_200_with_nse_ratios(self, client):
        """Happy path: NSE returns all fields, endpoint returns them as JSON."""
        from app.services import nse_client_async
        fake = _fake_stock_metadata()
        with patch.object(
            nse_client_async.nse_client_async, "get_stock_metadata",
            new=AsyncMock(return_value=fake),
        ):
            resp = client.get("/api/stockuniverse/RELIANCE/ratios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "RELIANCE"
        assert data["company_name"] == "Reliance Industries Limited"
        assert data["isin"] == "INE002A01018"
        assert data["symbol_pe"] == 18.86
        assert data["sector_pe"] == 18.86
        assert data["industry"] == "Refineries & Marketing"
        assert data["high_52w"] == 1611.8
        assert data["low_52w"] == 1253.2
        assert data["source"] == "NSE"

    def test_uppercases_symbol(self, client):
        from app.services import nse_client_async
        fake = _fake_stock_metadata(symbol="HDFCBANK")
        with patch.object(
            nse_client_async.nse_client_async, "get_stock_metadata",
            new=AsyncMock(return_value=fake),
        ) as mock_method:
            resp = client.get("/api/stockuniverse/hdfcbank/ratios")
        assert resp.status_code == 200
        assert resp.json()["symbol"] == "HDFCBANK"
        # The router called NSE with the uppercased symbol
        mock_method.assert_awaited_with("HDFCBANK")

    def test_404_when_nse_symbol_not_found(self, client):
        from app.services import nse_client_async
        from app.services.nse_client_async import SymbolNotFoundError
        with patch.object(
            nse_client_async.nse_client_async, "get_stock_metadata",
            new=AsyncMock(side_effect=SymbolNotFoundError("UNKNOWN", "not found")),
        ):
            resp = client.get("/api/stockuniverse/UNKNOWN/ratios")
        assert resp.status_code == 404

    def test_502_when_nse_request_fails(self, client):
        """Generic NSE failure (network, Akamai block, etc.) → 502 Bad Gateway."""
        from app.services import nse_client_async
        with patch.object(
            nse_client_async.nse_client_async, "get_stock_metadata",
            new=AsyncMock(side_effect=Exception("Connection refused")),
        ):
            resp = client.get("/api/stockuniverse/RELIANCE/ratios")
        assert resp.status_code == 502

    def test_handles_missing_optional_fields(self, client):
        """If NSE returns a StockUniverse with only some fields filled, the
        endpoint should still return 200 with the missing fields as null.
        This is important because smaller-cap stocks may not have 52W data
        or sector_pe in the NSE response.
        """
        from app.services import nse_client_async
        fake = _fake_stock_metadata(
            symbolPE=None, sectorPE=None, high_52w=None, low_52w=None,
            isin=None, companyName="Small Cap Co",
        )
        with patch.object(
            nse_client_async.nse_client_async, "get_stock_metadata",
            new=AsyncMock(return_value=fake),
        ):
            resp = client.get("/api/stockuniverse/RELIANCE/ratios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["company_name"] == "Small Cap Co"
        assert data["symbol_pe"] is None
        assert data["sector_pe"] is None
        assert data["high_52w"] is None
        assert data["low_52w"] is None

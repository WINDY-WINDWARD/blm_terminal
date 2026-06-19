"""Tests for the iinvest router.

Tests the public API surface of the iinvest integration:
  - /api/iinvest/health reports client state
  - /api/iinvest/path/{symbol} resolves a path (or 404)
  - /api/iinvest/{data-endpoint}/{symbol} returns the data (or 503)
  - /api/iinvest/all/{symbol} is the aggregator

Strategy: we monkeypatch ``get_iinvest_client`` so the router never
hits the real iinvest service. Each test injects the behavior it wants
to exercise (happy path, 503, 404).
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# A single module-level fake client. Tests mutate it before each request.
# This avoids the pytest fixture-instancing + closure capture pitfalls.
_fake_client = MagicMock()
_fake_client.is_authenticated = True
_fake_client.health = MagicMock(
    return_value={
        "configured": True,
        "healthy": True,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "last_error": None,
    }
)
_fake_client.resolve_path = AsyncMock(
    return_value=("INE002A01018", "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited")
)
for name in [
    "get_announcements", "get_auditors", "get_block_deals", "get_board_meetings",
    "get_capital_history", "get_corporate_actions", "get_financial_peer_filters",
    "get_financial_peers", "get_index_of_charges", "get_insider_trading",
    "get_key_shareholders", "get_legal_cases", "get_marketdata_timeseries",
    "get_pledged_shares", "get_sast", "get_tribunals", "get_news", "get_all",
]:
    setattr(_fake_client, name, AsyncMock(return_value={"status": True, "response": {"data": []}}))


@contextlib.contextmanager
def _using_fake_client():
    """Context manager that wires the fake client + clears the path cache."""
    from app.services import iinvest_client as mod
    from app.services.cache import iinvest_path_cache
    saved = mod.get_iinvest_client
    saved_singleton = mod._iinvest_client
    iinvest_path_cache.clear()
    mod._iinvest_client = _fake_client
    mod.get_iinvest_client = lambda: _fake_client
    try:
        yield _fake_client
    finally:
        mod.get_iinvest_client = saved
        mod._iinvest_client = saved_singleton


@pytest.fixture
def fake_client():
    """Returns the module-level fake client (mutated by tests)."""
    from app.services.cache import iinvest_path_cache
    iinvest_path_cache.clear()
    # Reset the data fetcher mocks to their default success
    for name in [
        "get_announcements", "get_auditors", "get_block_deals", "get_board_meetings",
        "get_capital_history", "get_corporate_actions", "get_financial_peer_filters",
        "get_financial_peers", "get_index_of_charges", "get_insider_trading",
        "get_key_shareholders", "get_legal_cases", "get_marketdata_timeseries",
        "get_pledged_shares", "get_sast", "get_tribunals", "get_news", "get_all",
    ]:
        getattr(_fake_client, name).reset_mock()
        getattr(_fake_client, name).return_value = {"status": True, "response": {"data": []}}
    _fake_client.is_authenticated = True
    _fake_client.resolve_path.reset_mock()
    _fake_client.resolve_path.return_value = (
        "INE002A01018",
        "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited",
    )
    return _fake_client


@pytest.fixture
def app(fake_client, monkeypatch):
    """Build a fresh FastAPI app with the iinvest router + fake client."""
    from app.services import iinvest_client as mod
    # Reset the module singleton so the router always gets our fake
    monkeypatch.setattr(mod, "_iinvest_client", _fake_client, raising=False)
    monkeypatch.setattr(mod, "get_iinvest_client", lambda: _fake_client)
    from app.routers.iinvest import router as iinvest_router
    app = FastAPI()
    # Mirror how main.py mounts it: router has prefix="/iinvest", main.py adds "/api"
    app.include_router(iinvest_router, prefix="/api")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Health ────────────────────────────────────────────────────────────────────


class TestIinvestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/api/iinvest/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["healthy"] is True
        assert "expires_at" in data


# ── Path resolution ──────────────────────────────────────────────────────────


class TestIinvestPath:
    def test_path_returns_200_with_isin_and_path(self, client):
        resp = client.get("/api/iinvest/path/RELIANCE")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "RELIANCE"
        assert data["isin"] == "INE002A01018"
        assert "reliance" in data["path"]

    def test_path_404_when_unresolvable(self, client, fake_client):
        fake_client.resolve_path = AsyncMock(return_value=(None, None))
        resp = client.get("/api/iinvest/path/UNKNOWN")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower() or "path" in resp.json()["detail"].lower()

    def test_path_uppercases_symbol(self, client, fake_client):
        resp = client.get("/api/iinvest/path/reliance")
        # Verify resolve_path was called with uppercased symbol
        fake_client.resolve_path.assert_awaited()
        call_args = fake_client.resolve_path.await_args
        assert call_args.args[0] == "RELIANCE"


# ── Data endpoints ───────────────────────────────────────────────────────────


class TestIinvestDataEndpoints:
    @pytest.mark.parametrize("endpoint_name", [
        "announcements", "auditors", "board-meetings", "capital-history",
        "insider-trading", "key-shareholders", "marketdata-timeseries",
        "pledged-shares", "sast",
    ])
    def test_path_based_endpoints_pass_resolved_path(self, client, fake_client, endpoint_name):
        resp = client.get(f"/api/iinvest/{endpoint_name}/RELIANCE")
        assert resp.status_code == 200
        # The right data fetcher was called with the resolved path
        method_name = "get_" + endpoint_name.replace("-", "_")
        method = getattr(fake_client, method_name)
        method.assert_awaited()
        # First positional arg should be the resolved path
        call_args = method.await_args
        assert call_args.args[0] == "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited"

    @pytest.mark.parametrize("endpoint_name,method_name", [
        ("legal-cases", "get_legal_cases"),
        ("index-of-charges", "get_index_of_charges"),
        ("tribunals", "get_tribunals"),
    ])
    def test_isin_based_endpoints_pass_isin(self, client, fake_client, endpoint_name, method_name):
        resp = client.get(f"/api/iinvest/{endpoint_name}/RELIANCE")
        assert resp.status_code == 200
        method = getattr(fake_client, method_name)
        method.assert_awaited()
        call_args = method.await_args
        # isin is the first positional arg in the fetcher calls
        assert call_args.args[0] == "INE002A01018"

    def test_news_endpoint(self, client, fake_client):
        resp = client.get("/api/iinvest/news/RELIANCE?limit=5")
        assert resp.status_code == 200
        fake_client.get_news.assert_awaited()
        call_args = fake_client.get_news.await_args
        assert call_args.args[0] == ["INE002A01018"]  # isins

    def test_503_when_client_unauthenticated(self, client, fake_client):
        """If is_authenticated is False, the router surfaces 503."""
        fake_client.is_authenticated = False
        fake_client.resolve_path = AsyncMock(side_effect=RuntimeError("not authenticated"))
        resp = client.get("/api/iinvest/announcements/RELIANCE")
        # When resolve_path raises, the router returns 503
        assert resp.status_code == 503

    def test_404_when_path_unresolvable(self, client, fake_client):
        fake_client.resolve_path = AsyncMock(return_value=(None, None))
        resp = client.get("/api/iinvest/announcements/UNKNOWN")
        assert resp.status_code == 404


# ── Aggregator ────────────────────────────────────────────────────────────────


class TestIinvestAggregator:
    def test_all_returns_dict_with_sections(self, client, fake_client):
        fake_client.get_all = AsyncMock(return_value={
            "announcements": {"data": []},
            "insider_trading": {"data": []},
        })
        resp = client.get("/api/iinvest/all/RELIANCE")
        assert resp.status_code == 200
        data = resp.json()
        assert "announcements" in data
        assert "insider_trading" in data
        fake_client.get_all.assert_awaited()


# ── Input validation ─────────────────────────────────────────────────────────


class TestIinvestValidation:
    def test_invalid_symbol_returns_422(self, client):
        resp = client.get("/api/iinvest/path/rel iance")  # space
        assert resp.status_code == 422

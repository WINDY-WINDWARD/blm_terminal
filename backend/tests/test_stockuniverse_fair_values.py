"""Tests for the database-backed fair-value batch endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers.stockuniverse import router as stockuniverse_router


class _Row:
    def __init__(self, symbol: str, fair_value: float | None, updated: datetime | None) -> None:
        self.symbol = symbol
        self.fair_value = fair_value
        self.fair_value_updated_at = updated
        self.morningstar_id = f"ms-{symbol}"


class _Result:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDb:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows

    async def execute(self, _query):
        return _Result(self.rows)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(stockuniverse_router, prefix="/api")

    rows = [
        _Row("TCS", 4200.0, datetime(2026, 11, 8, tzinfo=timezone.utc)),
        _Row("INFY", None, None),
    ]

    async def override_get_db():
        yield _FakeDb(rows)

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def test_returns_synced_fair_values(client: TestClient) -> None:
    resp = client.post(
        "/api/stockuniverse/fair-values/batch",
        json={"symbols": ["tcs", "INFY", "MISSING"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["TCS"]["fairValue"] == 4200.0
    assert data["TCS"]["morningstarId"] == "ms-TCS"
    assert data["INFY"]["fairValue"] is None
    assert "MISSING" not in data


def test_empty_symbols_returns_empty_object(client: TestClient) -> None:
    resp = client.post("/api/stockuniverse/fair-values/batch", json={"symbols": []})
    assert resp.status_code == 200
    assert resp.json() == {}


def test_accepts_a_100_symbol_batch(client: TestClient) -> None:
    symbols = [f"SYM{i:03d}" for i in range(100)]
    resp = client.post(
        "/api/stockuniverse/fair-values/batch",
        json={"symbols": symbols},
    )
    assert resp.status_code == 200
    assert resp.json()["TCS"]["fairValue"] == 4200.0


def test_rejects_more_than_the_batch_limit(client: TestClient) -> None:
    symbols = [f"SYM{i:03d}" for i in range(501)]
    resp = client.post(
        "/api/stockuniverse/fair-values/batch",
        json={"symbols": symbols},
    )
    assert resp.status_code == 422

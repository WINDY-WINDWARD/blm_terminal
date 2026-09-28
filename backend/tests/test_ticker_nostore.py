"""Tests for no-store chart backfill (extended history is never persisted).

Daily old-window fetches and 1h backward fills must serve NSE data without
writing to the DB: no backfill_symbol, no upsert_intraday for those windows.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.ticker_warehouse as warehouse


def _ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def app(monkeypatch):
    from app.routers.ticker import router as ticker_router

    app = FastAPI()
    app.include_router(ticker_router, prefix="/api")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _nse_row(ts_ms: int, base: float = 100.0) -> dict:
    return {
        "time_ms": ts_ms,
        "open": base,
        "high": base + 1,
        "low": base - 1,
        "close": base + 0.5,
        "volume": 1000,
    }


class TestDailyNoStore:
    def test_old_window_served_from_nse_without_db_write(self, client, monkeypatch):
        today = date.today()
        # Stored history covers only the last 30d; request starts 2y back.
        stored = [
            {
                "symbol": "RELIANCE",
                "date": today - timedelta(days=d),
                "series": "EQ",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 10,
                "value": 10.0,
                "source": "db",
            }
            for d in range(30)
        ]
        monkeypatch.setattr(
            warehouse, "get_ohlcv", lambda symbol, f, t: list(stored)
        )
        monkeypatch.setattr(
            warehouse, "get_latest_candle", lambda symbol: {"date": today}
        )
        monkeypatch.setattr(warehouse, "get_last_trading_day", lambda: today)

        backfill_calls: list = []
        monkeypatch.setattr(
            warehouse,
            "backfill_symbol",
            lambda symbol, days=365: backfill_calls.append((symbol, days)) or 0,
        )

        old_day = today - timedelta(days=400)
        old_ts = _ms(datetime(old_day.year, old_day.month, old_day.day))

        async def _fake_nse_daily(*a, **k):
            return [_nse_row(old_ts, 50.0)]

        monkeypatch.setattr(
            "app.routers.ticker.fetch_candles_async", _fake_nse_daily
        )

        from_d = (today - timedelta(days=730)).strftime("%d-%m-%Y")
        to_d = today.strftime("%d-%m-%Y")
        r = client.get(f"/api/ticker/ohlcv/RELIANCE?from_date={from_d}&to_date={to_d}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 31
        assert body["candles"][0]["close"] == 50.5  # NSE row prepended
        assert body["candles"][0]["source"] == "nse_charting_nostore"
        # No forward backfill scheduled (not stale) and no write path hit.
        assert backfill_calls == []

    def test_nse_failure_still_serves_db(self, client, monkeypatch):
        today = date.today()
        stored = [
            {
                "symbol": "TCS",
                "date": today - timedelta(days=1),
                "series": "EQ",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 2.0,
                "volume": 10,
                "value": 20.0,
                "source": "db",
            }
        ]
        monkeypatch.setattr(warehouse, "get_ohlcv", lambda symbol, f, t: list(stored))
        monkeypatch.setattr(
            warehouse, "get_latest_candle", lambda symbol: {"date": today}
        )
        monkeypatch.setattr(warehouse, "get_last_trading_day", lambda: today)

        async def _boom(*a, **k):
            raise RuntimeError("nse down")

        monkeypatch.setattr("app.routers.ticker.fetch_candles_async", _boom)

        from_d = (today - timedelta(days=730)).strftime("%d-%m-%Y")
        r = client.get(f"/api/ticker/ohlcv/TCS?from_date={from_d}")
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 1


class TestIntraday1hNoStore:
    def test_backward_fill_skips_upsert(self, client, monkeypatch):
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        old_ts = now_ms - 200 * 86400 * 1000  # ~200d back, older than 90d seed

        monkeypatch.setattr(warehouse, "get_intraday_latest", lambda s, i, n: {})
        monkeypatch.setattr(warehouse, "get_intraday", lambda s, i, **k: [])

        upserts: list = []
        monkeypatch.setattr(
            warehouse,
            "upsert_intraday",
            lambda s, i, rows: upserts.append((s, i, list(rows))),
        )

        async def _fake_fetch(symbol, interval, from_ts=0, to_ts=0):
            now_s = int(datetime.now(timezone.utc).timestamp())
            if from_ts < now_s - 100 * 86400:
                return [_nse_row(old_ts, 77.0)]
            return []

        monkeypatch.setattr("app.routers.ticker.fetch_candles_async", _fake_fetch)

        r = client.get(
            f"/api/ticker/intraday/RELIANCE?interval=1h&from_ts={old_ts}&to_ts={now_ms}"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1
        assert body["candles"][0]["close"] == 77.5
        # Forward delta fetch returned [] so nothing upserted at all, while
        # the backward window was still served: proof of no-store.
        assert upserts == []

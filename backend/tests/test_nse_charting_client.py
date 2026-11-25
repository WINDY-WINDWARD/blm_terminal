"""Tests for the NSE charting client's post-2026-11-13 API contract.

Covers: seconds-based intraday timeInterval, base64 date token,
API-frame (IST) window pass-through, raw time_ms pass-through, empty payload.
"""

import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services import nse_charting_client as client


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def captured_params(monkeypatch):
    """Patch requests.get and scripcode resolution; expose captured params."""
    state: dict = {"params": None}

    def fake_get(url, params=None, headers=None, timeout=None):
        state["params"] = params
        return _FakeResponse(
            {
                "status": True,
                "data": [
                    {
                        "time": 1795619400000,
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 7,
                    }
                ],
            }
        )

    monkeypatch.setattr("app.services.nse_charting_client.requests.get", fake_get)
    monkeypatch.setattr(
        "app.services.nse_charting_client.get_scripcode",
        lambda s, series=None: ("2885", "EQ"),
    )
    monkeypatch.setattr("app.services.nse_charting_client._rate_limit", lambda: None)
    return state


@pytest.mark.parametrize(
    "interval,expected_chart,expected_interval",
    [
        ("1m", "I", "60"),
        ("5m", "I", "300"),
        ("15m", "I", "900"),
        ("30m", "I", "1800"),
        ("1h", "I", "3600"),
        ("D", "D", "1"),
        ("W", "W", "1"),
        ("M", "M", "1"),
    ],
)
def test_interval_params_sent(
    captured_params, interval, expected_chart, expected_interval
):
    client.fetch_candles("RELIANCE", interval)

    assert captured_params["params"]["chartType"] == expected_chart
    assert captured_params["params"]["timeInterval"] == expected_interval


def test_token_is_base64_scripcode_and_ist_date(captured_params):
    client.fetch_candles("RELIANCE", "5m")

    today_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    expected = base64.b64encode(f"2885-{today_ist:%d%m%Y}".encode()).decode()
    assert captured_params["params"]["token"] == expected


def test_window_passes_through_in_api_frame(captured_params):
    client.fetch_candles("RELIANCE", "5m", from_ts=1000, to_ts=2000)

    # The client sends from_ts/to_ts unchanged: callers own the frame
    # conversion (api_now_s / to_api_s). This keeps from_ts=0 meaningful
    # for full-history W/M fetches and avoids a double shift.
    assert captured_params["params"]["fromDate"] == "1000"
    assert captured_params["params"]["toDate"] == "2000"


def test_default_to_ts_uses_api_now(captured_params):
    client.fetch_candles("RELIANCE", "5m")

    # None → current time in the API's IST frame.
    assert abs(int(captured_params["params"]["toDate"]) - client.api_now_s()) <= 5


def test_time_ms_passes_through_unchanged(captured_params):
    candles = client.fetch_candles("RELIANCE", "5m")

    assert len(candles) == 1
    assert candles[0]["time_ms"] == 1795619400000


def test_empty_payload_returns_empty_and_warns(monkeypatch, caplog):
    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse({"status": True, "data": []})

    monkeypatch.setattr("app.services.nse_charting_client.requests.get", fake_get)
    monkeypatch.setattr(
        "app.services.nse_charting_client.get_scripcode",
        lambda s, series=None: ("2885", "EQ"),
    )
    monkeypatch.setattr("app.services.nse_charting_client._rate_limit", lambda: None)

    with caplog.at_level(
        logging.WARNING, logger="app.services.nse_charting_client"
    ):
        result = client.fetch_candles("RELIANCE", "5m", from_ts=1000, to_ts=2000)

    assert result == []
    assert "returned 0 candles" in caplog.text

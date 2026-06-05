"""Tests for audit B.2 + B.3 — ``routers/announcements.py``.

B.2: replace the per-call ``requests.Session()`` with a module-shared
     ``httpx.AsyncClient`` pool (one TCP connection pool, persistent NSE
     cookie, no per-request connect cost).

B.3: the two URL fetches in ``_fetch_event_calendar_raw`` (main board +
     SME) must run concurrently via ``asyncio.gather`` instead of
     sequentially — this roughly halves the wall-clock cost of a cache
     miss.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.routers import announcements


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def reset_announcements_client() -> None:
    """Reset the module-level shared httpx client between tests.

    The router uses a lazy-initialised module-level client. After each
    test we tear it down so the next test gets a fresh one (and so
    monkeypatched behaviour does not leak).
    """
    announcements._close_shared_client()
    yield
    announcements._close_shared_client()


def _make_response(payload: list[dict] | str, status_code: int = 200) -> httpx.Response:
    """Build a real ``httpx.Response`` for the mock transport."""
    if isinstance(payload, list):
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
    else:
        body = payload.encode("utf-8") if isinstance(payload, str) else payload
        headers = {"content-type": "application/xml"}
    request = httpx.Request("GET", "https://example.invalid/")
    return httpx.Response(status_code, content=body, headers=headers, request=request)


def _mock_transport(handler):
    """Build an ``httpx.MockTransport`` from a sync handler function.

    The handler receives a ``httpx.Request`` and returns an
    ``httpx.Response``. Used to drive the shared client without real
    network I/O.
    """
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# B.2 — shared httpx.AsyncClient pool
# ---------------------------------------------------------------------------

class TestSharedAsyncClient:
    """The router must use ONE ``httpx.AsyncClient`` across calls."""

    def test_get_shared_client_returns_asyncclient_instance(
        self, reset_announcements_client
    ) -> None:
        client = announcements._get_shared_client()
        assert isinstance(client, httpx.AsyncClient)

    def test_get_shared_client_returns_same_instance(
        self, reset_announcements_client
    ) -> None:
        """A second call must return the cached client (singleton)."""
        a = announcements._get_shared_client()
        b = announcements._get_shared_client()
        assert a is b, "shared client must be a singleton"

    def test_close_shared_client_releases_instance(
        self, reset_announcements_client
    ) -> None:
        """After ``_close_shared_client`` the next ``_get_shared_client``
        returns a new instance, not the closed one."""
        a = announcements._get_shared_client()
        announcements._close_shared_client()
        b = announcements._get_shared_client()
        assert a is not b, "after close, a new client must be created"


# ---------------------------------------------------------------------------
# B.2 — fetch functions use the shared client (no per-call Session())
# ---------------------------------------------------------------------------

class TestFetchUsesSharedClient:
    """``_fetch_event_calendar_raw`` and ``_fetch_past_results_raw`` must
    route requests through the shared httpx client, not create their
    own ``requests.Session``."""

    def test_fetch_event_calendar_uses_shared_client(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both NSE event-calendar URLs are hit through the shared client
        (the module no longer imports sync ``requests``)."""
        client = announcements._get_shared_client()
        get_mock = AsyncMock(
            side_effect=[
                _make_response(
                    [
                        {
                            "symbol": "HDFCBANK",
                            "company": "HDFC Bank",
                            "purpose": "Board Meeting",
                            "bm_desc": "Quarterly results",
                            "date": "20-Apr-2026",
                        }
                    ]
                ),
                _make_response(
                    [
                        {
                            "bm_symbol": "SMEINFY",
                            "sm_name": "SME Infy",
                            "bm_purpose": "Board Meeting",
                            "bm_desc": "SME results",
                            "bm_date": "21-Apr-2026",
                        }
                    ]
                ),
            ]
        )
        monkeypatch.setattr(client, "get", get_mock)

        asyncio.run(announcements._fetch_event_calendar_raw())

        assert get_mock.await_count == 2, (
            "expected 2 calls to client.get (main + SME), "
            f"got {get_mock.await_count}"
        )
        # Both URLs must have been hit
        called_urls = [str(call.args[0]) for call in get_mock.call_args_list]
        assert any("event-calendar" in u and "sme" not in u for u in called_urls)
        assert any("event-calendar" in u and "sme" in u for u in called_urls)
        # The module must not import sync `requests` anymore.
        assert not hasattr(announcements, "requests"), (
            "announcements.py still imports `requests` — B.2 refactor incomplete"
        )

    def test_fetch_past_results_uses_shared_client(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = announcements._get_shared_client()
        get_mock = AsyncMock(
            return_value=_make_response(
                [
                    {
                        "symbol": "HDFCBANK",
                        "company": "HDFC Bank",
                        "purpose": "Financial Results",
                        "bm_desc": "Q4 results",
                        "date": "20-Apr-2026",
                    }
                ]
            )
        )
        monkeypatch.setattr(client, "get", get_mock)

        asyncio.run(announcements._fetch_past_results_raw())

        assert get_mock.await_count == 1

    def test_get_announcements_uses_shared_client(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The async RSS endpoint must also route through the shared
        client, not call ``requests.get`` directly."""
        client = announcements._get_shared_client()
        get_mock = AsyncMock(
            return_value=_make_response(
                "<rss><channel><title>test</title></channel></rss>",
            )
        )
        monkeypatch.setattr(client, "get", get_mock)

        loop = asyncio.new_event_loop()
        try:
            response = loop.run_until_complete(
                announcements.get_announcements()
            )
        finally:
            loop.close()

        assert get_mock.await_count == 1
        # The streaming response must wrap the XML body
        assert response.media_type == "application/rss+xml"


# ---------------------------------------------------------------------------
# B.3 — concurrent fetch via asyncio.gather
# ---------------------------------------------------------------------------

class TestConcurrentFetch:
    """The two URLs in ``_fetch_event_calendar_raw`` must be fetched
    concurrently. We assert this by giving each side-effect a 200ms
    sleep and checking that the total wall time is ~200ms, not ~400ms.
    """

    def test_main_and_sme_fetched_concurrently(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = announcements._get_shared_client()

        async def slow_get(url: str, **kwargs: Any) -> httpx.Response:
            await asyncio.sleep(0.2)
            if "sme" in url:
                return _make_response(
                    [
                        {
                            "bm_symbol": "SMEINFY",
                            "sm_name": "SME Infy",
                            "bm_purpose": "Board Meeting",
                            "bm_desc": "SME results",
                            "bm_date": "21-Apr-2026",
                        }
                    ]
                )
            return _make_response(
                [
                    {
                        "symbol": "HDFCBANK",
                        "company": "HDFC Bank",
                        "purpose": "Board Meeting",
                        "bm_desc": "Quarterly results",
                        "date": "20-Apr-2026",
                    }
                ]
            )

        monkeypatch.setattr(client, "get", slow_get)

        t0 = time.monotonic()
        asyncio.run(announcements._fetch_event_calendar_raw())
        elapsed = time.monotonic() - t0

        # If sequential: ~0.4s. If concurrent: ~0.2s. Allow 50ms slack.
        assert elapsed < 0.30, (
            f"main+SME fetches took {elapsed:.3f}s — looks sequential, "
            "expected ~0.2s with asyncio.gather"
        )

    def test_one_endpoint_failure_does_not_break_other(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If NSE returns 500 for main-board, the SME result must still
        appear in the merged list (no short-circuit on first failure)."""
        client = announcements._get_shared_client()

        async def flaky_get(url: str, **kwargs: Any) -> httpx.Response:
            if "sme" in url:
                return _make_response(
                    [
                        {
                            "bm_symbol": "SMEINFY",
                            "sm_name": "SME Infy",
                            "bm_purpose": "Board Meeting",
                            "bm_desc": "SME results",
                            "bm_date": "21-Apr-2026",
                        }
                    ]
                )
            # Main board blows up
            return _make_response([], status_code=500)

        monkeypatch.setattr(client, "get", flaky_get)

        items = asyncio.run(announcements._fetch_event_calendar_raw())
        # SME item should still be in the merged list
        assert any(item.symbol == "SMEINFY" for item in items), (
            "SME result lost when main-board failed — gather must use "
            "return_exceptions=True or per-task error handling"
        )


# ---------------------------------------------------------------------------
# Behavioural parity — same output for the same NSE responses
# ---------------------------------------------------------------------------

class TestBehaviorParity:
    """The refactor must not change the shape of the returned data."""

    def test_main_and_sme_results_merged_and_deduped(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = announcements._get_shared_client()
        get_mock = AsyncMock(
            side_effect=[
                _make_response(
                    [
                        {
                            "symbol": "HDFCBANK",
                            "company": "HDFC Bank",
                            "purpose": "Board Meeting",
                            "bm_desc": "Quarterly results",
                            "date": "20-Apr-2026",
                        },
                        {
                            "symbol": "INFY",
                            "company": "Infosys",
                            "purpose": "Board Meeting",
                            "bm_desc": "Quarterly results",
                            "date": "21-Apr-2026",
                        },
                    ]
                ),
                _make_response(
                    [
                        {
                            "bm_symbol": "SMEINFY",
                            "sm_name": "SME Infy",
                            "bm_purpose": "Board Meeting",
                            "bm_desc": "SME results",
                            "bm_date": "22-Apr-2026",
                        }
                    ]
                ),
            ]
        )
        monkeypatch.setattr(client, "get", get_mock)

        items = asyncio.run(announcements._fetch_event_calendar_raw())
        symbols = sorted(item.symbol for item in items)
        assert symbols == ["HDFCBANK", "INFY", "SMEINFY"]

    def test_past_results_filtered_to_financial_results(
        self, reset_announcements_client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = announcements._get_shared_client()
        get_mock = AsyncMock(
            return_value=_make_response(
                [
                    {
                        "symbol": "HDFCBANK",
                        "company": "HDFC Bank",
                        "purpose": "Financial Results",
                        "bm_desc": "Q4 results",
                        "date": "20-Apr-2026",
                    },
                    {
                        "symbol": "INFY",
                        "company": "Infosys",
                        "purpose": "Board Meeting",  # NOT results — filtered
                        "bm_desc": "Quarterly",
                        "date": "21-Apr-2026",
                    },
                ]
            )
        )
        monkeypatch.setattr(client, "get", get_mock)

        items = asyncio.run(announcements._fetch_past_results_raw())
        assert [item.symbol for item in items] == ["HDFCBANK"]

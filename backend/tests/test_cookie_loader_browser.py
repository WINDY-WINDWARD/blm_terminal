"""Tests for audit B.6 — extract cookie loader from screener/morningstar clients.

The two HTTP clients (screener_client.py, morningstar_client.py) each
have a near-identical "load cookies from pickle, fall back to
rookiepy(Chrome|Firefox)" routine.  This test verifies that
``cookie_loader.load_browser_cookies(service, domain, allowed_names)``
behaves correctly so both clients can delegate to it.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

from app.services import cookie_loader


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _cookie(name: str, value: str, **extras: Any) -> dict[str, Any]:
    """Build a rookiepy-style cookie dict."""
    out: dict[str, Any] = {"name": name, "value": value}
    out.update(extras)
    return out


# ---------------------------------------------------------------------------
# Pickle-first path
# ---------------------------------------------------------------------------

class TestPickleFirst:
    """When the pickle file has cookies with the allowed names, return
    them straight away (skip rookiepy)."""

    def test_returns_pickle_cookies_when_allowed_names_match(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        pickle_cookies = [
            _cookie("sessionid", "abc123"),
            _cookie("csrftoken", "def456"),
            _cookie("other", "skip_me"),
        ]
        monkeypatch.setattr(
            cookie_loader, "load_cookies_from_pickle", lambda s: pickle_cookies
        )
        # rookiepy should NOT be touched
        def boom(*a, **kw):
            raise AssertionError("rookiepy should not be called when pickle works")

        sys.modules["rookiepy"] = type(sys)("rookiepy")
        sys.modules["rookiepy"].chrome = boom
        sys.modules["rookiepy"].firefox = boom

        result = cookie_loader.load_browser_cookies(
            service="screener",
            domain="screener.in",
            allowed_names=["sessionid", "csrftoken"],
        )
        assert result == {"sessionid": "abc123", "csrftoken": "def456"}

    def test_falls_back_to_rookiepy_when_pickle_missing_sessionid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """screener needs a sessionid; if pickle has cookies but no
        sessionid, fall back to browser extraction."""
        monkeypatch.setattr(
            cookie_loader,
            "load_cookies_from_pickle",
            lambda s: [_cookie("irrelevant", "x")],
        )
        sys.modules["rookiepy"] = type(sys)("rookiepy")
        sys.modules["rookiepy"].chrome = lambda domains: [
            _cookie("sessionid", "from_chrome"),
            _cookie("csrftoken", "tok_chrome"),
        ]
        sys.modules["rookiepy"].firefox = lambda domains: []

        result = cookie_loader.load_browser_cookies(
            service="screener",
            domain="screener.in",
            allowed_names=["sessionid", "csrftoken"],
        )
        assert result == {"sessionid": "from_chrome", "csrftoken": "tok_chrome"}

    def test_returns_all_cookies_when_allowed_names_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """morningstar wants every cookie (no filter)."""
        pickle_cookies = [
            _cookie("a", "1"),
            _cookie("b", "2"),
            _cookie("c", "3"),
        ]
        monkeypatch.setattr(
            cookie_loader, "load_cookies_from_pickle", lambda s: pickle_cookies
        )

        result = cookie_loader.load_browser_cookies(
            service="morningstar",
            domain="morningstar.in",
            allowed_names=None,
        )
        assert result == {"a": "1", "b": "2", "c": "3"}


# ---------------------------------------------------------------------------
# Browser-fallback path
# ---------------------------------------------------------------------------

class TestBrowserFallback:
    """Pickle absent → try Chrome, then Firefox."""

    def test_chrome_used_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)
        sys.modules["rookiepy"] = type(sys)("rookiepy")
        chrome_called = {"n": 0}
        firefox_called = {"n": 0}

        def chrome(domains):
            chrome_called["n"] += 1
            return [_cookie("sessionid", "ch")]

        def firefox(domains):
            firefox_called["n"] += 1
            return []

        sys.modules["rookiepy"].chrome = chrome
        sys.modules["rookiepy"].firefox = firefox

        result = cookie_loader.load_browser_cookies(
            service="screener", domain="screener.in", allowed_names=["sessionid"]
        )
        assert result == {"sessionid": "ch"}
        assert chrome_called["n"] == 1
        assert firefox_called["n"] == 0, "firefox should not be tried if chrome worked"

    def test_firefox_used_when_chrome_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)
        sys.modules["rookiepy"] = type(sys)("rookiepy")
        sys.modules["rookiepy"].chrome = lambda domains: []
        sys.modules["rookiepy"].firefox = lambda domains: [_cookie("sessionid", "ff")]

        result = cookie_loader.load_browser_cookies(
            service="screener", domain="screener.in", allowed_names=["sessionid"]
        )
        assert result == {"sessionid": "ff"}

    def test_browser_exception_skipped_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If one browser raises (e.g. locked DB on macOS), try the next."""
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)
        sys.modules["rookiepy"] = type(sys)("rookiepy")

        def boom(domains):
            raise RuntimeError("browser locked")

        sys.modules["rookiepy"].chrome = boom
        sys.modules["rookiepy"].firefox = lambda domains: [_cookie("sessionid", "ff")]

        result = cookie_loader.load_browser_cookies(
            service="screener", domain="screener.in", allowed_names=["sessionid"]
        )
        assert result == {"sessionid": "ff"}


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------

class TestEmptyResult:
    def test_empty_dict_when_nothing_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)
        sys.modules["rookiepy"] = type(sys)("rookiepy")
        sys.modules["rookiepy"].chrome = lambda domains: []
        sys.modules["rookiepy"].firefox = lambda domains: []

        result = cookie_loader.load_browser_cookies(
            service="screener", domain="screener.in", allowed_names=["sessionid"]
        )
        assert result == {}

    def test_empty_dict_when_pickle_none_and_browser_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No filter (morningstar case) — empty when nothing found."""
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)
        sys.modules["rookiepy"] = type(sys)("rookiepy")
        sys.modules["rookiepy"].chrome = lambda domains: []
        sys.modules["rookiepy"].firefox = lambda domains: []

        result = cookie_loader.load_browser_cookies(
            service="morningstar", domain="morningstar.in", allowed_names=None
        )
        assert result == {}

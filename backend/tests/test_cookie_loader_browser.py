"""Tests for audit B.6 — cookie loader from pickle files.

rookiepy live extraction was removed for legal safety; cookie_loader now
safely loads pre-exported pickle files only.
"""

from __future__ import annotations

from typing import Any
import pytest

from app.services import cookie_loader


def _cookie(name: str, value: str, **extras: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "value": value}
    out.update(extras)
    return out


class TestPickleFirst:
    """Pickle path returns cookie dict."""

    def test_prefers_pickle_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pickle_cookies = [
            _cookie("sessionid", "from_pickle"),
            _cookie("csrftoken", "tok_pickle"),
            _cookie("other", "ignore_me"),
        ]
        monkeypatch.setattr(
            cookie_loader, "load_cookies_from_pickle", lambda s: pickle_cookies
        )

        result = cookie_loader.load_browser_cookies(
            service="screener",
            domain="screener.in",
            allowed_names=["sessionid", "csrftoken"],
        )
        assert result == {"sessionid": "from_pickle", "csrftoken": "tok_pickle"}

    def test_returns_empty_when_pickle_missing_sessionid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """screener needs a sessionid; if pickle has no sessionid, return empty."""
        monkeypatch.setattr(
            cookie_loader,
            "load_cookies_from_pickle",
            lambda s: [_cookie("irrelevant", "x")],
        )

        result = cookie_loader.load_browser_cookies(
            service="screener",
            domain="screener.in",
            allowed_names=["sessionid", "csrftoken"],
        )
        assert result == {}

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


class TestEmptyResult:
    def test_empty_dict_when_nothing_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)

        result = cookie_loader.load_browser_cookies(
            service="screener", domain="screener.in", allowed_names=["sessionid"]
        )
        assert result == {}

    def test_empty_dict_when_pickle_none_and_browser_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cookie_loader, "load_cookies_from_pickle", lambda s: None)

        result = cookie_loader.load_browser_cookies(
            service="morningstar", domain="morningstar.in", allowed_names=None
        )
        assert result == {}

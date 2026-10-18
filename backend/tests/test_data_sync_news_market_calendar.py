"""Tests for news + market + calendar sync core extractions (audit C.1, A.11 part 2).

Moves 3 sections (12 functions + 5 constants) from
``app/backgroundtasks/_impl.py`` into 3 new modules under
``app/services/data_sync/``:

- ``news.py`` (7 functions + 3 constants):
  - ``_crawl_news_async`` — async helper: crawl + store global news
  - ``_news_sync`` — sync wrapper for the initial crawl
  - ``_news_periodic_sync`` — single periodic news crawl with
    exponential backoff on empty result
  - ``_news_rss_sync`` — fetch + store from all RSS sources (sync)
  - ``_news_rss_sync_async`` — async version of RSS sync
  - ``_fetch_company_news_async`` — async helper: fetch news for
    a single symbol
  - ``_watchlist_news_sync`` — refresh news for every symbol on
    every watchlist
  - ``NEWS_CRON`` — every-5-minutes cron string
  - ``NEWS_CRAWL_MAX_INTERVAL`` — backoff ceiling (30 min)
  - ``WATCHLIST_NEWS_STALE_SECONDS`` — skip re-fetch if a
    symbol's news is fresher than 5 min

- ``market.py`` (4 functions):
  - ``_is_market_open`` — bool: is the NSE market currently open?
  - ``_seconds_until_market_open`` — float: how long until the
    next market open
  - ``_refresh_market_data_async`` — async helper: refresh
    industry + sector data from MoneyControl
  - ``_market_data_sync`` — sync wrapper

- ``calendar.py`` (1 function + 1 constant):
  - ``_results_calendar_sync`` — Fetch the NSE event calendar
    and create 'results_upcoming' notifications
  - ``_RESULTS_CALENDAR_CRON`` — "15 9,14 * * 1-5" cron

Each module uses the lazy-import pattern via
``app.backgroundtasks._runtime`` to avoid circular imports.

Tests pin the refactor invariants per module home:

- The module file is small (Pattern I).
- Each function now lives in its new home (``__module__``).
- The function is the SAME object (``is``) as its backgroundtasks
  re-export (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` still works.
- The function is NOT in ``_impl`` anymore
  (TestMovedWorkers contract).
- The function signature is preserved.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Module size regression checks (Pattern I)
# ---------------------------------------------------------------------------


class TestNewsModuleSize:
    def test_news_file_under_400_loc(self):
        path = ROOT / "app" / "services" / "data_sync" / "news.py"
        assert path.exists(), f"news.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # 7 functions, ~230 LOC for the bodies.  Allow 400 for
        # imports + docstring + lazy-resolve helpers.
        assert loc < 400, (
            f"news.py is {loc} LOC, expected < 400.  If you added "
            f"more, move it to a sibling module."
        )


class TestMarketModuleSize:
    def test_market_file_under_200_loc(self):
        path = ROOT / "app" / "services" / "data_sync" / "market.py"
        assert path.exists(), f"market.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # 4 functions, ~80 LOC for the bodies.  Allow 200 for
        # imports + docstring + lazy-resolve helpers.
        assert loc < 200, (
            f"market.py is {loc} LOC, expected < 200.  If you added "
            f"more, move it to a sibling module."
        )


class TestCalendarModuleSize:
    def test_calendar_file_under_250_loc(self):
        path = ROOT / "app" / "services" / "data_sync" / "calendar.py"
        assert path.exists(), f"calendar.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # 1 function, ~130 LOC for the body.  Allow 250 for imports
        # + docstring + lazy-resolve helpers.
        assert loc < 250, (
            f"calendar.py is {loc} LOC, expected < 250.  If you added "
            f"more, move it to a sibling module."
        )


# ---------------------------------------------------------------------------
# News module — function homes, identity, signatures
# ---------------------------------------------------------------------------


NEWS_FUNCTIONS = [
    "_crawl_news_async",
    "_news_sync",
    "_news_periodic_sync",
    "_news_rss_sync",
    "_news_rss_sync_async",
    "_fetch_company_news_async",
    "_watchlist_news_sync",
]

NEWS_CONSTANTS = [
    "NEWS_CRON",
    "NEWS_CRAWL_MAX_INTERVAL",
    "WATCHLIST_NEWS_STALE_SECONDS",
]


class TestNewsCoreExtraction:
    """The news sync cores now live in app.services.data_sync.news."""

    @pytest.mark.parametrize("name", NEWS_FUNCTIONS)
    def test_function_lives_in_news_module(self, name: str):
        from app.services.data_sync import news as news_mod

        fn = getattr(news_mod, name)
        assert fn.__module__ == "app.services.data_sync.news", (
            f"Expected {name}.__module__ to be "
            f"'app.services.data_sync.news', got {fn.__module__!r}"
        )

    @pytest.mark.parametrize("name", NEWS_FUNCTIONS)
    def test_function_importable_from_backgroundtasks_shim(self, name: str):
        """Existing callers use ``from app.backgroundtasks import <name>``.
        The shim must re-export it with is-identity to the new home."""
        from app import backgroundtasks as bg
        from app.services.data_sync import news as news_mod

        bg_fn = getattr(bg, name)
        new_fn = getattr(news_mod, name)
        assert bg_fn is new_fn, (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.news.{name} — re-export broken"
        )

    def test_news_constants_preserved(self):
        from app.services.data_sync import news as news_mod

        assert news_mod.NEWS_CRON == "*/5 * * * *"
        assert news_mod.NEWS_CRAWL_MAX_INTERVAL == 30 * 60
        assert news_mod.WATCHLIST_NEWS_STALE_SECONDS == 5 * 60

    @pytest.mark.parametrize("name", NEWS_CONSTANTS)
    def test_news_constants_importable_from_shim(self, name: str):
        from app import backgroundtasks as bg
        from app.services.data_sync import news as news_mod

        assert getattr(bg, name) is getattr(news_mod, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.news.{name}"
        )

    @pytest.mark.parametrize("name", NEWS_FUNCTIONS)
    def test_news_function_is_callable(self, name: str):
        from app.services.data_sync import news as news_mod

        assert callable(getattr(news_mod, name)), (
            f"app.services.data_sync.news.{name} should be callable"
        )

    def test_news_sync_signature(self):
        """The function takes no args (worker calls it positionally)."""
        from app.services.data_sync.news import _news_sync

        sig = inspect.signature(_news_sync)
        assert list(sig.parameters) == [], (
            f"_news_sync parameters changed: {list(sig.parameters)}"
        )

    def test_news_periodic_sync_signature(self):
        from app.services.data_sync.news import _news_periodic_sync

        sig = inspect.signature(_news_periodic_sync)
        assert list(sig.parameters) == ["backoff_secs"], (
            f"_news_periodic_sync parameters changed: {list(sig.parameters)}"
        )

    def test_crawl_news_async_signature(self):
        from app.services.data_sync.news import _crawl_news_async

        sig = inspect.signature(_crawl_news_async)
        assert list(sig.parameters) == ["pages"], (
            f"_crawl_news_async parameters changed: {list(sig.parameters)}"
        )

    def test_fetch_company_news_async_signature(self):
        from app.services.data_sync.news import _fetch_company_news_async

        sig = inspect.signature(_fetch_company_news_async)
        assert list(sig.parameters) == ["symbol"], (
            f"_fetch_company_news_async parameters changed: {list(sig.parameters)}"
        )


# ---------------------------------------------------------------------------
# Market module — function homes, identity, signatures
# ---------------------------------------------------------------------------


MARKET_FUNCTIONS = [
    "_is_market_open",
    "_seconds_until_market_open",
    "_refresh_market_data_async",
    "_market_data_sync",
]


class TestMarketCoreExtraction:
    """The market sync cores now live in app.services.data_sync.market."""

    @pytest.mark.parametrize("name", MARKET_FUNCTIONS)
    def test_function_lives_in_market_module(self, name: str):
        from app.services.data_sync import market as market_mod

        fn = getattr(market_mod, name)
        assert fn.__module__ == "app.services.data_sync.market", (
            f"Expected {name}.__module__ to be "
            f"'app.services.data_sync.market', got {fn.__module__!r}"
        )

    @pytest.mark.parametrize("name", MARKET_FUNCTIONS)
    def test_function_importable_from_backgroundtasks_shim(self, name: str):
        from app import backgroundtasks as bg
        from app.services.data_sync import market as market_mod

        bg_fn = getattr(bg, name)
        new_fn = getattr(market_mod, name)
        assert bg_fn is new_fn, (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.market.{name} — re-export broken"
        )

    @pytest.mark.parametrize("name", MARKET_FUNCTIONS)
    def test_market_function_is_callable(self, name: str):
        from app.services.data_sync import market as market_mod

        assert callable(getattr(market_mod, name)), (
            f"app.services.data_sync.market.{name} should be callable"
        )

    def test_is_market_open_returns_bool(self):
        from app.services.data_sync.market import _is_market_open

        result = _is_market_open()
        assert isinstance(result, bool), (
            f"_is_market_open() returned {type(result).__name__}, "
            f"expected bool"
        )

    def test_seconds_until_market_open_returns_float(self):
        from app.services.data_sync.market import _seconds_until_market_open

        result = _seconds_until_market_open()
        assert isinstance(result, float), (
            f"_seconds_until_market_open() returned "
            f"{type(result).__name__}, expected float"
        )
        assert result > 0, (
            f"_seconds_until_market_open() returned {result}, "
            f"expected positive (the next market open is in the future)"
        )


# ---------------------------------------------------------------------------
# Calendar module — function home, identity, signature
# ---------------------------------------------------------------------------


class TestCalendarCoreExtraction:
    """The results calendar sync core now lives in
    app.services.data_sync.calendar.
    """

    def test_function_lives_in_calendar_module(self):
        from app.services.data_sync.calendar import _results_calendar_sync

        assert _results_calendar_sync.__module__ == (
            "app.services.data_sync.calendar"
        ), (
            f"Expected _results_calendar_sync.__module__ to be "
            f"'app.services.data_sync.calendar', got "
            f"{_results_calendar_sync.__module__!r}"
        )

    def test_function_importable_from_backgroundtasks_shim(self):
        from app.backgroundtasks import _results_calendar_sync as bg_fn
        from app.services.data_sync.calendar import (
            _results_calendar_sync as new_fn,
        )

        assert bg_fn is new_fn, (
            "app.backgroundtasks._results_calendar_sync is not the same "
            "object as app.services.data_sync.calendar."
            "_results_calendar_sync — re-export broken"
        )

    def test_function_signature_preserved(self):
        from app.services.data_sync.calendar import _results_calendar_sync

        sig = inspect.signature(_results_calendar_sync)
        assert list(sig.parameters) == [], (
            f"_results_calendar_sync parameters changed: "
            f"{list(sig.parameters)}"
        )

    def test_results_calendar_cron_preserved(self):
        from app.services.data_sync.calendar import _RESULTS_CALENDAR_CRON

        # Pin the cron string — workers depend on this exact value.
        assert _RESULTS_CALENDAR_CRON == "15 9,14 * * 1-5", (
            f"_RESULTS_CALENDAR_CRON is {_RESULTS_CALENDAR_CRON!r}, "
            f"expected '15 9,14 * * 1-5'"
        )

    def test_results_calendar_cron_importable_from_shim(self):
        from app.backgroundtasks import (
            _RESULTS_CALENDAR_CRON as bg_const,
        )
        from app.services.data_sync.calendar import (
            _RESULTS_CALENDAR_CRON as new_const,
        )

        assert bg_const is new_const

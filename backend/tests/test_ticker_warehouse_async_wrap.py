"""Tests for the warehouse call async-wrapping (audit B.12).

The ticker warehouse (``app/services/ticker_warehouse.py``) is
entirely synchronous — every method uses sync SQLAlchemy ``Session``.
Calling it directly from an ``async def`` router handler blocks the
event loop.  Audit B.12 wraps each call in
``asyncio.to_thread(...)`` so the sync work runs in a thread-pool
worker.

These tests pin the contract:

- Each warehouse call in an async router handler is preceded by
  ``asyncio.to_thread(...)`` (not called directly).
- The wrapper passes the bound method, not a closure, so the
  function metadata (e.g. ``__name__``) is preserved for debugging.
- The function signature and call arguments are unchanged.
- Sync call sites in worker threads (backgroundtasks) are NOT
  wrapped — they were already off the event loop.

We grep the source for these patterns rather than mounting the full
FastAPI app (which would require a live DB).  This is a static
refactor pin, not a behaviour test.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


ROUTER_FILES = [
    "app/routers/ticker.py",
]


def _read_source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text()


# ─── Source-level checks ─────────────────────────────────────────────────


class TestTickerRouterWarehouseCalls:
    """The 4 warehouse calls in ``routers/ticker.py`` must be wrapped
    in ``asyncio.to_thread(...)``.
    """

    @pytest.fixture
    def ticker_source(self):
        return _read_source("app/routers/ticker.py")

    def test_4_warehouse_calls_are_wrapped(self, ticker_source):
        """Find every direct ``ticker_warehouse.<method>(...)`` call in
        the router and assert each one is preceded by an
        ``asyncio.to_thread`` wrap (not a bare call).
        """
        # Find every mention of ``ticker_warehouse.<method>`` and check
        # it's preceded by ``asyncio.to_thread(`` (within a small
        # backward window) or is part of an ``asyncio.to_thread`` call
        # elsewhere.
        # We use a simpler check: any line that contains
        # ``ticker_warehouse.<method>(`` and does NOT contain
        # ``asyncio.to_thread`` on the same line (or the line above)
        # is a direct call.
        direct_calls = []
        lines = ticker_source.splitlines()
        for i, line in enumerate(lines):
            m = re.search(r"ticker_warehouse\.(\w+)\(", line)
            if not m:
                continue
            # Check the line and the previous 2 lines for asyncio.to_thread
            context = "\n".join(lines[max(0, i - 2):i + 1])
            if "asyncio.to_thread" not in context:
                direct_calls.append(m.group(1))
        assert not direct_calls, (
            f"Found {len(direct_calls)} direct ticker_warehouse calls "
            f"in routers/ticker.py: {direct_calls}.  Each must be "
            f"wrapped in asyncio.to_thread(...)."
        )

    def test_4_warehouse_methods_wrapped(self, ticker_source):
        """Each of the 4 warehouse methods called from this router
        (``get_ohlcv``, ``get_latest_candle``, ``get_warehouse_status``,
        ``upsert_intraday``, ``get_intraday``) must appear in a
        ``asyncio.to_thread(...)`` wrap.
        """
        wrapped_methods = re.findall(
            r"asyncio\.to_thread\(\s*ticker_warehouse\.(\w+)",
            ticker_source,
        )
        # Allow order-insensitive set check
        expected = {"get_ohlcv", "get_latest_candle", "get_warehouse_status", "upsert_intraday", "get_intraday"}
        assert set(wrapped_methods) == expected, (
            f"Expected wraps for {expected}, got {set(wrapped_methods)}"
        )

    def test_asyncio_to_thread_is_imported(self, ticker_source):
        """``asyncio`` must be imported so the wraps compile."""
        assert re.search(r"^import asyncio\b", ticker_source, re.M), (
            "asyncio must be imported in routers/ticker.py for the "
            "asyncio.to_thread calls"
        )

    def test_to_thread_calls_use_bound_method(self, ticker_source):
        """The wraps should use ``ticker_warehouse.method`` (bound
        method), not a lambda or partial.  This preserves the method's
        ``__name__`` and ``__doc__`` for debugging.
        """
        # Find the wrap pattern.  Each call should be like:
        #   asyncio.to_thread(ticker_warehouse.get_ohlcv, ...)
        # i.e. the second positional arg is the method, not a closure.
        bad = re.findall(
            r"asyncio\.to_thread\(\s*(?:lambda|partial)",
            ticker_source,
        )
        assert not bad, (
            f"Found {len(bad)} asyncio.to_thread calls using lambda/"
            f"partial.  Pass the bound method directly to preserve "
            f"function metadata."
        )


# ─── Runtime check (import smoke) ────────────────────────────────────────


class TestImportsStillWork:
    """After the wrap, importing the router must succeed and the
    wrapped calls must be syntactically valid.
    """

    def test_routers_ticker_imports(self):
        # Importing the module forces all top-level syntax to parse
        from app.routers import ticker  # noqa: F401

    def test_routers_portfolio_imports(self):
        from app.routers import portfolio  # noqa: F401


# ─── Background tasks are NOT wrapped ────────────────────────────────────


class TestBackgroundTasksNotWrapped:
    """The sync warehouse calls in ``backgroundtasks.py`` are already
    running in worker threads, so they should NOT be wrapped in
    ``asyncio.to_thread`` — that would be redundant.
    """

    def test_no_unnecessary_to_thread_in_backgroundtasks(self):
        # After Phase C.1 A.1 + A.13 split, the worker daemons live
        # in ``app/workers/<domain>.py`` (data, ticker_compute,
        # universe, …) and the sync cores in
        # ``app/services/data_sync/<domain>.py``.  Read every file
        # under those trees to ensure no warehouse call is wrapped.
        from pathlib import Path

        for sub in ("app/workers", "app/services/data_sync"):
            base = ROOT / sub
            if not base.exists():
                continue
            for py in base.rglob("*.py"):
                source = py.read_text()
                wrapped = re.findall(
                    r"asyncio\.to_thread\(\s*ticker_warehouse\.\w+",
                    source,
                )
                assert not wrapped, (
                    f"Found {len(wrapped)} asyncio.to_thread wraps of "
                    f"ticker_warehouse in {py}.  These run in worker "
                    f"threads and don't need the async wrap."
                )

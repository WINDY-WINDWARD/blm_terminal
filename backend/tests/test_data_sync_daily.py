"""Tests for the daily update sync core extraction (audit C.1, A.6).

Moves 1 function from ``app/backgroundtasks/_impl.py`` into
``app/services/data_sync/daily.py``:

- ``_ticker_daily_update_sync()`` — post-market bhavcopy fetch
  for the last 5 weekdays, with watchlist-staleness fallback via
  equity_history.  Triggers the indicator-notification and scores
  cycles on successful inserts.

Tests pin the refactor invariants:

- ``daily.py`` is a small file (Pattern I: < 300 LOC).
- The function now lives in ``app.services.data_sync.daily``
  (``__module__`` attribute).
- It is the SAME object (``is``) as its backgroundtasks
  re-export (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` still works.
- All current callers (orchestrator) still work.
- The function is importable from BOTH the new module and the
  old package (the bridge shim).
- The function signature is preserved.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestDailyModuleSize:
    """``daily.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_daily_file_under_300_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "daily.py"
        )
        assert path.exists(), f"daily.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # _ticker_daily_update_sync is ~156 LOC.  Allow 300 for imports +
        # docstring + lazy-resolve helpers.
        assert loc < 300, (
            f"daily.py is {loc} LOC, expected < 300.  This file "
            f"should only contain the daily update sync core + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_FUNCTIONS = [
    "_ticker_daily_update_sync",
]


class TestFunctionsMovedToDaily:
    """The function must have ``__module__ == 'app.services.data_sync.daily'``."""

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_function_lives_in_daily_module(self, name):
        from app.services.data_sync import daily

        assert hasattr(daily, name), (
            f"daily.{name} not found — the move was incomplete"
        )
        fn = getattr(daily, name)
        assert fn.__module__ == "app.services.data_sync.daily", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.services.data_sync.daily'.  The function was "
            f"not moved (or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The function in ``daily`` must be the SAME object as
    its ``app.backgroundtasks`` re-export.
    """

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_daily_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.services.data_sync import daily

        assert getattr(bg, name) is getattr(daily, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.daily.{name} — the re-export "
            f"is broken or the function was re-defined locally"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_daily_module_imports(self):
        from app.services.data_sync import daily  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import path ``from app.backgroundtasks import _ticker_daily_update_sync``
        must still resolve (re-export shim).
        """
        from app.backgroundtasks import _ticker_daily_update_sync
        assert callable(_ticker_daily_update_sync)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The function must keep its original signature
    (a caller that did ``_ticker_daily_update_sync()`` must still work).
    """

    def test_ticker_daily_update_sync_signature(self):
        from app.services.data_sync.daily import _ticker_daily_update_sync
        sig = inspect.signature(_ticker_daily_update_sync)
        assert len(sig.parameters) == 0, (
            f"_ticker_daily_update_sync should take no arguments, got {sig}"
        )

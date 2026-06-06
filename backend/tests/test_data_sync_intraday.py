"""Tests for the intraday sync core extraction (audit C.1, A.5).

Moves 2 functions from ``app/backgroundtasks/_impl.py`` into
``app/services/data_sync/intraday.py``:

- ``_ticker_intraday_update_sync()`` — backfill intraday candles
  (1h/W/M intervals) for watchlist or all universe symbols, in
  batches of 10 with 1s inter-batch sleep
- ``_ticker_intraday_hourly_stale_check_sync()`` — detect
  watchlist symbols whose last 1h candle is older than the
  expected slot, backfill them, recompute indicators

Tests pin the refactor invariants:

- ``intraday.py`` is a small file (Pattern I: < 300 LOC).
- The 2 functions now live in ``app.services.data_sync.intraday``
  (``__module__`` attribute).
- They are the SAME object (``is``) as their backgroundtasks
  re-exports (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` still works.
- All current callers (orchestrator) still work.
- The functions are importable from BOTH the new module and the
  old package (the bridge shim).
- The function signatures are preserved.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestIntradayModuleSize:
    """``intraday.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_intraday_file_under_350_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "intraday.py"
        )
        assert path.exists(), f"intraday.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # 2 functions are ~244 LOC total.  Allow 350 for imports +
        # docstring + lazy-resolve helpers.
        assert loc < 350, (
            f"intraday.py is {loc} LOC, expected < 350.  This file "
            f"should only contain the intraday sync cores + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_FUNCTIONS = [
    "_ticker_intraday_update_sync",
    "_ticker_intraday_hourly_stale_check_sync",
]


class TestFunctionsMovedToIntraday:
    """The 2 functions must have ``__module__ == 'app.services.data_sync.intraday'``."""

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_function_lives_in_intraday_module(self, name):
        from app.services.data_sync import intraday

        assert hasattr(intraday, name), (
            f"intraday.{name} not found — the move was incomplete"
        )
        fn = getattr(intraday, name)
        assert fn.__module__ == "app.services.data_sync.intraday", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.services.data_sync.intraday'.  The function was "
            f"not moved (or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The functions in ``intraday`` must be the SAME object as
    their ``app.backgroundtasks`` re-exports.
    """

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_intraday_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.services.data_sync import intraday

        assert getattr(bg, name) is getattr(intraday, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.intraday.{name} — the re-export "
            f"is broken or the function was re-defined locally"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_intraday_module_imports(self):
        from app.services.data_sync import intraday  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import paths must still resolve (re-export shim)."""
        from app.backgroundtasks import (
            _ticker_intraday_update_sync,
            _ticker_intraday_hourly_stale_check_sync,
        )
        assert callable(_ticker_intraday_update_sync)
        assert callable(_ticker_intraday_hourly_stale_check_sync)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The functions must keep their original signatures."""

    def test_ticker_intraday_update_sync_signature(self):
        from app.services.data_sync.intraday import _ticker_intraday_update_sync
        sig = inspect.signature(_ticker_intraday_update_sync)
        params = list(sig.parameters.keys())
        # (intervals=None, scope="watchlist", smart=False,
        #  from_ts_overrides=None)
        assert "intervals" in params
        assert "scope" in params
        assert "smart" in params
        assert "from_ts_overrides" in params

    def test_ticker_intraday_hourly_stale_check_sync_signature(self):
        from app.services.data_sync.intraday import _ticker_intraday_hourly_stale_check_sync
        sig = inspect.signature(_ticker_intraday_hourly_stale_check_sync)
        assert len(sig.parameters) == 0, (
            f"_ticker_intraday_hourly_stale_check_sync should take no "
            f"arguments, got {sig}"
        )

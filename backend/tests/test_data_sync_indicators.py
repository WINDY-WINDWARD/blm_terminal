"""Tests for the indicator sync cores extraction (audit C.1, A.8).

Moves 2 functions from ``app/backgroundtasks/_impl.py`` into
``app/services/data_sync/indicators.py``:

- ``_ticker_indicators_sync()`` — backfill per-candle
  indicators for daily candles (RSI/MACD/BB/ATR/VWMA/HV/Sharpe)
  on symbols that have null or stale ``indicators_updated_at``.
  Triggers ``_ticker_indicator_notification_cycle()`` after.
- ``_ticker_intraday_indicators_sync()`` — same but for
  intraday candles (1h/W/M).  Triggers
  ``_ticker_intraday_indicator_notification_cycle()`` after.

Tests pin the refactor invariants:

- ``indicators.py`` is a small file (Pattern I: < 350 LOC).
- The 2 functions now live in ``app.services.data_sync.indicators``
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


class TestIndicatorsModuleSize:
    """``indicators.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_indicators_file_under_350_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "indicators.py"
        )
        assert path.exists(), f"indicators.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # 2 functions are ~190 LOC total.  Allow 350 for imports +
        # docstring + lazy-resolve helpers.
        assert loc < 350, (
            f"indicators.py is {loc} LOC, expected < 350.  This file "
            f"should only contain the indicator sync cores + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_FUNCTIONS = [
    "_ticker_indicators_sync",
    "_ticker_intraday_indicators_sync",
]


class TestFunctionsMovedToIndicators:
    """The 2 functions must have ``__module__ == 'app.services.data_sync.indicators'``."""

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_function_lives_in_indicators_module(self, name):
        from app.services.data_sync import indicators as ind_mod

        assert hasattr(ind_mod, name), (
            f"indicators.{name} not found — the move was incomplete"
        )
        fn = getattr(ind_mod, name)
        assert fn.__module__ == "app.services.data_sync.indicators", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.services.data_sync.indicators'.  The function was "
            f"not moved (or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The functions in ``indicators`` must be the SAME object as
    their ``app.backgroundtasks`` re-exports.
    """

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_indicators_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.services.data_sync import indicators as ind_mod

        assert getattr(bg, name) is getattr(ind_mod, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.indicators.{name} — the re-export "
            f"is broken or the function was re-defined locally"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_indicators_module_imports(self):
        from app.services.data_sync import indicators  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import paths must still resolve (re-export shim)."""
        from app.backgroundtasks import (
            _ticker_indicators_sync,
            _ticker_intraday_indicators_sync,
        )
        assert callable(_ticker_indicators_sync)
        assert callable(_ticker_intraday_indicators_sync)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The functions must keep their original signatures."""

    def test_ticker_indicators_sync_signature(self):
        from app.services.data_sync.indicators import _ticker_indicators_sync
        sig = inspect.signature(_ticker_indicators_sync)
        assert len(sig.parameters) == 0, (
            f"_ticker_indicators_sync should take no arguments, got {sig}"
        )

    def test_ticker_intraday_indicators_sync_signature(self):
        from app.services.data_sync.indicators import _ticker_intraday_indicators_sync
        sig = inspect.signature(_ticker_intraday_indicators_sync)
        params = list(sig.parameters.keys())
        # (intervals: list[str] = None)
        assert "intervals" in params

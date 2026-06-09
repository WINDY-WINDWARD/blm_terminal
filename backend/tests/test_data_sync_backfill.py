"""Tests for the backfill sync core extraction (audit C.1, A.4).

Moves 1 function from ``app/backgroundtasks/_impl.py`` into
``app/services/data_sync/backfill.py``:

- ``_ticker_backfill_sync()`` — backfill ~365 days of historical
  ticker data in batches of 10, refreshing the NSE session every
  50 symbols.

Tests pin the refactor invariants:

- ``backfill.py`` is a small file (Pattern I: < 300 LOC).
- The function now lives in ``app.services.data_sync.backfill``
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

import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestBackfillModuleSize:
    """``backfill.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_backfill_file_under_300_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "backfill.py"
        )
        assert path.exists(), f"backfill.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # _ticker_backfill_sync is ~56 LOC.  Allow 300 for imports +
        # docstring + lazy-resolve helpers.
        assert loc < 300, (
            f"backfill.py is {loc} LOC, expected < 300.  This file "
            f"should only contain the backfill sync core + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_FUNCTIONS = [
    "_ticker_backfill_sync",
]


class TestFunctionsMovedToBackfill:
    """The function must have ``__module__ == 'app.services.data_sync.backfill'``."""

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_function_lives_in_backfill_module(self, name):
        from app.services.data_sync import backfill

        assert hasattr(backfill, name), (
            f"backfill.{name} not found — the move was incomplete"
        )
        fn = getattr(backfill, name)
        assert fn.__module__ == "app.services.data_sync.backfill", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.services.data_sync.backfill'.  The function was "
            f"not moved (or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The function in ``backfill`` must be the SAME object as
    its ``app.backgroundtasks`` re-export.
    """

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_backfill_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.services.data_sync import backfill

        assert getattr(bg, name) is getattr(backfill, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.backfill.{name} — the re-export "
            f"is broken or the function was re-defined locally"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_backfill_module_imports(self):
        from app.services.data_sync import backfill  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import path ``from app.backgroundtasks import _ticker_backfill_sync``
        must still resolve (re-export shim).
        """
        from app.backgroundtasks import _ticker_backfill_sync
        assert callable(_ticker_backfill_sync)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The function must keep its original signature
    (a caller that did ``_ticker_backfill_sync()`` must still work).
    """

    def test_ticker_backfill_sync_signature(self):
        from app.services.data_sync.backfill import _ticker_backfill_sync
        sig = inspect.signature(_ticker_backfill_sync)
        assert len(sig.parameters) == 0, (
            f"_ticker_backfill_sync should take no arguments, got {sig}"
        )

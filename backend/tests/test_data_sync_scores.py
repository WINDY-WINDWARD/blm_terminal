"""Tests for the scores sync core extraction (audit C.1, A.7).

Moves 1 function from ``app/backgroundtasks/_impl.py`` into
``app/services/data_sync/scores.py``:

- ``_ticker_scores_sync()`` — bulk-window function query for
  the last 252 daily candles per symbol, computes
  1d/1w/1m/3m/6m/1y returns + 20d volume ratio + momentum
  score/rank, upserts to ``ticker_scores`` table.  Triggered
  by ``_ticker_daily_update_sync()``.

Tests pin the refactor invariants:

- ``scores.py`` is a small file (Pattern I: < 350 LOC).
- The function now lives in ``app.services.data_sync.scores``
  (``__module__`` attribute).
- It is the SAME object (``is``) as its backgroundtasks
  re-export (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` still works.
- All current callers (orchestrator, daily.py) still work.
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


class TestScoresModuleSize:
    """``scores.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_scores_file_under_350_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "scores.py"
        )
        assert path.exists(), f"scores.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # _ticker_scores_sync is ~209 LOC.  Allow 350 for imports +
        # docstring + lazy-resolve helpers.
        assert loc < 350, (
            f"scores.py is {loc} LOC, expected < 350.  This file "
            f"should only contain the scores sync core + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_FUNCTIONS = [
    "_ticker_scores_sync",
]


class TestFunctionsMovedToScores:
    """The function must have ``__module__ == 'app.services.data_sync.scores'``."""

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_function_lives_in_scores_module(self, name):
        from app.services.data_sync import scores

        assert hasattr(scores, name), (
            f"scores.{name} not found — the move was incomplete"
        )
        fn = getattr(scores, name)
        assert fn.__module__ == "app.services.data_sync.scores", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.services.data_sync.scores'.  The function was "
            f"not moved (or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The function in ``scores`` must be the SAME object as
    its ``app.backgroundtasks`` re-export.
    """

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_scores_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.services.data_sync import scores

        assert getattr(bg, name) is getattr(scores, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.scores.{name} — the re-export "
            f"is broken or the function was re-defined locally"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_scores_module_imports(self):
        from app.services.data_sync import scores  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import path ``from app.backgroundtasks import _ticker_scores_sync``
        must still resolve (re-export shim).
        """
        from app.backgroundtasks import _ticker_scores_sync
        assert callable(_ticker_scores_sync)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The function must keep its original signature
    (a caller that did ``_ticker_scores_sync()`` must still work).
    """

    def test_ticker_scores_sync_signature(self):
        from app.services.data_sync.scores import _ticker_scores_sync
        sig = inspect.signature(_ticker_scores_sync)
        assert len(sig.parameters) == 0, (
            f"_ticker_scores_sync should take no arguments, got {sig}"
        )

"""Tests for the screener snapshot sync core extraction (audit C.1, A.11 part 1).

Moves 1 function + 1 constant from ``app/backgroundtasks/_impl.py``
into ``app/services/data_sync/snapshot.py``:

- ``_screener_snapshot_sync()`` — Build/refresh
  ``ticker_screener_snapshot`` from in-memory 252d daily data plus
  2 supplementary queries (latest 1h/W/M intraday +
  ``stock_universe``).  Called from ``_ticker_scores_sync()`` right
  after the ``ticker_scores`` upsert.
- ``_INTRADAY_COLS`` — phase-B constant mapping snapshot column
  name → intraday source column name.

Tests pin the refactor invariants:

- ``snapshot.py`` is a small file (Pattern I: < 350 LOC).
- The function now lives in ``app.services.data_sync.snapshot``
  (``__module__`` attribute).
- It is the SAME object (``is``) as its backgroundtasks
  re-export (drift-proof).
- The re-export shim in ``app.backgroundtasks`` still works.
- The function signature is preserved (caller compat).
- The ``_INTRADAY_COLS`` constant lives in the new module.
"""
from __future__ import annotations

import inspect
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestSnapshotModuleSize:
    """``snapshot.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_snapshot_file_under_350_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "snapshot.py"
        )
        assert path.exists(), f"snapshot.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # _screener_snapshot_sync is ~200 LOC.  Allow 350 for imports
        # + docstring + lazy-resolve helpers.
        assert loc < 350, (
            f"snapshot.py is {loc} LOC, expected < 350.  This file "
            f"should only contain the snapshot sync core + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ + identity check ───────────────────────────────────────────


class TestSnapshotCoreExtraction:
    """The wrapper now lives in ``app.services.data_sync.snapshot``."""

    def test_function_lives_in_snapshot_module(self):
        from app.services.data_sync.snapshot import _screener_snapshot_sync

        assert _screener_snapshot_sync.__module__ == (
            "app.services.data_sync.snapshot"
        ), (
            f"Expected _screener_snapshot_sync.__module__ to be "
            f"'app.services.data_sync.snapshot', got "
            f"{_screener_snapshot_sync.__module__!r}"
        )

    def test_function_importable_from_backgroundtasks_shim(self):
        """Existing callers use ``from app.backgroundtasks import
        _screener_snapshot_sync``.  The shim must re-export it."""
        from app.backgroundtasks import _screener_snapshot_sync as bg_fn
        from app.services.data_sync.snapshot import _screener_snapshot_sync as new_fn

        assert bg_fn is new_fn, (
            "app.backgroundtasks._screener_snapshot_sync is not the "
            "same object as app.services.data_sync.snapshot."
            "_screener_snapshot_sync — re-export broken"
        )

    def test_function_signature_preserved(self):
        """Callers depend on the exact signature; refactor must not
        rename/remove/change parameter order."""
        from app.services.data_sync.snapshot import _screener_snapshot_sync

        sig = inspect.signature(_screener_snapshot_sync)
        params = list(sig.parameters)
        assert params == [
            "daily_df",
            "today_date",
            "now",
        ], (
            f"Signature drift in _screener_snapshot_sync — "
            f"parameters changed: {params}"
        )


# ─── _INTRADAY_COLS constant moved to snapshot module ─────────────────────


class TestIntradayColsConstant:
    """The phase-B ``_INTRADAY_COLS`` constant moved with the function."""

    def test_intraday_cols_in_snapshot_module(self):
        from app.services.data_sync.snapshot import _INTRADAY_COLS

        assert isinstance(_INTRADAY_COLS, list)
        # All entries are (snapshot_col, source_col) tuples of strings
        for entry in _INTRADAY_COLS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            assert all(isinstance(c, str) for c in entry)
        # Spot-check the first and last entries — these are the
        # source of truth and any rename here would be a refactor
        # regression.
        assert _INTRADAY_COLS[0] == ("intraday_close", "close")
        assert _INTRADAY_COLS[-1] == ("sharpe_126", "sharpe_126")

    def test_intraday_cols_has_17_entries(self):
        """The 1h/W/M × 17 fields = 51+ snapshot columns, but the
        constant has exactly 17 source columns (one per metric).
        Pin the count so accidental truncation/duplication is caught."""
        from app.services.data_sync.snapshot import _INTRADAY_COLS

        assert len(_INTRADAY_COLS) == 17, (
            f"_INTRADAY_COLS has {len(_INTRADAY_COLS)} entries, "
            f"expected exactly 17 (intraday metrics)"
        )

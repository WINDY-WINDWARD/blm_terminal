"""Tests for the new ``app.services.data_sync`` package skeleton
(audit C.1, A.2).

After Phase C.1 A.1 split ``app/backgroundtasks`` into a package,
A.2 creates ``app/services/data_sync`` as the target home for the
sync cores (the business logic that runs in a worker thread).

This file tests the **skeleton**:

- The package is importable.
- Future-targeted sync-core symbols (``_stock_universe_sync``,
  ``_ticker_backfill_sync``, ``_ticker_daily_update_sync``,
  ``_ticker_intraday_update_sync``, ``_ticker_indicators_sync``,
  ``_ticker_scores_sync``) are still accessible via
  ``app.backgroundtasks`` (they will be **moved** to this
  package in subsequent A.x commits).
- Caller imports (``main.py``, ``orchestrator.py``) still work.

The actual re-exports from ``app.services.data_sync.X`` will be
added when each module is created (A.3 onwards).  For A.2, the
package is empty and we only assert it can be imported.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Package shape ────────────────────────────────────────────────────────


class TestDataSyncPackageShape:
    """``app.services.data_sync`` must be a package (not a module)."""

    def test_data_sync_is_a_package(self):
        spec = importlib.util.find_spec("app.services.data_sync")
        assert spec is not None, (
            "app.services.data_sync must be importable — this is "
            "the new home for the sync cores per audit C.1.A.2"
        )
        assert spec.submodule_search_locations is not None, (
            "app.services.data_sync must be a PACKAGE (with __init__.py), "
            "not a single module"
        )

    def test_data_sync_init_imports(self):
        pkg = importlib.import_module("app.services.data_sync")
        assert pkg is not None
        assert "__init__.py" in pkg.__file__


# ─── Sync-core symbols still accessible ───────────────────────────────────


# These 6 sync cores are slated to MOVE from ``app.backgroundtasks``
# into dedicated ``app/services/data_sync/{universe,backfill,daily,
# intrayday,indicators,scores}.py`` modules in A.3-A.7.  For A.2 they
# must still be importable from ``app.backgroundtasks`` (no
# re-exports needed yet; just confirm they're not gone).
SYNC_CORES = [
    "_stock_universe_sync",
    "_ticker_backfill_sync",
    "_ticker_daily_update_sync",
    "_ticker_intraday_update_sync",
    "_ticker_indicators_sync",
    "_ticker_scores_sync",
]


class TestSyncCoresStillAccessible:
    """The 6 sync-core symbols must still be accessible from
    ``app.backgroundtasks`` (they haven't been moved yet).
    """

    @pytest.mark.parametrize("name", SYNC_CORES)
    def test_sync_core_still_in_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.backgroundtasks import _impl

        assert hasattr(_impl, name), (
            f"_impl.{name} missing — the original sync core was lost"
        )
        assert hasattr(bg, name), (
            f"app.backgroundtasks.{name} no longer re-exported"
        )
        assert getattr(bg, name) is getattr(_impl, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"_impl.{name} — re-export is broken"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still import."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_main_imports(self):
        import main  # noqa: F401

    def test_data_sync_package_imports(self):
        from app.services import data_sync  # noqa: F401

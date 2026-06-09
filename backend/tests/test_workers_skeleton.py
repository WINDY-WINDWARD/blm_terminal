"""Tests for the new ``app.workers`` package skeleton (audit C.1, A.2).

After Phase C.1 A.1 split ``app/backgroundtasks`` into a package,
A.2 creates ``app/workers`` and ``app/services/data_sync`` as the
target homes for the split.  This file tests the **skeleton**:

- Both packages are importable.
- ``app.workers`` re-exports every worker symbol from
  ``app.backgroundtasks`` (the bridge shim that keeps callers
  working during migration).
- All worker symbols are the same object (``is``) as their
  backgroundtasks counterparts.
- All current callers (``main.py``, ``orchestrator.py``,
  ``mcp_server.py``) still import successfully.

Worker symbols moved into dedicated submodules (``workers/data.py``,
``workers/news.py``, etc.) will be added in subsequent A.x
commits; this file only covers the skeleton + re-export contract.
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


class TestWorkersPackageShape:
    """``app.workers`` must be a package (not a module)."""

    def test_workers_is_a_package(self):
        spec = importlib.util.find_spec("app.workers")
        assert spec is not None
        assert spec.submodule_search_locations is not None, (
            "app.workers must be a PACKAGE (with __init__.py), "
            "not a single module — this is the split target of C.1.A.2"
        )

    def test_workers_init_imports(self):
        pkg = importlib.import_module("app.workers")
        assert pkg is not None
        assert "__init__.py" in pkg.__file__


# ─── Re-export contract ───────────────────────────────────────────────────


EXPECTED_WORKER_SYMBOLS = [
    # Worker lifecycle (public)
    "start_all_workers",
    "stop_all_workers",
    "start_cache_cleanup",
    # Data workers
    "stock_universe_worker",
    "ticker_backfill_worker",
    "ticker_daily_update_worker",
    "ticker_intraday_hourly_update_worker",
    "ticker_indicators_worker",
    "ticker_intraday_hourly_indicators_worker",
    "ticker_scores_worker",
    # News workers
    "news_worker",
    "news_rss_worker",
    "watchlist_news_worker",
    # Notification workers
    "watchlist_notification_worker",
    "global_scan_worker",
    # Results calendar + maintenance
    "results_calendar_worker",
    "vacuum_worker",
]


class TestWorkerReExports:
    """Each worker symbol must be re-exported from ``app.workers``
    and be the same object as in ``app.backgroundtasks``.
    """

    @pytest.mark.parametrize("name", EXPECTED_WORKER_SYMBOLS)
    def test_symbol_re_exported(self, name):
        from app import backgroundtasks as bg
        from app import workers

        assert hasattr(bg, name), (
            f"app.backgroundtasks.{name} missing — original was lost"
        )
        assert hasattr(workers, name), (
            f"app.workers.{name} not re-exported — callers will break"
        )
        assert getattr(workers, name) is getattr(bg, name), (
            f"app.workers.{name} is not the same object as "
            f"app.backgroundtasks.{name} — re-export is broken"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers of ``app.backgroundtasks`` must still
    import after the workers package skeleton is created.
    """

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_main_imports(self):
        import main  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_workers_package_imports(self):
        from app import workers  # noqa: F401

    def test_specific_worker_reexports(self):
        """Spot-check a few specific worker re-exports that
        ``main.py`` and ``orchestrator.py`` use.
        """
        from app.workers import (
            start_all_workers,
            stop_all_workers,
            stock_universe_worker,
            ticker_backfill_worker,
            ticker_daily_update_worker,
            news_worker,
            watchlist_notification_worker,
            global_scan_worker,
            vacuum_worker,
        )
        assert callable(start_all_workers)
        assert callable(stop_all_workers)

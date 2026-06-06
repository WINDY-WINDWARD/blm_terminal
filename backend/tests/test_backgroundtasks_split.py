"""Tests for the backgroundtasks package split (audit C.1, Phase A.1).

The 4994-LOC ``app/backgroundtasks.py`` is being split into 12 modules
under ``app/workers/`` and ``app/services/data_sync/`` (see audit §4.3).
To make this an incremental, low-risk refactor, we use the
**expand-and-contract** pattern:

1. The current ``backgroundtasks.py`` is renamed to
   ``app/backgroundtasks/_impl.py`` (private).
2. ``app/backgroundtasks/__init__.py`` re-exports every public symbol
   from ``_impl``.
3. Every caller continues to work unchanged during the migration.
4. Once all symbols are migrated to their final homes, the ``_impl``
   module is deleted and callers are updated to import from the new
   locations.

These tests pin the contract of step 1-3 so future commits cannot
break the re-export shim or accidentally lose a public symbol.

Coverage:

- ``app/backgroundtasks`` is a package (not a module).
- All public symbols of the original module are re-exported.
- The re-exported symbols are **the same object** (``is``) as the
  definitions in ``_impl`` (drift-proof: a future commit that
  re-defines a symbol locally without re-exporting will fail).
- External imports (``from app.backgroundtasks import X``) still
  resolve.
- The ``_impl.py`` file is smaller than the original (sanity check
  that the split is actually happening).
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


class TestBackgroundtasksPackageShape:
    """``app.backgroundtasks`` must be a package (not a module)."""

    def test_backgroundtasks_is_a_package(self):
        spec = importlib.util.find_spec("app.backgroundtasks")
        assert spec is not None, "app.backgroundtasks must be importable"
        # When it's a package, spec.submodule_search_locations is a list.
        # When it's a module, it's None.
        assert spec.submodule_search_locations is not None, (
            "app.backgroundtasks must be a PACKAGE (with __init__.py), "
            "not a single module — this is the split point of C.1.A.1"
        )

    def test_backgroundtasks_init_imports(self):
        """Importing the package must succeed without errors."""
        bg = importlib.import_module("app.backgroundtasks")
        assert bg is not None
        # __file__ should be the __init__.py inside the package dir
        assert "__init__.py" in bg.__file__, (
            f"app.backgroundtasks.__file__ should be in __init__.py, got {bg.__file__}"
        )


# ─── Re-export contract ───────────────────────────────────────────────────


# Symbols that MUST remain importable from ``app.backgroundtasks``.
# Sourced from the original module's top-level definitions (the
# orchestrator + workers import from this list).
EXPECTED_PUBLIC_SYMBOLS = [
    # Cross-cutting helpers (used by orchestrator + workers)
    "_is_job_enabled",
    "_is_first_run",
    "_set_first_run_complete",
    "_sleep_interruptible",
    "_wait_for_startup_event",
    "_wait_for_pipeline",
    "_run_async",
    # _run_vacuum moved to app.workers.maintenance — see TestMovedWorkers
    "_report_job_waiting",
    "_seconds_until_next_cron",
    # Shutdown / pipeline state
    "get_async_shutdown_event",
    "reset_async_shutdown_event",
    "set_async_shutdown_event",
    "_shutdown_event",
    "_pipeline_lock",
    "_pipeline_idle",
    # First-run
    "register_all_jobs",
    # Universe sync
    "_stock_universe_sync",
    "_update_symbol_error_status",
    "_bulk_insert_stock_universe",
    # Ticker sync cores
    "_ticker_backfill_sync",
    "_ticker_daily_update_sync",
    "_ticker_intraday_update_sync",
    "_ticker_intraday_hourly_stale_check_sync",
    "_parallel_indicator_sync",
    "_ticker_indicators_sync",
    "_ticker_intraday_indicators_sync",
    "_ticker_scores_sync",
    "_screener_snapshot_sync",
    # NOTE: the 7 ticker-data worker daemons moved to
    # app.workers.{universe,data,ticker_compute} in audit C.1
    # A.9 step 2 — see TestMovedWorkers / MOVED_SYMBOLS
    # News sync functions (5 worker daemons moved to app.workers.{news,
    # market_calendar} in A.9 step 4 — see TestMovedWorkers)
    "_crawl_news_async",
    "_news_sync",
    "_news_periodic_sync",
    "_news_rss_sync",
    "_news_rss_sync_async",
    "_watchlist_news_sync",
    "_fetch_company_news_async",
    "_is_market_open",
    "_seconds_until_market_open",
    "_refresh_market_data_async",
    "_market_data_sync",
    # Results calendar sync (results_calendar_worker moved to
    # app.workers.market_calendar in A.9 step 4)
    "_results_calendar_sync",
    # Maintenance (vacuum_worker moved to app.workers.maintenance — see TestMovedWorkers)
    "_run_cleanup_if_due",
    # Notification workers (watchlist_notification_worker + global_scan_worker
    # moved to app.workers.notifications in A.9 step 3 — see TestMovedWorkers)
    "_notification_cycle_full",
    "_notification_cycle_reduced",
    "_build_alerts",
    "_ticker_indicator_notification_cycle",
    "_ticker_intraday_indicator_notification_cycle",
    "_global_scan_cycle",
    # Worker lifecycle
    "start_all_workers",
    "stop_all_workers",
    "start_cache_cleanup",
    # Notifications (sync helpers used by workers)
    "_get_watchlist_symbols",
    "_get_seen_today",
    "_bulk_upsert_notifications",
    "_get_global_seen_today",
    "_bulk_upsert_global_notifications",
    "get_notif_config",
    "_fetch_deal_market_caps",
    "_fetch_short_deal_close_prices",
    "_is_deal_significant",
    "_fetch_insider_trades_cached",
    "_fetch_insider_trades_async",
    # Fair value
    "_batch_update_fair_values",
    "_batch_resolve_morningstar_ids",
    "sync_watchlist_fair_values",
    "sync_all_fair_values",
    "_update_sync_timestamp",
    "_should_trigger_full_sync",
    "_get_watchlist_lock",
    "_get_full_lock",
    "_run_watchlist_scheduler",
    "_run_nightly_scheduler",
    # Parsing helpers (used by global scan cycle)
    "_parse_52week_data",
    "_parse_volume_gainers",
    "_parse_largedeal_snapshot",
    "_safe_fetch_52week_high",
    "_safe_fetch_52week_low",
    "_safe_fetch_volume_gainers",
    "_safe_fetch_top_gainers",
    "_safe_fetch_top_losers",
    "_safe_fetch_largedeal_snapshot",
    # Misc
    "DealRecord",
    "_coerce_int",
    "_coerce_float",
    "_is_recent",
]


class TestReExports:
    """Every public symbol must still be importable from
    ``app.backgroundtasks`` after the package split.
    """

    @pytest.mark.parametrize("name", EXPECTED_PUBLIC_SYMBOLS)
    def test_symbol_re_exported(self, name):
        from app.backgroundtasks import _impl
        from app import backgroundtasks as bg

        # The symbol must exist on _impl (the original definitions)
        assert hasattr(_impl, name), (
            f"_impl.{name} missing — the original symbol was lost "
            f"during the package split"
        )

        # The symbol must be re-exported on the package
        assert hasattr(bg, name), (
            f"app.backgroundtasks.{name} not re-exported — external "
            f"callers will break"
        )

        # The re-exported symbol must be the SAME object as the
        # original (drift-proof: prevents accidentally re-defining
        # locally and breaking identity tests in callers).
        impl_obj = getattr(_impl, name)
        pkg_obj = getattr(bg, name)
        assert pkg_obj is impl_obj, (
            f"app.backgroundtasks.{name} is not the same object as "
            f"_impl.{name} — re-export is broken (got {type(pkg_obj)} "
            f"vs {type(impl_obj)})"
        )


# Symbols that have been moved to a new home under ``app.workers.<domain>``
# (or ``app.services.data_sync.*``) during the Phase C.1 split.  These
# are NO LONGER defined in ``_impl.py`` — they live in their final
# module — but ``app.backgroundtasks`` re-exports them so existing
# callers (``from app.backgroundtasks import vacuum_worker``) keep
# working unchanged.
#
# Mapping: name → final module
MOVED_SYMBOLS = [
    ("_run_vacuum", "app.workers.maintenance"),
    ("vacuum_worker", "app.workers.maintenance"),
    # A.9 step 2 — ticker-data workers
    ("stock_universe_worker", "app.workers.universe"),
    ("ticker_backfill_worker", "app.workers.data"),
    ("ticker_daily_update_worker", "app.workers.data"),
    ("ticker_intraday_hourly_update_worker", "app.workers.data"),
    ("ticker_scores_worker", "app.workers.ticker_compute"),
    ("ticker_indicators_worker", "app.workers.ticker_compute"),
    ("ticker_intraday_hourly_indicators_worker", "app.workers.ticker_compute"),
    ("watchlist_notification_worker", "app.workers.notifications"),
    ("global_scan_worker", "app.workers.notifications"),
    ("news_worker", "app.workers.news"),
    ("news_rss_worker", "app.workers.news"),
    ("watchlist_news_worker", "app.workers.news"),
    ("market_data_worker", "app.workers.market_calendar"),
    ("results_calendar_worker", "app.workers.market_calendar"),
]


class TestMovedWorkers:
    """Symbols moved to a new module must still be importable from
    ``app.backgroundtasks`` (re-export shim contract) and must be the
    same object as the one in their new home.
    """

    @pytest.mark.parametrize("name,new_home", MOVED_SYMBOLS)
    def test_moved_symbol_re_exported(self, name, new_home):
        import importlib
        from app import backgroundtasks as bg

        new_mod = importlib.import_module(new_home)

        # Must be re-exported on the package
        assert hasattr(bg, name), (
            f"app.backgroundtasks.{name} not re-exported — external "
            f"callers will break"
        )
        # Must NOT live in _impl anymore (otherwise the re-export
        # is a stale local copy, not a forwarding import)
        from app.backgroundtasks import _impl
        assert not hasattr(_impl, name), (
            f"_impl.{name} still defined — the move to {new_home} "
            f"is incomplete (delete it from _impl to avoid drift)"
        )
        # Identity: bg.<name> must be the exact same object as
        # <new_home>.<name>
        new_obj = getattr(new_mod, name)
        pkg_obj = getattr(bg, name)
        assert pkg_obj is new_obj, (
            f"app.backgroundtasks.{name} is not the same object as "
            f"{new_home}.{name} — re-export is broken "
            f"(got {type(pkg_obj)} vs {type(new_obj)})"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers of ``app.backgroundtasks`` must still import
    after the package split.
    """

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_main_imports(self):
        import main  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_routers_notifications_imports(self):
        from app.routers import notifications  # noqa: F401

    def test_legacy_specific_imports(self):
        """Spot-check a few specific import paths that the orchestrator
        uses frequently.  These would have broken loudly if the
        re-export shim was missing a symbol.
        """
        from app.backgroundtasks import (
            start_all_workers,
            stop_all_workers,
            get_async_shutdown_event,
            reset_async_shutdown_event,
            set_async_shutdown_event,
            sync_all_fair_values,
            sync_watchlist_fair_values,
            _is_first_run,
            _set_first_run_complete,
            _should_trigger_full_sync,
            _is_job_enabled,
            _pipeline_idle,
            _pipeline_lock,
            _shutdown_event,
        )
        # Smoke: each is callable / accessible
        assert callable(start_all_workers)
        assert callable(stop_all_workers)
        assert callable(get_async_shutdown_event)


# ─── _impl.py size regression check ───────────────────────────────────────


class TestImplFileShrinks:
    """The ``_impl.py`` file must shrink over time as symbols migrate
    to their final modules.  This test pins the initial size so we
    can detect accidental bloat.
    """

    def test_impl_starts_smaller_than_original(self):
        """The original was 4994 LOC.  After the package split, the
        _impl file should be at most the original size (ideally
        smaller as we migrate symbols out).

        This is a **regression sentinel** — if a future commit adds
        code to _impl.py instead of moving it to a new module, the
        test fails.  We assert ``<= original_size + 50`` to allow
        the trivial boilerplate of the package re-export.
        """
        impl_path = ROOT / "app" / "backgroundtasks" / "_impl.py"
        assert impl_path.exists(), f"_impl.py not found at {impl_path}"
        impl_loc = sum(1 for _ in impl_path.read_text().splitlines())

        # The original was 4994 LOC.  After the split, _impl should
        # be at most original + 50 lines (for any incidental re-
        # export boilerplate in the package init).
        # NOTE: For A.1, _impl IS the original (just renamed), so
        # this is exactly 4994 today.  Future commits will shrink it.
        assert impl_loc <= 4994 + 50, (
            f"_impl.py is {impl_loc} LOC, expected <= {4994 + 50}. "
            f"The file should shrink as symbols migrate to their "
            f"final modules.  If you added code to _impl.py instead "
            f"of moving it, move it."
        )

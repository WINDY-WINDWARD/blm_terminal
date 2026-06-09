"""Tests for the backgroundtasks package split (audit C.1, Phase A.1).

The 4994-LOC ``app/backgroundtasks.py`` was split into 12 modules
under ``app/workers/`` and ``app/services/data_sync/`` (see audit §4.3).
The final shape is:

- ``app/backgroundtasks/_runtime.py`` — cross-cutting runtime helpers
  (state + scheduling primitives) that worker modules use.
- ``app/workers/<domain>`` — domain-specific worker daemons.
- ``app/services/data_sync/<domain>`` — sync cores.
- ``app/services/fair_value`` — Morningstar fair-value sync.
- ``app/backgroundtasks/__init__.py`` — re-export shim that re-exports
  the public API for backward compatibility with every existing
  caller (``from app.backgroundtasks import X``).

These tests pin the shim contract: every public symbol of the
original module is still reachable through the package, and the
re-exported symbol is the **same object** (``is``) as the one in its
final home (drift-proof: a future commit that re-defines a symbol
locally without re-exporting will fail).

Coverage:

- ``app/backgroundtasks`` is a package (not a module).
- All public symbols of the original module are re-exported.
- The re-exported symbols are ``is``-identical to their canonical
  homes.
- External imports (``from app.backgroundtasks import X``) still
  resolve.
- All current callers (orchestrator, main.py, mcp_server, routers) still
  import.
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
    # NOTE: register_all_jobs moved to app.workers.jobs in A.12 part 1 —
    # see MOVED_SYMBOLS / TestMovedWorkers
    # NOTE: A.3-A.8 sync cores (universe, backfill, intraday, daily,
    # scores, indicators) moved to app.services.data_sync.<domain> —
    # see MOVED_SYMBOLS / TestMovedWorkers
    # NOTE: _parallel_indicator_sync and _screener_snapshot_sync
    # moved to app.services.data_sync.{parallel,snapshot} in A.11
    # part 1 — see MOVED_SYMBOLS / TestMovedWorkers
    # NOTE: the 7 ticker-data worker daemons moved to
    # app.workers.{universe,data,ticker_compute} in audit C.1
    # A.9 step 2 — see TestMovedWorkers / MOVED_SYMBOLS
    # NOTE: news + market + calendar sync cores moved to
    # app.services.data_sync.{news,market,calendar} in A.11 part 2 —
    # see MOVED_SYMBOLS / TestMovedWorkers
    # NOTE: nse_parsing / cleanup / deal_significance / insider_trades
    # / notifications + cycle functions moved to data_sync.* and
    # app.workers.* in A.12 part 1 — see MOVED_SYMBOLS / TestMovedWorkers
    # NOTE: fair-value sync moved to app.services.fair_value in A.12
    # part 2 — see MOVED_SYMBOLS / TestMovedWorkers
    # Maintenance (vacuum_worker moved to app.workers.maintenance — see TestMovedWorkers)
    # Notification workers (watchlist_notification_worker + global_scan_worker
    # moved to app.workers.notifications in A.9 step 3 — see TestMovedWorkers)
    # NOTE: start_all_workers / stop_all_workers / start_cache_cleanup
    # moved to app.workers.lifecycle in A.12 part 3 — see
    # MOVED_SYMBOLS / TestMovedWorkers.
]


class TestReExports:
    """Every public symbol must still be importable from
    ``app.backgroundtasks`` after the package split.
    """

    @pytest.mark.parametrize("name", EXPECTED_PUBLIC_SYMBOLS)
    def test_symbol_re_exported(self, name):
        from app.backgroundtasks import _runtime
        from app import backgroundtasks as bg

        # The symbol must exist on _runtime (the final home for
        # cross-cutting runtime helpers).
        assert hasattr(_runtime, name), (
            f"_runtime.{name} missing — the original symbol was lost "
            f"during the package split"
        )

        # The symbol must be re-exported on the package
        assert hasattr(bg, name), (
            f"app.backgroundtasks.{name} not re-exported — external "
            f"callers will break"
        )

        # The re-exported symbol must be the SAME object as the
        # final home (drift-proof: prevents accidentally re-defining
        # locally and breaking identity tests in callers).
        rt_obj = getattr(_runtime, name)
        pkg_obj = getattr(bg, name)
        assert pkg_obj is rt_obj, (
            f"app.backgroundtasks.{name} is not the same object as "
            f"_runtime.{name} — re-export is broken (got {type(pkg_obj)} "
            f"vs {type(rt_obj)})"
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
    # A.3 — universe sync (split out of _impl in audit C.1 A.3)
    ("_stock_universe_sync", "app.services.data_sync.universe"),
    ("_update_symbol_error_status", "app.services.data_sync.universe"),
    ("_bulk_insert_stock_universe", "app.services.data_sync.universe"),
    # A.4 — backfill sync
    ("_ticker_backfill_sync", "app.services.data_sync.backfill"),
    # A.5 — intraday sync
    ("_ticker_intraday_update_sync", "app.services.data_sync.intraday"),
    ("_ticker_intraday_hourly_stale_check_sync", "app.services.data_sync.intraday"),
    # A.6 — daily update sync
    ("_ticker_daily_update_sync", "app.services.data_sync.daily"),
    # A.7 — scores sync
    ("_ticker_scores_sync", "app.services.data_sync.scores"),
    # A.8 — indicator sync
    ("_ticker_indicators_sync", "app.services.data_sync.indicators"),
    ("_ticker_intraday_indicators_sync", "app.services.data_sync.indicators"),
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
    ("results_calendar_worker", "app.workers.market_calendar"),
    # A.11 part 1 — split remaining sync cores (parallel + snapshot)
    ("_parallel_indicator_sync", "app.services.data_sync.parallel"),
    ("_screener_snapshot_sync", "app.services.data_sync.snapshot"),
    # A.11 part 2 — news + market + calendar sync cores
    ("_crawl_news_async", "app.services.data_sync.news"),
    ("_news_sync", "app.services.data_sync.news"),
    ("_news_periodic_sync", "app.services.data_sync.news"),
    ("_news_rss_sync", "app.services.data_sync.news"),
    ("_news_rss_sync_async", "app.services.data_sync.news"),
    ("_watchlist_news_sync", "app.services.data_sync.news"),
    ("_fetch_company_news_async", "app.services.data_sync.news"),
    ("_is_market_open", "app.services.data_sync.market"),
    ("_seconds_until_market_open", "app.services.data_sync.market"),
    ("_refresh_market_data_async", "app.services.data_sync.market"),
    ("_market_data_sync", "app.services.data_sync.market"),
    ("_results_calendar_sync", "app.services.data_sync.calendar"),
    # A.12 part 1 — nse_parsing (8 safe-fetch + parse helpers)
    ("_parse_52week_data", "app.services.data_sync.nse_parsing"),
    ("_parse_volume_gainers", "app.services.data_sync.nse_parsing"),
    ("_safe_fetch_52week_high", "app.services.data_sync.nse_parsing"),
    ("_safe_fetch_52week_low", "app.services.data_sync.nse_parsing"),
    ("_safe_fetch_volume_gainers", "app.services.data_sync.nse_parsing"),
    ("_safe_fetch_top_gainers", "app.services.data_sync.nse_parsing"),
    ("_safe_fetch_top_losers", "app.services.data_sync.nse_parsing"),
    ("_safe_fetch_largedeal_snapshot", "app.services.data_sync.nse_parsing"),
    # A.12 part 1 — deal_significance (DealRecord + 7 helpers)
    ("DealRecord", "app.services.data_sync.deal_significance"),
    ("_coerce_int", "app.services.data_sync.deal_significance"),
    ("_coerce_float", "app.services.data_sync.deal_significance"),
    ("_is_recent", "app.services.data_sync.deal_significance"),
    ("_parse_largedeal_snapshot", "app.services.data_sync.deal_significance"),
    ("_fetch_deal_market_caps", "app.services.data_sync.deal_significance"),
    ("_fetch_short_deal_close_prices", "app.services.data_sync.deal_significance"),
    ("_is_deal_significant", "app.services.data_sync.deal_significance"),
    # A.12 part 1 — insider_trades
    ("_fetch_insider_trades_cached", "app.services.data_sync.insider_trades"),
    ("_fetch_insider_trades_async", "app.services.data_sync.insider_trades"),
    # A.12 part 1 — cleanup
    ("_run_cleanup_if_due", "app.services.data_sync.cleanup"),
    ("CLEANUP_READ_AFTER_DAYS", "app.services.data_sync.cleanup"),
    ("CLEANUP_INTERVAL", "app.services.data_sync.cleanup"),
    ("INTRADAY_1H_RETENTION_DAYS", "app.services.data_sync.cleanup"),
    ("INTRADAY_W_RETENTION_YEARS", "app.services.data_sync.cleanup"),
    ("NEWS_RETENTION_DAYS", "app.services.data_sync.cleanup"),
    ("_cleanup_last_run", "app.services.data_sync.cleanup"),
    # A.12 part 1 — notifications (helpers + _build_alerts)
    ("NOTIFICATION_CHECK_INTERVAL", "app.services.data_sync.notifications"),
    ("AFTER_HOURS_INTERVAL", "app.services.data_sync.notifications"),
    ("DAILY_NOTIFICATION_WINDOW_DAYS", "app.services.data_sync.notifications"),
    ("_get_watchlist_symbols", "app.services.data_sync.notifications"),
    ("_get_seen_today", "app.services.data_sync.notifications"),
    ("_bulk_upsert_notifications", "app.services.data_sync.notifications"),
    ("_get_global_seen_today", "app.services.data_sync.notifications"),
    ("_bulk_upsert_global_notifications", "app.services.data_sync.notifications"),
    ("get_notif_config", "app.services.data_sync.notifications"),
    ("_build_alerts", "app.services.data_sync.notifications"),
    # A.12 part 1 — notification_cycles (4 watchlist cycle functions)
    ("_notification_cycle_full", "app.workers.notification_cycles"),
    ("_notification_cycle_reduced", "app.workers.notification_cycles"),
    ("_ticker_indicator_notification_cycle", "app.workers.notification_cycles"),
    ("_ticker_intraday_indicator_notification_cycle", "app.workers.notification_cycles"),
    # A.12 part 1 — global_scan_cycle (1 function + 2 constants)
    ("_global_scan_cycle", "app.workers.global_scan_cycle"),
    ("GLOBAL_SCAN_BATCH_SIZE", "app.workers.global_scan_cycle"),
    ("GLOBAL_SCAN_DELAY", "app.workers.global_scan_cycle"),
    # A.12 part 1 — register_all_jobs moved to app.workers.jobs
    ("register_all_jobs", "app.workers.jobs"),
    # A.12 part 2 — fair-value sync moved to app.services.fair_value
    ("_batch_update_fair_values", "app.services.fair_value"),
    ("_batch_resolve_morningstar_ids", "app.services.fair_value"),
    ("sync_watchlist_fair_values", "app.services.fair_value"),
    ("sync_all_fair_values", "app.services.fair_value"),
    ("_update_sync_timestamp", "app.services.fair_value"),
    ("_should_trigger_full_sync", "app.services.fair_value"),
    ("_get_watchlist_lock", "app.services.fair_value"),
    ("_get_full_lock", "app.services.fair_value"),
    ("_run_watchlist_scheduler", "app.services.fair_value"),
    ("_run_nightly_scheduler", "app.services.fair_value"),
    # A.12 part 3 — worker lifecycle moved to app.workers.lifecycle
    ("start_all_workers", "app.workers.lifecycle"),
    ("stop_all_workers", "app.workers.lifecycle"),
    ("start_cache_cleanup", "app.workers.lifecycle"),
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


"""Background tasks package — re-export shim during Phase C migration.

The original 4994-LOC ``app/backgroundtasks.py`` is being split into
12 modules under ``app/workers/`` and ``app/services/data_sync/``
(see audit §4.3).  This package is the **expand-and-contract** shim
that keeps every existing caller working unchanged during the
migration.

Once all symbols have been moved to their final homes and all
callers have been updated, this re-export shim is deleted and the
``_impl.py`` file is removed.  See ``tests/test_backgroundtasks_split.py``
for the contract this shim must maintain.

Public API of this package is the union of the public API of the
original module.  Re-exports are explicit (no ``import *``) so that
``from app.backgroundtasks import X`` resolves to a real symbol on
``_impl`` (and the ``is``-identity test in
``test_backgroundtasks_split.py`` catches accidental local re-definitions).
"""

# Session factories and re-exported stdlib — re-exported so that
# tests can ``monkeypatch.setattr(backgroundtasks, "AsyncSessionLocal", ...)``
# without the AttributeError.  Functions in ``_impl`` still look up
# these names in their own module globals; tests that need to mock
# must also patch ``backgroundtasks._impl.AsyncSessionLocal`` (and
# friends) directly.  See ``tests/test_utcnow_migration_parity.py``.
from app.backgroundtasks._impl import (  # noqa: F401
    AsyncSessionLocal,
    _SyncSessionLocal,
)

# Cross-cutting helpers (used by orchestrator + workers)
from app.backgroundtasks._impl import (  # noqa: F401
    _is_job_enabled,
    _is_first_run,
    _set_first_run_complete,
    _sleep_interruptible,
    _wait_for_startup_event,
    _wait_for_pipeline,
    _run_async,
    _run_vacuum,
    _report_job_waiting,
    _seconds_until_next_cron,
    # Shutdown / pipeline state
    get_async_shutdown_event,
    reset_async_shutdown_event,
    set_async_shutdown_event,
    _shutdown_event,
    _pipeline_lock,
    _pipeline_idle,
    # First-run + job registry
    register_all_jobs,
    # Universe sync (moved to app.services.data_sync.universe in A.3)
    _stock_universe_sync,
    _update_symbol_error_status,
    _bulk_insert_stock_universe,
    stock_universe_worker,
    # Backfill sync (moved to app.services.data_sync.backfill in A.4)
    _ticker_backfill_sync,
    ticker_backfill_worker,
    ticker_daily_update_worker,
    # Intraday sync (moved to app.services.data_sync.intraday in A.5)
    _ticker_intraday_update_sync,
    # Daily update sync (moved to app.services.data_sync.daily in A.6)
    _ticker_daily_update_sync,
    _ticker_intraday_hourly_stale_check_sync,
    # Scores sync (moved to app.services.data_sync.scores in A.7)
    _ticker_scores_sync,
    ticker_intraday_hourly_update_worker,
    _parallel_indicator_sync,
    _ticker_indicators_sync,
    _ticker_intraday_indicators_sync,
    _screener_snapshot_sync,
    ticker_scores_worker,
    ticker_indicators_worker,
    ticker_intraday_hourly_indicators_worker,
    # News sync
    news_worker,
    news_rss_worker,
    watchlist_news_worker,
    market_data_worker,
    _crawl_news_async,
    _news_sync,
    _news_periodic_sync,
    _news_rss_sync,
    _news_rss_sync_async,
    _watchlist_news_sync,
    _fetch_company_news_async,
    _is_market_open,
    _seconds_until_market_open,
    _refresh_market_data_async,
    _market_data_sync,
    # Results calendar
    results_calendar_worker,
    _results_calendar_sync,
    # Maintenance
    vacuum_worker,
    _run_cleanup_if_due,
    # Notification workers
    watchlist_notification_worker,
    _notification_cycle_full,
    _notification_cycle_reduced,
    _build_alerts,
    _ticker_indicator_notification_cycle,
    _ticker_intraday_indicator_notification_cycle,
    global_scan_worker,
    _global_scan_cycle,
    # Worker lifecycle
    start_all_workers,
    stop_all_workers,
    start_cache_cleanup,
    # Notifications (sync helpers used by workers)
    _get_watchlist_symbols,
    _get_seen_today,
    _bulk_upsert_notifications,
    _get_global_seen_today,
    _bulk_upsert_global_notifications,
    get_notif_config,
    _fetch_deal_market_caps,
    _fetch_short_deal_close_prices,
    _is_deal_significant,
    _fetch_insider_trades_cached,
    _fetch_insider_trades_async,
    # Fair value
    _batch_update_fair_values,
    _batch_resolve_morningstar_ids,
    sync_watchlist_fair_values,
    sync_all_fair_values,
    _update_sync_timestamp,
    _should_trigger_full_sync,
    _get_watchlist_lock,
    _get_full_lock,
    _run_watchlist_scheduler,
    _run_nightly_scheduler,
    # Parsing helpers (used by global scan cycle)
    _parse_52week_data,
    _parse_volume_gainers,
    _parse_largedeal_snapshot,
    _safe_fetch_52week_high,
    _safe_fetch_52week_low,
    _safe_fetch_volume_gainers,
    _safe_fetch_top_gainers,
    _safe_fetch_top_losers,
    _safe_fetch_largedeal_snapshot,
    # Misc
    DealRecord,
    _coerce_int,
    _coerce_float,
    _is_recent,
)

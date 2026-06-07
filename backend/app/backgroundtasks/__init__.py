"""Background tasks package — re-export shim during Phase C migration.

The original 4994-LOC ``app/backgroundtasks.py`` is being split into
12+ modules under ``app/workers/`` and ``app/services/data_sync/``
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
# without the AttributeError.  These come directly from
# ``app.database`` / ``app.config`` (not from ``_impl`` — which
# after A.12 part 3 no longer re-exports them).
from app.database import (  # noqa: E402,F401
    AsyncSessionLocal,
    _SyncSessionLocal,
)
from app.config import settings  # noqa: E402,F401

# Cross-cutting helpers (used by orchestrator + workers)
from app.backgroundtasks._impl import (  # noqa: F401
    _is_job_enabled,
    _is_first_run,
    _set_first_run_complete,
    _sleep_interruptible,
    _wait_for_startup_event,
    _wait_for_pipeline,
    _run_async,
    _report_job_waiting,
    _seconds_until_next_cron,
    # Shutdown / pipeline state
    get_async_shutdown_event,
    reset_async_shutdown_event,
    set_async_shutdown_event,
    _shutdown_event,
    _worker_threads,
    _pipeline_lock,
    _pipeline_idle,
    _startup_stock_universe_done,
    _startup_ticker_backfill_done,
    _startup_ticker_indicators_done,
    _startup_ticker_scores_done,
    _startup_ticker_hourly_done,
    # NOTE: A.3-A.8 sync cores (universe, backfill, intraday, daily,
    # scores, indicators) + A.11 part 1/2 + A.12 part 1/2 are all
    # imported separately below from their final homes — see
    # MOVED_SYMBOLS / TestMovedWorkers.
    # NOTE: register_all_jobs lives in app.workers.jobs since A.12
    # part 1 — re-exported at the bottom of this shim.
    # NOTE: start_all_workers / stop_all_workers / start_cache_cleanup
    # moved to app.workers.lifecycle in A.12 part 3 — see
    # MOVED_SYMBOLS / TestMovedWorkers.
)

# Workers that have moved to ``app/workers/<domain>.py`` during the
# Phase C.1 split.  Imported separately (NOT through ``_impl``) so
# that ``app.workers.__init__`` can re-export these names without
# re-entering this package mid-init and triggering a circular import.
from app.workers.maintenance import (  # noqa: E402,F401
    _run_vacuum,
    vacuum_worker,
    VACUUM_CRON,
)
from app.workers.universe import (  # noqa: E402,F401
    stock_universe_worker,
)
from app.workers.data import (  # noqa: E402,F401
    ticker_backfill_worker,
    ticker_daily_update_worker,
    ticker_intraday_hourly_update_worker,
)
from app.workers.ticker_compute import (  # noqa: E402,F401
    ticker_scores_worker,
    ticker_indicators_worker,
    ticker_intraday_hourly_indicators_worker,
)
from app.workers.notifications import (  # noqa: E402,F401
    watchlist_notification_worker,
    global_scan_worker,
)
from app.workers.news import (  # noqa: E402,F401
    news_worker,
    news_rss_worker,
    watchlist_news_worker,
)
from app.workers.market_calendar import (  # noqa: E402,F401
    market_data_worker,
    results_calendar_worker,
)

# A.11 part 1 — sync cores moved out of _impl.py into
# app.services.data_sync.{parallel,snapshot}.  Imported separately
# (NOT through ``_impl``) so the re-export shim test
# (``tests/test_backgroundtasks_split.py::TestMovedWorkers``) can
# pin the canonical home with ``is``-identity.
from app.services.data_sync.parallel import (  # noqa: E402,F401
    _parallel_indicator_sync,
)
from app.services.data_sync.snapshot import (  # noqa: E402,F401
    _screener_snapshot_sync,
)
# A.11 part 2 — news + market + calendar sync cores moved out of
# _impl.py into app.services.data_sync.{news,market,calendar}.
from app.services.data_sync.news import (  # noqa: E402,F401
    _crawl_news_async,
    _news_sync,
    _news_periodic_sync,
    _news_rss_sync,
    _news_rss_sync_async,
    _watchlist_news_sync,
    _fetch_company_news_async,
    NEWS_CRON,
    NEWS_CRAWL_MAX_INTERVAL,
    WATCHLIST_NEWS_STALE_SECONDS,
)
from app.services.data_sync.market import (  # noqa: E402,F401
    _is_market_open,
    _seconds_until_market_open,
    _refresh_market_data_async,
    _market_data_sync,
)
from app.services.data_sync.calendar import (  # noqa: E402,F401
    _results_calendar_sync,
    _RESULTS_CALENDAR_CRON,
)
# A.12 part 1 — leaf data_sync helpers + cycle functions + register_all_jobs
from app.services.data_sync.nse_parsing import (  # noqa: E402,F401
    _parse_52week_data,
    _parse_volume_gainers,
    _safe_fetch_52week_high,
    _safe_fetch_52week_low,
    _safe_fetch_volume_gainers,
    _safe_fetch_top_gainers,
    _safe_fetch_top_losers,
    _safe_fetch_largedeal_snapshot,
)
from app.services.data_sync.deal_significance import (  # noqa: E402,F401
    DealRecord,
    _coerce_int,
    _coerce_float,
    _is_recent,
    _parse_largedeal_snapshot,
    _fetch_deal_market_caps,
    _fetch_short_deal_close_prices,
    _is_deal_significant,
)
from app.services.data_sync.insider_trades import (  # noqa: E402,F401
    _fetch_insider_trades_cached,
    _fetch_insider_trades_async,
)
from app.services.data_sync.cleanup import (  # noqa: E402,F401
    _run_cleanup_if_due,
    CLEANUP_READ_AFTER_DAYS,
    CLEANUP_INTERVAL,
    INTRADAY_1H_RETENTION_DAYS,
    INTRADAY_W_RETENTION_YEARS,
    NEWS_RETENTION_DAYS,
    _cleanup_last_run,
)
from app.services.data_sync.notifications import (  # noqa: E402,F401
    NOTIFICATION_CHECK_INTERVAL,
    AFTER_HOURS_INTERVAL,
    DAILY_NOTIFICATION_WINDOW_DAYS,
    _get_watchlist_symbols,
    _get_seen_today,
    _bulk_upsert_notifications,
    _get_global_seen_today,
    _bulk_upsert_global_notifications,
    get_notif_config,
    _build_alerts,
)
from app.workers.notification_cycles import (  # noqa: E402,F401
    _notification_cycle_full,
    _notification_cycle_reduced,
    _ticker_indicator_notification_cycle,
    _ticker_intraday_indicator_notification_cycle,
)
from app.workers.global_scan_cycle import (  # noqa: E402,F401
    _global_scan_cycle,
    GLOBAL_SCAN_BATCH_SIZE,
    GLOBAL_SCAN_DELAY,
)
# A.12 part 1 — register_all_jobs moved out of _impl to
# app.workers.jobs.  Imported separately (NOT through ``_impl``) so
# the re-export shim test
# (``tests/test_backgroundtasks_split.py::TestMovedWorkers``) can
# pin the canonical home with ``is``-identity.
from app.workers.jobs import (  # noqa: E402,F401
    register_all_jobs,
)
# A.3-A.8 — universe, backfill, intraday, daily, scores, indicators
# sync cores.  Imported directly from their final homes (NOT through
# ``_impl``) so the re-export shim test
# (``tests/test_backgroundtasks_split.py::TestMovedWorkers``) can pin
# the canonical home with ``is``-identity.
from app.services.data_sync.universe import (  # noqa: E402,F401
    _stock_universe_sync,
    _update_symbol_error_status,
    _bulk_insert_stock_universe,
)
from app.services.data_sync.backfill import (  # noqa: E402,F401
    _ticker_backfill_sync,
)
from app.services.data_sync.intraday import (  # noqa: E402,F401
    _ticker_intraday_update_sync,
    _ticker_intraday_hourly_stale_check_sync,
)
from app.services.data_sync.daily import (  # noqa: E402,F401
    _ticker_daily_update_sync,
)
from app.services.data_sync.scores import (  # noqa: E402,F401
    _ticker_scores_sync,
)
from app.services.data_sync.indicators import (  # noqa: E402,F401
    _ticker_indicators_sync,
    _ticker_intraday_indicators_sync,
)
# A.12 part 2 — Morningstar fair-value sync moved to
# ``app.services.fair_value``.  Imported directly (NOT through
# ``_impl``) so the re-export shim test
# (``tests/test_backgroundtasks_split.py::TestMovedWorkers``) can pin
# the canonical home with ``is``-identity.
from app.services.fair_value import (  # noqa: E402,F401
    _batch_resolve_morningstar_ids,
    _batch_update_fair_values,
    _get_full_lock,
    _get_watchlist_lock,
    _run_nightly_scheduler,
    _run_watchlist_scheduler,
    _should_trigger_full_sync,
    _update_sync_timestamp,
    sync_all_fair_values,
    sync_watchlist_fair_values,
)
# A.12 part 3 — worker lifecycle moved to ``app.workers.lifecycle``.
# Imported directly (NOT through ``_impl``) so the re-export shim test
# (``tests/test_backgroundtasks_split.py::TestMovedWorkers``) can pin
# the canonical home with ``is``-identity.
from app.workers.lifecycle import (  # noqa: E402,F401
    start_all_workers,
    stop_all_workers,
    start_cache_cleanup,
)

"""Background-job registry (audit C.1, A.12 part 1, A.13).

Defines every job (cron + callable) the system runs and registers
them with the ``JobRegistry``.  The daemons in ``app.workers.*``
spawn the actual threads that drive these callables on schedule.

Why a separate module:  ``register_all_jobs`` was the last
``_impl``-resident function that needed every other cycle /
sync core in its closure (each ``JobDefinition.callable=`` was
a direct reference to a function in another module).  Moving
it here isolates it from the rest of ``_impl`` and gives the
call-sites (``start_all_workers``) a single import.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
import logging

from app.jobs.registry import JobDefinition, JobRegistry
from app.services.data_sync.backfill import _ticker_backfill_sync
from app.services.data_sync.calendar import _results_calendar_sync
from app.services.data_sync.daily import _ticker_daily_update_sync
from app.services.data_sync.indicators import (
    _ticker_indicators_sync,
    _ticker_intraday_indicators_sync,
)
from app.services.data_sync.intraday import (
    _ticker_intraday_hourly_stale_check_sync,
    _ticker_intraday_update_sync,
)
from app.services.data_sync.fundamentals import _fundamentals_sync
from app.services.data_sync.market import _market_data_sync
from app.services.data_sync.news import _news_sync, _watchlist_news_sync
from app.services.data_sync.scores import _ticker_scores_sync
from app.services.data_sync.universe import _stock_universe_sync
from app.services.fair_value import sync_all_fair_values, sync_watchlist_fair_values
from app.workers.global_scan_cycle import _global_scan_cycle
from app.workers.maintenance import VACUUM_CRON, _run_vacuum
from app.workers.notification_cycles import (
    _notification_cycle_full,
)


logger = logging.getLogger(__name__)


def register_all_jobs() -> None:
    """Register all background jobs with the job registry."""
    from app.workers.ai_picks_worker import run_loop_1_and_2, run_loop_3

    jobs = [
        # --- Data warehouse (startup / daily) ---
        # NOTE: callables here are the *sync* (work) functions, not the worker
        # daemon loops.  The daemons are spawned separately by start_all_workers()
        # and own the first_run guard + cron-sleep loop.  Registering sync
        # functions here means trigger_job() / manual API calls execute the
        # real work directly without touching first_run flags or sleeping.
        JobDefinition(
            job_key="job.ticker_backfill",
            name="ticker_backfill",
            description="Backfill 1-year OHLCV daily history for all NSE stocks (watchlist-first)",
            category="data_warehouse",
            cron_expression="@startup",
            callable=_ticker_backfill_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.stock_universe",
            name="stock_universe",
            description="Sync stock metadata from NSE",
            category="data_sync",
            cron_expression="0 0 * * *",
            callable=_stock_universe_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_indicators",
            name="ticker_indicators",
            description="Compute and store technical indicators for all symbols",
            category="data_warehouse",
            cron_expression="0 11 * * 1-5",
            callable=_ticker_indicators_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_scores",
            name="ticker_scores",
            description="Compute and cache returns + momentum for all symbols (once per day)",
            category="data_warehouse",
            cron_expression="0 0 * * *",
            callable=_ticker_scores_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_daily_update",
            name="ticker_daily_update",
            description="Post-close bhavcopy download + nightly catch-up for all NSE stocks",
            category="data_warehouse",
            cron_expression="*/30 15,16,17,18,19,20 * * 1-5",
            callable=_ticker_daily_update_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_intraday_hourly_update",
            name="ticker_intraday_hourly_update",
            description="Backfill 1h candles from NSE charting API for all watchlist symbols during market hours",
            category="data_warehouse",
            cron_expression="15 9,10,11,12,13,14,15 * * 1-5",
            callable=_ticker_intraday_update_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_intraday_hourly_indicators",
            name="ticker_intraday_hourly_indicators",
            description="Compute and store technical indicators for 1h intraday candles during market hours",
            category="data_warehouse",
            cron_expression="30 9,10,11,12,13,14,15 * * 1-5",
            callable=_ticker_intraday_indicators_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_intraday_hourly_stale_check",
            name="ticker_intraday_hourly_stale_check",
            description="Check watchlist 1h candles for gaps and backfill stale symbols (startup/nightly orchestrator stage)",
            category="data_warehouse",
            cron_expression=None,
            callable=_ticker_intraday_hourly_stale_check_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_weekly_monthly_update",
            name="ticker_weekly_monthly_update",
            description="Backfill W/M candles from NSE charting API for all universe symbols (startup + nightly orchestrator stage)",
            category="data_warehouse",
            cron_expression=None,
            callable=_ticker_intraday_update_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.vacuum",
            name="vacuum",
            description="Weekly SQLite VACUUM to reclaim space from deleted rows (Sunday 04:00)",
            category="data_warehouse",
            cron_expression=VACUUM_CRON,
            callable=_run_vacuum,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.ticker_weekly_monthly_indicators",
            name="ticker_weekly_monthly_indicators",
            description="Compute and store technical indicators for W/M intraday candles (nightly orchestrator stage)",
            category="data_warehouse",
            cron_expression=None,
            callable=_ticker_intraday_indicators_sync,
            is_async=False,
        ),
        # --- Live market data ---
        JobDefinition(
            job_key="job.market_data",
            name="market_data",
            description="Rebuild sector/industry aggregates locally every 20 min during market hours (one freeze sync after close)",
            category="data_sync",
            cron_expression="*/20 * * * *",
            callable=_market_data_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.global_scan",
            name="global_scan",
            description="Scan all NSE stocks for technical & market alerts",
            category="notifications",
            cron_expression="*/30 * * * *",
            callable=_global_scan_cycle,
            is_async=False,
        ),
        # --- Notifications ---
        JobDefinition(
            job_key="job.notifications",
            name="notifications",
            description="Generate watchlist stock alerts",
            category="notifications",
            cron_expression="*/5 * * * *",
            callable=_notification_cycle_full,
            is_async=False,
        ),
        # --- Fundamentals (screener market cap + net-profit YoY backfill) ---
        JobDefinition(
            job_key="job.fundamentals",
            name="fundamentals",
            description="Backfill screener market cap + quarterly net-profit YoY for symbols missing them (bounded nightly batches)",
            category="data_sync",
            cron_expression="30 1 * * *",
            callable=_fundamentals_sync,
            is_async=False,
        ),
        # --- News ---
        JobDefinition(
            job_key="job.news",
            name="news",
            description="Crawl global news from MoneyControl",
            category="data_sync",
            cron_expression="*/5 * * * *",
            callable=_news_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.watchlist_news",
            name="watchlist_news",
            description="Fetch news for watchlist symbols",
            category="notifications",
            cron_expression="*/5 * * * *",
            callable=_watchlist_news_sync,
            is_async=False,
        ),
        JobDefinition(
            job_key="job.watchlist_deals",
            name="watchlist_deals",
            description="Fetch deals and insider trades for watchlist symbols",
            category="notifications",
            cron_expression="*/30 * * * *",
            callable=__import__("app.services.data_sync.deals", fromlist=["_watchlist_deals_sync"])._watchlist_deals_sync,
            is_async=False,
        ),
        # --- Fair value (async) ---
        JobDefinition(
            job_key="job.watchlist_fair_value",
            name="watchlist_fair_value",
            description="Fetch Morningstar fair values for watchlist",
            category="analytics",
            cron_expression="0 */3 * * *",
            callable=sync_watchlist_fair_values,
            is_async=True,
        ),
        JobDefinition(
            job_key="job.full_fair_value",
            name="full_fair_value",
            description="Fetch Morningstar fair values for all stocks",
            category="analytics",
            cron_expression="30 20 * * *",
            callable=sync_all_fair_values,
            is_async=True,
        ),
        JobDefinition(
            job_key="job.results_calendar",
            name="results_calendar",
            description="Sync upcoming board meeting results alerts from NSE event calendar",
            category="notifications",
            cron_expression="0 8,14 * * 1-5",
            callable=_results_calendar_sync,
            is_async=False,
        ),

        # --- AI Picks ---
        JobDefinition(
            job_key="job.ai_picks_morning",
            name="ai_picks_morning",
            description="AI Picks Hunter/Verifier loop (Pre-market scan)",
            category="analytics",
            cron_expression="0 8 * * *",
            callable=run_loop_1_and_2,
            is_async=True,
        ),
        JobDefinition(
            job_key="job.ai_picks_evening",
            name="ai_picks_evening",
            description="AI Picks Evaluator loop (Post-market review)",
            category="analytics",
            cron_expression="0 17 * * *",
            callable=run_loop_3,
            is_async=True,
        ),
    ]

    for job in jobs:
        JobRegistry.register(job)
        logger.info(f"Registered job: {job.job_key}")

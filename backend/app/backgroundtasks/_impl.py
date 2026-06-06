import asyncio
import logging
import queue
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import time as dt_time
from dataclasses import dataclass
from datetime import datetime, timedelta, date, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError as _SAOperationalError

from app.services.nse_client import NSEClient, SymbolNotFoundError
from app.services import ticker_warehouse
from app.services import indicators
from app.models import stockuniverse
from app.models.ticker import TickerScore, TickerScreenerSnapshot, TickerIntraday
from app.models.stockuniverse import StockUniverse
from app.models.watchlist import WatchlistItem
from app.models.news import NewsArticle
from app.models.notification import Notification, GlobalNotification
from app.models.system_config import SystemConfig
from app.models.job import Job
from app.database import _SyncSessionLocal, AsyncSessionLocal
from app.config import settings
from app.services.news_fetcher import news_fetcher
from app.services.news_aggregator import fetch_all_feeds, store_articles
from app.services.news_sources import HIGH_PRIORITY_SOURCES
from app.routers.news_ws import broadcast_news_update
from app.services.mc_market_fetcher import market_data_fetcher
from app.services.morningstar_client import (
    REQUEST_DELAY,
    DB_BATCH_SIZE,
    morningstar_client,
)
from app.services.screener_client import screener_client
from app.jobs.registry import JobRegistry, JobDefinition
from app.jobs.runner import sync_all_jobs_to_db, report_progress, update_job_status, update_job_status_sync

logger = logging.getLogger(__name__)


def _is_job_enabled(job_key: str) -> bool:
    """Check if a job is enabled in the database."""
    try:
        with _SyncSessionLocal() as db:
            stmt = select(Job).where(Job.job_key == job_key)
            result = db.execute(stmt)
            job = result.scalar_one_or_none()
            return job.is_enabled if job else True
    except Exception as e:
        logger.warning(f"Failed to check is_enabled for {job_key}, defaulting to enabled: {e}")
        return True


def register_all_jobs() -> None:
    """Register all background jobs with the job registry."""
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
            description="Fetch sector/industry data from MoneyControl",
            category="data_sync",
            cron_expression="*/5 * * * *",
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
    ]

    for job in jobs:
        JobRegistry.register(job)
        logger.info(f"Registered job: {job.job_key}")

_nse_client = NSEClient()


# ---------------------------------------------------------------------------
# Data structures and helpers for notification system
# ---------------------------------------------------------------------------

@dataclass
class DealRecord:
    """Normalized deal record from NSE largedeal snapshot."""
    symbol: str
    deal_type: str       # "bulk", "block", "short"
    date: str            # raw date string from NSE (e.g., "12-Mar-2026")
    qty: int             # coerced from string
    watp: float          # coerced from string/null
    client_name: str | None
    buy_sell: str | None


def _coerce_int(val) -> int:
    """Coerce string/None to int safely."""
    if val is None:
        return 0
    try:
        return int(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0


def _coerce_float(val) -> float:
    """Coerce string/None to float safely."""
    if val is None:
        return 0.0
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _is_recent(date_str: str | None, days: int) -> bool:
    """Check if a date string is within the last N days.
    
    Args:
        date_str: Date in NSE format "12-Mar-2026", or None
        days: Number of days to look back
    Returns:
        True if date is within the last `days` days, False otherwise
    """
    if not date_str:
        return False
    try:
        dt = datetime.strptime(date_str, "%d-%b-%Y").date()
        today = date.today()
        if dt > today:
            return False
        return (today - dt).days <= days
    except ValueError:
        logger.warning("Unparseable date: %s", date_str)
        return False


# ---------------------------------------------------------------------------
# Worker thread state — do not access from async code
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()
_worker_threads: list[threading.Thread] = []


# ---------------------------------------------------------------------------
# Startup sequencing events
# Set by each worker after its first-run sync completes (or is skipped).
# Downstream workers poll these before starting their own first-run work.
# ---------------------------------------------------------------------------
_startup_stock_universe_done   = threading.Event()
_startup_ticker_backfill_done    = threading.Event()
_startup_ticker_indicators_done   = threading.Event()
_startup_ticker_scores_done       = threading.Event()
_startup_ticker_hourly_done       = threading.Event()


# ---------------------------------------------------------------------------
# Cron-cycle pipeline coordination
#
# _pipeline_lock   — mutual exclusion between pipeline *producers*
#                    (ticker_daily_update, ticker_indicators, ticker_scores).
#                    Only one producer runs its pipeline at a time.
#
# _pipeline_idle   — event that is SET when no pipeline is active.
#                    Pipeline consumers (global_scan, watchlist_notification)
#                    wait on this before each cycle so they never run on
#                    stale data while a refresh is in progress.
# ---------------------------------------------------------------------------
_pipeline_lock = threading.Lock()
_pipeline_idle = threading.Event()
_pipeline_idle.set()   # initially idle


def _wait_for_startup_event(event: threading.Event, name: str, job_key: str) -> bool:
    """Block until *event* is set, polling every 5 s with a status update.

    Returns True if shutdown was requested before the event fired (caller
    should return immediately), False if the event is now set.
    """
    while not event.is_set():
        if _shutdown_event.is_set():
            return True
        update_job_status_sync(
            job_key, "waiting", progress=0,
            message=f"Waiting for {name} to complete...",
        )
        _shutdown_event.wait(timeout=5)
    return False


def _wait_for_pipeline(job_key: str, job_name: str) -> bool:
    """Block until the data pipeline is idle (no producer is running).

    Returns True if shutdown was requested, False when pipeline is idle.
    """
    while not _pipeline_idle.is_set():
        if _shutdown_event.is_set():
            return True
        update_job_status_sync(
            job_key, "waiting", progress=0,
            message="Waiting for data pipeline to complete...",
        )
        # Wait on _shutdown_event (not _pipeline_idle) so a shutdown signal
        # wakes this loop immediately rather than blocking the full 5 s timeout.
        _shutdown_event.wait(timeout=5)
    return False


# ---------------------------------------------------------------------------
# Async task shutdown event — for asyncio tasks
# ---------------------------------------------------------------------------
_async_shutdown_event: asyncio.Event | None = None


def get_async_shutdown_event() -> asyncio.Event:
    """Get or create the async shutdown event."""
    global _async_shutdown_event
    if _async_shutdown_event is None:
        _async_shutdown_event = asyncio.Event()
        _async_shutdown_event.set()
    return _async_shutdown_event


def reset_async_shutdown_event() -> None:
    """Reset the async shutdown event (clear it) to allow async tasks to run."""
    global _async_shutdown_event
    if _async_shutdown_event is not None:
        _async_shutdown_event.clear()


def set_async_shutdown_event() -> None:
    """Set the async shutdown event to signal async tasks to stop."""
    global _async_shutdown_event
    if _async_shutdown_event is None:
        _async_shutdown_event = asyncio.Event()
    _async_shutdown_event.set()


# ---------------------------------------------------------------------------
# First run detection — per-worker flags in SystemConfig
# ---------------------------------------------------------------------------
# Each worker owns its own key: "first_run.<worker_name>"
# Workers never share a flag, so a fast-starting worker cannot steal the
# first-run opportunity from a slower one.
# ---------------------------------------------------------------------------
_first_run_completed_cache: dict[str, bool] = {}
_first_run_lock = threading.Lock()


def _is_first_run(worker: str) -> bool:
    """Return True if this worker has not yet completed its first-run sync.

    Uses key ``first_run.<worker>`` in SystemConfig.  If the key is absent it
    is created (value ``"True"``) and True is returned.  Thread-safe: a lock
    prevents two threads from both seeing the key as absent simultaneously.
    """
    if _first_run_completed_cache.get(worker):
        return False

    key = f"first_run.{worker}"
    with _first_run_lock:
        # Re-check inside lock in case another thread just set it.
        if _first_run_completed_cache.get(worker):
            return False
        try:
            with _SyncSessionLocal() as db:
                stmt = select(SystemConfig).where(SystemConfig.key == key)
                config = db.execute(stmt).scalar_one_or_none()
                if config is None:
                    db.add(SystemConfig(key=key, value="True"))
                    db.commit()
                    return True
                return config.value == "True"
        except Exception as e:
            logger.warning(f"Failed to check first_run for {worker}, defaulting to True: {e}")
            return True


def _set_first_run_complete(worker: str) -> None:
    """Mark this worker's first-run as complete.

    Sets ``first_run.<worker>`` to ``"False"`` in SystemConfig and caches the
    result in-process so subsequent calls are free.
    """
    if _first_run_completed_cache.get(worker):
        return

    key = f"first_run.{worker}"
    try:
        with _SyncSessionLocal() as db:
            stmt = select(SystemConfig).where(SystemConfig.key == key)
            config = db.execute(stmt).scalar_one_or_none()
            if config:
                config.value = "False"
            else:
                db.add(SystemConfig(key=key, value="False"))
            db.commit()
            _first_run_completed_cache[worker] = True
            logger.info(f"first_run flag set to False for worker: {worker}")
    except Exception as e:
        logger.warning(f"Failed to set first_run to False for {worker}: {e}")


def _sleep_interruptible(seconds: float) -> bool:
    """Sleep for up to `seconds`, returning True if interrupted by shutdown."""
    return _shutdown_event.wait(timeout=seconds)


def _run_async(coro):
    """
    Run an async coroutine to completion using a fresh event loop.

    Creates a new event loop in the worker thread, runs the coroutine, and
    closes the loop. The Semaphore/Event in news_fetcher (created at module
    load in the main thread) is passed as an argument, so it's used within
    the same fresh loop — avoiding "bound to a different event loop" errors.

    NEVER call this from the main async event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _seconds_until_next_cron(cron_expr: str) -> float:
    """Return seconds from now until the next fire time for the given cron expression.

    Returns a large sentinel (24 hours) for @startup — that expression means
    'run once at startup then idle forever', so callers that mistakenly reach
    this helper should simply sleep a long time rather than crash.
    """
    if cron_expr == "@startup":
        return 86400.0  # 24 hours — effectively idle
    from croniter import croniter
    now = datetime.now()
    return (croniter(cron_expr, now).get_next(datetime) - now).total_seconds()


def _report_job_waiting(job_key: str, cron_expr: str | None, message: str | None = None) -> float:
    """Set job status to 'waiting' with a computed next_trigger_at, then return the
    number of seconds until the next cron fire for the caller to sleep.

    For ``@startup`` or ``None`` cron expressions, next_trigger_at is left NULL
    (manual-only / one-shot behaviour).
    """
    if cron_expr is None or cron_expr == "@startup":
        update_job_status_sync(job_key, "waiting", progress=100,
                               message=message or "Manual only")
        return 86400.0  # long idle

    wait_secs = _seconds_until_next_cron(cron_expr)
    next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
    update_job_status_sync(
        job_key, "waiting", progress=100,
        message=message or f"Next run in {wait_secs / 3600:.1f}h",
        next_trigger=next_trigger,
    )
    return wait_secs


def _stock_universe_sync() -> None:
    """Populate or refresh the stock universe table. Runs synchronously in a worker thread."""
    try:
        logger.info("stock_universe_sync: starting")
        stock_list: list[str] = _nse_client.get_stock_list()
        total = len(stock_list)
        logger.info("stock_universe_sync: %d symbols to process", total)

        stale_delta = timedelta(hours=12)
        batch_size = 50

        with _SyncSessionLocal() as session:
            batch: list = []
            for i, symbol in enumerate(stock_list, 1):
                if _shutdown_event.is_set():
                    logger.info("stock_universe_sync: shutdown requested mid-run, aborting")
                    return

                if i % 100 == 0:
                    progress = int((i / total) * 100)
                    update_job_status_sync(
                        "job.stock_universe", "running", progress=progress,
                        message=f"Processing {i}/{total} symbols",
                    )

                existing = session.get(stockuniverse.StockUniverse, symbol)
                last_time = None
                if existing is not None:
                    last_time = getattr(existing, "last_update_time", None) or getattr(
                        existing, "last_fetched_at", None
                    )
                if last_time is not None:
                    try:
                        now = datetime.now()
                        if (now - last_time) < stale_delta:
                            logger.debug(
                                "Skipping %s — last update was %s (within %.0f hours)",
                                symbol,
                                last_time,
                                stale_delta.total_seconds() / 3600,
                            )
                            continue
                    except Exception:
                        logger.debug(
                            "Unable to compare last update time for %s; refreshing",
                            symbol,
                        )

                try:
                    metadata = _nse_client.get_stock_metadata(symbol)
                    batch.append(metadata)
                    if len(batch) >= batch_size:
                        _bulk_insert_stock_universe(session, batch)
                        session.commit()
                        batch.clear()
                        if _sleep_interruptible(0.5):
                            return
                except SymbolNotFoundError:
                    _update_symbol_error_status(session, symbol, "unknown")
                    session.commit()
                    logger.warning("Symbol %s: no tradeable series found, marked as unknown", symbol)
                    if _sleep_interruptible(0.5):
                        return
                    continue
                except _SAOperationalError as e:
                    logger.warning(
                        "DB write failed for %s (will retry next cycle): %s", symbol, e
                    )
                    session.rollback()
                    if _sleep_interruptible(1.0):
                        return
                    continue
                except Exception:
                    logger.warning("Failed to fetch NSE metadata for %s, skipping", symbol)
                    if _sleep_interruptible(1.0):
                        return
                    continue

            if batch:
                _bulk_insert_stock_universe(session, batch)
                session.commit()

        update_job_status_sync(
            "job.stock_universe",
            "idle",
            progress=100,
            message="Stock universe sync complete",
        )
        logger.info("stock_universe_sync: complete")
    except Exception:
        logger.exception("stock_universe_sync: unhandled exception; will retry next cycle")


def _update_symbol_error_status(session, symbol: str, reason: str, series: str | None = None) -> None:
    """Set review_status (and optionally series) on an existing stock_universe row."""
    values: dict[str, object] = {"review_status": reason}
    if series is not None:
        values["series"] = series
    session.execute(
        update(stockuniverse.StockUniverse)
        .where(stockuniverse.StockUniverse.symbol == symbol)
        .values(**values)
    )


def _bulk_insert_stock_universe(session, batch: list) -> None:
    """Bulk insert or update a batch of stock universe records."""
    if not batch:
        return
    for metadata in batch:
        stmt = (
            sqlite_insert(stockuniverse.StockUniverse)
.values(
                symbol=metadata.symbol,
                company_name=metadata.companyName,
                segment=metadata.segment,
                industry=metadata.industry,
                sector_pe=metadata.sectorPE,
                symbol_pe=metadata.symbolPE,
                industry_info=metadata.industryInfo,
                last_update_time=metadata.lastUpdateTime,
                high_52w=metadata.high_52w,
                low_52w=metadata.low_52w,
                high_52w_date=metadata.high_52w_date,
                low_52w_date=metadata.low_52w_date,
                series=metadata.series if hasattr(metadata, "series") else None,
                review_status=None,
            )
            .on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "company_name": metadata.companyName,
                    "segment": metadata.segment,
                    "industry": metadata.industry,
                    "sector_pe": metadata.sectorPE,
                    "symbol_pe": metadata.symbolPE,
                    "industry_info": metadata.industryInfo,
                    "last_update_time": metadata.lastUpdateTime,
                    "high_52w": metadata.high_52w,
                    "low_52w": metadata.low_52w,
                    "high_52w_date": metadata.high_52w_date,
                    "low_52w_date": metadata.low_52w_date,
                    "series": metadata.series if hasattr(metadata, "series") else None,
                    "review_status": None,  # clear error status on re-fetch
                    "high_52w_updated_at": func.now(),
                    "updated_at": func.now(),
                },
            )
        )
        session.execute(stmt)


def stock_universe_worker() -> None:
    """Daemon thread target for stock universe refresh."""
    logger.info("stock_universe_worker: started")

    if not _is_job_enabled("job.stock_universe"):
        logger.info("stock_universe_worker: disabled, waiting...")
        update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.stock_universe", "idle", progress=0, message="Stopped")
        logger.info("stock_universe_worker: stopped")
        return

    # Startup sequencing is owned by the orchestrator pipeline. The worker only
    # handles scheduled cron refreshes after startup completes.
    if _is_first_run("stock_universe"):
        logger.info("stock_universe_worker: orchestrator owns startup sync, skipping worker first-run execution")
        _set_first_run_complete("stock_universe")
    else:
        logger.info("stock_universe_worker: first_run=False, skipping startup execution")
    update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Waiting for orchestrator / cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.stock_universe", "0 0 * * *")
        logger.info("stock_universe_worker: sleeping %.0fs until next cron (0 0 * * *)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.stock_universe"):
                update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.stock_universe", "running", progress=0, message="Syncing stock universe...")
            _stock_universe_sync()

    update_job_status_sync("job.stock_universe", "idle", progress=0, message="Stopped")
    logger.info("stock_universe_worker: stopped")


def _ticker_backfill_sync() -> None:
    """Perform the ticker backfill synchronization.

    Processes up to 10 symbols concurrently using a thread pool. Each batch
    of 10 is submitted together; results are collected before moving to the
    next batch. One REQUEST_DELAY_SECONDS sleep is applied per batch (not per
    symbol) to stay within NSE rate limits while improving throughput ~10x.
    """
    _BATCH_SIZE = 10

    symbols = ticker_warehouse.get_symbols_needing_backfill()
    total = len(symbols)
    if total == 0:
        logger.info("ticker_backfill_sync: no symbols need backfill")
        update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="All symbols up to date")
        return

    logger.info(f"ticker_backfill_sync: {total} symbols need backfill (batch_size={_BATCH_SIZE})")

    processed = 0
    for batch_start in range(0, total, _BATCH_SIZE):
        if _shutdown_event.is_set():
            break

        batch = symbols[batch_start : batch_start + _BATCH_SIZE]

        # Refresh NSE session every 50 cumulative symbols
        if processed > 0 and (processed // 50) != ((processed - len(batch)) // 50):
            logger.info(f"ticker_backfill_sync: refreshing session after {processed} symbols")
            ticker_warehouse._refresh_nse_session()

        progress = int((batch_start / total) * 100)
        update_job_status_sync(
            "job.ticker_backfill",
            "running",
            progress=progress,
            message=f"Backfilling {batch[0]}..{batch[-1]} ({batch_start + 1}-{min(batch_start + _BATCH_SIZE, total)}/{total})",
        )

        with ThreadPoolExecutor(max_workers=_BATCH_SIZE) as pool:
            future_to_symbol = {
                pool.submit(ticker_warehouse.backfill_symbol, sym, 365): sym
                for sym in batch
            }
            for future in as_completed(future_to_symbol):
                sym = future_to_symbol[future]
                try:
                    future.result()
                except Exception as e:
                    logger.warning(f"ticker_backfill_sync: failed for {sym}: {e}")

        processed += len(batch)
        time.sleep(ticker_warehouse.REQUEST_DELAY_SECONDS)

    update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="Backfill complete")
    logger.info("ticker_backfill_sync: complete")


def ticker_backfill_worker() -> None:
    """Daemon thread target for ticker backfill.

    Runs on every server startup (after stock universe is ready).
    get_symbols_needing_backfill() now checks both row count and staleness, so
    when data is current this completes near-instantly with no symbols to process.
    """
    logger.info("ticker_backfill_worker: started")

    if not _is_job_enabled("job.ticker_backfill"):
        logger.info("ticker_backfill_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_backfill", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
        logger.info("ticker_backfill_worker: stopped")
        return

    # Wait for stock universe to be populated before backfilling
    if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.ticker_backfill"):
        update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
        logger.info("ticker_backfill_worker: stopped")
        return

    if _is_first_run("ticker_backfill"):
        logger.info("ticker_backfill_worker: orchestrator owns startup backfill, skipping worker first-run execution")
        _set_first_run_complete("ticker_backfill")
    else:
        logger.info("ticker_backfill_worker: first_run=False, startup already delegated to orchestrator")

    update_job_status_sync("job.ticker_backfill", "waiting", progress=0, message="Waiting for orchestrator startup / idle")
    logger.info("ticker_backfill_worker: startup work delegated to orchestrator, idling until shutdown")

    while not _shutdown_event.is_set():
        _sleep_interruptible(3600)

    update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
    logger.info("ticker_backfill_worker: stopped")


def _ticker_daily_update_sync() -> None:
    """Perform the daily ticker update via bhavcopy.

    Only runs during post-market hours (after 15:30 IST) on trading days.
    Loops over the last CATCH_UP_DAYS weekdays (newest first) and fetches
    bhavcopy for every date that is missing or has insufficient data —
    regardless of whether a more-recent date already has data (gap-safe).

    After bhavcopy runs, any watchlist symbols that are still stale (e.g.
    listed under a different bhavcopy name) are patched individually via
    the equity_history fallback.

    After candles are inserted, triggers _ticker_indicator_notification_cycle()
    and _ticker_scores_sync() so that indicator-based alerts are evaluated
    on the freshest data.
    """
    from sqlalchemy import func
    from app.models.ticker import TickerDaily
    from app.models.watchlist import WatchlistItem

    CATCH_UP_DAYS = 5  # look back at most this many weekdays
    BHAVCOPY_MIN_ROWS = 2000  # minimum rows expected from a valid bhavcopy

    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(ZoneInfo("Asia/Kolkata"))

    if now_ist.weekday() >= 5:
        logger.info("ticker_daily_update_sync: weekend, skipping")
        return

    market_start = now_ist.replace(
        hour=settings.market_start_hour,
        minute=settings.market_start_minute,
        second=0,
        microsecond=0,
    )
    market_end = now_ist.replace(
        hour=settings.market_end_hour,
        minute=settings.market_end_minute,
        second=0,
        microsecond=0,
    )

    if now_ist < market_start:
        logger.info(f"ticker_daily_update_sync: pre-market ({now_ist.strftime('%H:%M:%S %Z')}), skipping")
        return

    if now_ist <= market_end:
        logger.info(f"ticker_daily_update_sync: market hours ({now_ist.strftime('%H:%M:%S %Z')}), waiting for post-market")
        return

    # Build list of up to CATCH_UP_DAYS recent weekdays (newest first)
    candidates: list[date] = []
    cursor = date.today()
    while len(candidates) < CATCH_UP_DAYS:
        if cursor.weekday() < 5:
            candidates.append(cursor)
        cursor -= timedelta(days=1)

    inserted_any = False
    for i, target_date in enumerate(candidates):
        date_str = target_date.strftime("%d-%m-%Y")
        progress_pct = int(20 + (i / len(candidates)) * 60)

        # Check if this date already has sufficient data — if so, skip it
        # (but do NOT break: older dates may still have gaps)
        with _SyncSessionLocal() as db:
            row_count = db.query(func.count(TickerDaily.symbol)).filter(TickerDaily.date == target_date).scalar() or 0

        if row_count >= BHAVCOPY_MIN_ROWS:
            logger.info(f"ticker_daily_update_sync: {date_str} already has {row_count} rows — skipping")
            continue

        logger.info(f"ticker_daily_update_sync: fetching bhavcopy for {date_str} (currently {row_count} rows)")
        update_job_status_sync(
            "job.ticker_daily_update", "running", progress=progress_pct,
            message=f"Fetching bhavcopy for {date_str}...",
        )

        try:
            rows = ticker_warehouse.bulk_update_via_bhavcopy(date_str)
            if rows > 0:
                logger.info(f"ticker_daily_update_sync: inserted {rows} rows for {date_str}")
                inserted_any = True
                update_job_status_sync(
                    "job.ticker_daily_update", "running", progress=progress_pct,
                    message=f"Updated {rows} symbols for {date_str}",
                )
            else:
                logger.info(
                    f"ticker_daily_update_sync: bhavcopy returned 0 rows for {date_str} "
                    f"(likely a public holiday), skipping"
                )
        except Exception as e:
            logger.warning(f"ticker_daily_update_sync: bhavcopy failed for {date_str}: {e}")

    # --- Watchlist staleness fallback ---
    # After bhavcopy, check watchlist symbols still missing today's candle.
    # Some symbols appear under different names in bhavcopy (e.g. SME stocks)
    # so we patch them individually via equity_history.
    last_trading_day = ticker_warehouse.get_last_trading_day()
    try:
        with _SyncSessionLocal() as db:
            watchlist_symbols = list(
                db.execute(
                    select(func.distinct(WatchlistItem.symbol))
                ).scalars().all()
            )

        if watchlist_symbols:
            # Find which watchlist symbols are missing today's candle
            with _SyncSessionLocal() as db:
                covered = set(
                    db.execute(
                        select(TickerDaily.symbol)
                        .where(TickerDaily.date == last_trading_day)
                        .where(TickerDaily.symbol.in_(watchlist_symbols))
                    ).scalars().all()
                )

            stale_watchlist = [s for s in watchlist_symbols if s not in covered]

            if stale_watchlist:
                logger.info(
                    f"ticker_daily_update_sync: {len(stale_watchlist)} watchlist symbol(s) still "
                    f"stale after bhavcopy — patching via equity_history: {stale_watchlist[:10]}"
                    + ("..." if len(stale_watchlist) > 10 else "")
                )
                update_job_status_sync(
                    "job.ticker_daily_update", "running", progress=85,
                    message=f"Patching {len(stale_watchlist)} stale watchlist symbols...",
                )
                patched = 0
                for sym in stale_watchlist:
                    try:
                        n = ticker_warehouse.update_symbol_today(sym, last_trading_day)
                        if n > 0:
                            patched += 1
                            inserted_any = True
                    except Exception as e:
                        logger.warning(f"ticker_daily_update_sync: equity_history fallback failed for {sym}: {e}")
                    # Small delay to avoid hammering NSE
                    time.sleep(0.5)

                if patched:
                    logger.info(f"ticker_daily_update_sync: patched {patched}/{len(stale_watchlist)} watchlist symbols")
    except Exception as e:
        logger.warning(f"ticker_daily_update_sync: watchlist staleness check failed: {e}")

    update_job_status_sync(
        "job.ticker_daily_update", "running", progress=95,
        message="Running indicators and scores..." if inserted_any else "No new data",
    )

    if inserted_any:
        _ticker_indicator_notification_cycle()
        _ticker_scores_sync()


def ticker_daily_update_worker() -> None:
    """Daemon thread target for ticker daily updates (cron: */30 15,16,17,18,19,20 * * 1-5)."""
    logger.info("ticker_daily_update_worker: started")

    if not _is_job_enabled("job.ticker_daily_update"):
        logger.info("ticker_daily_update_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_daily_update", "idle", progress=0, message="Stopped")
        logger.info("ticker_daily_update_worker: stopped")
        return

    # Startup sequencing is owned by the orchestrator. Daily update is a nightly
    # stage there, so the worker should only handle its recurring cron schedule.
    if _is_first_run("ticker_daily_update"):
        logger.info("ticker_daily_update_worker: orchestrator owns startup/nightly sequencing, skipping worker first-run execution")
        _set_first_run_complete("ticker_daily_update")
    else:
        logger.info("ticker_daily_update_worker: first_run=False, skipping startup execution")
    update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_daily_update", "*/30 15,16,17,18,19,20 * * 1-5")
        logger.info("ticker_daily_update_worker: sleeping %.0fs until next cron (*/30 15,16,17,18,19,20 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_daily_update"):
                update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            # Acquire pipeline lock: daily_update runs the full pipeline
            # (candles → indicators → scores) so scan/notif workers wait
            with _pipeline_lock:
                _pipeline_idle.clear()
                try:
                    update_job_status_sync("job.ticker_daily_update", "running", progress=0, message="Running daily update...")
                    _ticker_daily_update_sync()
                finally:
                    _pipeline_idle.set()

    update_job_status_sync("job.ticker_daily_update", "idle", progress=0, message="Stopped")
    logger.info("ticker_daily_update_worker: stopped")


# ---------------------------------------------------------------------------
# Intraday / Weekly / Monthly candle worker
# ---------------------------------------------------------------------------

def _ticker_intraday_update_sync(
    intervals: list[str] = None,
    scope: str = "watchlist",
    smart: bool = False,
    from_ts_overrides: Optional[dict[str, int]] = None,
) -> None:
    """Synchronous core: backfill intraday candles for watchlist or all universe symbols.

    Args:
        intervals: List of intervals to backfill (e.g. ["1h"], ["W", "M"]).
            Defaults to ["1h", "W", "M"] for backward compatibility.
        scope: "watchlist" (default) — only symbols in any watchlist.
               "universe" — all symbols in stock_universe (for W/M nightly/startup runs).
        smart: If True, only backfill symbols whose latest stored candle is older
            than the DB consensus (most common latest timestamp). Skips up-to-date
            symbols. Uses DB consensus to avoid false positives from live API
            returning incomplete current periods.
        from_ts_overrides: Optional dict mapping interval → from_ts (Unix seconds).
            When provided, existing symbols get the override window; new symbols
            always fetch full history (from_ts=0).

    Called from workers/orchestrator. Loops symbols, calls backfill_intraday_symbol()
    for each, logs counts. 1 s delay between symbols to avoid NSE charting API rate limits.
    """
    from app.services.ticker_warehouse import (
        backfill_intraday_symbol,
        get_all_universe_symbols,
        get_symbols_needing_intraday_backfill,
        get_watchlist_symbols,
    )

    intervals = intervals or ["1h", "W", "M"]
    if scope == "universe":
        symbols = get_all_universe_symbols()
        scope_label = "universe"
    else:
        symbols = get_watchlist_symbols()
        scope_label = "watchlist"
    if not symbols:
        logger.info("[intraday_worker] no %s symbols to backfill", scope_label)
        return

    # Smart mode: filter to only stale symbols
    symbol_intervals: dict[str, list[str]]
    if smart:
        stale_map = get_symbols_needing_intraday_backfill(intervals, symbols)
        if stale_map is None:
            logger.warning(
                "[intraday_worker] smart mode: consensus check failed, falling back to full %s scope",
                scope_label,
            )
            symbol_intervals = {sym: intervals for sym in symbols}
        elif not stale_map:
            logger.info(
                "[intraday_worker] smart mode: all %d %s symbols up to date for intervals %s",
                len(symbols), scope_label, intervals,
            )
            return
        else:
            symbol_intervals = {}
            for iv, syms in stale_map.items():
                for sym in syms:
                    symbol_intervals.setdefault(sym, []).append(iv)
            logger.info(
                "[intraday_worker] smart mode: %d/%d %s symbols need backfill for intervals %s",
                len(symbol_intervals), len(symbols), scope_label, intervals,
            )
    else:
        symbol_intervals = {sym: intervals for sym in symbols}

    symbols_to_process = list(symbol_intervals.keys())
    total: dict[str, int] = {iv: 0 for iv in intervals}
    errors = 0
    _BATCH_SIZE = 10

    for batch_start in range(0, len(symbols_to_process), _BATCH_SIZE):
        if _shutdown_event.is_set():
            break

        batch = symbols_to_process[batch_start : batch_start + _BATCH_SIZE]

        def _run_intraday(sym: str) -> dict:
            needed = symbol_intervals.get(sym, intervals)
            if not needed:
                return {}
            return backfill_intraday_symbol(sym, needed, from_ts_overrides=from_ts_overrides)

        with ThreadPoolExecutor(max_workers=_BATCH_SIZE) as pool:
            future_to_sym = {pool.submit(_run_intraday, sym): sym for sym in batch}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    counts = future.result()
                    for iv, n in counts.items():
                        if iv in total:
                            total[iv] = total.get(iv, 0) + n
                    logger.debug("[intraday_worker] %s → %s", sym, counts)
                except Exception as exc:
                    logger.warning("[intraday_worker] %s failed: %s", sym, exc)
                    errors += 1

        time.sleep(1.0)

    logger.info(
        "[intraday_worker] done — %s, %d errors",
        ", ".join(f"{iv}:{n}" for iv, n in total.items()),
        errors,
    )


def _ticker_intraday_hourly_stale_check_sync() -> None:
    """Backfill stale 1h candles for watchlist symbols and recompute indicators.

    This stage is orchestrator-managed and runs at startup + nightly. A symbol
    is considered stale when its latest 1h candle for the last trading session
    is older than the latest expected hourly slot for that session.

    Expected slots are 09:15, 10:15, 11:15, 12:15, 13:15, 14:15, 15:15 IST.
    After backfilling a stale symbol, recompute its 1h indicators immediately so
    downstream pipeline stages see fresh data.
    """
    from app.models.ticker import TickerIntraday
    from app.services.indicators import compute_intraday_indicators_for_all_rows
    from app.services.ticker_warehouse import backfill_intraday_symbol, get_last_trading_day, get_watchlist_symbols

    ist = ZoneInfo("Asia/Kolkata")
    symbols = get_watchlist_symbols()
    if not symbols:
        logger.info("[hourly_stale_check] no watchlist symbols to inspect")
        update_job_status_sync(
            "job.ticker_intraday_hourly_stale_check",
            "idle",
            progress=100,
            message="No watchlist symbols to inspect",
        )
        return

    last_trading_day = get_last_trading_day()
    now_ist = datetime.now(ist)
    target_date = last_trading_day

    session_slots = [
        datetime.combine(target_date, dt_time(9, 15)),
        datetime.combine(target_date, dt_time(10, 15)),
        datetime.combine(target_date, dt_time(11, 15)),
        datetime.combine(target_date, dt_time(12, 15)),
        datetime.combine(target_date, dt_time(13, 15)),
        datetime.combine(target_date, dt_time(14, 15)),
        datetime.combine(target_date, dt_time(15, 15)),
    ]

    # During the active session only expect candles up to the latest elapsed slot.
    # After market close, expect the full session through 15:15.
    if target_date == now_ist.date() and now_ist.weekday() < 5:
        slots_elapsed = [slot for slot in session_slots if now_ist >= slot.replace(tzinfo=ist)]
        expected_latest = slots_elapsed[-1] if slots_elapsed else None
    else:
        expected_latest = session_slots[-1]

    if expected_latest is None:
        logger.info("[hourly_stale_check] before first hourly slot; nothing to do")
        update_job_status_sync(
            "job.ticker_intraday_hourly_stale_check",
            "idle",
            progress=100,
            message="Before first hourly slot",
        )
        return

    stale_symbols: list[str] = []
    with _SyncSessionLocal() as db:
        for symbol in symbols:
            latest_ts = db.execute(
                select(func.max(TickerIntraday.timestamp))
                .where(
                    TickerIntraday.symbol == symbol,
                    TickerIntraday.interval == "1h",
                    func.date(TickerIntraday.timestamp) == target_date.isoformat(),
                )
            ).scalar()
            if latest_ts is None or latest_ts < expected_latest:
                stale_symbols.append(symbol)

    total = len(stale_symbols)
    if total == 0:
        logger.info(
            "[hourly_stale_check] all %d watchlist symbols current through %s",
            len(symbols),
            expected_latest.strftime("%Y-%m-%d %H:%M"),
        )
        update_job_status_sync(
            "job.ticker_intraday_hourly_stale_check",
            "idle",
            progress=100,
            message="All watchlist symbols current",
        )
        return

    logger.info(
        "[hourly_stale_check] backfilling %d/%d stale symbols through %s",
        total,
        len(symbols),
        expected_latest.strftime("%Y-%m-%d %H:%M"),
    )

    total_rows = 0
    indicator_updates = 0
    errors = 0

    for idx, symbol in enumerate(stale_symbols, start=1):
        if _shutdown_event.is_set():
            logger.info("[hourly_stale_check] shutdown requested, aborting")
            break

        update_job_status_sync(
            "job.ticker_intraday_hourly_stale_check",
            "running",
            progress=int((idx - 1) / total * 100),
            message=f"Backfilling {symbol} ({idx}/{total})",
        )
        try:
            counts = backfill_intraday_symbol(symbol, ["1h"])
            total_rows += counts.get("1h", 0)
            indicator_updates += compute_intraday_indicators_for_all_rows(symbol, "1h")
            logger.debug("[hourly_stale_check] %s → %s", symbol, counts)
        except Exception as exc:
            logger.warning("[hourly_stale_check] %s failed: %s", symbol, exc)
            errors += 1
        time.sleep(1.0)

    update_job_status_sync(
        "job.ticker_intraday_hourly_stale_check",
        "idle",
        progress=100,
        message=(
            f"Checked {total} stale symbols — rows:{total_rows}, "
            f"indicator updates:{indicator_updates}, errors:{errors}"
        ),
    )
    logger.info(
        "[hourly_stale_check] complete — stale:%d rows:%d indicator_updates:%d errors:%d",
        total,
        total_rows,
        indicator_updates,
        errors,
    )


def ticker_intraday_hourly_update_worker() -> None:
    """Daemon thread target for hourly (1h) intraday candle updates.

    Cron: at :15 past each trading hour 09:15–15:15 IST on weekdays.
    Also executes once at startup (first_run pattern).
    """
    logger.info("ticker_intraday_hourly_update_worker: started")

    if not _is_job_enabled("job.ticker_intraday_hourly_update"):
        logger.info("ticker_intraday_hourly_update_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_intraday_hourly_update", "idle", progress=0, message="Stopped")
        logger.info("ticker_intraday_hourly_update_worker: stopped")
        return

    if _is_first_run("ticker_intraday_hourly_update"):
        update_job_status_sync("job.ticker_intraday_hourly_update", "running", progress=0, message="Starting hourly backfill...")
        try:
            _ticker_intraday_update_sync(["1h"])
        except Exception as exc:
            logger.error("[hourly_worker] startup run failed: %s", exc)
        _set_first_run_complete("ticker_intraday_hourly_update")
        _startup_ticker_hourly_done.set()
        logger.info("ticker_intraday_hourly_update_worker: startup gate released (_startup_ticker_hourly_done)")
        update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Waiting for cron schedule")
    else:
        logger.info("ticker_intraday_hourly_update_worker: first_run=False, skipping startup execution")
        _startup_ticker_hourly_done.set()
        logger.info("ticker_intraday_hourly_update_worker: startup gate released (first_run=False)")
        update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_intraday_hourly_update", "15 9,10,11,12,13,14,15 * * 1-5")
        logger.info("ticker_intraday_hourly_update_worker: sleeping %.0fs until next cron (15 9,10,11,12,13,14,15 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_intraday_hourly_update"):
                update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_intraday_hourly_update", "running", progress=0, message="Running hourly update...")
            try:
                _ticker_intraday_update_sync(["1h"])
            except Exception as exc:
                logger.error("[hourly_worker] cron run failed: %s", exc)
            update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Waiting for cron schedule")

    update_job_status_sync("job.ticker_intraday_hourly_update", "idle", progress=0, message="Stopped")
    logger.info("ticker_intraday_hourly_update_worker: stopped")


def _parallel_indicator_sync(
    items: list[tuple],
    prepare_fn,
    flush_fn,
    *,
    job_key: str,
    pipeline_job_key: str | None = None,
    pipeline_progress_start: int | None = None,
    pipeline_progress_end: int | None = None,
    num_compute_workers: int = 3,
    queue_maxsize: int = 100,
    writer_batch_size: int = 50,
    heartbeat_every_s: float = 10.0,
    progress_every: int = 10,
    slow_threshold_s: float = 5.0,
) -> dict:
    """Thin wrapper around `app.services.parallel_sync.parallel_indicator_sync`
    that wires in the orchestrator's `_shutdown_event`, `_ticker_*_status_sync`
    callbacks, and default logging.

    The full implementation lives in `app.services.parallel_sync` so it can
    be unit-tested without importing the heavy transitive dependencies of
    `app.backgroundtasks` (NSE client, news aggregator, etc.).
    """
    from app.services.parallel_sync import parallel_indicator_sync

    def _on_progress(enqueued: int, total: int, elapsed_s: float, rate: float) -> None:
        logger.info(
            "indicator_sync: enqueued %d/%d (%.1fs, %.1f items/s)",
            enqueued, total, elapsed_s, rate,
        )

    def _on_heartbeat(enqueued: int, total: int, elapsed_s: float) -> None:
        logger.info(
            "indicator_sync: heartbeat — %d/%d enqueued (%.1fs elapsed)",
            enqueued, total, elapsed_s,
        )

    def _update_job(job_key_: str, status: str, progress: int, message: str) -> None:
        update_job_status_sync(job_key_, status, progress=progress, message=message)

    return parallel_indicator_sync(
        items=items,
        prepare_fn=prepare_fn,
        flush_fn=flush_fn,
        shutdown_event=_shutdown_event,
        update_job_status_fn=_update_job,
        job_key=job_key,
        pipeline_job_key=pipeline_job_key,
        pipeline_progress_start=pipeline_progress_start,
        pipeline_progress_end=pipeline_progress_end,
        num_compute_workers=num_compute_workers,
        queue_maxsize=queue_maxsize,
        writer_batch_size=writer_batch_size,
        heartbeat_every_s=heartbeat_every_s,
        progress_every=progress_every,
        slow_threshold_s=slow_threshold_s,
        heartbeat_fn=_on_heartbeat,
        progress_fn=_on_progress,
    )


def _ticker_indicators_sync() -> None:
    """Startup backfill: compute and store per-candle indicators for symbols that
    have uncomputed or stale indicator data.

    A symbol is considered stale when its latest ticker_daily row has a date
    strictly newer than its indicators_updated_at timestamp (i.e. a new candle
    arrived but indicators haven't been recomputed for the full history yet).

    Processes in batches of 100 with a configurable inter-batch delay (env
    `INDICATOR_INTER_BATCH_SLEEP_S`, default 0).  Triggers
    _ticker_indicator_notification_cycle() after completing.
    """
    from app.config import settings
    from app.models.ticker import TickerDaily

    logger.info(
        "ticker_indicators_sync: scanning ticker_daily for stale/null symbols "
        "(this can take ~1-2 min on a large universe)…"
    )
    scan_start = time.monotonic()

    with _SyncSessionLocal() as db:
        # Symbols with any row where indicators_updated_at IS NULL (never backfilled)
        null_result = db.execute(
            select(TickerDaily.symbol)
            .where(TickerDaily.indicators_updated_at.is_(None))
            .distinct()
        )
        null_symbols = {row[0] for row in null_result.fetchall()}

        # Symbols where latest candle date > indicators_updated_at (stale after new candle)
        latest_subq = (
            select(
                TickerDaily.symbol,
                func.max(TickerDaily.date).label("max_date"),
                func.max(TickerDaily.indicators_updated_at).label("max_ind_at"),
            )
            .group_by(TickerDaily.symbol)
            .subquery()
        )
        stale_result = db.execute(
            select(latest_subq.c.symbol)
            .where(
                latest_subq.c.max_ind_at.isnot(None),
                func.date(latest_subq.c.max_date) > func.date(latest_subq.c.max_ind_at),
            )
        )
        stale_symbols = {row[0] for row in stale_result.fetchall()}

    symbols = list(null_symbols | stale_symbols)
    scan_elapsed = time.monotonic() - scan_start

    total = len(symbols)
    logger.info(
        "ticker_indicators_sync: scan complete in %.1fs — %d null, %d stale, %d to process",
        scan_elapsed, len(null_symbols), len(stale_symbols), total,
    )

    if total == 0:
        logger.info("ticker_indicators_sync: all symbols already have per-candle indicators")
        update_job_status_sync("job.ticker_indicators", "idle", progress=100, message="All symbols up to date")
        _ticker_indicator_notification_cycle()
        return

    logger.info("ticker_indicators_sync: backfilling indicators for %d symbols (3 compute + 1 writer threads)", total)

    items = [(s,) for s in symbols]
    summary = _parallel_indicator_sync(
        items,
        indicators.prepare_daily_indicator_updates,
        indicators.flush_daily_indicator_updates,
        job_key="job.ticker_indicators",
        pipeline_job_key="job.pipeline.startup",
        pipeline_progress_start=50,
        pipeline_progress_end=62,
    )

    update_job_status_sync("job.ticker_indicators", "idle", progress=100, message="Indicator backfill complete")
    logger.info(
        "ticker_indicators_sync: complete (%d/%d symbols in %.1fs, %d rows written)",
        summary["success"], total, summary["elapsed_s"], summary["rows_written"],
    )

    _ticker_indicator_notification_cycle()


def _ticker_intraday_indicators_sync(intervals: list[str] = None) -> None:
    """Startup backfill: compute and store per-candle indicators for intraday symbols.

    A symbol+interval pair is considered stale when its latest ticker_intraday
    row has a timestamp strictly newer than its indicators_updated_at.

    Args:
        intervals: List of intervals to process (e.g. ["1h"], ["W", "M"]).
            Defaults to ["1h", "W", "M"] for backward compatibility.

    Processes in batches of 50 with a configurable inter-batch delay (env
    `INDICATOR_INTER_BATCH_SLEEP_S`, default 0).  Triggers
    _ticker_intraday_indicator_notification_cycle() after completing.
    """
    from app.models.ticker import TickerIntraday
    from app.services import indicators

    intervals = intervals or ["1h", "W", "M"]
    job_key = "job.ticker_intraday_indicators" if set(intervals) == {"1h", "W", "M"} else (
        "job.ticker_intraday_hourly_indicators" if intervals == ["1h"] else "job.ticker_weekly_monthly_indicators"
    )

    try:
        logger.info(
            "ticker_intraday_indicators_sync: scanning ticker_intraday for stale/null pairs "
            "intervals=%s",
            intervals,
        )
        scan_start = time.monotonic()

        with _SyncSessionLocal() as db:
            # Symbols with any row where indicators_updated_at IS NULL
            null_result = db.execute(
                select(TickerIntraday.symbol, TickerIntraday.interval)
                .where(TickerIntraday.indicators_updated_at.is_(None),
                       TickerIntraday.interval.in_(intervals))
                .distinct()
            )
            null_pairs = {(row[0], row[1]) for row in null_result.fetchall()}

            # Symbols where latest candle timestamp > indicators_updated_at (stale)
            latest_subq = (
                select(
                    TickerIntraday.symbol,
                    TickerIntraday.interval,
                    func.max(TickerIntraday.timestamp).label("max_ts"),
                    func.max(TickerIntraday.indicators_updated_at).label("max_ind_at"),
                )
                .where(TickerIntraday.interval.in_(intervals))
                .group_by(TickerIntraday.symbol, TickerIntraday.interval)
                .subquery()
            )
            stale_result = db.execute(
                select(latest_subq.c.symbol, latest_subq.c.interval)
                .where(
                    latest_subq.c.max_ind_at.isnot(None),
                    func.date(latest_subq.c.max_ts) > func.date(latest_subq.c.max_ind_at),
                )
            )
            stale_pairs = {(row[0], row[1]) for row in stale_result.fetchall()}

        pairs = list(null_pairs | stale_pairs)
        scan_elapsed = time.monotonic() - scan_start

        total = len(pairs)
        logger.info(
            "ticker_intraday_indicators_sync: scan complete in %.1fs — %d null, %d stale, %d to process (intervals=%s)",
            scan_elapsed, len(null_pairs), len(stale_pairs), total, intervals,
        )

        if total == 0:
            logger.info("ticker_intraday_indicators_sync: all pairs up to date for intervals=%s", intervals)
            update_job_status_sync(job_key, "idle", progress=100, message="All pairs up to date")
            _ticker_intraday_indicator_notification_cycle()
            return

        logger.info(
            "ticker_intraday_indicators_sync: backfilling %d symbol+interval pairs "
            "(3 compute + 1 writer threads, intervals=%s)",
            total, intervals,
        )

        items = list(pairs)  # already a list of (symbol, interval) tuples
        summary = _parallel_indicator_sync(
            items,
            indicators.prepare_intraday_indicator_updates,
            indicators.flush_intraday_indicator_updates,
            job_key=job_key,
            heartbeat_every_s=10.0,
            progress_every=10,
            slow_threshold_s=5.0,
        )

        update_job_status_sync(job_key, "idle", progress=100, message="Intraday indicator backfill complete")
        logger.info(
            "ticker_intraday_indicators_sync: complete (%d/%d pairs in %.1fs, %d rows written, intervals=%s)",
            summary["success"], total, summary["elapsed_s"], summary["rows_written"], intervals,
        )

        _ticker_intraday_indicator_notification_cycle()

    except Exception:
        logger.exception("ticker_intraday_indicators_sync: unhandled exception")


def _ticker_scores_sync() -> None:
    """Compute and cache multi-period returns + momentum scores for all symbols.

    Single bulk query loads last 252 candles for ALL symbols using a window function,
    then computes all returns in-memory. Upserts to ticker_scores table.
    Triggered by _ticker_daily_update_sync() after bhavcopy/fallback.
    """
    from app.models.ticker import TickerDaily, TickerScore

    try:
        logger.info("ticker_scores_sync: starting")
        now = datetime.now()
        today_date = now.date()

        update_job_status_sync("job.ticker_scores", "running", progress=5, message="Querying symbols with 60+ days of data...")
        with _SyncSessionLocal() as db:
            stmt = db.execute(
                select(TickerDaily.symbol, func.count(TickerDaily.id).label("cnt"))
                .group_by(TickerDaily.symbol)
                .having(func.count(TickerDaily.id) >= 60)
            )
            symbols_with_data = [row[0] for row in stmt.fetchall()]

        universe_size = len(symbols_with_data)
        if universe_size == 0:
            logger.warning("ticker_scores_sync: no symbols with 60+ days of data, skipping")
            return

        logger.info("ticker_scores_sync: loading last 252 candles for %d symbols", universe_size)
        update_job_status_sync("job.ticker_scores", "running", progress=10, message=f"Loading candle data for {universe_size} symbols...")

        with _SyncSessionLocal() as db:
            raw = db.execute(
                select(TickerDaily)
                .where(TickerDaily.symbol.in_(symbols_with_data))
                .order_by(TickerDaily.symbol, TickerDaily.date.desc())
            )
            all_rows = list(raw.scalars().all())

        if not all_rows:
            logger.warning("ticker_scores_sync: no ticker_daily rows found")
            return

        df = pd.DataFrame([
            {
                "symbol": r.symbol,
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "rsi_14": r.rsi_14,
                "macd": r.macd,
                "macd_signal": r.macd_signal,
                "macd_histogram": r.macd_histogram,
                "bb_middle": r.bb_middle,
                "bb_upper": r.bb_upper,
                "bb_lower": r.bb_lower,
                "bb_width": r.bb_width,
                "bb_squeeze": r.bb_squeeze,
                "atr_14": r.atr_14,
                "atr_percent": r.atr_percent,
                "vwma_20": r.vwma_20,
                "hv_20": r.hv_20,
                "hv_60": r.hv_60,
                "sharpe_60": r.sharpe_60,
                "sharpe_126": r.sharpe_126,
            }
            for r in all_rows
        ])

        TRADING_DAYS = {"1d": 1, "1w": 5, "1m": 20, "3m": 60, "6m": 120, "1y": 252}

        def calc_return(group_df: pd.DataFrame, days: int) -> Optional[float]:
            if len(group_df) < days + 1:
                return None
            sorted_df = group_df.sort_values("date")
            start_price = sorted_df.iloc[-days - 1]["close"]
            end_price = sorted_df.iloc[-1]["close"]
            if start_price is None or end_price is None or start_price == 0:
                return None
            return ((end_price - start_price) / start_price) * 100

        results: list[dict] = []
        symbols = df["symbol"].unique()
        total = len(symbols)

        for idx, symbol in enumerate(symbols):
            if _shutdown_event.is_set():
                logger.info("ticker_scores_sync: shutdown requested, stopping at %d/%d", idx, total)
                break

            if idx > 0 and idx % 100 == 0:
                logger.info("ticker_scores_sync: progress %d/%d symbols", idx, total)
                # Scale idx from 10% → 70% across the return-computation loop
                progress = 10 + int((idx / total) * 60)
                update_job_status_sync(
                    "job.ticker_scores", "running", progress=progress,
                    message=f"Computing returns: {idx}/{total} symbols",
                )

            sym_df = df[df["symbol"] == symbol].sort_values("date")

            ret_1d = calc_return(sym_df, TRADING_DAYS["1d"])
            ret_1w = calc_return(sym_df, TRADING_DAYS["1w"])
            ret_1m = calc_return(sym_df, TRADING_DAYS["1m"])
            ret_3m = calc_return(sym_df, TRADING_DAYS["3m"])
            ret_6m = calc_return(sym_df, TRADING_DAYS["6m"])
            ret_1y = calc_return(sym_df, TRADING_DAYS["1y"])

            if len(sym_df) >= 21:
                vol_20 = sym_df.tail(21)["volume"].iloc[:-1].mean()
                current_vol = sym_df.iloc[-1]["volume"]
                volume_ratio_20d = current_vol / vol_20 if vol_20 and vol_20 > 0 else None
            else:
                volume_ratio_20d = None

            results.append({
                "symbol": symbol,
                "compute_date": today_date,
                "computed_at": now,
                "return_1d": ret_1d,
                "return_1w": ret_1w,
                "return_1m": ret_1m,
                "return_3m": ret_3m,
                "return_6m": ret_6m,
                "return_1y": ret_1y,
                "volume_ratio_20d": volume_ratio_20d,
            })

        logger.info("ticker_scores_sync: computed returns for %d symbols, computing momentum", len(results))
        update_job_status_sync("job.ticker_scores", "running", progress=75, message=f"Computing momentum scores for {len(results)} symbols...")

        valid_3m = {r["symbol"]: r["return_3m"] for r in results if r["return_3m"] is not None}
        valid_6m = {r["symbol"]: r["return_6m"] for r in results if r["return_6m"] is not None}
        valid_vol = {r["symbol"]: r["volume_ratio_20d"] for r in results if r["volume_ratio_20d"] is not None}

        values_3m = list(valid_3m.values())
        values_6m = list(valid_6m.values())
        values_vol = list(valid_vol.values())

        def percentile_rank(value: Optional[float], all_vals: list[float]) -> float:
            if value is None or not all_vals:
                return 50.0
            sorted_vals = sorted(all_vals)
            rank = sum(1 for v in sorted_vals if v < value)
            return (rank / len(sorted_vals)) * 100

        scores: list[tuple[str, float]] = []
        for r in results:
            sym = r["symbol"]
            r_3m = r["return_3m"]
            r_6m = r["return_6m"]
            r_vol = r["volume_ratio_20d"]

            rank_3m = percentile_rank(r_3m, values_3m)
            rank_6m = percentile_rank(r_6m, values_6m)
            rank_vol = percentile_rank(r_vol, values_vol)

            score = 0.30 * rank_3m + 0.30 * rank_6m + 0.20 * rank_vol
            r["momentum_score"] = round(score, 1)
            scores.append((sym, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        rank_map = {sym: idx + 1 for idx, (sym, _) in enumerate(scores)}

        for r in results:
            r["momentum_rank"] = rank_map.get(r["symbol"])
            r["universe_size"] = universe_size

        logger.info("ticker_scores_sync: upserting %d rows to ticker_scores", len(results))
        update_job_status_sync("job.ticker_scores", "running", progress=90, message=f"Upserting {len(results)} scores to DB...")

        with _SyncSessionLocal() as db:
            insert_stmt = sqlite_insert(TickerScore).values(results)
            insert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "compute_date": insert_stmt.excluded.compute_date,
                    "computed_at": insert_stmt.excluded.computed_at,
                    "return_1d": insert_stmt.excluded.return_1d,
                    "return_1w": insert_stmt.excluded.return_1w,
                    "return_1m": insert_stmt.excluded.return_1m,
                    "return_3m": insert_stmt.excluded.return_3m,
                    "return_6m": insert_stmt.excluded.return_6m,
                    "return_1y": insert_stmt.excluded.return_1y,
                    "momentum_score": insert_stmt.excluded.momentum_score,
                    "momentum_rank": insert_stmt.excluded.momentum_rank,
                    "universe_size": insert_stmt.excluded.universe_size,
                    "volume_ratio_20d": insert_stmt.excluded.volume_ratio_20d,
                },
            )
            db.execute(insert_stmt)
            db.commit()

        # Phase B: also write pre-computed screener snapshot so TQL→SQL
        # queries are O(1) reads against a small denormalized table instead
        # of window-function scans over ticker_daily/ticker_intraday.
        try:
            _screener_snapshot_sync(df, today_date, now)
        except Exception:
            logger.exception("ticker_scores_sync: screener snapshot failed (non-fatal)")

        logger.info("ticker_scores_sync: complete, cached %d symbols", len(results))
        update_job_status_sync("job.ticker_scores", "waiting", progress=100, message=f"Cached {len(results)} symbols")

    except Exception:
        logger.exception("ticker_scores_sync: unhandled exception")


# Phase B: fields to copy from latest 1h/W/M ticker_intraday row into snapshot.
# Each value is (snapshot_column_name, intraday_column_name).
_INTRADAY_COLS: list[tuple[str, str]] = [
    ("intraday_close", "close"),
    ("rsi", "rsi_14"),
    ("macd", "macd"),
    ("macd_signal", "macd_signal"),
    ("macd_histogram", "macd_histogram"),
    ("bb_middle", "bb_middle"),
    ("bb_upper", "bb_upper"),
    ("bb_lower", "bb_lower"),
    ("bb_width", "bb_width"),
    ("bb_squeeze", "bb_squeeze"),
    ("atr", "atr_14"),
    ("atr_percent", "atr_percent"),
    ("vwma_20", "vwma_20"),
    ("hv_20", "hv_20"),
    ("hv_60", "hv_60"),
    ("sharpe_60", "sharpe_60"),
    ("sharpe_126", "sharpe_126"),
]


def _screener_snapshot_sync(
    daily_df: pd.DataFrame,
    today_date: date,
    now: datetime,
) -> None:
    """Build/refresh ticker_screener_snapshot from in-memory 252d daily data
    plus 2 supplementary queries (latest 1h/W/M intraday + stock_universe).

    Called from _ticker_scores_sync() right after the ticker_scores upsert.
    Snapshot is one row per symbol with all screener fields denormalized.
    TQL→SQL queries read this table via INNER JOIN with ticker_scores.
    """
    update_job_status_sync(
        "job.ticker_scores", "running", progress=95,
        message="Building screener snapshot...",
    )

    # 1. Reduce 252d window to the latest row per symbol
    daily_df_sorted = daily_df.sort_values(["symbol", "date"], ascending=[True, False])
    latest_per_sym = daily_df_sorted.groupby("symbol", as_index=False).first()

    # 2. Compute 52w high/low from the same 252d window (per symbol)
    def _agg_52w(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "high_52w": g["high"].max(),
            "low_52w": g["low"].min(),
        })

    # SQLite + SQLAlchemy return date columns as ISO strings via raw execute();
    # convert to Python date objects so the snapshot upsert doesn't fail with
    # "SQLite Date type only accepts Python date objects as input".
    if len(latest_per_sym) > 0 and not isinstance(latest_per_sym["date"].iloc[0], date):
        latest_per_sym["date"] = pd.to_datetime(latest_per_sym["date"]).dt.date
    w52 = (
        daily_df_sorted.groupby("symbol", as_index=False)
        .apply(_agg_52w, include_groups=False)
        .reset_index(drop=True)
    )
    latest_per_sym = latest_per_sym.merge(w52, on="symbol", how="left")
    last_close = latest_per_sym["close"].astype(float)
    latest_per_sym["pct_from_52w_high"] = (
        (last_close - latest_per_sym["high_52w"]) / latest_per_sym["high_52w"] * 100
    )
    latest_per_sym["pct_from_52w_low"] = (
        (last_close - latest_per_sym["low_52w"]) / latest_per_sym["low_52w"] * 100
    )
    latest_per_sym["pct_from_52w_high"] = latest_per_sym["pct_from_52w_high"].round(2)
    latest_per_sym["pct_from_52w_low"] = latest_per_sym["pct_from_52w_low"].round(2)

    # 3. Latest 1h/W/M from ticker_intraday — one query per interval
    symbols = latest_per_sym["symbol"].tolist()
    intraday_latest: dict[tuple[str, str], dict] = {}
    # Map source column name → ORM attribute for SELECT
    intraday_attr_map = {
        "close": TickerIntraday.close,
        "rsi_14": TickerIntraday.rsi_14,
        "macd": TickerIntraday.macd,
        "macd_signal": TickerIntraday.macd_signal,
        "macd_histogram": TickerIntraday.macd_histogram,
        "bb_middle": TickerIntraday.bb_middle,
        "bb_upper": TickerIntraday.bb_upper,
        "bb_lower": TickerIntraday.bb_lower,
        "bb_width": TickerIntraday.bb_width,
        "bb_squeeze": TickerIntraday.bb_squeeze,
        "atr_14": TickerIntraday.atr_14,
        "atr_percent": TickerIntraday.atr_percent,
        "vwma_20": TickerIntraday.vwma_20,
        "hv_20": TickerIntraday.hv_20,
        "hv_60": TickerIntraday.hv_60,
        "sharpe_60": TickerIntraday.sharpe_60,
        "sharpe_126": TickerIntraday.sharpe_126,
    }
    intraday_value_cols = [c[1] for c in _INTRADAY_COLS]
    with _SyncSessionLocal() as db:
        for iv in ("1h", "W", "M"):
            stmt = (
                select(TickerIntraday.symbol, *[intraday_attr_map[c] for c in intraday_value_cols])
                .where(TickerIntraday.symbol.in_(symbols))
                .where(TickerIntraday.interval == iv)
                .order_by(TickerIntraday.symbol, TickerIntraday.timestamp.desc())
            )
            # Reduce to latest per symbol (rows already sorted desc)
            seen: set[str] = set()
            for row in db.execute(stmt).all():
                sym = row[0]
                if sym in seen:
                    continue
                seen.add(sym)
                rec = dict(zip(intraday_value_cols, row[1:]))
                intraday_latest[(sym, iv)] = rec

    # 4. Sector/industry/PE/market_cap/fair_value from stock_universe
    universe_meta: dict[str, dict] = {}
    with _SyncSessionLocal() as db:
        stmt = select(
            StockUniverse.symbol,
            StockUniverse.symbol_pe,
            StockUniverse.industry,
            StockUniverse.fair_value,
            StockUniverse.high_52w,
            StockUniverse.low_52w,
        ).where(StockUniverse.symbol.in_(symbols))
        for sym, pe, industry, fv, h52, l52 in db.execute(stmt).all():
            # industry field stores the description (e.g. "Banks", "IT - Software");
            # treat it as the sector for TQL Sector filtering (legacy behavior).
            universe_meta[sym] = {
                "pe": pe,
                "sector": industry,  # TQL "Sector" maps to industry description
                "industry": industry,
                "fair_value": fv,
            }

    # 5. Assemble snapshot rows
    snapshot_rows: list[dict] = []
    for _, r in latest_per_sym.iterrows():
        sym = r["symbol"]
        meta = universe_meta.get(sym, {})

        row: dict = {
            "symbol": sym,
            "last_date": r["date"],
            "compute_date": today_date,
            "computed_at": now,
            "last_close": float(r["close"]),
            "last_volume": int(r["volume"]),
            "last_open": float(r["open"]),
            "last_high": float(r["high"]),
            "last_low": float(r["low"]),
            # 1d indicators (sourced from TickerDaily)
            "rsi_1d": r["rsi_14"],
            "macd_1d": r["macd"],
            "macd_signal_1d": r["macd_signal"],
            "macd_histogram_1d": r["macd_histogram"],
            "bb_middle_1d": r["bb_middle"],
            "bb_upper_1d": r["bb_upper"],
            "bb_lower_1d": r["bb_lower"],
            "bb_width_1d": r["bb_width"],
            "bb_squeeze_1d": r["bb_squeeze"],
            "atr_1d": r["atr_14"],
            "atr_percent_1d": r["atr_percent"],
            "vwma_20_1d": r["vwma_20"],
            "hv_20": r["hv_20"],
            "hv_60": r["hv_60"],
            "sharpe_60": r["sharpe_60"],
            "sharpe_126": r["sharpe_126"],
            "high_52w": r["high_52w"],
            "low_52w": r["low_52w"],
            "pct_from_52w_high": r["pct_from_52w_high"],
            "pct_from_52w_low": r["pct_from_52w_low"],
            "sector": meta.get("sector"),
            "industry": meta.get("industry"),
            "pe": meta.get("pe"),
            "market_cap": None,  # Not in stock_universe; reserved for future
            "fair_value": meta.get("fair_value"),
        }

        # Add 1h/W/M intraday columns
        for iv in ("1h", "W", "M"):
            iv_row = intraday_latest.get((sym, iv), {})
            for snap_col, src_col in _INTRADAY_COLS:
                row[f"{snap_col}_{iv}"] = iv_row.get(src_col)

        snapshot_rows.append(row)

    # 6. Bulk upsert (ON CONFLICT(symbol) DO UPDATE)
    set_dict = {col: sqlite_insert(TickerScreenerSnapshot).excluded[col] for col in [
        "last_date", "compute_date", "computed_at",
        "last_close", "last_volume", "last_open", "last_high", "last_low",
        "rsi_1d", "macd_1d", "macd_signal_1d", "macd_histogram_1d",
        "bb_middle_1d", "bb_upper_1d", "bb_lower_1d", "bb_width_1d",
        "bb_squeeze_1d", "atr_1d", "atr_percent_1d", "vwma_20_1d",
        "hv_20", "hv_60", "sharpe_60", "sharpe_126",
        "high_52w", "low_52w", "pct_from_52w_high", "pct_from_52w_low",
        "sector", "industry", "pe", "market_cap", "fair_value",
        "intraday_close_1h", "rsi_1h", "macd_1h", "macd_signal_1h",
        "macd_histogram_1h", "bb_middle_1h", "bb_upper_1h", "bb_lower_1h",
        "bb_width_1h", "bb_squeeze_1h", "atr_1h", "atr_percent_1h",
        "vwma_20_1h", "hv_20_1h", "hv_60_1h", "sharpe_60_1h", "sharpe_126_1h",
        "intraday_close_W", "rsi_W", "macd_W", "macd_signal_W",
        "macd_histogram_W", "bb_middle_W", "bb_upper_W", "bb_lower_W",
        "bb_width_W", "bb_squeeze_W", "atr_W", "atr_percent_W",
        "vwma_20_W", "hv_20_W", "hv_60_W", "sharpe_60_W", "sharpe_126_W",
        "intraday_close_M", "rsi_M", "macd_M", "macd_signal_M",
        "macd_histogram_M", "bb_middle_M", "bb_upper_M", "bb_lower_M",
        "bb_width_M", "bb_squeeze_M", "atr_M", "atr_percent_M",
        "vwma_20_M", "hv_20_M", "hv_60_M", "sharpe_60_M", "sharpe_126_M",
    ]}
    with _SyncSessionLocal() as db:
        ins = sqlite_insert(TickerScreenerSnapshot).values(snapshot_rows)
        ins = ins.on_conflict_do_update(
            index_elements=["symbol"],
            set_=set_dict,
        )
        db.execute(ins)
        db.commit()
    logger.info(
        "screener_snapshot_sync: wrote %d rows to ticker_screener_snapshot",
        len(snapshot_rows),
    )


def ticker_scores_worker() -> None:
    """Daemon thread: computes ticker scores at startup then on cron 0 0 * * * (midnight).

    Also triggered mid-day by _ticker_daily_update_sync() after bhavcopy lands.
    """
    logger.info("ticker_scores_worker: started")

    if not _is_job_enabled("job.ticker_scores"):
        logger.info("ticker_scores_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_scores", "idle", progress=0, message="Stopped")
        logger.info("ticker_scores_worker: stopped")
        return

    # Startup sequencing is owned by the orchestrator pipeline. The worker waits
    # for the upstream stage gate, then yields to the orchestrator instead of
    # running its own first-run computation.
    if _is_first_run("ticker_scores"):
        # Wait for indicators to be computed before scoring
        if _wait_for_startup_event(_startup_ticker_indicators_done, "ticker_indicators", "job.ticker_scores"):
            update_job_status_sync("job.ticker_scores", "idle", progress=0, message="Stopped")
            logger.info("ticker_scores_worker: stopped")
            return
        logger.info("ticker_scores_worker: orchestrator owns startup score computation, skipping worker first-run execution")
        _set_first_run_complete("ticker_scores")
    else:
        logger.info("ticker_scores_worker: first_run=False, skipping startup computation")
    update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Waiting for orchestrator / cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_scores", "0 0 * * *")
        logger.info("ticker_scores_worker: sleeping %.0fs until next cron (0 0 * * *)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_scores"):
                update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            # Acquire pipeline lock so scan/notif workers wait during score recomputation
            with _pipeline_lock:
                _pipeline_idle.clear()
                try:
                    update_job_status_sync("job.ticker_scores", "running", progress=0, message="Computing ticker scores...")
                    _ticker_scores_sync()
                finally:
                    _pipeline_idle.set()

    update_job_status_sync("job.ticker_scores", "idle", progress=0, message="Stopped")
    logger.info("ticker_scores_worker: stopped")

def ticker_indicators_worker() -> None:
    """Daemon thread target for computing technical indicators (cron: 0 11 * * 1-5)."""
    logger.info("ticker_indicators_worker: started")

    if not _is_job_enabled("job.ticker_indicators"):
        logger.info("ticker_indicators_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_indicators", "idle", progress=0, message="Stopped")
        logger.info("ticker_indicators_worker: stopped")
        return

    # Startup sequencing is owned by the orchestrator pipeline. The worker waits
    # for the upstream stage gate, then yields to the orchestrator instead of
    # running its own first-run computation.
    if _is_first_run("ticker_indicators"):
        # Wait for candle backfill to complete before computing indicators
        if _wait_for_startup_event(_startup_ticker_backfill_done, "ticker_backfill", "job.ticker_indicators"):
            update_job_status_sync("job.ticker_indicators", "idle", progress=0, message="Stopped")
            logger.info("ticker_indicators_worker: stopped")
            return
        logger.info("ticker_indicators_worker: orchestrator owns startup indicator computation, skipping worker first-run execution")
        _set_first_run_complete("ticker_indicators")
    else:
        logger.info("ticker_indicators_worker: first_run=False, skipping startup computation")
    update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Waiting for orchestrator / cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_indicators", "0 11 * * 1-5")
        logger.info("ticker_indicators_worker: sleeping %.0fs until next cron (0 11 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_indicators"):
                update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            # Acquire pipeline lock so scan/notif workers wait during recomputation
            with _pipeline_lock:
                _pipeline_idle.clear()
                try:
                    update_job_status_sync("job.ticker_indicators", "running", progress=0, message="Computing indicators...")
                    _ticker_indicators_sync()
                finally:
                    _pipeline_idle.set()

    update_job_status_sync("job.ticker_indicators", "idle", progress=0, message="Stopped")
    logger.info("ticker_indicators_worker: stopped")


def ticker_intraday_hourly_indicators_worker() -> None:
    """Daemon thread target for computing hourly (1h) intraday technical indicators.

    Cron: at :30 past each trading hour 09:30–15:30 IST on weekdays.
    """
    logger.info("ticker_intraday_hourly_indicators_worker: started")

    if not _is_job_enabled("job.ticker_intraday_hourly_indicators"):
        logger.info("ticker_intraday_hourly_indicators_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "idle", progress=0, message="Stopped")
        logger.info("ticker_intraday_hourly_indicators_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("ticker_intraday_hourly_indicators"):
        # Wait for hourly backfill to complete before computing indicators
        if _wait_for_startup_event(_startup_ticker_hourly_done, "ticker_intraday_hourly_update", "job.ticker_intraday_hourly_indicators"):
            update_job_status_sync("job.ticker_intraday_hourly_indicators", "idle", progress=0, message="Stopped")
            logger.info("ticker_intraday_hourly_indicators_worker: stopped")
            return
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "running", progress=0, message="Starting initial computation...")
        _ticker_intraday_indicators_sync(["1h"])
        _set_first_run_complete("ticker_intraday_hourly_indicators")
    else:
        logger.info("ticker_intraday_hourly_indicators_worker: first_run=False, skipping startup computation")
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_intraday_hourly_indicators", "30 9,10,11,12,13,14,15 * * 1-5")
        logger.info("ticker_intraday_hourly_indicators_worker: sleeping %.0fs until next cron (30 9,10,11,12,13,14,15 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_intraday_hourly_indicators"):
                update_job_status_sync("job.ticker_intraday_hourly_indicators", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_intraday_hourly_indicators", "running", progress=0, message="Computing hourly indicators...")
            _ticker_intraday_indicators_sync(["1h"])

    update_job_status_sync("job.ticker_intraday_hourly_indicators", "idle", progress=0, message="Stopped")
    logger.info("ticker_intraday_hourly_indicators_worker: stopped")


NEWS_CRON = "*/5 * * * *"
NEWS_CRAWL_MAX_INTERVAL = 30 * 60


async def _crawl_news_async(pages: int) -> int:
    """Async helper: crawl and store news using AsyncSession.

    Uses AsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread. NullPool is already
    thread-safe; each ``engine.connect()`` opens a fresh DBAPI connection
    bound to the loop that opened it.
    """
    async with AsyncSessionLocal() as session:
        return await news_fetcher.crawl_and_store(pages=pages, db=session)


def _news_sync() -> None:
    """Crawl and persist global news. Runs synchronously in a worker thread."""
    try:
        logger.info("news_sync: starting")
        update_job_status_sync("job.news", "running", progress=10, message="Starting news crawl...")
        stored = _run_async(_crawl_news_async(pages=6))
        if stored > 0:
            logger.info("news_sync: initial crawl stored %d articles", stored)
        update_job_status_sync("job.news", "waiting", progress=100, message="Waiting for next cycle")
        logger.info("news_sync: complete")
    except Exception:
        logger.exception("news_sync: unhandled exception; will retry next cycle")
        update_job_status_sync("job.news", "failed", message="Error occurred")


def _news_periodic_sync(backoff_secs: float) -> float:
    """Single periodic news crawl (page 1 only).

    Returns the next sleep duration: resets to cron interval on success,
    doubles (up to NEWS_CRAWL_MAX_INTERVAL) on empty result.
    """
    base = _seconds_until_next_cron(NEWS_CRON)
    try:
        update_job_status_sync("job.news", "running", progress=50, message="Crawling news...")
        stored = _run_async(_crawl_news_async(pages=1))
        if stored == 0:
            new_interval = min(backoff_secs * 2, NEWS_CRAWL_MAX_INTERVAL)
            logger.warning("news_sync: crawl returned 0 articles — backing off to %.0f s", new_interval)
            update_job_status_sync("job.news", "waiting", progress=0, message=f"Backing off {new_interval:.0f}s")
            return new_interval
        else:
            if backoff_secs > base:
                logger.info("news_sync: crawl succeeded (%d articles) — resetting to cron schedule", stored)
            update_job_status_sync("job.news", "waiting", progress=100, message="Waiting for next cycle")
            return base
    except Exception:
        logger.exception("news_sync: periodic crawl exception — keeping interval")
        update_job_status_sync("job.news", "failed", message="Error in periodic crawl")
        return backoff_secs


def news_worker() -> None:
    """Daemon thread target for news crawling (cron: */5 * * * * with backoff)."""
    logger.info("news_worker: started")

    if not _is_job_enabled("job.news"):
        logger.info("news_worker: disabled, waiting...")
        update_job_status_sync("job.news", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.news", "idle", progress=0, message="Stopped")
        logger.info("news_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("news"):
        # Wait for stock universe before crawling news (universe provides symbol context)
        if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.news"):
            update_job_status_sync("job.news", "idle", progress=0, message="Stopped")
            logger.info("news_worker: stopped")
            return
        update_job_status_sync("job.news", "running", progress=10, message="Starting initial news crawl...")
        _news_sync()
        _set_first_run_complete("news")
    else:
        logger.info("news_worker: first_run=False, skipping startup crawl")
        update_job_status_sync("job.news", "waiting", progress=0, message="Waiting for cron schedule")

    current_interval = _seconds_until_next_cron(NEWS_CRON)
    while not _shutdown_event.is_set():
        is_backoff = current_interval > _seconds_until_next_cron(NEWS_CRON)
        logger.info("news_worker: next run in %.0f s (backoff: %s)", current_interval, is_backoff)
        if is_backoff:
            next_trig = datetime.now(timezone.utc) + timedelta(seconds=current_interval)
            update_job_status_sync("job.news", "waiting", progress=0,
                                   message=f"Next run in {current_interval:.0f}s (backoff)",
                                   next_trigger=next_trig)
        else:
            _report_job_waiting("job.news", NEWS_CRON)
        if _sleep_interruptible(current_interval):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.news"):
                update_job_status_sync("job.news", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            current_interval = _news_periodic_sync(current_interval)

    update_job_status_sync("job.news", "idle", progress=0, message="Stopped")
    try:
        _run_async(news_fetcher.close())
    except Exception:
        logger.debug("news_worker: close() raised, ignoring (client may already be closed)")
    logger.info("news_worker: stopped")


# RSS News Worker - Multi-source RSS aggregation
NEWS_RSS_CRON = "*/5 * * * *"  # Every 5 minutes


def _news_rss_sync() -> None:
    """Fetch and store articles from all RSS sources."""
    logger.info("news_rss_sync: starting RSS aggregation")
    try:
        from app.services.news_aggregator import _parsed_article_to_db_dict

        all_articles, results = _run_async(
            fetch_all_feeds(
                sources=HIGH_PRIORITY_SOURCES,
                concurrency=5,
                timeout=15.0,
            )
        )

        success_count = sum(1 for r in results if not r.error)
        error_count = sum(1 for r in results if r.error)
        logger.info(
            "news_rss_sync: fetched %d articles from %d sources (%d errors)",
            len(all_articles), success_count, error_count
        )

        # Convert ParsedArticle objects to DB dicts with NLP fields
        processed = []
        for article in all_articles:
            try:
                processed.append(_parsed_article_to_db_dict(article))
            except Exception as e:
                logger.debug("Failed to process article %s: %s", article.url, e)

        if processed:
            with _SyncSessionLocal() as session:
                stored = 0
                for article_dict in processed:
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(NewsArticle).values(article_dict)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
                    session.execute(stmt)
                    stored += 1
                session.commit()
                logger.info("news_rss_sync: stored %d articles", stored)

                # Broadcast new articles via WebSocket (sync path — dead code, async path is active)
                for article_dict in processed[:10]:
                    try:
                        _run_async(broadcast_news_update(article_dict))
                    except Exception as e:
                        logger.debug("Failed to broadcast article: %s", e)

        for r in results:
            if r.error:
                logger.debug("news_rss_sync: %s failed: %s", r.source.id, r.error)

    except Exception as e:
        logger.exception("news_rss_sync: failed with exception: %s", e)


async def _news_rss_sync_async() -> None:
    """Async version of news RSS sync for use in worker threads."""
    from app.services.news_aggregator import fetch_and_process_all, store_articles

    try:
        processed, results = await fetch_and_process_all(
            sources=HIGH_PRIORITY_SOURCES,
            concurrency=5,
            timeout=15.0,
        )

        success_count = sum(1 for r in results if not r.error)
        error_count = sum(1 for r in results if r.error)
        logger.info(
            "news_rss_sync: fetched %d articles from %d sources (%d errors)",
            len(processed), success_count, error_count
        )

        if processed:
            async with AsyncSessionLocal() as session:
                stored = await store_articles(session, processed)
                logger.info("news_rss_sync_async: stored %d articles", stored)

                # Broadcast new articles via WebSocket
                for article_dict in processed[:10]:  # Broadcast newest 10
                    try:
                        await broadcast_news_update(article_dict)
                    except Exception as e:
                        logger.debug("Failed to broadcast article: %s", e)

    except Exception as e:
        logger.exception("news_rss_sync_async: failed with exception: %s", e)


def news_rss_worker() -> None:
    """Daemon thread target for RSS news aggregation (cron: */5 * * * *)."""
    logger.info("news_rss_worker: started")

    if not _is_job_enabled("job.news_rss"):
        logger.info("news_rss_worker: disabled, waiting...")
        update_job_status_sync("job.news_rss", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.news_rss", "idle", progress=0, message="Stopped")
        logger.info("news_rss_worker: stopped")
        return

    # Run immediately on startup
    logger.info("news_rss_worker: running initial sync")
    update_job_status_sync("job.news_rss", "running", progress=10, message="Initial RSS sync...")
    _run_async(_news_rss_sync_async())

    # Then run on cron schedule
    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.news_rss", NEWS_RSS_CRON)
        logger.info("news_rss_worker: next run in %.0f s", wait_secs)
        if _sleep_interruptible(wait_secs):
            break

        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.news_rss"):
                update_job_status_sync("job.news_rss", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue

            update_job_status_sync("job.news_rss", "running", progress=50, message="Fetching RSS feeds...")
            _run_async(_news_rss_sync_async())
            update_job_status_sync("job.news_rss", "completed", progress=100, message="Sync complete")

    update_job_status_sync("job.news_rss", "idle", progress=0, message="Stopped")
    logger.info("news_rss_worker: stopped")


# ---------------------------------------------------------------------------
# Phase C: weekly SQLite VACUUM worker
# ---------------------------------------------------------------------------
# SQLite stores data in pages; DELETE leaves free pages in the file until
# VACUUM rebuilds the file.  News/intraday retention deletes thousands of
# rows each week; running VACUUM once a week (Sunday 04:00) reclaims space
# without adding meaningful write overhead.  This is a single-threaded
# rebuild — takes 5-15 min on a 1-2GB DB.

VACUUM_CRON = "0 4 * * 0"   # Every Sunday 04:00 (low-traffic window)


def _run_vacuum() -> None:
    """Run VACUUM on the SQLite warehouse to reclaim space from deleted rows.

    Uses a dedicated short-lived connection because VACUUM cannot run inside
    an open transaction.  Disables WAL briefly to allow the rebuild.
    """
    db_path = settings.db_path
    logger.info("vacuum: starting VACUUM on %s", db_path)
    update_job_status_sync("job.vacuum", "running", progress=10, message="Starting VACUUM...")
    t0 = time.time()
    try:
        # VACUUM cannot be executed inside a transaction.  Use a fresh
        # connection with isolation_level=None (autocommit) so each
        # statement is its own transaction.
        with sqlite3.connect(db_path, timeout=600, isolation_level=None) as con:
            # 1. checkpoint WAL to fold pending writes into the main DB
            update_job_status_sync("job.vacuum", "running", progress=20,
                                   message="Checkpointing WAL...")
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError as e:
                logger.warning("vacuum: wal_checkpoint failed (continuing): %s", e)

            # 2. rebuild the database file in place
            update_job_status_sync("job.vacuum", "running", progress=50,
                                   message="VACUUM in progress (may take 5-15 min)...")
            con.execute("VACUUM")

            # 3. update query planner stats
            update_job_status_sync("job.vacuum", "running", progress=90,
                                   message="Running ANALYZE...")
            con.execute("ANALYZE")

        elapsed = time.time() - t0
        logger.info("vacuum: complete in %.1fs", elapsed)
        update_job_status_sync("job.vacuum", "waiting", progress=100,
                               message=f"Complete in {elapsed:.0f}s")
    except Exception:
        logger.exception("vacuum: failed")
        update_job_status_sync("job.vacuum", "waiting", progress=0,
                               message="Failed (will retry next week)")


def vacuum_worker() -> None:
    """Daemon thread: runs VACUUM weekly on Sunday 04:00.

    Skips if disabled via system_config.  On first launch (first_run=True)
    waits for ticker_scores to complete before triggering (we don't want to
    race with the nightly pipeline).  Subsequent cycles use the cron schedule.
    """
    logger.info("vacuum_worker: started")

    if not _is_job_enabled("job.vacuum"):
        logger.info("vacuum_worker: disabled, waiting...")
        update_job_status_sync("job.vacuum", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
        logger.info("vacuum_worker: stopped")
        return

    # Wait for ticker_scores to finish its first run so we don't fight for the
    # DB lock during startup.  This is a soft check — if the worker hasn't
    # started, just proceed.
    if _is_first_run("vacuum") and _wait_for_startup_event(
        _startup_ticker_scores_done, "ticker_scores", "job.vacuum"
    ):
        update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
        return
    if _is_first_run("vacuum"):
        _set_first_run_complete("vacuum")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.vacuum", VACUUM_CRON,
                                        message="Weekly maintenance")
        logger.info("vacuum_worker: sleeping %.0fs until next cron (%s)",
                    wait_secs, VACUUM_CRON)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.vacuum"):
                update_job_status_sync("job.vacuum", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            _run_vacuum()

    update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
    logger.info("vacuum_worker: stopped")


WATCHLIST_NEWS_STALE_SECONDS = 5 * 60


async def _fetch_company_news_async(symbol: str) -> int:
    """Async helper: fetch company news using AsyncSession.

    Uses AsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread. NullPool is already
    thread-safe; each ``engine.connect()`` opens a fresh DBAPI connection
    bound to the loop that opened it.

    Note: We can't easily cancel HTTP requests mid-flight, but we can at least
    check for shutdown between symbols in the caller.
    """
    try:
        async with AsyncSessionLocal() as session:
            return await news_fetcher.fetch_company_news(symbol=symbol, db=session)
    finally:
        await news_fetcher.close()


def _watchlist_news_sync() -> None:
    """Fetch and persist news for each symbol in the watchlist."""
    try:
        logger.info("watchlist_news_sync: starting")
        with _SyncSessionLocal() as session:
            result = session.execute(select(WatchlistItem.symbol))
            symbols = [row[0] for row in result]

        if not symbols:
            logger.debug("watchlist_news_sync: watchlist is empty, skipping")
            return

        total = len(symbols)
        logger.info("watchlist_news_sync: refreshing news for %d symbols: %s", total, symbols)

        for idx, symbol in enumerate(symbols, 1):
            if _shutdown_event.is_set():
                logger.info("watchlist_news_sync: shutdown requested, aborting")
                return

            update_job_status_sync(
                "job.watchlist_news", "running",
                progress=int((idx / total) * 100),
                message=f"Fetching news: {symbol} ({idx}/{total})",
            )

            with _SyncSessionLocal() as session:
                stale_check = session.execute(
                    select(func.max(NewsArticle.fetched_at)).where(
                        NewsArticle.company_symbol == symbol.upper()
                    )
                )
                latest = stale_check.scalar_one_or_none()

            if latest is not None:
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - latest).total_seconds()
                if age < WATCHLIST_NEWS_STALE_SECONDS:
                    logger.debug("watchlist_news_sync: %s is fresh (age=%.0fs), skipping", symbol, age)
                    continue

            try:
                count = _run_async(_fetch_company_news_async(symbol))
                logger.info("watchlist_news_sync: %s — %d articles stored/tagged", symbol, count)
            except Exception:
                logger.exception("watchlist_news_sync: failed for %s", symbol)

            if _sleep_interruptible(2.0):
                return

        logger.info("watchlist_news_sync: complete")
    except Exception:
        logger.exception("watchlist_news_sync: unhandled exception; will retry next cycle")


def watchlist_news_worker() -> None:
    """Daemon thread target for watchlist news fetching (cron: */5 * * * *)."""
    logger.info("watchlist_news_worker: started")

    if not _is_job_enabled("job.watchlist_news"):
        logger.info("watchlist_news_worker: disabled, waiting...")
        update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.watchlist_news", "idle", progress=0, message="Stopped")
        logger.info("watchlist_news_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("watchlist_news"):
        # Wait for stock universe to be populated before fetching per-symbol news
        if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.watchlist_news"):
            update_job_status_sync("job.watchlist_news", "idle", progress=0, message="Stopped")
            logger.info("watchlist_news_worker: stopped")
            return
        update_job_status_sync("job.watchlist_news", "running", progress=0, message="Starting initial fetch...")
        _watchlist_news_sync()
        _set_first_run_complete("watchlist_news")
    else:
        logger.info("watchlist_news_worker: first_run=False, skipping startup fetch")
        update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.watchlist_news", "*/5 * * * *")
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.watchlist_news"):
                update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.watchlist_news", "running", progress=50, message="Fetching watchlist news...")
            _watchlist_news_sync()

    update_job_status_sync("job.watchlist_news", "idle", progress=0, message="Stopped")
    logger.info("watchlist_news_worker: stopped")


def _is_market_open() -> bool:
    """Check if the market is currently open (Mon-Fri, 09:15-15:30 IST)."""
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(ZoneInfo("Asia/Kolkata"))

    if now_ist.weekday() >= 5:
        return False

    market_start = now_ist.replace(
        hour=settings.market_start_hour,
        minute=settings.market_start_minute,
        second=0,
        microsecond=0,
    )
    market_end = now_ist.replace(
        hour=settings.market_end_hour,
        minute=settings.market_end_minute,
        second=0,
        microsecond=0,
    )

    return market_start <= now_ist <= market_end


def _seconds_until_market_open() -> float:
    """Calculate seconds until the next market open time (09:15 IST)."""
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(ZoneInfo("Asia/Kolkata"))

    if now_ist.weekday() == 5:
        days_until_monday = 2
    elif now_ist.weekday() == 6:
        days_until_monday = 1
    else:
        market_start = now_ist.replace(
            hour=settings.market_start_hour,
            minute=settings.market_start_minute,
            second=0,
            microsecond=0,
        )

        if now_ist < market_start:
            return (market_start - now_ist).total_seconds()
        else:
            days_until_monday = 1
            if now_ist.weekday() == 4:
                days_until_monday = 3

    next_open = now_ist + timedelta(days=days_until_monday)
    next_open = next_open.replace(
        hour=settings.market_start_hour,
        minute=settings.market_start_minute,
        second=0,
        microsecond=0,
    )

    return (next_open - now_ist).total_seconds()


async def _refresh_market_data_async() -> None:
    """Async helper: refresh all market data using AsyncSession.

    Uses AsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread. NullPool is already
    thread-safe; each ``engine.connect()`` opens a fresh DBAPI connection
    bound to the loop that opened it.
    """
    async with AsyncSessionLocal() as session:
        await market_data_fetcher.refresh_all(session)


def _market_data_sync() -> None:
    """Fetch and store all industry and sector data from MoneyControl."""
    try:
        logger.info("market_data_sync: starting")
        _run_async(_refresh_market_data_async())
        logger.info("market_data_sync: complete")
    except Exception:
        logger.exception("market_data_sync: unhandled exception; will retry next cycle")


def market_data_worker() -> None:
    """Daemon thread target for market data fetching (cron: */5 * * * *, market-hours only)."""
    logger.info("market_data_worker: started")

    if not _is_job_enabled("job.market_data"):
        logger.info("market_data_worker: disabled, waiting...")
        update_job_status_sync("job.market_data", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.market_data", "idle", progress=0, message="Stopped")
        logger.info("market_data_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("market_data"):
        # Wait for stock universe before fetching market data
        if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.market_data"):
            update_job_status_sync("job.market_data", "idle", progress=0, message="Stopped")
            logger.info("market_data_worker: stopped")
            return
        update_job_status_sync("job.market_data", "running", progress=0, message="Starting initial sync...")
        _market_data_sync()
        _set_first_run_complete("market_data")
    else:
        logger.info("market_data_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.market_data", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        if _is_market_open():
            wait = _report_job_waiting("job.market_data", "*/5 * * * *", f"Market open, next run soon")
            logger.info("market_data_worker: market is open, next run in %.0f s", wait)
            if _sleep_interruptible(wait):
                break
            if not _shutdown_event.is_set() and _is_market_open():
                if not _is_job_enabled("job.market_data"):
                    update_job_status_sync("job.market_data", "waiting", progress=0, message="Disabled")
                    _sleep_interruptible(60)
                    continue
                update_job_status_sync("job.market_data", "running", progress=50, message="Fetching market data...")
                _market_data_sync()
        else:
            wait = _seconds_until_market_open()
            logger.info("market_data_worker: market is closed, next run in %.0f s (%.1f hours)", wait, wait / 3600)
            update_job_status_sync("job.market_data", "waiting", progress=0, message=f"Market closed, opens in {wait/3600:.1f}h")
            if _sleep_interruptible(wait):
                break

    update_job_status_sync("job.market_data", "idle", progress=0, message="Stopped")
    try:
        _run_async(market_data_fetcher.close())
    except Exception:
        logger.debug("market_data_worker: close() raised, ignoring (client may already be closed)")
    logger.info("market_data_worker: stopped")


# ---------------------------------------------------------------------------
# Results calendar worker — upcoming board meeting alerts for watchlist stocks
# ---------------------------------------------------------------------------

_RESULTS_CALENDAR_CRON = "0 8,14 * * 1-5"  # 8am + 2pm IST on trading days


def _results_calendar_sync() -> None:
    """Fetch NSE event calendar and create 'results_upcoming' notifications.

    For each board meeting event that mentions "Financial Results" in its
    purpose and whose symbol is in any watchlist, upserts a Notification row
    with:
      - trigger_type = 'results_upcoming'
      - triggered_date = the board meeting date  (dedup key)
      - triggered_at   = now (time the alert was generated)

    The existing uq_notification_daily constraint (watchlist_id, symbol,
    trigger_type, triggered_date) ensures each alert fires only once per
    meeting date per watchlist — re-running the job produces no duplicates.
    """
    try:
        logger.info("results_calendar_sync: starting")
        update_job_status_sync(
            "job.results_calendar", "running", progress=10,
            message="Fetching event calendar from NSE...",
        )

        # Import here to avoid circular imports at module level
        from app.routers.announcements import get_event_calendar_cached

        try:
            events = get_event_calendar_cached()
        except Exception:
            logger.exception("results_calendar_sync: failed to fetch event calendar")
            update_job_status_sync(
                "job.results_calendar", "failed",
                message="Failed to fetch event calendar from NSE",
            )
            return

        # Filter to only entries that include "Financial Results" in purpose
        results_events = [
            e for e in events
            if "financial results" in e.purpose.lower()
        ]

        if not results_events:
            logger.info("results_calendar_sync: no upcoming financial results events found")
            update_job_status_sync(
                "job.results_calendar", "waiting", progress=100,
                message="No upcoming results events",
            )
            return

        logger.info(
            "results_calendar_sync: %d results events found, cross-referencing watchlists",
            len(results_events),
        )
        update_job_status_sync(
            "job.results_calendar", "running", progress=40,
            message=f"Cross-referencing {len(results_events)} events against watchlists...",
        )

        # Load all watchlist symbols grouped by watchlist_id
        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.info("results_calendar_sync: watchlist is empty, skipping")
            update_job_status_sync(
                "job.results_calendar", "waiting", progress=100,
                message="Watchlist empty",
            )
            return

        # Build reverse map: symbol → list of watchlist_ids
        watchlists_by_symbol: dict[str, list[int]] = {}
        for wl_id, symbols in symbols_by_watchlist.items():
            for sym in symbols:
                watchlists_by_symbol.setdefault(sym.upper(), []).append(wl_id)

        now = datetime.now()
        pending: list[dict] = []

        for event in results_events:
            sym = event.symbol.upper()
            if sym not in watchlists_by_symbol:
                continue

            # Parse the board meeting date string, e.g. "20-Apr-2026"
            try:
                meeting_date = datetime.strptime(event.date, "%d-%b-%Y").date()
            except ValueError:
                logger.warning(
                    "results_calendar_sync: unparseable date '%s' for %s, skipping",
                    event.date, sym,
                )
                continue

            # Truncate description to 200 chars for the notification message
            desc = event.description or event.purpose
            msg = f"Results on {event.date}: {desc[:180]}"
            if len(desc) > 180:
                msg += "…"

            for wl_id in watchlists_by_symbol[sym]:
                pending.append(
                    {
                        "watchlist_id": wl_id,
                        "symbol": sym,
                        "exchange": "NSE",
                        "trigger_type": "results_upcoming",
                        "message": msg[:256],
                        "triggered_at": now,
                        "triggered_date": meeting_date,
                        "is_read": False,
                    }
                )

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info(
                "results_calendar_sync: upserted %d notification rows (%d unique events)",
                len(pending),
                len({(r["symbol"], r["triggered_date"]) for r in pending}),
            )
        else:
            logger.info("results_calendar_sync: no watchlist symbols matched upcoming results events")

        update_job_status_sync(
            "job.results_calendar", "waiting", progress=100,
            message=f"Done — {len(pending)} notifications upserted",
        )

    except Exception:
        logger.exception("results_calendar_sync: unhandled exception; will retry next cycle")
        update_job_status_sync("job.results_calendar", "failed", message="Unhandled exception")


def results_calendar_worker() -> None:
    """Daemon thread: syncs upcoming results notifications twice daily (8am + 2pm IST)."""
    logger.info("results_calendar_worker: started")

    if not _is_job_enabled("job.results_calendar"):
        logger.info("results_calendar_worker: disabled, waiting...")
        update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.results_calendar", "idle", progress=0, message="Stopped")
        logger.info("results_calendar_worker: stopped")
        return

    # Wait for stock universe to be ready (replaces the old fixed 15s delay)
    if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.results_calendar"):
        update_job_status_sync("job.results_calendar", "idle", progress=0, message="Stopped")
        logger.info("results_calendar_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("results_calendar"):
        update_job_status_sync("job.results_calendar", "running", progress=0, message="Starting initial sync...")
        _results_calendar_sync()
        _set_first_run_complete("results_calendar")
    else:
        logger.info("results_calendar_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.results_calendar", _RESULTS_CALENDAR_CRON)
        logger.info(
            "results_calendar_worker: sleeping %.0f s until next cron (%s)",
            wait_secs, _RESULTS_CALENDAR_CRON,
        )
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.results_calendar"):
                update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            _results_calendar_sync()

    update_job_status_sync("job.results_calendar", "idle", progress=0, message="Stopped")
    logger.info("results_calendar_worker: stopped")


async def start_all_workers() -> list[threading.Thread]:
    """Register jobs and spawn all background worker threads.

    Startup ordering is strictly enforced via threading.Event gates:

      1. stock_universe_worker               — runs first; sets _startup_stock_universe_done
                                                 All other workers wait on this before their first-run.
      2. ticker_backfill_worker              — waits stock_universe_done; sets _startup_ticker_backfill_done
      3. ticker_indicators_worker            — waits ticker_backfill_done; sets _startup_ticker_indicators_done
      4. ticker_scores_worker                — waits ticker_indicators_done; sets _startup_ticker_scores_done
      5. ticker_daily_update_worker          — waits ticker_backfill_done (runs its own inline pipeline)
      6. ticker_intraday_hourly_update_worker    — runs independently; sets _startup_ticker_hourly_done
      6b. ticker_intraday_hourly_indicators_worker — waits _startup_ticker_hourly_done
      7. global_scan_worker                  — waits ticker_scores_done; polls _pipeline_idle on every cycle
      8. watchlist_notification_worker       — waits ticker_scores_done; polls _pipeline_idle on every cycle
      9. news_worker                         — waits stock_universe_done; then runs independently
      10. watchlist_news_worker              — waits stock_universe_done; then runs independently
      11. market_data_worker                 — waits stock_universe_done; then runs independently
      12. results_calendar_worker            — waits stock_universe_done; then runs independently
      13. vacuum_worker                      — waits ticker_scores_done; weekly Sunday 04:00 cron

    Cron-cycle ordering is enforced via _pipeline_lock + _pipeline_idle:
      ticker_daily_update / ticker_indicators / ticker_scores each acquire
      _pipeline_lock and clear _pipeline_idle while running. global_scan and
      watchlist_notification call _wait_for_pipeline() before each cycle, so
      they will not start a new cycle while a pipeline run is known to be in
      progress. Note: there is an inherent narrow race where a consumer passes
      the idle check and a producer then starts — this is accepted because scan
      workers are DB-read-only and the window is sub-millisecond.

    Weekly/Monthly (W/M) candle sync + indicators are NOT run by standalone
    workers — they are Stage 5 of the nightly orchestrator pipeline (see
    orchestrator.py) so that W/M data is fresh before the nightly scan.
    """
    reset_async_shutdown_event()
    register_all_jobs()
    await sync_all_jobs_to_db()

    targets = [
        ticker_backfill_worker,                      # 1 — candle history first
        stock_universe_worker,                       # 2 — symbol metadata
        ticker_indicators_worker,                    # 3 — indicator backfill
        ticker_scores_worker,                          # 4 — momentum scores
        ticker_daily_update_worker,                  # 5 — daily bhavcopy + refresh
        ticker_intraday_hourly_update_worker,       # 6 — 1h candles during market hours
        ticker_intraday_hourly_indicators_worker,   # 6b — 1h indicators during market hours
        market_data_worker,                          # 7 — live market data
        global_scan_worker,                          # 8 — full-universe scan
        watchlist_notification_worker,               # 9 — watchlist alerts
        news_worker,                                 # 10 — global news (MoneyControl)
        news_rss_worker,                             # 11 — RSS news aggregation
        watchlist_news_worker,                       # 12 — per-symbol news
        results_calendar_worker,                     # 13 — upcoming results alerts
        vacuum_worker,                               # 14 — weekly VACUUM (Sunday 04:00)
    ]
    for target in targets:
        t = threading.Thread(target=target, daemon=True, name=target.__name__)
        t.start()
        _worker_threads.append(t)
        logger.info("start_all_workers: spawned %s", t.name)
        # Stagger launches so all workers don't simultaneously hammer the DB
        # at startup. 500 ms per worker = 4.5 s spread across 10 workers.
        await asyncio.sleep(0.5)
    return _worker_threads


# ---------------------------------------------------------------------------
# Parse helpers for NSE data
# ---------------------------------------------------------------------------

def _parse_52week_data(data: dict) -> dict[str, dict]:
    """Parse 52-week high/low response into {symbol: {...}} mapping."""
    result = {}
    for item in data.get("data", []):
        symbol = item.get("symbol")
        if symbol:
            result[symbol] = {
                "ltp": item.get("ltp"),
                "new52WHL": item.get("new52WHL"),
                "pChange": item.get("pChange") or item.get("perChange"),
            }
    return result


def _parse_volume_gainers(data: dict) -> dict[str, dict]:
    """Parse volume gainers response into {symbol: {...}} mapping."""
    result = {}
    for item in data.get("data", []):
        symbol = item.get("symbol")
        if symbol:
            result[symbol] = {
                "week1volChange": item.get("week1volChange"),
                "pChange": item.get("pChange") or item.get("perChange"),
            }
    return result


def _parse_largedeal_snapshot(snapshot: dict) -> dict[str, list[DealRecord]]:
    """Parse largedeal snapshot into dict of {symbol: [DealRecord, ...]}."""
    deals_by_symbol: dict[str, list[DealRecord]] = {}
    
    # Process bulk deals
    for item in snapshot.get("BULK_DEALS_DATA", []):
        if item.get("symbol"):
            symbol = item["symbol"].upper()
            deal = DealRecord(
                symbol=symbol,
                deal_type="bulk",
                date=item.get("date", ""),
                qty=_coerce_int(item.get("qty")),
                watp=_coerce_float(item.get("watp")),
                client_name=item.get("clientName"),
                buy_sell=item.get("buySell"),
            )
            deals_by_symbol.setdefault(symbol, []).append(deal)
    
    # Process block deals
    for item in snapshot.get("BLOCK_DEALS_DATA", []):
        if item.get("symbol"):
            symbol = item["symbol"].upper()
            deal = DealRecord(
                symbol=symbol,
                deal_type="block",
                date=item.get("date", ""),
                qty=_coerce_int(item.get("qty")),
                watp=_coerce_float(item.get("watp")),
                client_name=item.get("clientName"),
                buy_sell=item.get("buySell"),
            )
            deals_by_symbol.setdefault(symbol, []).append(deal)
    
    # Process short deals (short-selling, NOT insider trades)
    for item in snapshot.get("SHORT_DEALS_DATA", []):
        if item.get("symbol"):
            symbol = item["symbol"].upper()
            deal = DealRecord(
                symbol=symbol,
                deal_type="short",
                date=item.get("date", ""),
                qty=_coerce_int(item.get("qty")),
                watp=_coerce_float(item.get("watp")),
                client_name=item.get("clientName"),
                buy_sell=item.get("buySell"),
            )
            deals_by_symbol.setdefault(symbol, []).append(deal)
    
    return deals_by_symbol


# ---------------------------------------------------------------------------
# Safe fetch wrappers for NSE endpoints
# ---------------------------------------------------------------------------

def _safe_fetch_52week_high() -> dict:
    try:
        return _nse_client.get_52week_high_stocks()
    except Exception:
        logger.exception("Failed to fetch 52-week high data")
        return {}


def _safe_fetch_52week_low() -> dict:
    try:
        return _nse_client.get_52week_low_stocks()
    except Exception:
        logger.exception("Failed to fetch 52-week low data")
        return {}


def _safe_fetch_volume_gainers() -> dict:
    try:
        return _nse_client.get_volume_gainers()
    except Exception:
        logger.exception("Failed to fetch volume gainers")
        return {}


def _safe_fetch_top_gainers() -> pd.DataFrame | None:
    try:
        return _nse_client.get_top_gainers()
    except Exception:
        logger.exception("Failed to fetch top gainers")
        return None


def _safe_fetch_top_losers() -> pd.DataFrame | None:
    try:
        return _nse_client.get_top_losers()
    except Exception:
        logger.exception("Failed to fetch top losers")
        return None


def _safe_fetch_largedeal_snapshot() -> dict:
    try:
        return _nse_client.get_largedeal_snapshot()
    except Exception:
        logger.exception("Failed to fetch largedeal snapshot")
        return {}


# ---------------------------------------------------------------------------
# Notification worker — watchlist stock alert generator
# ---------------------------------------------------------------------------

NOTIFICATION_CHECK_INTERVAL = 5 * 60       # 5 minutes  (market hours)
AFTER_HOURS_INTERVAL = 30 * 60             # 30 minutes (outside market hours)
DAILY_NOTIFICATION_WINDOW_DAYS = 7          # lookback for deals and insider trades
CLEANUP_READ_AFTER_DAYS = 30              # hard-delete read notifications older than this
CLEANUP_INTERVAL = 24 * 60 * 60            # run cleanup at most once per 24 hours

# Phase C: data-retention policies for high-volume tables
NEWS_RETENTION_DAYS = 30                   # hard-delete news_articles older than this
INTRADAY_1H_RETENTION_DAYS = 30            # 1h candles older than this are pruned
INTRADAY_W_RETENTION_YEARS = 2             # weekly candles older than this are pruned
# Monthly (M) candles: kept forever (small footprint, useful for long-term charts)

_cleanup_last_run: datetime | None = None


def _get_watchlist_symbols() -> dict[int, list[str]]:
    """Return all watchlist items grouped by watchlist_id."""
    with _SyncSessionLocal() as session:
        result = session.execute(select(WatchlistItem.watchlist_id, WatchlistItem.symbol))
        rows = result.fetchall()
    grouped: dict[int, list[str]] = {}
    for wl_id, symbol in rows:
        grouped.setdefault(wl_id, []).append(symbol.upper())
    return grouped


def _get_seen_today() -> set[tuple[int, str, str]]:
    """Return {(watchlist_id, symbol, trigger_type)} for all unread notifications today."""
    today = datetime.now().date()
    with _SyncSessionLocal() as session:
        rows = session.execute(
            select(Notification.watchlist_id, Notification.symbol, Notification.trigger_type)
            .where(
                Notification.triggered_date == today,
                Notification.is_read == False,
            )
        )
        return {(r[0], r[1], r[2]) for r in rows}


def _bulk_upsert_notifications(rows: list[dict]) -> None:
    """Insert notification rows, skipping duplicates via UniqueConstraint.

    rows is a list of plain dicts keyed by column name — NOT ORM objects.
    Using ORM object __dict__ would include SQLAlchemy internal state keys,
    causing the insert to fail or behave unexpectedly.
    """
    if not rows:
        return
    with _SyncSessionLocal() as session:
        stmt = (
            sqlite_insert(Notification)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["watchlist_id", "symbol", "trigger_type", "triggered_date"]
            )
        )
        session.execute(stmt)
        session.commit()


def _run_cleanup_if_due() -> None:
    """Run the daily cleanup suite.

    - Hard-delete read notifications older than CLEANUP_READ_AFTER_DAYS
    - Phase C: hard-delete news_articles older than NEWS_RETENTION_DAYS
    - Phase C: prune ticker_intraday 1h bars older than INTRADAY_1H_RETENTION_DAYS
    - Phase C: prune ticker_intraday W bars older than INTRADAY_W_RETENTION_YEARS
    - Monthly bars are never pruned.

    Runs at most once per CLEANUP_INTERVAL to avoid unnecessary DB writes.
    Errors in any single pruner are logged and do not prevent the others.
    """
    global _cleanup_last_run
    now = datetime.now()
    if _cleanup_last_run is not None and (now - _cleanup_last_run).total_seconds() < CLEANUP_INTERVAL:
        return

    # 1) notifications
    try:
        cutoff = datetime.combine(now.date() - timedelta(days=CLEANUP_READ_AFTER_DAYS), datetime.min.time())
        with _SyncSessionLocal() as session:
            deleted = session.execute(
                delete(Notification).where(
                    Notification.is_read == True,
                    Notification.triggered_at < cutoff,
                )
            )
            session.commit()
            if deleted.rowcount > 0:
                logger.info(
                    "notification_cleanup: deleted %d read notifications older than %s",
                    deleted.rowcount,
                    cutoff.date(),
                )
    except Exception:
        logger.exception("notification_cleanup: failed (non-fatal)")

    # 2) news articles (full row hard-delete) — use raw SQL for speed
    #    (SQLAlchemy ORM delete() does a SELECT-then-DELETE-per-row)
    try:
        news_cutoff = now - timedelta(days=NEWS_RETENTION_DAYS)
        with _SyncSessionLocal() as session:
            deleted = session.execute(
                text("DELETE FROM news_articles WHERE publish_date < :cutoff"),
                {"cutoff": news_cutoff},
            )
            session.commit()
            if deleted.rowcount > 0:
                logger.info(
                    "news_cleanup: deleted %d articles older than %s",
                    deleted.rowcount, news_cutoff.date(),
                )
    except Exception:
        logger.exception("news_cleanup: failed (non-fatal)")

    # 3) intraday 1h — chunked DELETE so the WAL lock is held briefly per batch
    try:
        cutoff_1h = now - timedelta(days=INTRADAY_1H_RETENTION_DAYS)
        total_1h = 0
        for _ in range(50):  # up to 50 batches per cleanup cycle
            with _SyncSessionLocal() as session:
                deleted = session.execute(
                    text(
                        "DELETE FROM ticker_intraday WHERE rowid IN ("
                        "  SELECT rowid FROM ticker_intraday "
                        "  WHERE interval = '1h' AND timestamp < :cutoff "
                        "  LIMIT 50000"
                        ")"
                    ),
                    {"cutoff": cutoff_1h},
                )
                session.commit()
                count = deleted.rowcount
            total_1h += count
            if count < 50000:
                break
        if total_1h > 0:
            logger.info(
                "intraday_cleanup: deleted %d 1h candles older than %s",
                total_1h, cutoff_1h,
            )
    except Exception:
        logger.exception("intraday_1h_cleanup: failed (non-fatal)")

    # 4) intraday W
    try:
        cutoff_w = now - timedelta(days=365 * INTRADAY_W_RETENTION_YEARS)
        total_W = 0
        for _ in range(50):
            with _SyncSessionLocal() as session:
                deleted = session.execute(
                    text(
                        "DELETE FROM ticker_intraday WHERE rowid IN ("
                        "  SELECT rowid FROM ticker_intraday "
                        "  WHERE interval = 'W' AND timestamp < :cutoff "
                        "  LIMIT 50000"
                        ")"
                    ),
                    {"cutoff": cutoff_w},
                )
                session.commit()
                count = deleted.rowcount
            total_W += count
            if count < 50000:
                break
        if total_W > 0:
            logger.info(
                "intraday_cleanup: deleted %d W candles older than %s",
                total_W, cutoff_w.date(),
            )
    except Exception:
        logger.exception("intraday_W_cleanup: failed (non-fatal)")

    _cleanup_last_run = now


# ---------------------------------------------------------------------------
# Global notification helpers (for market-wide scan)
# ---------------------------------------------------------------------------

def _get_global_seen_today() -> set[tuple[str, str]]:
    """Return {(symbol, trigger_type)} for all unread global notifications today."""
    today = datetime.now().date()
    with _SyncSessionLocal() as session:
        rows = session.execute(
            select(GlobalNotification.symbol, GlobalNotification.trigger_type)
            .where(
                GlobalNotification.triggered_date == today,
                GlobalNotification.is_read == False,
            )
        )
        return {(r[0], r[1]) for r in rows}


def _bulk_upsert_global_notifications(rows: list[dict]) -> None:
    """Insert global notification rows, skipping duplicates via UniqueConstraint."""
    if not rows:
        return
    with _SyncSessionLocal() as session:
        stmt = (
            sqlite_insert(GlobalNotification)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["symbol", "trigger_type", "triggered_date"]
            )
        )
        session.execute(stmt)
        session.commit()


# ---------------------------------------------------------------------------
# Configurable notification thresholds (read from system_config)
# ---------------------------------------------------------------------------

def get_notif_config() -> dict:
    """Read notif.* threshold values from system_config with hardcoded fallbacks."""
    DEFAULTS: dict = {
        "notif.rsi_oversold_threshold":        30.0,
        "notif.rsi_overbought_threshold":      70.0,
        "notif.volatility_spike_ratio":         1.5,
        "notif.atr_expansion_threshold":        4.0,
        "notif.momentum_surge_threshold":      70.0,
        "notif.return_1w_spike_threshold":     10.0,
        "notif.streak_days_threshold":          5.0,
        "notif.near_52w_threshold":             3.0,
        # Deal significance thresholds
        "notif.deal_significance_pct":          0.05,
        "notif.deal_absolute_threshold_cr":     2.0,
    }
    try:
        with _SyncSessionLocal() as db:
            rows = db.execute(
                select(SystemConfig.key, SystemConfig.value)
                .where(SystemConfig.key.like("notif.%"))
            ).fetchall()
            db_vals: dict = {row[0]: row[1] for row in rows}
    except Exception:
        logger.warning("get_notif_config: failed to read system_config, using defaults")
        db_vals = {}

    config: dict = {}
    for key, default in DEFAULTS.items():
        raw = db_vals.get(key)
        if raw is not None:
            try:
                config[key] = type(default)(raw)
            except (ValueError, TypeError):
                config[key] = default
        else:
            config[key] = default
    return config


# ---------------------------------------------------------------------------
# Deal significance helpers
# ---------------------------------------------------------------------------

def _fetch_deal_market_caps(symbols: set[str]) -> dict[str, float]:
    """Bulk-fetch market caps (Rs Cr) for deal symbols from MarketCategoryStock."""
    from app.models.marketcategory import MarketCategoryStock
    if not symbols:
        return {}
    try:
        with _SyncSessionLocal() as db:
            rows = db.execute(
                select(MarketCategoryStock.symbol, MarketCategoryStock.market_cap)
                .where(MarketCategoryStock.symbol.in_(symbols))
            ).fetchall()
        return {row[0]: float(row[1]) for row in rows if row[1] is not None}
    except Exception:
        logger.warning("_fetch_deal_market_caps: DB query failed, returning empty dict")
        return {}


def _fetch_short_deal_close_prices(
    short_deals: list["DealRecord"],
) -> dict[str, dict[str, float]]:
    """Fetch closing prices for short deals (which carry no watp) from TickerDaily.

    Returns: {symbol: {date_str: close_price}} where date_str is the original
    NSE format "12-Mar-2026".
    """
    from sqlalchemy import tuple_ as sa_tuple
    from app.models.ticker import TickerDaily

    pairs: list[tuple[str, date]] = []
    for deal in short_deals:
        if deal.deal_type != "short" or not deal.date:
            continue
        try:
            d = datetime.strptime(deal.date, "%d-%b-%Y").date()
            pairs.append((deal.symbol, d))
        except (ValueError, AttributeError):
            pass

    if not pairs:
        return {}

    try:
        result: dict[str, dict[str, float]] = {}
        unique_pairs = list({(sym, d) for sym, d in pairs})
        with _SyncSessionLocal() as db:
            rows = db.execute(
                select(TickerDaily.symbol, TickerDaily.date, TickerDaily.close).where(
                    sa_tuple(TickerDaily.symbol, TickerDaily.date).in_(unique_pairs)
                )
            ).all()
        for symbol, d, close in rows:
            if close is not None:
                date_str = d.strftime("%d-%b-%Y")
                result.setdefault(symbol, {})[date_str] = float(close)
        return result
    except Exception:
        logger.warning("_fetch_short_deal_close_prices: DB query failed")
        return {}


def _is_deal_significant(
    deal: "DealRecord",
    short_close_prices: dict[str, dict[str, float]],
    market_caps_cr: dict[str, float],
    significance_pct: float,
    absolute_threshold_cr: float,
) -> tuple[bool, float]:
    """Check whether a deal is significant enough to generate an alert.

    Significance is defined as:
      trade_value >= significance_pct * market_cap
    with a fallback of trade_value >= absolute_threshold_cr (Rs Cr) when the
    market cap is unknown.

    Short deals carry no watp from NSE — their price is resolved from TickerDaily.

    Returns:
        (is_significant, trade_value_cr)
    """
    if deal.deal_type == "short":
        price = short_close_prices.get(deal.symbol, {}).get(deal.date, 0.0)
    else:
        price = deal.watp

    if price <= 0 or deal.qty <= 0:
        return False, 0.0

    trade_value_cr = (deal.qty * price) / 1e7  # Rs → Rs Cr

    market_cap_cr = market_caps_cr.get(deal.symbol)
    if market_cap_cr and market_cap_cr > 0:
        is_sig = (trade_value_cr / market_cap_cr) >= significance_pct
    else:
        is_sig = trade_value_cr >= absolute_threshold_cr

    return is_sig, trade_value_cr


# ---------------------------------------------------------------------------
# Indicator-based notification cycle (15 technical triggers)
# ---------------------------------------------------------------------------

def _ticker_indicator_notification_cycle() -> None:
    """Generate indicator-based notifications for all watchlist symbols.

    Evaluates all 15 technical trigger types (RSI, MACD, Bollinger, ATR,
    volatility, momentum, returns, streaks, 52W proximity) against the latest
    stored ticker_daily indicator columns.

    Momentum and 1W return alerts are read from the pre-computed `ticker_scores`
    cache (populated by Stage 4 `_ticker_scores_sync`), NOT from
    `get_momentum_score`/`get_returns`. Those services do O(universe_size) work
    per call, which previously caused the per-symbol loop to hang for hours when
    invoked across the 65-symbol watchlist.
    """
    from app.models.ticker import TickerDaily, TickerScore
    from app.models.stockuniverse import StockUniverse

    try:
        logger.info("ticker_indicator_notification_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = get_notif_config()
        rsi_oversold_thr   = float(cfg["notif.rsi_oversold_threshold"])
        rsi_overbought_thr = float(cfg["notif.rsi_overbought_threshold"])
        vol_spike_ratio    = float(cfg["notif.volatility_spike_ratio"])
        atr_exp_thr        = float(cfg["notif.atr_expansion_threshold"])
        momentum_thr       = float(cfg["notif.momentum_surge_threshold"])
        return_1w_thr      = float(cfg["notif.return_1w_spike_threshold"])
        streak_thr         = int(cfg["notif.streak_days_threshold"])
        near52w_thr        = float(cfg["notif.near_52w_threshold"])

        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("ticker_indicator_notification_cycle: watchlist is empty, skipping")
            return

        all_symbols = list({s for wl_symbols in symbols_by_watchlist.values() for s in wl_symbols})
        total_symbols = len(all_symbols)
        logger.info("ticker_indicator_notification_cycle: starting for %d symbols in %d watchlists",
                    total_symbols, len(symbols_by_watchlist))

        # Load TickerScore cache once for the whole cycle. Stage 4
        # `_ticker_scores_sync` pre-computes momentum_score and return_1w for
        # every symbol; reading from this cache keeps the cycle O(watchlist)
        # instead of O(watchlist × universe).
        scores_cache: dict[str, TickerScore] = {}
        try:
            with _SyncSessionLocal() as db:
                rows = db.execute(
                    select(TickerScore).where(TickerScore.compute_date == today_date)
                )
                for row in rows.scalars():
                    scores_cache[row.symbol] = row
            logger.info("ticker_indicator_notification_cycle: loaded %d ticker_scores from cache",
                        len(scores_cache))
        except Exception as e:
            logger.warning("ticker_indicator_notification_cycle: failed to load ticker_scores: %s", e)

        seen_today = _get_seen_today()
        pending: list[dict] = []
        processed = 0
        alerts_generated = 0

        for symbol in all_symbols:
            if _shutdown_event.is_set():
                logger.info("ticker_indicator_notification_cycle: shutdown requested, stopping at %d/%d symbols",
                            processed, total_symbols)
                return

            processed += 1
            if processed % 20 == 0 or processed == 1:
                logger.info("ticker_indicator_notification_cycle: progress %d/%d symbols (%.0f%%)",
                            processed, total_symbols, processed / total_symbols * 100)

            try:
                with _SyncSessionLocal() as db:
                    # Last 10 candles for streak + indicator comparison
                    rows = list(
                        db.execute(
                            select(TickerDaily)
                            .where(TickerDaily.symbol == symbol)
                            .order_by(TickerDaily.date.desc())
                            .limit(10)
                        ).scalars()
                    )
                    su_row = db.execute(
                        select(StockUniverse).where(StockUniverse.symbol == symbol)
                    ).scalar_one_or_none()

                if not rows or len(rows) < 2:
                    continue

                rows_asc = list(reversed(rows))  # oldest → newest
                latest = rows_asc[-1]
                prev   = rows_asc[-2]

                # --- consecutive day streak (close vs open) ---
                up_streak = 0
                dn_streak = 0
                for r in reversed(rows_asc):
                    if r.close is None or r.open is None:
                        break
                    if r.close > r.open:
                        if dn_streak > 0:
                            break
                        up_streak += 1
                    elif r.close < r.open:
                        if up_streak > 0:
                            break
                        dn_streak += 1
                    else:
                        break  # flat day breaks streak

                # --- 52W proximity ---
                pct_from_52w_high: float | None = None
                pct_from_52w_low:  float | None = None
                if su_row and su_row.high_52w and su_row.low_52w and latest.close:
                    if su_row.high_52w > 0:
                        pct_from_52w_high = (latest.close - su_row.high_52w) / su_row.high_52w * 100
                    if su_row.low_52w > 0:
                        pct_from_52w_low  = (latest.close - su_row.low_52w) / su_row.low_52w  * 100

                # --- momentum and return_1w from pre-computed TickerScore cache ---
                # Avoid get_momentum_score/get_returns: those are O(universe_size)
                # per call and were the root cause of the Stage 3 hang.
                ts = scores_cache.get(symbol)
                momentum_score = ts.momentum_score if ts else None
                return_1w      = ts.return_1w      if ts else None

                # --- build alerts per watchlist that contains this symbol ---
                for wl_id, wl_symbols in symbols_by_watchlist.items():
                    if symbol not in wl_symbols:
                        continue

                    alerts: list[tuple[str, str]] = []

                    # RSI
                    if latest.rsi_14 is not None:
                        if latest.rsi_14 < rsi_oversold_thr:
                            alerts.append(("rsi_oversold",
                                f"{symbol} RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
                        elif latest.rsi_14 > rsi_overbought_thr:
                            alerts.append(("rsi_overbought",
                                f"{symbol} RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

                    # MACD crossover (requires 2 rows with stored histograms)
                    if latest.macd_histogram is not None and prev.macd_histogram is not None:
                        if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
                            alerts.append(("macd_bullish_cross",
                                f"{symbol} MACD bullish crossover "
                                f"({prev.macd_histogram:.4f} → {latest.macd_histogram:.4f})"))
                        elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
                            alerts.append(("macd_bearish_cross",
                                f"{symbol} MACD bearish crossover "
                                f"({prev.macd_histogram:.4f} → {latest.macd_histogram:.4f})"))

                    # Bollinger Bands
                    if latest.bb_squeeze == "Y":
                        alerts.append(("bb_squeeze_alert",
                            f"{symbol} Bollinger Band squeeze detected (bb_width={latest.bb_width})"))
                    if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
                        alerts.append(("bb_upper_break",
                            f"{symbol} close ₹{latest.close} broke above BB upper ₹{latest.bb_upper}"))
                    if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
                        alerts.append(("bb_lower_break",
                            f"{symbol} close ₹{latest.close} broke below BB lower ₹{latest.bb_lower}"))

                    # Volatility
                    if (latest.hv_20 is not None and latest.hv_60 is not None
                            and latest.hv_60 > 0
                            and latest.hv_20 > latest.hv_60 * vol_spike_ratio):
                        alerts.append(("volatility_spike",
                            f"{symbol} HV20 {latest.hv_20:.1f}% > {vol_spike_ratio}× HV60 {latest.hv_60:.1f}%"))
                    if latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
                        alerts.append(("atr_expansion",
                            f"{symbol} ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

                    # Momentum / returns (read from TickerScore cache)
                    if momentum_score is not None and momentum_score > momentum_thr:
                        alerts.append(("momentum_surge",
                            f"{symbol} momentum score {momentum_score:.1f} > {momentum_thr}"))
                    if return_1w is not None and return_1w > return_1w_thr:
                        alerts.append(("return_1w_spike",
                            f"{symbol} 1W return {return_1w:+.1f}% > {return_1w_thr}%"))

                    # Streaks
                    if up_streak >= streak_thr:
                        alerts.append(("streak_up_5d",
                            f"{symbol} up {up_streak} consecutive days"))
                    if dn_streak >= streak_thr:
                        alerts.append(("streak_down_5d",
                            f"{symbol} down {dn_streak} consecutive days"))

                    # 52W proximity
                    if pct_from_52w_high is not None and -near52w_thr <= pct_from_52w_high <= 0:
                        alerts.append(("near_52w_high",
                            f"{symbol} within {near52w_thr}% of 52W high ({pct_from_52w_high:+.1f}%)"))
                    if pct_from_52w_low is not None and 0 <= pct_from_52w_low <= near52w_thr:
                        alerts.append(("near_52w_low",
                            f"{symbol} within {near52w_thr}% of 52W low ({pct_from_52w_low:+.1f}%)"))

                    for trigger_type, message in alerts:
                        key = (wl_id, symbol, trigger_type)
                        if key in seen_today:
                            continue
                        seen_today.add(key)
                        pending.append({
                            "watchlist_id":   wl_id,
                            "symbol":         symbol,
                            "exchange":       "NSE",
                            "trigger_type":   trigger_type,
                            "message":        message,
                            "triggered_at":   now,
                            "triggered_date": today_date,
                            "is_read":        False,
                        })
                        alerts_generated += 1

            except Exception:
                logger.exception(f"ticker_indicator_notification_cycle: failed for {symbol}")

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info(
                "ticker_indicator_notification_cycle: processed %d symbols, generated %d notifications, upserted %d",
                processed, alerts_generated, len(pending)
            )
        else:
            logger.info("ticker_indicator_notification_cycle: processed %d symbols, no new notifications", processed)

    except Exception:
        logger.exception("ticker_indicator_notification_cycle: unhandled exception")


def _ticker_intraday_indicator_notification_cycle() -> None:
    """Generate indicator-based notifications for watchlist symbols using intraday data.

    Evaluates RSI, MACD, Bollinger, ATR, and MTF alignment triggers against
    the latest stored ticker_intraday indicator columns for 1h, W, and M.
    """
    from app.models.ticker import TickerIntraday, TickerDaily
    from app.models.stockuniverse import StockUniverse

    try:
        logger.info("ticker_intraday_indicator_notification_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = get_notif_config()
        rsi_oversold_thr   = float(cfg.get("notif.rsi_oversold_threshold", "30.0"))
        rsi_overbought_thr = float(cfg.get("notif.rsi_overbought_threshold", "70.0"))
        atr_exp_thr        = float(cfg.get("notif.atr_expansion_threshold", "4.0"))

        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("ticker_intraday_indicator_notification_cycle: watchlist empty, skipping")
            return

        all_symbols = list({s for wl_symbols in symbols_by_watchlist.values() for s in wl_symbols})
        total_symbols = len(all_symbols)

        seen_today = _get_seen_today()
        pending: list[dict] = []
        processed = 0
        alerts_generated = 0

        for symbol in all_symbols:
            if _shutdown_event.is_set():
                return

            processed += 1
            if processed % 20 == 0 or processed == 1:
                logger.info("ticker_intraday_indicator_notification_cycle: progress %d/%d", processed, total_symbols)

            try:
                # Load latest 2 rows per interval for crossover detection
                intraday_rows: dict[str, list] = {}
                with _SyncSessionLocal() as db:
                    for interval in ("1h", "W", "M"):
                        rows = list(
                            db.execute(
                                select(TickerIntraday)
                                .where(TickerIntraday.symbol == symbol)
                                .where(TickerIntraday.interval == interval)
                                .order_by(TickerIntraday.timestamp.desc())
                                .limit(2)
                            ).scalars()
                        )
                        if rows:
                            intraday_rows[interval] = list(reversed(rows))  # oldest → newest

                    su_row = db.execute(
                        select(StockUniverse).where(StockUniverse.symbol == symbol)
                    ).scalar_one_or_none()

                if not intraday_rows:
                    continue

                # Build per-watchlist alerts
                for wl_id, wl_symbols in symbols_by_watchlist.items():
                    if symbol not in wl_symbols:
                        continue

                    alerts: list[tuple[str, str]] = []

                    for interval, rows in intraday_rows.items():
                        if len(rows) < 1:
                            continue
                        latest = rows[-1]
                        prev = rows[-2] if len(rows) >= 2 else None
                        sfx = f"_{interval}"

                        # RSI
                        if latest.rsi_14 is not None:
                            if latest.rsi_14 < rsi_oversold_thr:
                                alerts.append((f"rsi_oversold{sfx}",
                                    f"{symbol} [{interval}] RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
                            elif latest.rsi_14 > rsi_overbought_thr:
                                alerts.append((f"rsi_overbought{sfx}",
                                    f"{symbol} [{interval}] RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

                        # MACD crossover
                        if prev and latest.macd_histogram is not None and prev.macd_histogram is not None:
                            if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
                                alerts.append((f"macd_bullish_cross{sfx}",
                                    f"{symbol} [{interval}] MACD bullish crossover"))
                            elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
                                alerts.append((f"macd_bearish_cross{sfx}",
                                    f"{symbol} [{interval}] MACD bearish crossover"))

                        # Bollinger Bands
                        if latest.bb_squeeze == "Y":
                            alerts.append((f"bb_squeeze_alert{sfx}",
                                f"{symbol} [{interval}] BB squeeze (width={latest.bb_width})"))
                        if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
                            alerts.append((f"bb_upper_break{sfx}",
                                f"{symbol} [{interval}] close > BB upper"))
                        if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
                            alerts.append((f"bb_lower_break{sfx}",
                                f"{symbol} [{interval}] close < BB lower"))

                        # ATR expansion (1h only — meaningful for intraday)
                        if interval == "1h" and latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
                            alerts.append((f"atr_expansion{sfx}",
                                f"{symbol} [1h] ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

                    # MTF alignment (daily + weekly + monthly RSI all same direction)
                    daily_rsi = None
                    weekly_rsi = None
                    monthly_rsi = None
                    if "1h" in intraday_rows:
                        # 1h is not used for MTF; use daily from ticker_daily if available
                        with _SyncSessionLocal() as db:
                            daily_row = db.execute(
                                select(TickerDaily.rsi_14)
                                .where(TickerDaily.symbol == symbol)
                                .order_by(TickerDaily.date.desc())
                                .limit(1)
                            ).scalar_one_or_none()
                            daily_rsi = daily_row
                    if "W" in intraday_rows:
                        weekly_rsi = intraday_rows["W"][-1].rsi_14
                    if "M" in intraday_rows:
                        monthly_rsi = intraday_rows["M"][-1].rsi_14

                    if daily_rsi is not None and weekly_rsi is not None and monthly_rsi is not None:
                        if daily_rsi > 50 and weekly_rsi > 50 and monthly_rsi > 50:
                            alerts.append(("mtf_bullish_alignment",
                                f"{symbol} MTF bullish: D={daily_rsi:.1f} W={weekly_rsi:.1f} M={monthly_rsi:.1f} all > 50"))
                        elif daily_rsi < 50 and weekly_rsi < 50 and monthly_rsi < 50:
                            alerts.append(("mtf_bearish_alignment",
                                f"{symbol} MTF bearish: D={daily_rsi:.1f} W={weekly_rsi:.1f} M={monthly_rsi:.1f} all < 50"))

                    for trigger_type, message in alerts:
                        key = (wl_id, symbol, trigger_type)
                        if key in seen_today:
                            continue
                        seen_today.add(key)
                        pending.append({
                            "watchlist_id":   wl_id,
                            "symbol":         symbol,
                            "exchange":       "NSE",
                            "trigger_type":   trigger_type,
                            "message":        message,
                            "triggered_at":   now,
                            "triggered_date": today_date,
                            "is_read":        False,
                        })
                        alerts_generated += 1

            except Exception:
                logger.exception("ticker_intraday_indicator_notification_cycle: failed for %s", symbol)

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info(
                "ticker_intraday_indicator_notification_cycle: processed %d symbols, generated %d notifications, upserted %d",
                processed, alerts_generated, len(pending)
            )
        else:
            logger.info("ticker_intraday_indicator_notification_cycle: processed %d symbols, no new notifications", processed)

    except Exception:
        logger.exception("ticker_intraday_indicator_notification_cycle: unhandled exception")


def _build_alerts(
    symbol: str,
    high52_data: dict | None = None,
    low52_data: dict | None = None,
    vol_data: dict | None = None,
    gainers_df: pd.DataFrame | None = None,
    losers_df: pd.DataFrame | None = None,
    deals_by_symbol: dict[str, list[DealRecord]] | None = None,
    insider_trades: list[dict] | None = None,
    deal_significance_pct: float = 0.05,
    deal_absolute_threshold_cr: float = 2.0,
    deal_market_caps_cr: dict[str, float] | None = None,
    deal_short_prices: dict[str, dict[str, float]] | None = None,
) -> list[tuple[str, str]]:
    """Build list of (trigger_type, message) tuples for a symbol."""
    alerts: list[tuple[str, str]] = []
    
    # 52-week high/low
    if high52_data and symbol in high52_data:
        row = high52_data[symbol]
        price = row.get("ltp") or row.get("new52WHL") or "—"
        alerts.append(("52w_high_breakout", f"{symbol} hit a new 52-week HIGH @ ₹{price}"))
    
    if low52_data and symbol in low52_data:
        row = low52_data[symbol]
        price = row.get("ltp") or row.get("new52WHL") or "—"
        alerts.append(("52w_low_breakout", f"{symbol} hit a new 52-week LOW @ ₹{price}"))
    
    # Volume breakout
    if vol_data and symbol in vol_data:
        ratio = vol_data[symbol].get("week1volChange", 0)
        alerts.append(("volume_breakout", f"{symbol} showing volume breakout ({ratio:+.0f}x avg)"))
    
    # Top gainers/losers (DataFrame)
    def _row_pchg(row) -> float:
        """Read % change from either pChange (legacy) or perChange (new API)."""
        return getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0

    if gainers_df is not None:
        for row in gainers_df.itertuples():
            if row.symbol == symbol:
                pchg = _row_pchg(row)
                if pchg:
                    alerts.append(("top_gainer", f"{symbol} among TOP GAINERS ({pchg:+.1f}%)"))
                break

    if losers_df is not None:
        for row in losers_df.itertuples():
            if row.symbol == symbol:
                pchg = _row_pchg(row)
                if pchg:
                    alerts.append(("top_loser", f"{symbol} among TOP LOSERS ({pchg:+.1f}%)"))
                break
    
    # Deals (bulk/block/short) — O(1) lookup via pre-indexed dict.
    # Only fire for trades whose value is significant relative to market cap.
    if deals_by_symbol and symbol in deals_by_symbol:
        _mkt_caps = deal_market_caps_cr or {}
        _short_px = deal_short_prices or {}
        for deal in deals_by_symbol[symbol]:
            if not _is_recent(deal.date, DAILY_NOTIFICATION_WINDOW_DAYS):
                continue
            is_sig, trade_val_cr = _is_deal_significant(
                deal, _short_px, _mkt_caps,
                deal_significance_pct, deal_absolute_threshold_cr,
            )
            if not is_sig:
                continue
            val_str = f" = ₹{trade_val_cr:.1f} Cr" if trade_val_cr > 0 else ""
            alerts.append((
                f"{deal.deal_type}_deal",
                f"{symbol} — {deal.deal_type} deal: {deal.qty:,} shares @ ₹{deal.watp}{val_str}",
            ))
    
    # Insider trades (from screener.in)
    if insider_trades:
        for trade in insider_trades:
            # trade is a dict with "direction": "up"/"down"
            direction = (trade.get("direction") or "").lower()
            if direction == "up":
                t_type = "insider_buy"
            elif direction == "down":
                t_type = "insider_sell"
            else:
                t_type = f"insider_{direction}" if direction else "insider_unknown"
            
            person = trade.get("person", "Unknown")
            qty = trade.get("quantity", 0)
            alerts.append((
                t_type,
                f"{symbol} insider {direction}: {person} {direction} {qty:,} shares"
            ))
    
    return alerts


def _notification_cycle_full() -> None:
    """Full cycle: check all 9 trigger types. Called in a worker thread."""
    global _cleanup_last_run

    try:
        logger.info("notification_cycle_full: starting")
        now = datetime.now()
        today_date = now.date()

        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("notification_cycle_full: watchlist is empty, skipping")
            return

        seen_today = _get_seen_today()
        pending: list[dict] = []

        # Fetch NSE data with error handling
        high52_raw = _safe_fetch_52week_high()
        low52_raw = _safe_fetch_52week_low()
        vol_raw = _safe_fetch_volume_gainers()
        gainers_df = _safe_fetch_top_gainers()
        losers_df = _safe_fetch_top_losers()
        deals_raw = _safe_fetch_largedeal_snapshot()

        # Parse raw data
        high52_data = _parse_52week_data(high52_raw)
        low52_data = _parse_52week_data(low52_raw)
        vol_data = _parse_volume_gainers(vol_raw)
        deals = _parse_largedeal_snapshot(deals_raw)

        # Read deal significance thresholds
        cfg = get_notif_config()
        deal_sig_pct = float(cfg["notif.deal_significance_pct"])
        deal_abs_cr  = float(cfg["notif.deal_absolute_threshold_cr"])

        # Pre-fetch deal significance data (single DB round-trip)
        deal_symbols = set(deals.keys())
        deal_mkt_caps = _fetch_deal_market_caps(deal_symbols)
        short_deals   = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px = _fetch_short_deal_close_prices(short_deals)

        # Cache insider trades per symbol
        insider_cache: dict[str, list[dict]] = {}

        for wl_id, symbols in symbols_by_watchlist.items():
            for symbol in symbols:
                # Get insider trades for this symbol (cached)
                if symbol not in insider_cache:
                    insider_cache[symbol] = _fetch_insider_trades_cached(symbol)

                # Build all alerts for this symbol
                alerts = _build_alerts(
                    symbol=symbol,
                    high52_data=high52_data,
                    low52_data=low52_data,
                    vol_data=vol_data,
                    gainers_df=gainers_df,
                    losers_df=losers_df,
                    deals_by_symbol=deals,
                    insider_trades=insider_cache[symbol],
                    deal_significance_pct=deal_sig_pct,
                    deal_absolute_threshold_cr=deal_abs_cr,
                    deal_market_caps_cr=deal_mkt_caps,
                    deal_short_prices=deal_short_px,
                )

                # Add to pending if not seen today
                for trigger_type, message in alerts:
                    key = (wl_id, symbol, trigger_type)
                    if key in seen_today:
                        continue
                    seen_today.add(key)
                    pending.append({
                        "watchlist_id": wl_id,
                        "symbol": symbol,
                        "exchange": "NSE",
                        "trigger_type": trigger_type,
                        "message": message,
                        "triggered_at": now,
                        "triggered_date": today_date,
                        "is_read": False,
                    })

                if _shutdown_event.is_set():
                    return

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info("notification_cycle_full: upserted %d notifications", len(pending))
        else:
            logger.info("notification_cycle_full: no new notifications")

        _run_cleanup_if_due()
    except Exception:
        logger.exception("notification_cycle_full: unhandled exception")


def _notification_cycle_reduced() -> None:
    """Reduced cycle: deals + insider only. Outside market hours."""
    try:
        logger.info("notification_cycle_reduced: starting")
        now = datetime.now()
        today_date = now.date()

        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("notification_cycle_reduced: watchlist is empty, skipping")
            return

        seen_today = _get_seen_today()
        pending: list[dict] = []

        # Only fetch deals (market-hour triggers omitted)
        deals_raw = _safe_fetch_largedeal_snapshot()
        deals = _parse_largedeal_snapshot(deals_raw)

        # Read deal significance thresholds
        cfg = get_notif_config()
        deal_sig_pct = float(cfg["notif.deal_significance_pct"])
        deal_abs_cr  = float(cfg["notif.deal_absolute_threshold_cr"])

        # Pre-fetch deal significance data
        deal_symbols  = set(deals.keys())
        deal_mkt_caps = _fetch_deal_market_caps(deal_symbols)
        short_deals   = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px = _fetch_short_deal_close_prices(short_deals)

        insider_cache: dict[str, list[dict]] = {}

        for wl_id, symbols in symbols_by_watchlist.items():
            for symbol in symbols:
                # Get insider trades for this symbol (cached)
                if symbol not in insider_cache:
                    insider_cache[symbol] = _fetch_insider_trades_cached(symbol)

                # Build alerts (only deals + insider)
                alerts = _build_alerts(
                    symbol=symbol,
                    deals_by_symbol=deals,
                    insider_trades=insider_cache[symbol],
                    deal_significance_pct=deal_sig_pct,
                    deal_absolute_threshold_cr=deal_abs_cr,
                    deal_market_caps_cr=deal_mkt_caps,
                    deal_short_prices=deal_short_px,
                )

                # Add to pending if not seen today
                for trigger_type, message in alerts:
                    key = (wl_id, symbol, trigger_type)
                    if key in seen_today:
                        continue
                    seen_today.add(key)
                    pending.append({
                        "watchlist_id": wl_id,
                        "symbol": symbol,
                        "exchange": "NSE",
                        "trigger_type": trigger_type,
                        "message": message,
                        "triggered_at": now,
                        "triggered_date": today_date,
                        "is_read": False,
                    })

                if _shutdown_event.is_set():
                    return

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info("notification_cycle_reduced: upserted %d notifications", len(pending))
        _run_cleanup_if_due()
    except Exception:
        logger.exception("notification_cycle_reduced: unhandled exception")


def _fetch_insider_trades_cached(symbol: str) -> list[dict]:
    """Fetch insider trades from screener.in, returning a list of trade dicts."""
    try:
        result = _run_async(_fetch_insider_trades_async(symbol))
        return result
    except Exception:
        logger.debug("insider_trades: failed for %s, skipping", symbol)
        return []


async def _fetch_insider_trades_async(symbol: str) -> list[dict]:
    """Async helper: call screener_client.get_insider_trades."""
    try:
        data = await screener_client.get_insider_trades(symbol)
        if data and "insider_trades" in data:
            return data["insider_trades"]
    except Exception:
        pass
    return []


def watchlist_notification_worker() -> None:
    """Daemon thread: monitors watchlist stocks for significant market events.

    Cron: */5 * * * * during market hours; */30 * * * * after hours.
    """
    logger.info("watchlist_notification_worker: started")

    if not _is_job_enabled("job.notifications"):
        logger.info("watchlist_notification_worker: disabled, waiting...")
        update_job_status_sync("job.notifications", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.notifications", "idle", progress=0, message="Stopped")
        logger.info("watchlist_notification_worker: stopped")
        return

    # Wait for ticker scores to be ready before first notification cycle
    update_job_status_sync("job.notifications", "waiting", progress=0, message="Waiting for startup pipeline...")
    if _wait_for_startup_event(_startup_ticker_scores_done, "ticker_scores", "job.notifications"):
        update_job_status_sync("job.notifications", "idle", progress=0, message="Stopped")
        logger.info("watchlist_notification_worker: stopped")
        return

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.notifications"):
            update_job_status_sync("job.notifications", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
        # Wait for any active data pipeline (daily_update/indicators/scores) to finish
        if _wait_for_pipeline("job.notifications", "watchlist_notification"):
            break
        if _is_market_open():
            update_job_status_sync("job.notifications", "running", progress=50, message="Checking market events...")
            _notification_cycle_full()
            wait = _report_job_waiting("job.notifications", "*/5 * * * *")
            _sleep_interruptible(wait)
        else:
            update_job_status_sync("job.notifications", "waiting", progress=0, message="Market closed, checking after-hours...")
            _notification_cycle_reduced()
            wait = _report_job_waiting("job.notifications", "*/30 * * * *")
            _sleep_interruptible(wait)

    update_job_status_sync("job.notifications", "idle", progress=0, message="Stopped")
    logger.info("watchlist_notification_worker: stopped")


# ---------------------------------------------------------------------------
# Global scan worker — monitors all NSE stocks for technical & market alerts
# ---------------------------------------------------------------------------

GLOBAL_SCAN_BATCH_SIZE = 100
GLOBAL_SCAN_DELAY = 1.0


def _global_scan_cycle() -> None:
    """Generate alerts for all NSE stocks with indicator data.

    Scans all symbols in ticker_daily (not just watchlist), evaluates:
    - Technical indicators (RSI, MACD, Bollinger, ATR, volatility, streaks, 52W proximity)
    - Live NSE triggers (52W high/low, volume breakout, top gainer/loser)
    - Deal triggers (bulk/block/short deals)
    - Momentum triggers (momentum_surge, return_1w_spike) from ticker_scores cache
    """
    from app.models.ticker import TickerDaily
    from app.models.stockuniverse import StockUniverse

    try:
        logger.info("global_scan_cycle: starting")
        now = datetime.now()
        today_date = now.date()

        cfg = get_notif_config()
        rsi_oversold_thr = float(cfg["notif.rsi_oversold_threshold"])
        rsi_overbought_thr = float(cfg["notif.rsi_overbought_threshold"])
        vol_spike_ratio = float(cfg["notif.volatility_spike_ratio"])
        atr_exp_thr = float(cfg["notif.atr_expansion_threshold"])
        momentum_thr = float(cfg["notif.momentum_surge_threshold"])
        return_1w_thr = float(cfg["notif.return_1w_spike_threshold"])
        streak_thr = int(cfg["notif.streak_days_threshold"])
        near52w_thr = float(cfg["notif.near_52w_threshold"])
        deal_sig_pct = float(cfg["notif.deal_significance_pct"])
        deal_abs_cr  = float(cfg["notif.deal_absolute_threshold_cr"])

        with _SyncSessionLocal() as db:
            result = db.execute(
                select(TickerDaily.symbol)
                .where(TickerDaily.indicators_updated_at.isnot(None))
                .distinct()
            )
            all_symbols = [row[0] for row in result.fetchall()]

        total_symbols = len(all_symbols)
        if total_symbols == 0:
            logger.info("global_scan_cycle: no symbols with indicator data, skipping")
            return

        logger.info("global_scan_cycle: starting for %d symbols", total_symbols)

        scores_cache: dict[str, TickerScore] = {}
        try:
            with _SyncSessionLocal() as db:
                rows = db.execute(
                    select(TickerScore)
                    .where(TickerScore.compute_date == today_date)
                )
                for row in rows.scalars():
                    scores_cache[row.symbol] = row
            logger.info("global_scan_cycle: loaded %d ticker_scores from cache", len(scores_cache))
        except Exception as e:
            logger.warning("global_scan_cycle: failed to load ticker_scores: %s", e)

        seen_today = _get_global_seen_today()
        pending: list[dict] = []

        high52_raw = _safe_fetch_52week_high()
        low52_raw = _safe_fetch_52week_low()
        vol_raw = _safe_fetch_volume_gainers()
        gainers_df = _safe_fetch_top_gainers()
        losers_df = _safe_fetch_top_losers()
        deals_raw = _safe_fetch_largedeal_snapshot()

        high52_data = _parse_52week_data(high52_raw)
        low52_data = _parse_52week_data(low52_raw)
        vol_data = _parse_volume_gainers(vol_raw)
        deals = _parse_largedeal_snapshot(deals_raw)

        # Pre-fetch deal significance data once for the whole scan
        deal_symbols      = set(deals.keys())
        deal_mkt_caps     = _fetch_deal_market_caps(deal_symbols)
        short_deals_list  = [d for ds in deals.values() for d in ds if d.deal_type == "short"]
        deal_short_px     = _fetch_short_deal_close_prices(short_deals_list)

        processed = 0
        alerts_generated = 0

        for i in range(0, total_symbols, GLOBAL_SCAN_BATCH_SIZE):
            if _shutdown_event.is_set():
                logger.info("global_scan_cycle: shutdown requested, stopping at %d/%d symbols",
                            processed, total_symbols)
                return

            batch = all_symbols[i:i + GLOBAL_SCAN_BATCH_SIZE]
            for symbol in batch:
                processed += 1

                if processed % 200 == 0 or processed == 1:
                    logger.info("global_scan_cycle: progress %d/%d symbols (%.0f%%)",
                                processed, total_symbols, processed / total_symbols * 100)

                try:
                    with _SyncSessionLocal() as db:
                        rows = list(
                            db.execute(
                                select(TickerDaily)
                                .where(TickerDaily.symbol == symbol)
                                .order_by(TickerDaily.date.desc())
                                .limit(10)
                            ).scalars()
                        )
                        su_row = db.execute(
                            select(StockUniverse).where(StockUniverse.symbol == symbol)
                        ).scalar_one_or_none()

                    if not rows or len(rows) < 2:
                        continue

                    rows_asc = list(reversed(rows))
                    latest = rows_asc[-1]
                    prev = rows_asc[-2]

                    up_streak = 0
                    dn_streak = 0
                    for r in reversed(rows_asc):
                        if r.close is None or r.open is None:
                            break
                        if r.close > r.open:
                            if dn_streak > 0:
                                break
                            up_streak += 1
                        elif r.close < r.open:
                            if up_streak > 0:
                                break
                            dn_streak += 1
                        else:
                            break

                    pct_from_52w_high: float | None = None
                    pct_from_52w_low: float | None = None
                    if su_row and su_row.high_52w and su_row.low_52w and latest.close:
                        if su_row.high_52w > 0:
                            pct_from_52w_high = (latest.close - su_row.high_52w) / su_row.high_52w * 100
                        if su_row.low_52w > 0:
                            pct_from_52w_low = (latest.close - su_row.low_52w) / su_row.low_52w * 100

                    alerts: list[tuple[str, str]] = []

                    if latest.rsi_14 is not None:
                        if latest.rsi_14 < rsi_oversold_thr:
                            alerts.append(("rsi_oversold",
                                f"{symbol} RSI oversold: {latest.rsi_14:.1f} < {rsi_oversold_thr}"))
                        elif latest.rsi_14 > rsi_overbought_thr:
                            alerts.append(("rsi_overbought",
                                f"{symbol} RSI overbought: {latest.rsi_14:.1f} > {rsi_overbought_thr}"))

                    if latest.macd_histogram is not None and prev.macd_histogram is not None:
                        if prev.macd_histogram < 0 and latest.macd_histogram >= 0:
                            alerts.append(("macd_bullish_cross",
                                f"{symbol} MACD bullish crossover"))
                        elif prev.macd_histogram > 0 and latest.macd_histogram <= 0:
                            alerts.append(("macd_bearish_cross",
                                f"{symbol} MACD bearish crossover"))

                    if latest.bb_squeeze == "Y":
                        alerts.append(("bb_squeeze_alert",
                            f"{symbol} Bollinger Band squeeze (bb_width={latest.bb_width})"))
                    if latest.close is not None and latest.bb_upper is not None and latest.close > latest.bb_upper:
                        alerts.append(("bb_upper_break",
                            f"{symbol} broke above BB upper"))
                    if latest.close is not None and latest.bb_lower is not None and latest.close < latest.bb_lower:
                        alerts.append(("bb_lower_break",
                            f"{symbol} broke below BB lower"))

                    if (latest.hv_20 is not None and latest.hv_60 is not None
                            and latest.hv_60 > 0
                            and latest.hv_20 > latest.hv_60 * vol_spike_ratio):
                        alerts.append(("volatility_spike",
                            f"{symbol} HV20 > {vol_spike_ratio}x HV60"))
                    if latest.atr_percent is not None and latest.atr_percent > atr_exp_thr:
                        alerts.append(("atr_expansion",
                            f"{symbol} ATR% {latest.atr_percent:.1f}% > {atr_exp_thr}%"))

                    if up_streak >= streak_thr:
                        alerts.append(("streak_up_5d", f"{symbol} up {up_streak} days"))
                    if dn_streak >= streak_thr:
                        alerts.append(("streak_down_5d", f"{symbol} down {dn_streak} days"))

                    if pct_from_52w_high is not None and -near52w_thr <= pct_from_52w_high <= 0:
                        alerts.append(("near_52w_high",
                            f"{symbol} within {near52w_thr}% of 52W high"))
                    if pct_from_52w_low is not None and 0 <= pct_from_52w_low <= near52w_thr:
                        alerts.append(("near_52w_low",
                            f"{symbol} within {near52w_thr}% of 52W low"))

                    # --- Intraday / Weekly / Monthly indicator triggers ---
                    try:
                        from app.models.ticker import TickerIntraday
                        intraday_rows: dict[str, list] = {}
                        with _SyncSessionLocal() as db:
                            for interval in ("1h", "W", "M"):
                                iv_rows = list(
                                    db.execute(
                                        select(TickerIntraday)
                                        .where(TickerIntraday.symbol == symbol)
                                        .where(TickerIntraday.interval == interval)
                                        .where(TickerIntraday.indicators_updated_at.isnot(None))
                                        .order_by(TickerIntraday.timestamp.desc())
                                        .limit(2)
                                    ).scalars()
                                )
                                if iv_rows:
                                    intraday_rows[interval] = list(reversed(iv_rows))

                        for interval, iv_rows in intraday_rows.items():
                            if len(iv_rows) < 1:
                                continue
                            latest_iv = iv_rows[-1]
                            prev_iv = iv_rows[-2] if len(iv_rows) >= 2 else None
                            sfx = f"_{interval}"

                            if latest_iv.rsi_14 is not None:
                                if latest_iv.rsi_14 < rsi_oversold_thr:
                                    alerts.append((f"rsi_oversold{sfx}",
                                        f"{symbol} [{interval}] RSI oversold: {latest_iv.rsi_14:.1f}"))
                                elif latest_iv.rsi_14 > rsi_overbought_thr:
                                    alerts.append((f"rsi_overbought{sfx}",
                                        f"{symbol} [{interval}] RSI overbought: {latest_iv.rsi_14:.1f}"))

                            if prev_iv and latest_iv.macd_histogram is not None and prev_iv.macd_histogram is not None:
                                if prev_iv.macd_histogram < 0 and latest_iv.macd_histogram >= 0:
                                    alerts.append((f"macd_bullish_cross{sfx}",
                                        f"{symbol} [{interval}] MACD bullish crossover"))
                                elif prev_iv.macd_histogram > 0 and latest_iv.macd_histogram <= 0:
                                    alerts.append((f"macd_bearish_cross{sfx}",
                                        f"{symbol} [{interval}] MACD bearish crossover"))

                            if latest_iv.bb_squeeze == "Y":
                                alerts.append((f"bb_squeeze_alert{sfx}",
                                    f"{symbol} [{interval}] BB squeeze"))
                            if latest_iv.close is not None and latest_iv.bb_upper is not None and latest_iv.close > latest_iv.bb_upper:
                                alerts.append((f"bb_upper_break{sfx}",
                                    f"{symbol} [{interval}] close > BB upper"))
                            if latest_iv.close is not None and latest_iv.bb_lower is not None and latest_iv.close < latest_iv.bb_lower:
                                alerts.append((f"bb_lower_break{sfx}",
                                    f"{symbol} [{interval}] close < BB lower"))

                            if interval == "1h" and latest_iv.atr_percent is not None and latest_iv.atr_percent > atr_exp_thr:
                                alerts.append((f"atr_expansion{sfx}",
                                    f"{symbol} [1h] ATR% {latest_iv.atr_percent:.1f}% > {atr_exp_thr}%"))
                    except Exception:
                        logger.debug("global_scan_cycle: intraday eval failed for %s", symbol, exc_info=True)

                    ts = scores_cache.get(symbol)
                    if ts:
                        if ts.momentum_score is not None and ts.momentum_score > momentum_thr:
                            alerts.append(("momentum_surge",
                                f"{symbol} momentum {ts.momentum_score:.1f} > {momentum_thr}"))
                        if ts.return_1w is not None and ts.return_1w > return_1w_thr:
                            alerts.append(("return_1w_spike",
                                f"{symbol} 1w return {ts.return_1w:+.1f}% > {return_1w_thr}%"))

                    if high52_data and symbol in high52_data:
                        row = high52_data[symbol]
                        price = row.get("ltp") or row.get("new52WHL") or "—"
                        alerts.append(("52w_high_breakout", f"{symbol} 52W HIGH @ ₹{price}"))

                    if low52_data and symbol in low52_data:
                        row = low52_data[symbol]
                        price = row.get("ltp") or row.get("new52WHL") or "—"
                        alerts.append(("52w_low_breakout", f"{symbol} 52W LOW @ ₹{price}"))

                    if vol_data and symbol in vol_data:
                        ratio = vol_data[symbol].get("week1volChange", 0)
                        alerts.append(("volume_breakout", f"{symbol} vol {ratio:+.0f}x"))

                    if gainers_df is not None:
                        for row in gainers_df.itertuples():
                            if row.symbol == symbol:
                                pchg = getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0
                                if pchg:
                                    alerts.append(("top_gainer", f"{symbol} +{pchg:.1f}%"))
                                break

                    if losers_df is not None:
                        for row in losers_df.itertuples():
                            if row.symbol == symbol:
                                pchg = getattr(row, "pChange", None) or getattr(row, "perChange", 0) or 0
                                if pchg:
                                    alerts.append(("top_loser", f"{symbol} {pchg:.1f}%"))
                                break

                    if deals and symbol in deals:
                        for deal in deals[symbol]:
                            if not _is_recent(deal.date, DAILY_NOTIFICATION_WINDOW_DAYS):
                                continue
                            is_sig, trade_val_cr = _is_deal_significant(
                                deal, deal_short_px, deal_mkt_caps,
                                deal_sig_pct, deal_abs_cr,
                            )
                            if not is_sig:
                                continue
                            val_str = f" = ₹{trade_val_cr:.1f} Cr" if trade_val_cr > 0 else ""
                            alerts.append((
                                f"{deal.deal_type}_deal",
                                f"{symbol} {deal.deal_type} {deal.qty:,} @ ₹{deal.watp}{val_str}",
                            ))

                    for trigger_type, message in alerts:
                        key = (symbol, trigger_type)
                        if key in seen_today:
                            continue
                        seen_today.add(key)
                        pending.append({
                            "symbol": symbol,
                            "exchange": "NSE",
                            "trigger_type": trigger_type,
                            "message": message,
                            "triggered_at": now,
                            "triggered_date": today_date,
                            "is_read": False,
                        })
                        alerts_generated += 1

                except Exception:
                    logger.exception(f"global_scan_cycle: failed for {symbol}")

            if i + GLOBAL_SCAN_BATCH_SIZE < total_symbols:
                progress = int((processed / total_symbols) * 100)
                update_job_status_sync(
                    "job.global_scan", "running", progress=progress,
                    message=f"Scanning {processed}/{total_symbols} symbols, {alerts_generated} alerts",
                )
                if _sleep_interruptible(GLOBAL_SCAN_DELAY):
                    break

        if pending:
            _bulk_upsert_global_notifications(pending)
            logger.info(
                "global_scan_cycle: processed %d symbols, generated %d alerts, upserted %d",
                processed, alerts_generated, len(pending)
            )
        else:
            logger.info("global_scan_cycle: processed %d symbols, no new alerts", processed)

    except Exception:
        logger.exception("global_scan_cycle: unhandled exception")


def global_scan_worker() -> None:
    """Daemon thread: scans all NSE stocks on cron */30 * * * *."""
    logger.info("global_scan_worker: started")

    if not _is_job_enabled("job.global_scan"):
        logger.info("global_scan_worker: disabled, waiting...")
        update_job_status_sync("job.global_scan", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.global_scan", "idle", progress=0, message="Stopped")
        logger.info("global_scan_worker: stopped")
        return

    # Wait for ticker scores to be ready before first scan
    update_job_status_sync("job.global_scan", "waiting", progress=0, message="Waiting for startup pipeline...")
    if _wait_for_startup_event(_startup_ticker_scores_done, "ticker_scores", "job.global_scan"):
        update_job_status_sync("job.global_scan", "idle", progress=0, message="Stopped")
        logger.info("global_scan_worker: stopped")
        return

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.global_scan"):
            update_job_status_sync("job.global_scan", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
        # Wait for any active data pipeline (daily_update/indicators/scores) to finish
        if _wait_for_pipeline("job.global_scan", "global_scan"):
            break
        update_job_status_sync("job.global_scan", "running", progress=50, message="Scanning all NSE stocks...")
        _global_scan_cycle()
        wait = _report_job_waiting("job.global_scan", "*/30 * * * *")
        if _sleep_interruptible(wait):
            break

    update_job_status_sync("job.global_scan", "idle", progress=0, message="Stopped")
    logger.info("global_scan_worker: stopped")


def stop_all_workers(timeout: float = 35.0) -> None:
    """Signal all workers to stop and wait up to `timeout` seconds for each to exit.
    
    Default timeout is 35 seconds to allow for HTTP requests to complete (max 30s).
    """
    logger.info("stop_all_workers: setting shutdown event")
    _shutdown_event.set()
    for t in _worker_threads:
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning("stop_all_workers: %s did not exit within %.1fs, abandoning", t.name, timeout)
        else:
            logger.info("stop_all_workers: %s exited cleanly", t.name)


async def start_cache_cleanup(interval: float = 600.0) -> asyncio.Task:
    """No-op: cachetools.TTLCache auto-evicts expired entries.
    
    Kept for backward compatibility with existing callers.
    """
    async def _noop() -> None:
        while True:
            await asyncio.sleep(interval)

    task = asyncio.create_task(_noop(), name="cache-cleanup-noop")
    logger.info("Cache cleanup: using cachetools.TTLCache (auto-eviction, no manual cleanup needed)")
    return task


# ---------------------------------------------------------------------------
# Morningstar Fair Value Sync
# ---------------------------------------------------------------------------

_watchlist_sync_lock: asyncio.Lock | None = None
_full_sync_lock: asyncio.Lock | None = None


def _get_watchlist_lock() -> asyncio.Lock:
    global _watchlist_sync_lock
    if _watchlist_sync_lock is None:
        _watchlist_sync_lock = asyncio.Lock()
    return _watchlist_sync_lock


def _get_full_lock() -> asyncio.Lock:
    global _full_sync_lock
    if _full_sync_lock is None:
        _full_sync_lock = asyncio.Lock()
    return _full_sync_lock


async def _batch_update_fair_values(
    symbols: list[str],
    update_morningstar_id: bool = False,
    update_fair_value: bool = True,
    progress_job_key: str | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> tuple[int, int]:
    """Batch update fair values for symbols. Returns (updated, failed)."""
    updated = 0
    failed = 0
    pending: list[tuple] = []
    total = len(symbols)

    async with AsyncSessionLocal() as db:
        for i, symbol in enumerate(symbols, 1):
            try:
                result = await morningstar_client.get_fair_value_by_symbol(symbol)
                fair_value = result.get("fairValue")
                
                if fair_value:
                    values: dict = {
                        "fair_value": fair_value,
                        "fair_value_updated_at": datetime.now(timezone.utc),
                    }
                    if update_morningstar_id:
                        values["morningstar_id"] = result.get("morningstarId")
                    
                    pending.append((values, symbol))
                    updated += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning(f"Failed to fetch fair value for {symbol}: {e}")
                failed += 1

            if len(pending) >= DB_BATCH_SIZE:
                for values, sym in pending:
                    stmt = (
                        update(stockuniverse.StockUniverse)
                        .where(stockuniverse.StockUniverse.symbol == sym)
                        .values(**values)
                    )
                    await db.execute(stmt)
                await db.commit()
                if progress_job_key and total:
                    pct = progress_start + int((i / total) * (progress_end - progress_start))
                    await update_job_status(
                        progress_job_key, "running", progress=pct,
                        message=f"Fetching fair values: {i}/{total}",
                    )
                logger.debug(f"Fair value sync progress: {i}/{total}")
                pending = []

            await asyncio.sleep(REQUEST_DELAY)

        if pending:
            for values, sym in pending:
                stmt = (
                    update(stockuniverse.StockUniverse)
                    .where(stockuniverse.StockUniverse.symbol == sym)
                    .values(**values)
                )
                await db.execute(stmt)
            await db.commit()

    return updated, failed


async def _batch_resolve_morningstar_ids(
    symbols: list[str],
    progress_job_key: str | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> int:
    """Batch resolve Morningstar IDs for symbols. Returns count of resolved IDs."""
    resolved = 0
    pending: list[tuple] = []
    total = len(symbols)

    async with AsyncSessionLocal() as db:
        for i, symbol in enumerate(symbols, 1):
            try:
                ms_id = await morningstar_client.resolve_symbol_to_id(symbol)
                if ms_id:
                    pending.append((ms_id, symbol))
                    resolved += 1
                    logger.debug(f"Resolved {symbol} -> {ms_id}")
            except Exception as e:
                logger.warning(f"Failed to resolve ID for {symbol}: {e}")

            if len(pending) >= DB_BATCH_SIZE:
                for mid, sym in pending:
                    stmt = (
                        update(stockuniverse.StockUniverse)
                        .where(stockuniverse.StockUniverse.symbol == sym)
                        .values(morningstar_id=mid)
                    )
                    await db.execute(stmt)
                await db.commit()
                if progress_job_key and total:
                    pct = progress_start + int((i / total) * (progress_end - progress_start))
                    await update_job_status(
                        progress_job_key, "running", progress=pct,
                        message=f"Resolving Morningstar IDs: {i}/{total}",
                    )
                logger.info(f"ID sync progress: {i}/{total}")
                pending = []

            await asyncio.sleep(REQUEST_DELAY)

        if pending:
            for mid, sym in pending:
                stmt = (
                    update(stockuniverse.StockUniverse)
                    .where(stockuniverse.StockUniverse.symbol == sym)
                    .values(morningstar_id=mid)
                )
                await db.execute(stmt)
            await db.commit()

    return resolved


async def sync_watchlist_fair_values():
    """Fetch fair values for all watchlist stocks every 3 hours."""
    if not _is_job_enabled("job.watchlist_fair_value"):
        logger.info("watchlist_fair_value sync disabled, skipping")
        return
    
    lock = _get_watchlist_lock()
    if lock.locked():
        logger.warning("Watchlist sync already running, skipping this cycle")
        return

    async with lock:
        try:
            logger.info("Starting watchlist fair value sync")
            await update_job_status("job.watchlist_fair_value", "running", progress=0, message="Starting watchlist fair value sync...")

            async with AsyncSessionLocal() as db:
                stmt = select(WatchlistItem.symbol).distinct()
                result = await db.execute(stmt)
                symbols = [row[0] for row in result.fetchall()]

            if not symbols:
                logger.info("No symbols in watchlist to sync")
                await _update_sync_timestamp("last_watchlist_fairvalue_sync")
                await update_job_status("job.watchlist_fair_value", "idle", progress=100, message="No symbols to sync")
                return

            updated, failed = await _batch_update_fair_values(
                symbols,
                progress_job_key="job.watchlist_fair_value",
                progress_start=5,
                progress_end=95,
            )

            logger.info(f"Watchlist fair value sync complete: {updated} updated, {failed} failed")
            await _update_sync_timestamp("last_watchlist_fairvalue_sync")
            await update_job_status("job.watchlist_fair_value", "idle", progress=100, message=f"Completed: {updated} updated, {failed} failed")
        except Exception as e:
            logger.exception("Watchlist fair value sync failed")
            await update_job_status("job.watchlist_fair_value", "failed", error=str(e)[:512])


async def sync_all_fair_values():
    """Fetch fair values for all stocks in stock_universe."""
    if not _is_job_enabled("job.full_fair_value"):
        logger.info("full_fair_value sync disabled, skipping")
        return
    
    lock = _get_full_lock()
    if lock.locked():
        logger.warning("Full sync already running, skipping this cycle")
        return

    async with lock:
        try:
            logger.info("Starting full universe fair value sync")
            await update_job_status("job.full_fair_value", "running", progress=0, message="Starting full fair value sync...")

            async with AsyncSessionLocal() as db:
                stmt = select(stockuniverse.StockUniverse.symbol)
                result = await db.execute(stmt)
                all_symbols = [row[0] for row in result.fetchall()]

            if not all_symbols:
                logger.info("No symbols in stock universe to sync")
                await _update_sync_timestamp("last_full_fairvalue_sync")
                await update_job_status("job.full_fair_value", "idle", progress=100, message="No symbols to sync")
                return

            logger.info("Step 1: Populating missing Morningstar IDs")
            await update_job_status("job.full_fair_value", "running", progress=5, message="Resolving Morningstar IDs...")
            resolved_count = await _batch_resolve_morningstar_ids(
                all_symbols,
                progress_job_key="job.full_fair_value",
                progress_start=5,
                progress_end=45,
            )
            logger.info(f"Step 1 complete: {resolved_count} IDs populated")

            logger.info("Step 2: Fetching fair values")
            await update_job_status("job.full_fair_value", "running", progress=50, message="Fetching fair values...")
            updated, failed = await _batch_update_fair_values(
                all_symbols,
                update_morningstar_id=True,
                progress_job_key="job.full_fair_value",
                progress_start=50,
                progress_end=95,
            )
            
            logger.info(f"Full universe fair value sync complete: {updated} updated, {failed} failed")
            await _update_sync_timestamp("last_full_fairvalue_sync")
            await update_job_status("job.full_fair_value", "idle", progress=100, message=f"Completed: {updated} updated, {failed} failed")
        except Exception as e:
            logger.exception("Full fair value sync failed")
            await update_job_status("job.full_fair_value", "failed", error=str(e)[:512])


async def _update_sync_timestamp(key: str):
    """Update system_config with current timestamp using upsert."""
    async with AsyncSessionLocal() as db:
        stmt = sqlite_insert(SystemConfig).values(
            key=key,
            value=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": stmt.excluded.value,
                "updated_at": stmt.excluded.updated_at,
            }
        )
        await db.execute(stmt)
        await db.commit()


async def _should_trigger_full_sync() -> bool:
    """Check if full sync should run at startup."""
    async with AsyncSessionLocal() as db:
        stmt = select(func.max(stockuniverse.StockUniverse.fair_value_updated_at))
        result = await db.execute(stmt)
        last_update = result.scalar()

        if last_update is None:
            return True

        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if now_naive - last_update > timedelta(hours=24):
            return True

        return False


async def _run_watchlist_scheduler():
    """Run every 3 hours (cron: 0 */3 * * *)."""
    shutdown_event = get_async_shutdown_event()
    while not shutdown_event.is_set():
        await asyncio.sleep(_seconds_until_next_cron("0 */3 * * *"))
        if shutdown_event.is_set():
            break
        await sync_watchlist_fair_values()
    logger.info("watchlist_scheduler: stopped")


async def _run_nightly_scheduler():
    """Run at 8:30 PM UTC daily (cron: 30 20 * * *)."""
    shutdown_event = get_async_shutdown_event()
    while not shutdown_event.is_set():
        await asyncio.sleep(_seconds_until_next_cron("30 20 * * *"))
        if shutdown_event.is_set():
            break
        await sync_all_fair_values()
    logger.info("nightly_scheduler: stopped")

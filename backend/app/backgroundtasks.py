import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, date, timezone
from typing import Any, Optional

import pandas as pd
import pytz
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError as _SAOperationalError

from app.services.nse_client import NSEClient
from app.services import ticker_warehouse
from app.services import indicators
from app.models import stockuniverse
from app.models.ticker import TickerScore
from app.models.watchlist import WatchlistItem
from app.models.news import NewsArticle
from app.models.notification import Notification, GlobalNotification
from app.models.system_config import SystemConfig
from app.models.job import Job
from app.database import _SyncSessionLocal, AsyncSessionLocal, _ThreadAsyncSessionLocal
from app.config import settings
from app.services.news_fetcher import news_fetcher
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
            cron_expression="30 10,14 * * 1-5",
            callable=_ticker_daily_update_sync,
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

        logger.info("stock_universe_sync: complete")
    except Exception:
        logger.exception("stock_universe_sync: unhandled exception; will retry next cycle")


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

    # Check first_run for startup execution
    if _is_first_run("stock_universe"):
        update_job_status_sync("job.stock_universe", "running", progress=0, message="Starting initial sync...")
        _stock_universe_sync()
        _set_first_run_complete("stock_universe")
    else:
        logger.info("stock_universe_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_next_cron("0 0 * * *")
        logger.info("stock_universe_worker: sleeping %.0fs until next cron (0 0 * * *)", wait_secs)
        update_job_status_sync("job.stock_universe", "waiting", progress=100, message=f"Next run in {wait_secs/3600:.1f}h")
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
    """Perform the ticker backfill synchronization."""
    symbols = ticker_warehouse.get_symbols_needing_backfill()
    total = len(symbols)
    if total == 0:
        logger.info("ticker_backfill_sync: no symbols need backfill")
        update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="All symbols up to date")
        return

    logger.info(f"ticker_backfill_sync: {total} symbols need backfill")

    for i, symbol in enumerate(symbols):
        if _shutdown_event.is_set():
            break

        if i % 10 == 0:
            progress = int((i / total) * 100)
            update_job_status_sync(
                "job.ticker_backfill",
                "running",
                progress=progress,
                message=f"Backfilling {symbol} ({i+1}/{total})",
            )

        if i > 0 and i % 50 == 0:
            logger.info(f"ticker_backfill_sync: refreshing session after {i} symbols")
            ticker_warehouse._refresh_nse_session()

        try:
            ticker_warehouse.backfill_symbol(symbol, days=365)
        except Exception as e:
            logger.warning(f"ticker_backfill_sync: failed for {symbol}: {e}")

        time.sleep(ticker_warehouse.REQUEST_DELAY_SECONDS)

    update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="Backfill complete")
    logger.info("ticker_backfill_sync: complete")


def ticker_backfill_worker() -> None:
    """Daemon thread target for ticker backfill. Runs once at startup (if first_run=True), then idles."""
    logger.info("ticker_backfill_worker: started")

    if not _is_job_enabled("job.ticker_backfill"):
        logger.info("ticker_backfill_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_backfill", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
        logger.info("ticker_backfill_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("ticker_backfill"):
        _ticker_backfill_sync()
        _set_first_run_complete("ticker_backfill")
    else:
        logger.info("ticker_backfill_worker: first_run=False, skipping backfill")

    update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="Backfill complete — run-once job")
    logger.info("ticker_backfill_worker: backfill complete, idling until shutdown")

    while not _shutdown_event.is_set():
        _sleep_interruptible(3600)

    update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
    logger.info("ticker_backfill_worker: stopped")


def _ticker_daily_update_sync() -> None:
    """Perform the daily ticker update via bhavcopy.

    Only runs during post-market hours (after 15:30 IST) on trading days.
    Checks for existing data before attempting fetches to avoid redundant calls.
    After candles are inserted, triggers _ticker_indicator_notification_cycle()
    and _ticker_scores_sync() so that indicator-based alerts are evaluated
    on the freshest data.
    """
    import pytz
    from sqlalchemy import func
    from app.models.ticker import TickerDaily

    now_utc = datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

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

    today = date.today()
    date_str = today.strftime("%d-%m-%Y")

    update_job_status_sync("job.ticker_daily_update", "running", progress=10, message="Checking for existing data...")
    with _SyncSessionLocal() as db:
        row = db.query(func.count(TickerDaily.symbol)).filter(TickerDaily.date == today).scalar()
        if row and row > 2000:
            logger.info(f"ticker_daily_update_sync: data already present ({row} symbols), skipping")
            return

    logger.info(f"ticker_daily_update_sync: fetching bhavcopy for {date_str}")
    update_job_status_sync("job.ticker_daily_update", "running", progress=30, message=f"Fetching bhavcopy for {date_str}...")

    try:
        rows = ticker_warehouse.bulk_update_via_bhavcopy(date_str)
        if rows > 0:
            logger.info(f"ticker_daily_update_sync: inserted {rows} rows via bhavcopy")
            update_job_status_sync(
                "job.ticker_daily_update",
                "waiting",
                progress=100,
                message=f"Updated {rows} symbols",
            )
            _ticker_indicator_notification_cycle()
            _ticker_scores_sync()
            return
    except Exception as e:
        logger.warning(f"ticker_daily_update_sync: bhavcopy failed: {e}")

    logger.info("ticker_daily_update_sync: bhavcopy failed, likely NSE holiday, skipping fallback")


def ticker_daily_update_worker() -> None:
    """Daemon thread target for ticker daily updates (cron: 30 10,14 * * 1-5)."""
    logger.info("ticker_daily_update_worker: started")

    if not _is_job_enabled("job.ticker_daily_update"):
        logger.info("ticker_daily_update_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_daily_update", "idle", progress=0, message="Stopped")
        logger.info("ticker_daily_update_worker: stopped")
        return

    # Check first_run for startup execution (will also check market hours inside sync)
    if _is_first_run("ticker_daily_update"):
        update_job_status_sync("job.ticker_daily_update", "running", progress=0, message="Starting daily update...")
        _ticker_daily_update_sync()
        _set_first_run_complete("ticker_daily_update")
    else:
        logger.info("ticker_daily_update_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_next_cron("30 10,14 * * 1-5")
        logger.info("ticker_daily_update_worker: sleeping %.0fs until next cron (30 10,14 * * 1-5)", wait_secs)
        update_job_status_sync("job.ticker_daily_update", "waiting", progress=100, message=f"Next run in {wait_secs/3600:.1f}h")
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_daily_update"):
                update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_daily_update", "running", progress=0, message="Running daily update...")
            _ticker_daily_update_sync()

    update_job_status_sync("job.ticker_daily_update", "idle", progress=0, message="Stopped")
    logger.info("ticker_daily_update_worker: stopped")


def _ticker_indicators_sync() -> None:
    """Startup backfill: compute and store per-candle indicators for symbols that
    have uncomputed or stale indicator data.

    A symbol is considered stale when its latest ticker_daily row has a date
    strictly newer than its indicators_updated_at timestamp (i.e. a new candle
    arrived but indicators haven't been recomputed for the full history yet).

    Processes in batches of 100 with a 1 s inter-batch delay and prints
    progress to stdout.  Triggers _ticker_indicator_notification_cycle() after
    completing.
    """
    from app.models.ticker import TickerDaily

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

    total = len(symbols)
    if total == 0:
        logger.info("ticker_indicators_sync: all symbols already have per-candle indicators")
        update_job_status_sync("job.ticker_indicators", "idle", progress=100, message="All symbols up to date")
        _ticker_indicator_notification_cycle()
        return

    logger.info(f"ticker_indicators_sync: backfilling indicators for {total} symbols")

    BATCH_SIZE = 100
    for i in range(0, total, BATCH_SIZE):
        if _shutdown_event.is_set():
            logger.info("ticker_indicators_sync: shutdown requested, aborting")
            break

        batch = symbols[i:i + BATCH_SIZE]
        for j, symbol in enumerate(batch):
            global_idx = i + j + 1
            print(f"\rticker_indicators_sync: [{global_idx}/{total}] {symbol}   ", end="", flush=True)
            try:
                indicators.compute_indicators_for_all_rows(symbol)
            except Exception as e:
                logger.warning(f"ticker_indicators_sync: failed for {symbol}: {e}")

        progress = int(((i + len(batch)) / total) * 100)
        update_job_status_sync(
            "job.ticker_indicators",
            "running",
            progress=progress,
            message=f"Backfilled {i + len(batch)}/{total} symbols",
        )

        if i + BATCH_SIZE < total:
            if _sleep_interruptible(1.0):
                break

    print()  # newline after in-place progress output
    update_job_status_sync("job.ticker_indicators", "idle", progress=100, message="Indicator backfill complete")
    logger.info("ticker_indicators_sync: complete")

    _ticker_indicator_notification_cycle()


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
                "close": r.close,
                "volume": r.volume,
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

        logger.info("ticker_scores_sync: complete, cached %d symbols", len(results))
        update_job_status_sync("job.ticker_scores", "waiting", progress=100, message=f"Cached {len(results)} symbols")

    except Exception:
        logger.exception("ticker_scores_sync: unhandled exception")


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

    # Check first_run for startup execution
    if _is_first_run("ticker_scores"):
        update_job_status_sync("job.ticker_scores", "running", progress=0, message="Computing ticker scores...")
        _ticker_scores_sync()
        _set_first_run_complete("ticker_scores")
    else:
        logger.info("ticker_scores_worker: first_run=False, skipping startup computation")
        update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_next_cron("0 0 * * *")
        logger.info("ticker_scores_worker: sleeping %.0fs until next cron (0 0 * * *)", wait_secs)
        update_job_status_sync("job.ticker_scores", "waiting", progress=100, message=f"Next run in {wait_secs/3600:.1f}h")
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_scores"):
                update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_scores", "running", progress=0, message="Computing ticker scores...")
            _ticker_scores_sync()

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

    # Check first_run for startup execution
    if _is_first_run("ticker_indicators"):
        update_job_status_sync("job.ticker_indicators", "running", progress=0, message="Starting initial computation...")
        _ticker_indicators_sync()
        _set_first_run_complete("ticker_indicators")
    else:
        logger.info("ticker_indicators_worker: first_run=False, skipping startup computation")
        update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_next_cron("0 11 * * 1-5")
        logger.info("ticker_indicators_worker: sleeping %.0fs until next cron (0 11 * * 1-5)", wait_secs)
        update_job_status_sync("job.ticker_indicators", "waiting", progress=100, message=f"Next run in {wait_secs/3600:.1f}h")
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_indicators"):
                update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_indicators", "running", progress=0, message="Computing indicators...")
            _ticker_indicators_sync()

    update_job_status_sync("job.ticker_indicators", "idle", progress=0, message="Stopped")
    logger.info("ticker_indicators_worker: stopped")


NEWS_CRON = "*/5 * * * *"
NEWS_CRAWL_MAX_INTERVAL = 30 * 60


async def _crawl_news_async(pages: int) -> int:
    """Async helper: crawl and store news using AsyncSession.

    Uses _ThreadAsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread, so it must not share the main
    StaticPool connection.
    """
    async with _ThreadAsyncSessionLocal() as session:
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
        update_job_status_sync("job.news", "waiting", progress=0, message=f"Next run in {current_interval:.0f}s")
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


WATCHLIST_NEWS_STALE_SECONDS = 5 * 60


async def _fetch_company_news_async(symbol: str) -> int:
    """Async helper: fetch company news using AsyncSession.

    Uses _ThreadAsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread, so it must not share the main
    StaticPool connection.

    Note: We can't easily cancel HTTP requests mid-flight, but we can at least
    check for shutdown between symbols in the caller.
    """
    try:
        async with _ThreadAsyncSessionLocal() as session:
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
        update_job_status_sync("job.watchlist_news", "running", progress=0, message="Starting initial fetch...")
        _watchlist_news_sync()
        _set_first_run_complete("watchlist_news")
    else:
        logger.info("watchlist_news_worker: first_run=False, skipping startup fetch")
        update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_next_cron("*/5 * * * *")
        update_job_status_sync("job.watchlist_news", "waiting", progress=0, message=f"Next run in {wait_secs:.0f}s")
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
    import pytz

    now_utc = datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

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
    import pytz

    now_utc = datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

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

    Uses _ThreadAsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread, so it must not share the main
    StaticPool connection.
    """
    async with _ThreadAsyncSessionLocal() as session:
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
        update_job_status_sync("job.market_data", "running", progress=0, message="Starting initial sync...")
        _market_data_sync()
        _set_first_run_complete("market_data")
    else:
        logger.info("market_data_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.market_data", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        if _is_market_open():
            wait = _seconds_until_next_cron("*/5 * * * *")
            logger.info("market_data_worker: market is open, next run in %.0f s", wait)
            update_job_status_sync("job.market_data", "waiting", progress=100, message=f"Market open, next run in {wait:.0f}s")
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

    # Small startup delay so the main app event loop is stable
    _sleep_interruptible(15)

    # Check first_run for startup execution
    if _is_first_run("results_calendar"):
        update_job_status_sync("job.results_calendar", "running", progress=0, message="Starting initial sync...")
        _results_calendar_sync()
        _set_first_run_complete("results_calendar")
    else:
        logger.info("results_calendar_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_next_cron(_RESULTS_CALENDAR_CRON)
        logger.info(
            "results_calendar_worker: sleeping %.0f s until next cron (%s)",
            wait_secs, _RESULTS_CALENDAR_CRON,
        )
        update_job_status_sync(
            "job.results_calendar", "waiting", progress=100,
            message=f"Next run in {wait_secs / 3600:.1f}h",
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

    Order matters — later workers depend on data produced by earlier ones:
      1. ticker_backfill_worker    — ensures candle history exists (run-once)
      2. stock_universe_worker     — populates symbol metadata
      3. ticker_indicators_worker  — backfills indicators after candles exist
      4. ticker_scores_worker      — needs indicators up to date
      5. ticker_daily_update_worker — ongoing daily candle + score refresh
      6. market_data_worker        — live sector/industry data (market-hours)
      7. global_scan_worker        — needs ticker_scores populated
      8. watchlist_notification_worker — needs market data + indicators
      9. news_worker               — independent; crawls global news
      10. watchlist_news_worker     — independent; per-symbol news
      11. results_calendar_worker  — upcoming board meeting results alerts
    """
    reset_async_shutdown_event()
    register_all_jobs()
    await sync_all_jobs_to_db()

    targets = [
        ticker_backfill_worker,        # 1 — candle history first
        stock_universe_worker,         # 2 — symbol metadata
        ticker_indicators_worker,      # 3 — indicator backfill
        ticker_scores_worker,          # 4 — momentum scores
        ticker_daily_update_worker,    # 5 — daily bhavcopy + refresh
        market_data_worker,            # 6 — live market data
        global_scan_worker,            # 7 — full-universe scan
        watchlist_notification_worker, # 8 — watchlist alerts
        news_worker,                   # 9 — global news
        watchlist_news_worker,         # 10 — per-symbol news
        results_calendar_worker,       # 11 — upcoming results alerts
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
                "pChange": item.get("pChange"),
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
                "pChange": item.get("pChange"),
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
    """Hard-delete read notifications older than CLEANUP_READ_AFTER_DAYS.

    Runs at most once per CLEANUP_INTERVAL to avoid unnecessary DB writes.
    """
    global _cleanup_last_run
    now = datetime.now()
    if _cleanup_last_run is not None and (now - _cleanup_last_run).total_seconds() < CLEANUP_INTERVAL:
        return

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
        with _SyncSessionLocal() as db:
            for symbol, d in pairs:
                close = db.execute(
                    select(TickerDaily.close)
                    .where(TickerDaily.symbol == symbol, TickerDaily.date == d)
                    .limit(1)
                ).scalar_one_or_none()
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
    """
    from app.models.ticker import TickerDaily
    from app.models.stockuniverse import StockUniverse
    from app.services import returns as returns_service
    from app.services import momentum as momentum_service

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

                # --- returns and momentum (service calls) ---
                returns = returns_service.get_returns(symbol)
                return_1w = returns.get("1w") if returns else None

                momentum_data  = momentum_service.get_momentum_score(symbol)
                momentum_score = momentum_data.get("score") if momentum_data else None

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

                    # Momentum / returns
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
    if gainers_df is not None:
        for row in gainers_df.itertuples():
            if row.symbol == symbol:
                pchg = getattr(row, "pChange", 0) or 0
                alerts.append(("top_gainer", f"{symbol} among TOP GAINERS ({pchg:+.1f}%)"))
                break
    
    if losers_df is not None:
        for row in losers_df.itertuples():
            if row.symbol == symbol:
                pchg = getattr(row, "pChange", 0) or 0
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

    update_job_status_sync("job.notifications", "running", progress=0, message="Starting...")
    _sleep_interruptible(30)  # wait for app startup before first cycle

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.notifications"):
            update_job_status_sync("job.notifications", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
        if _is_market_open():
            update_job_status_sync("job.notifications", "running", progress=50, message="Checking market events...")
            _notification_cycle_full()
            wait = _seconds_until_next_cron("*/5 * * * *")
            update_job_status_sync("job.notifications", "waiting", progress=100, message=f"Next run in {wait:.0f}s")
            _sleep_interruptible(wait)
        else:
            update_job_status_sync("job.notifications", "waiting", progress=0, message="Market closed, checking after-hours...")
            _notification_cycle_reduced()
            wait = _seconds_until_next_cron("*/30 * * * *")
            update_job_status_sync("job.notifications", "waiting", progress=100, message=f"After-hours, next run in {wait:.0f}s")
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
                                pchg = getattr(row, "pChange", 0) or 0
                                alerts.append(("top_gainer", f"{symbol} +{pchg:.1f}%"))
                                break

                    if losers_df is not None:
                        for row in losers_df.itertuples():
                            if row.symbol == symbol:
                                pchg = getattr(row, "pChange", 0) or 0
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

    update_job_status_sync("job.global_scan", "running", progress=0, message="Starting...")
    _sleep_interruptible(60)  # allow other workers to initialise before first scan

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.global_scan"):
            update_job_status_sync("job.global_scan", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
        update_job_status_sync("job.global_scan", "running", progress=50, message="Scanning all NSE stocks...")
        _global_scan_cycle()
        wait = _seconds_until_next_cron("*/30 * * * *")
        update_job_status_sync("job.global_scan", "waiting", progress=100, message=f"Next scan in {wait:.0f}s")
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

        now_naive = datetime.utcnow()
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

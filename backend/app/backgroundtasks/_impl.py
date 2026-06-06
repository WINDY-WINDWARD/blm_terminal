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


# Re-exports from _runtime (audit C.1, A.10).  Worker modules do
# `from app.backgroundtasks import _impl as _bg_impl` and read
# `_bg_impl._shutdown_event` etc. — re-exporting here keeps the
# worker body unchanged after A.10's split.  The canonical home
# for these helpers is ``app.backgroundtasks._runtime``; the shim
# re-exports from there directly.
from app.backgroundtasks._runtime import (  # noqa: E402,F401
    _shutdown_event,
    _worker_threads,
    _startup_stock_universe_done,
    _startup_ticker_backfill_done,
    _startup_ticker_indicators_done,
    _startup_ticker_scores_done,
    _startup_ticker_hourly_done,
    _pipeline_lock,
    _pipeline_idle,
    _is_job_enabled,
    _wait_for_startup_event,
    _wait_for_pipeline,
    get_async_shutdown_event,
    reset_async_shutdown_event,
    set_async_shutdown_event,
    _is_first_run,
    _set_first_run_complete,
    _sleep_interruptible,
    _run_async,
    _seconds_until_next_cron,
    _report_job_waiting,
)


def register_all_jobs() -> None:
    """Register all background jobs with the job registry."""
    # Lazy imports for symbols that moved to app.workers.* in Phase C.1.
    # Top-level import would create a circular reference
    # (workers.* → _impl).  These are only used inside JobDefinition
    # callables, so the cost is negligible.
    from app.workers.maintenance import VACUUM_CRON, _run_vacuum

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
# Phase C: weekly SQLite VACUUM worker
# ---------------------------------------------------------------------------
# SQLite stores data in pages; DELETE leaves free pages in the file until
# VACUUM rebuilds the file.  News/intraday retention deletes thousands of
# rows each week; running VACUUM once a week (Sunday 04:00) reclaims space
# without adding meaningful write overhead.  This is a single-threaded
# rebuild — takes 5-15 min on a 1-2GB DB.


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


# ─── Re-exports from split submodules (audit C.1) ────────────────────────
#
# Each of these was moved out of this file to a dedicated submodule
# (e.g. ``app/services/data_sync/universe.py``).  The re-exports here
# keep the package-level import path working and preserve
# ``is``-identity for tests that pin the move.  See
# ``tests/test_data_sync_universe.py`` etc. for the contract.
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
# NOTE: ``vacuum_worker`` is re-exported from ``app.backgroundtasks``
# via a direct import in its __init__.py (NOT through ``_impl``),
# to avoid a circular import where ``_impl.py`` triggers
# ``app.workers.maintenance`` which triggers ``app.workers.__init__``
# which tries to import from ``app.backgroundtasks`` (mid-init).

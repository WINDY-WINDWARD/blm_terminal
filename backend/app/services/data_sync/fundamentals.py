"""Screener fundamentals backfill — market cap fallback + quarterly net-profit YoY.

Market cap primarily comes from the NSE universe sync (tradeInfo.totalMarketCap
stored as ``StockUniverse.market_cap_cr``); this worker fills the gaps from
screener.in (the same source the Fundamentals widget already uses on demand)
and is the sole source of quarterly net-profit YoY for the Analysis widget's
Earn % / NP YoY columns.

Design (polite + resumable, screener.in is throttled and login-walled):
- Each invocation runs a loop of up to ``MAX_BATCHES_PER_RUN`` batches of
  ``batch_limit`` symbols missing market cap (from every source) or
  net-profit YoY, resuming from a ``SyncState`` cursor
  (``task_name = "fundamentals"``) so-краsh restarts and nightly runs make
  steady progress across the ~2500-symbol universe instead of hammering
  screener.in. One quiet-period run can therefore cover the whole universe.
- After each batch the loop consults ``_system_is_quiet()`` (in-memory
  write-queue telemetry only — zero SQL): quiet → next batch immediately;
  busy → interruptible 5-minute backoff, then recheck. The 20-min
  market_data rebuilds and news/universe write storms simply pause the
  backfill; the cursor is persisted per batch so resume is exact.
- A run also stops on: candidates exhausted (cursor reset for wrap-around),
  10 consecutive failures, ``max_batches`` reached, an overall runtime cap,
  or app shutdown (clean exit between batches).
- ``ScreenerClient.get_company`` already applies a 24h persistent cache and
  the shared screener throttle; an extra 1s politeness sleep is added here.
- Writes go through the serial write queue (``PRIO_BULK_DATA``) into
  ``ticker_screener_snapshot.market_cap`` and ``market_category_stocks``
  (market_cap / net_profit / net_profit_yoy). ``market_local`` picks the
  values up on its next aggregation and fills the widget columns.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

TASK_NAME = "fundamentals"
POLITENESS_SLEEP_S = 1.0
MAX_CONSECUTIVE_FAILURES = 10
# Loop-until-caught-up caps: one constant each (see plan tradeoff note).
MAX_BATCHES_PER_RUN = 10
BUSY_BACKOFF_S = 300.0
MAX_RUN_SECONDS = 45 * 60
# Load-gate thresholds (read from write-queue telemetry, never from SQLite).
GATE_MAX_OCCUPANCY_PCT = 30.0
GATE_MAX_P95_LATENCY_MS = 1000.0
GATE_MAX_QUEUE_WAIT_MS = 2000.0

_MONTH_TO_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_mcap_cr(value: str | None) -> float | None:
    """Parse a screener market-cap string ("8,13,988 Cr.", "56.7 Cr") to Rs Cr float."""
    if not value:
        return None
    cleaned = (
        value.replace("₹", "").replace(",", "").replace("%", "")
        .replace("Cr.", "").replace("Cr", "").strip()
    )
    try:
        result = float(cleaned)
    except ValueError:
        return None
    return result if result > 0 else None


def _parse_num(value: str | None) -> float | None:
    """Parse a screener quarterly cell ("1,234", "-", "") to float."""
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    if cleaned in ("", "-", "--"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def compute_np_yoy(all_quarters: dict[str, dict[str, dict[str, str | None]]]) -> tuple[float | None, float | None]:
    """Compute latest-quarter net profit and its year-ago % change.

    ``all_quarters`` is the ``_parse_all_quarters`` shape (year → month →
    {metric: value}). Discrete quarter periods are sorted chronologically;
    TTM columns are ignored. Returns (latest_net_profit, yoy_pct) where
    yoy compares the latest quarter against the same quarter a year earlier
    (4 quarters back). Either element may be None when data is missing.
    """
    points: list[tuple[int, int, float]] = []
    for year_key, months in (all_quarters or {}).items():
        try:
            year = int(str(year_key).strip().split()[0])
        except (ValueError, IndexError):
            continue
        if not isinstance(months, dict):
            continue
        for month_key, metrics in months.items():
            if not isinstance(metrics, dict):
                continue
            tokens = str(month_key).strip().split()
            month = _MONTH_TO_NUM.get(tokens[0].lower()[:3]) if tokens else None
            if month is None:
                continue
            # Skip TTM rollups — only discrete quarters (month_key "Mar TTM").
            if any(t.upper() == "TTM" for t in tokens[1:]):
                continue
            np_val = None
            for metric_key in ("Net Profit", "Net Profit +", "Net Profit/Loss"):
                if metric_key in metrics:
                    np_val = _parse_num(metrics.get(metric_key))
                    if np_val is not None:
                        break
            if np_val is None:
                # Fall back to any metric whose label starts with Net Profit
                for k, v in metrics.items():
                    if str(k).startswith("Net Profit"):
                        np_val = _parse_num(v)
                        if np_val is not None:
                            break
            if np_val is not None:
                points.append((year, month, np_val))

    if not points:
        return None, None
    points.sort()
    latest_np = points[-1][2]
    yoy: float | None = None
    if len(points) >= 5:
        year_ago_np = points[-5][2]
        if year_ago_np:
            yoy = ((latest_np - year_ago_np) / abs(year_ago_np)) * 100
    return latest_np, yoy


async def _read_cursor(session) -> str | None:
    from app.models.sync_state import SyncState

    row = (
        await session.execute(
            select(SyncState.last_symbol).where(SyncState.task_name == TASK_NAME)
        )
    ).scalar_one_or_none()
    return row


async def _write_cursor_async(session, last_symbol: str | None) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.models.sync_state import SyncState

    stmt = sqlite_insert(SyncState).values(
        task_name=TASK_NAME, last_symbol=last_symbol
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["task_name"],
        set_={"last_symbol": stmt.excluded.last_symbol},
    )
    await session.execute(stmt)
    await session.commit()


def _system_is_quiet() -> bool:
    """Load gate: True when the DB writer pipeline is quiet enough for more work.

    Reads only in-memory write-queue telemetry (trylock-guarded snapshot +
    metrics rings) — the gate itself never touches SQLite, so calling it
    between batches costs nothing. Fail-open (True) when telemetry is
    unavailable: a single batch is always allowed, matching pre-loop behavior.
    """
    try:
        from app.services.write_queue import (
            _aggregate_metrics,
            _peek_queue_snapshot,
            _writer_thread,
        )
    except Exception:
        logger.debug("fundamentals_sync: telemetry unavailable — gate fail-open")
        return True
    try:
        if _writer_thread is None or not _writer_thread.is_alive():
            return False
        snap = _peek_queue_snapshot()
        if snap.get("occupancy_pct", 0.0) >= GATE_MAX_OCCUPANCY_PCT:
            return False
        metrics = _aggregate_metrics()
        if metrics.get("p95_latency_ms", 0.0) >= GATE_MAX_P95_LATENCY_MS:
            return False
        if metrics.get("avg_queue_wait_ms", 0.0) >= GATE_MAX_QUEUE_WAIT_MS:
            return False
        return True
    except Exception:
        logger.debug("fundamentals_sync: gate check failed — fail-open", exc_info=True)
        return True


async def _async_sleep_interruptible(seconds: float) -> None:
    """Sleep in 5s slices, waking early when the app shuts down."""
    from app.backgroundtasks._runtime import _shutdown_event

    deadline = time.monotonic() + seconds
    while True:
        if _shutdown_event.is_set():
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(5.0, remaining))


def _candidate_filter(StockUniverse, TickerScreenerSnapshot, MarketCategoryStock):
    """WHERE clause shared by the candidate select and the progress COUNT."""
    return (
        (
            (StockUniverse.market_cap_cr.is_(None))
            & (TickerScreenerSnapshot.market_cap.is_(None))
        )
        | (MarketCategoryStock.net_profit_yoy.is_(None))
    )


async def _count_candidates() -> int:
    """Cheap COUNT of symbols still needing fundamentals (for batch k/N progress)."""
    from app.database import AsyncSessionLocal
    from app.models.marketcategory import MarketCategoryStock
    from app.models.stockuniverse import StockUniverse
    from app.models.ticker import TickerScreenerSnapshot

    async with AsyncSessionLocal() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(StockUniverse)
                .outerjoin(
                    TickerScreenerSnapshot,
                    TickerScreenerSnapshot.symbol == StockUniverse.symbol,
                )
                .outerjoin(
                    MarketCategoryStock,
                    MarketCategoryStock.symbol == StockUniverse.symbol,
                )
                .where(
                    _candidate_filter(
                        StockUniverse, TickerScreenerSnapshot, MarketCategoryStock
                    )
                )
            )
        ).scalar_one()
        return int(total or 0)


async def _run_fundamentals_batch(
    batch_limit: int, after_cursor: str | None
) -> dict[str, Any]:
    """Process a single batch of candidates after ``after_cursor``.

    Returns stats plus ``last_symbol`` (resume cursor), ``exhausted`` (no
    candidates left — caller should reset the cursor for wrap-around) and
    ``aborted`` (10 consecutive failures — caller should stop the run).
    Assumes the screener client is already initialised. Cursor persistence is
    handled by ``_store_enriched_chunks`` (finally-guaranteed).
    """
    from app.database import AsyncSessionLocal
    from app.models.stockuniverse import StockUniverse
    from app.models.ticker import TickerScreenerSnapshot
    from app.services.screener_client import _parse_all_quarters, screener_client
    from app.models.marketcategory import MarketCategoryStock

    stats: dict[str, Any] = {
        "processed": 0,
        "enriched": 0,
        "skipped": 0,
        "failed": 0,
        "last_symbol": after_cursor,
        "exhausted": False,
        "aborted": False,
    }

    async with AsyncSessionLocal() as session:
        stmt = (
            select(StockUniverse.symbol)
            .outerjoin(
                TickerScreenerSnapshot,
                TickerScreenerSnapshot.symbol == StockUniverse.symbol,
            )
            .outerjoin(
                MarketCategoryStock,
                MarketCategoryStock.symbol == StockUniverse.symbol,
            )
            .where(
                _candidate_filter(
                    StockUniverse, TickerScreenerSnapshot, MarketCategoryStock
                )
            )
            .order_by(StockUniverse.symbol)
        )
        if after_cursor:
            stmt = stmt.where(StockUniverse.symbol > after_cursor)
        symbols = [r[0] for r in (await session.execute(stmt.limit(batch_limit))).all()]

    if not symbols:
        stats["exhausted"] = True
        return stats

    enriched: list[dict[str, Any]] = []
    consecutive_failures = 0
    last_symbol: str | None = after_cursor

    for idx, symbol in enumerate(symbols, 1):
        try:
            company = await screener_client.get_company(symbol)
            ratios = company.get("ratios", {}) or {}
            mcap = parse_mcap_cr(ratios.get("market_cap"))

            np_latest: float | None = None
            np_yoy: float | None = None
            try:
                html = await screener_client.get_company_html(symbol)
                from bs4 import BeautifulSoup

                all_q = _parse_all_quarters(BeautifulSoup(html, "lxml"))
                np_latest, np_yoy = compute_np_yoy(all_q)
            except Exception:
                logger.debug("fundamentals_sync: quarterly parse failed for %s", symbol, exc_info=True)

            if mcap is not None or np_yoy is not None or np_latest is not None:
                enriched.append({
                    "symbol": symbol,
                    "market_cap": mcap,
                    "net_profit": np_latest,
                    "net_profit_yoy": np_yoy,
                })
                stats["enriched"] += 1
            else:
                stats["skipped"] += 1
            consecutive_failures = 0
        except Exception as exc:
            stats["failed"] += 1
            consecutive_failures += 1
            logger.debug("fundamentals_sync: %s failed: %s", symbol, exc)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning(
                    "fundamentals_sync: %d consecutive failures — aborting run "
                    "(likely login wall / outage), cursor kept at %s",
                    consecutive_failures, last_symbol,
                )
                stats["aborted"] = True
                break
        finally:
            stats["processed"] += 1
            last_symbol = symbol

        if idx % 10 == 0:
            logger.info("fundamentals_sync: %d/%d symbols processed", idx, len(symbols))
        await asyncio.sleep(POLITENESS_SLEEP_S)

    from app.database import AsyncSessionLocal as _AsyncSessionLocal

    await _store_enriched_chunks(enriched, after_cursor, _AsyncSessionLocal)
    stats["last_symbol"] = last_symbol
    return stats


async def _fundamentals_sync_async(
    batch_limit: int = 120,
    max_batches: int = MAX_BATCHES_PER_RUN,
    run_timeout_s: float = MAX_RUN_SECONDS,
) -> dict[str, int]:
    """Loop-until-caught-up driver: chain batches while quiet, back off while busy."""
    from app.backgroundtasks._runtime import _shutdown_event
    from app.database import AsyncSessionLocal
    from app.services.screener_client import screener_client

    def _report(status: str, progress: int | None, message: str) -> None:
        try:
            from app.jobs.runner import update_job_status_sync

            update_job_status_sync(
                "job.fundamentals", status, progress=progress, message=message
            )
        except Exception:
            pass

    total = {"processed": 0, "enriched": 0, "skipped": 0, "failed": 0}

    total_candidates = await _count_candidates()
    if total_candidates == 0:
        logger.info("fundamentals_sync: no symbols missing fundamentals — nothing to do")
        _report("idle", 100, "All symbols enriched — nothing to do")
        return total
    batches_total = max(1, -(-total_candidates // batch_limit))  # ceil div

    try:
        await screener_client.init()
    except Exception as exc:
        logger.warning("fundamentals_sync: screener client init failed: %s", exc)
        return total

    async with AsyncSessionLocal() as session:
        cursor = await _read_cursor(session)

    started = time.monotonic()
    for batch_no in range(1, max_batches + 1):
        if _shutdown_event.is_set():
            logger.info("fundamentals_sync: shutdown requested — exiting loop")
            break
        if time.monotonic() - started >= run_timeout_s:
            logger.info(
                "fundamentals_sync: runtime cap reached after %d batches", batch_no - 1
            )
            break
        if batch_no > 1:
            while not _system_is_quiet():
                if _shutdown_event.is_set():
                    break
                if time.monotonic() - started >= run_timeout_s:
                    break
                logger.info(
                    "fundamentals_sync: system busy — backing off %ds "
                    "(batch %d/%d, cursor %s)",
                    int(BUSY_BACKOFF_S), batch_no, batches_total, cursor,
                )
                _report(
                    "running",
                    int(100 * (batch_no - 1) / batches_total),
                    f"Waiting for quiet DB (batch {batch_no}/{batches_total})...",
                )
                await _async_sleep_interruptible(BUSY_BACKOFF_S)
            if _shutdown_event.is_set() or time.monotonic() - started >= run_timeout_s:
                break

        logger.info(
            "fundamentals_sync: batch %d/%d (cursor %s)",
            batch_no, batches_total, cursor,
        )
        res = await _run_fundamentals_batch(batch_limit, cursor)
        for key in ("processed", "enriched", "skipped", "failed"):
            total[key] += int(res.get(key, 0) or 0)
        cursor = res.get("last_symbol")

        if res.get("exhausted"):
            # End of universe — reset cursor so the next run wraps around
            # and refreshes values from the top.
            try:
                async with AsyncSessionLocal() as session:
                    await _write_cursor_async(session, None)
            except Exception:
                logger.debug("fundamentals_sync: cursor reset failed", exc_info=True)
            logger.info("fundamentals_sync: universe exhausted — cursor reset")
            break
        _report(
            "running",
            int(100 * batch_no / batches_total),
            f"Batch {batch_no}/{batches_total}: enriched {total['enriched']}/{total['processed']} symbols",
        )
        if res.get("aborted"):
            break

    _report(
        "idle", 100,
        f"Enriched {total['enriched']}/{total['processed']} symbols",
    )
    logger.info(
        "fundamentals_sync: done — processed=%d enriched=%d skipped=%d failed=%d cursor=%s",
        total["processed"], total["enriched"], total["skipped"], total["failed"], cursor,
    )
    return total


def _store_fundamentals_rows(rows: list[dict[str, Any]]) -> None:
    """Persist one chunk of enriched fundamentals (runs on the writer thread)."""
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.database import _SyncSessionLocal
    from app.models.marketcategory import MarketCategoryStock
    from app.models.ticker import TickerScreenerSnapshot as _Snap

    from sqlalchemy import update as sa_update

    with _SyncSessionLocal() as session:
        for row in rows:
            if row["market_cap"] is not None:
                # UPDATE only — never insert stub snapshot rows (a
                # stub last_close=0 would corrupt screener consumers).
                session.execute(
                    sa_update(_Snap)
                    .where(_Snap.symbol == row["symbol"])
                    .values(market_cap=row["market_cap"])
                )
            stmt2 = sqlite_insert(MarketCategoryStock).values(
                symbol=row["symbol"],
                company_name=row["symbol"],
                categories=[],
                market_cap=row["market_cap"],
                net_profit=row["net_profit"],
                net_profit_yoy=row["net_profit_yoy"],
                last_updated=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            stmt2 = stmt2.on_conflict_do_update(
                index_elements=["symbol"],
                set_={
                    "market_cap": stmt2.excluded.market_cap,
                    "net_profit": stmt2.excluded.net_profit,
                    "net_profit_yoy": stmt2.excluded.net_profit_yoy,
                },
            )
            session.execute(stmt2)
        session.commit()


async def _store_enriched_chunks(
    enriched: list[dict[str, Any]],
    start_cursor: str | None,
    session_factory,
) -> str | None:
    """Store enriched rows in 50-row chunks and persist the resume cursor.

    Each chunk is isolated: a slow/locked writer (TimeoutError) fails just
    that chunk instead of aborting the whole batch (120s timeout per chunk —
    the writer thread is shared with universe/news/market syncs and can
    backlog). Returns the last successfully written symbol (or the incoming
    cursor when nothing was stored). The cursor persist lives in ``finally``
    so partial failures never lose completed progress; failed chunks keep
    NULL metrics and stay candidates for the next run / wrap-around.
    """
    from app.services.write_queue import enqueue_write_sync, PRIO_BULK_DATA

    last_written: str | None = start_cursor
    chunks = [enriched[i:i + 50] for i in range(0, len(enriched), 50)]
    try:
        for chunk in chunks:
            try:
                enqueue_write_sync(
                    PRIO_BULK_DATA, _store_fundamentals_rows, chunk, timeout=120.0
                )
                last_written = chunk[-1]["symbol"]
            except Exception:
                logger.warning(
                    "fundamentals_sync: chunk ending at %s failed — "
                    "continuing with remaining %d chunks",
                    chunk[-1]["symbol"], len(chunks), exc_info=True,
                )
    finally:
        try:
            async with session_factory() as session:
                await _write_cursor_async(session, last_written)
        except Exception:
            logger.debug("fundamentals_sync: cursor persist failed", exc_info=True)
    return last_written


def _fundamentals_sync(batch_limit: int = 120) -> None:
    """Sync wrapper (worker-thread context): screener fundamentals backfill."""
    from app.backgroundtasks._runtime import _run_async
    from app.jobs.runner import update_job_status_sync

    try:
        logger.info("fundamentals_sync: starting (batch_limit=%d)", batch_limit)
        update_job_status_sync("job.fundamentals", "running", progress=0,
                               message="Enriching fundamentals from screener.in...")
        _run_async(_fundamentals_sync_async(batch_limit))
        logger.info("fundamentals_sync: complete")
    except Exception:
        logger.exception("fundamentals_sync: unhandled exception; will retry next cycle")

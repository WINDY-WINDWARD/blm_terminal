"""Ticker intraday sync cores (audit C.1, A.5, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public functions:
- ``_ticker_intraday_update_sync()`` — backfill 1h/W/M intraday
  candles in batches of 10, supporting watchlist or full-universe
  scope, and a "smart" mode that only refreshes stale symbols.
- ``_ticker_intraday_hourly_stale_check_sync()`` — find
  watchlist symbols whose last 1h candle is older than the
  expected slot for the current/last session, backfill them, and
  recompute intraday indicators.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time
from time import sleep
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select


logger = logging.getLogger(__name__)


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
    from app.backgroundtasks._runtime import _shutdown_event
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

        sleep(1.0)

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
    from app.backgroundtasks._runtime import _shutdown_event
    from app.database import _SyncSessionLocal
    from app.jobs.runner import update_job_status_sync
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
        rows = db.execute(
            select(
                TickerIntraday.symbol,
                func.max(TickerIntraday.timestamp).label("max_ts"),
            )
            .where(
                TickerIntraday.symbol.in_(symbols),
                TickerIntraday.interval == "1h",
                func.date(TickerIntraday.timestamp) == target_date.isoformat(),
            )
            .group_by(TickerIntraday.symbol)
        ).all()
        max_ts_by_sym = {row.symbol: row.max_ts for row in rows}
        stale_symbols = [
            sym
            for sym in symbols
            if max_ts_by_sym.get(sym) is None or max_ts_by_sym[sym] < expected_latest
        ]

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
        sleep(1.0)

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

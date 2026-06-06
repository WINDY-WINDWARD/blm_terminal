"""Ticker daily update sync core (audit C.1, A.6).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public function:
- ``_ticker_daily_update_sync()`` — post-market bhavcopy fetch
  for the last 5 weekdays (gap-safe: re-fetches any date with
  insufficient rows even if newer dates have data).  After
  bhavcopy, patches any still-stale watchlist symbols via the
  equity_history fallback.  On successful inserts, triggers
  ``_ticker_indicator_notification_cycle()`` and
  ``_ticker_scores_sync()`` so indicator-based alerts are
  evaluated on the freshest data.

NOTE: We import ``logger``, ``settings``, ``ticker_warehouse``,
``update_job_status_sync``, ``_SyncSessionLocal``, and the two
downstream sync functions lazily inside the function body to
avoid a circular import: ``app.backgroundtasks._impl`` re-exports
us at the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from time import sleep
from zoneinfo import ZoneInfo

from sqlalchemy import select


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
    from app.backgroundtasks import _impl as _bg_impl
    from app.models.ticker import TickerDaily
    from app.models.watchlist import WatchlistItem

    logger = _bg_impl.logger
    settings = _bg_impl.settings
    ticker_warehouse = _bg_impl.ticker_warehouse
    update_job_status_sync = _bg_impl.update_job_status_sync
    _SyncSessionLocal = _bg_impl._SyncSessionLocal
    _ticker_indicator_notification_cycle = _bg_impl._ticker_indicator_notification_cycle
    _ticker_scores_sync = _bg_impl._ticker_scores_sync

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
                    sleep(0.5)

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

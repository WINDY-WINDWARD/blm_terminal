"""Ticker indicator sync cores (audit C.1, A.8).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public functions:
- ``_ticker_indicators_sync()`` — startup backfill: compute
  and store per-candle indicators (RSI/MACD/BB/ATR/VWMA/HV/Sharpe)
  for daily candles on symbols with null or stale
  ``indicators_updated_at``.  Triggers
  ``_ticker_indicator_notification_cycle()`` after.
- ``_ticker_intraday_indicators_sync()`` — same but for
  intraday candles (1h/W/M).  Triggers
  ``_ticker_intraday_indicator_notification_cycle()`` after.

NOTE: We import ``logger``, ``_SyncSessionLocal``, ``_shutdown_event``,
``update_job_status_sync``, ``_parallel_indicator_sync``, and the
two downstream ``_ticker_*_notification_cycle`` functions lazily
inside the function body to avoid a circular import:
``app.backgroundtasks._impl`` re-exports us at the bottom of its
own module, so a top-level import from ``_impl`` here would
deadlock the import machinery.

NOTE 2: This module is named ``indicators.py`` to live under
``app/services/data_sync/``, but it must NOT be confused with
``app/services/indicators.py`` (the actual compute service).
We import the latter as ``svc_indicators`` to avoid shadowing
our own module name.
"""
from __future__ import annotations

from time import monotonic

from sqlalchemy import func, select


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
    from app.backgroundtasks import _impl as _bg_impl
    from app.models.ticker import TickerDaily
    from app.services import indicators as svc_indicators

    logger = _bg_impl.logger
    _SyncSessionLocal = _bg_impl._SyncSessionLocal
    update_job_status_sync = _bg_impl.update_job_status_sync
    _parallel_indicator_sync = _bg_impl._parallel_indicator_sync
    _ticker_indicator_notification_cycle = _bg_impl._ticker_indicator_notification_cycle

    logger.info(
        "ticker_indicators_sync: scanning ticker_daily for stale/null symbols "
        "(this can take ~1-2 min on a large universe)…"
    )
    scan_start = monotonic()

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
    scan_elapsed = monotonic() - scan_start

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
        svc_indicators.prepare_daily_indicator_updates,
        svc_indicators.flush_daily_indicator_updates,
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
    from app.backgroundtasks import _impl as _bg_impl
    from app.models.ticker import TickerIntraday
    from app.services import indicators as svc_indicators

    logger = _bg_impl.logger
    _SyncSessionLocal = _bg_impl._SyncSessionLocal
    update_job_status_sync = _bg_impl.update_job_status_sync
    _parallel_indicator_sync = _bg_impl._parallel_indicator_sync
    _ticker_intraday_indicator_notification_cycle = _bg_impl._ticker_intraday_indicator_notification_cycle

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
        scan_start = monotonic()

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
        scan_elapsed = monotonic() - scan_start

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
            svc_indicators.prepare_intraday_indicator_updates,
            svc_indicators.flush_intraday_indicator_updates,
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

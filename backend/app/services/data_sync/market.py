"""Market data sync cores (audit C.1, A.11 part 2).

Extracted from ``app/backgroundtasks/_impl.py``.  Holds the
market-data sync cores (work bodies) called by the
``market_data_worker`` daemon in ``app.workers.market_calendar``.

Public functions (4):
- ``_is_market_open()`` — bool: is the NSE market currently open
  (Mon-Fri, 09:15-15:30 IST)?
- ``_seconds_until_market_open()`` — float: how long until the
  next market open
- ``_refresh_market_data_async()`` — async helper: refresh
  industry + sector data from MoneyControl
- ``_market_data_sync()`` — sync wrapper called by the worker

NOTE: We import ``logger``, ``_run_async``, ``AsyncSessionLocal``
and ``settings`` lazily inside the function bodies to avoid a
circular import: ``app.backgroundtasks._impl`` re-exports us at
the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _is_market_open() -> bool:
    """Check if the market is currently open (Mon-Fri, 09:15-15:30 IST)."""
    from app.backgroundtasks import _impl as _bg_impl

    settings = _bg_impl.settings

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
    from app.backgroundtasks import _impl as _bg_impl

    settings = _bg_impl.settings

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
    from app.backgroundtasks import _impl as _bg_impl

    AsyncSessionLocal = _bg_impl.AsyncSessionLocal
    market_data_fetcher = _bg_impl.market_data_fetcher

    async with AsyncSessionLocal() as session:
        await market_data_fetcher.refresh_all(session)


def _market_data_sync() -> None:
    """Fetch and store all industry and sector data from MoneyControl."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _run_async = _bg_impl._run_async

    try:
        logger.info("market_data_sync: starting")
        _run_async(_refresh_market_data_async())
        logger.info("market_data_sync: complete")
    except Exception:
        logger.exception("market_data_sync: unhandled exception; will retry next cycle")

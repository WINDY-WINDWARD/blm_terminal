"""Market data sync cores (audit C.1, A.11 part 2, A.13).

Extracted from ``app/backgroundtasks/_impl.py``.  Holds the
market-data sync cores (work bodies).

``market_data`` is now managed by the orchestrator — it runs as
Stage 7 of the startup/nightly pipeline and on a ``*/20 * * * *``
cron scheduler during market hours with one freeze sync after close (see
``Orchestrator._run_market_data_scheduler``).

Public functions (4):
- ``_is_market_session_at()`` — bool: does an IST datetime fall in
  the regular weekday session?
- ``_is_market_open()`` — bool: is the NSE market currently open
  (Mon-Fri, 09:15-15:30 IST)?
- ``_seconds_until_market_open()`` — float: how long until the
  next market open
- ``_refresh_market_data_async()`` — async helper: refresh
  industry + sector data from MoneyControl
- ``_market_data_sync()`` — sync wrapper called by the pipeline
  and scheduler

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)


def _is_market_session_at(now_ist: datetime) -> bool:
    """Return whether an IST datetime falls in the regular weekday session."""
    from app.config import settings

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


def _is_market_open() -> bool:
    """Check if the market is currently open (Mon-Fri, 09:15-15:30 IST)."""
    now_ist = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
    return _is_market_session_at(now_ist)


def _seconds_until_market_open() -> float:
    """Calculate seconds until the next market open time (09:15 IST)."""
    from app.config import settings

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
    """Local aggregator — delegates to market_local (no network)."""
    from app.services.data_sync.market_local import _refresh_market_data_local_async as _local

    await _local()


# Serializes aggregate rebuilds: the */20 scheduler, the nightly pipeline
# stage, manual triggers, and the market_caps chain all funnel through
# _market_data_sync — without this two writers interleave category
# delete/insert commits (last-writer-wins flap, torn aggregates).
_MARKET_REBUILD_LOCK = threading.Lock()


def _market_data_sync() -> None:
    """Build industry/sector aggregates locally from stock_universe (no network)."""
    from app.services.data_sync.market_local import _market_local_sync

    with _MARKET_REBUILD_LOCK:
        _market_local_sync()

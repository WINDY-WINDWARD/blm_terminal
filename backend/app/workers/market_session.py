"""Shared market-session gating for scheduled alert jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def _market_hours_wait_seconds(cron_expr: str) -> tuple[float, bool]:
    """Return the next valid market-hours wait and whether it was shifted."""
    from app.backgroundtasks._runtime import _seconds_until_next_cron
    from app.services.data_sync.market import (
        _is_market_session_at,
        _seconds_until_market_open,
    )

    wait_secs = _seconds_until_next_cron(cron_expr)
    now_ist = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
    if _is_market_session_at(now_ist + timedelta(seconds=wait_secs)):
        return wait_secs, False
    return _seconds_until_market_open(), True


def _report_market_hours_waiting(
    job_key: str,
    cron_expr: str,
    message: str | None = None,
) -> float:
    """Report the next market-hours run and return the interruptible wait."""
    from app.jobs.runner import update_job_status_sync

    wait_secs, shifted = _market_hours_wait_seconds(cron_expr)
    next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
    waiting_message = message or (
        "Market closed — waiting for next session"
        if shifted
        else f"Next run in {wait_secs / 3600:.1f}h"
    )
    update_job_status_sync(
        job_key,
        "waiting",
        progress=100,
        message=waiting_message,
        next_trigger=next_trigger,
    )
    return wait_secs


def _wait_for_market_session(job_key: str) -> bool:
    """Block outside market hours, returning True when shutdown is requested."""
    from app.backgroundtasks._runtime import _shutdown_event
    from app.jobs.runner import update_job_status_sync
    from app.services.data_sync.market import _is_market_open, _seconds_until_market_open

    while not _is_market_open():
        if _shutdown_event.is_set():
            return True
        wait_secs = _seconds_until_market_open()
        next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
        update_job_status_sync(
            job_key,
            "waiting",
            progress=0,
            message="Market closed — waiting for next session",
            next_trigger=next_trigger,
        )
        if _shutdown_event.wait(timeout=wait_secs):
            return True
    return False

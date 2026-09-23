"""Missed-schedule catch-up for desktop machines.

Desktops are off at night when most cron jobs fire (universe 00:00,
fundamentals 01:30, vacuum Sun 04:00, ...). Daemon loops simply sleep until
the next fire, so a machine that is never on at 01:30 can go weeks without
a fundamentals pass. The nightly pipeline has its own >24h catch-up; this
module covers the standalone cron jobs it doesn't own.

Runs once after the startup pipeline completes (see Orchestrator): for each
eligible job it compares the cron schedule's previous fire time against
``last_success_at`` (written ONLY on real work completion — never by
waiting/idle bookkeeping) and runs what was missed, serialized with stagger
so boot never storms. Continuous/self-scheduling jobs (news, notif, scan,
intraday, market_data scheduler, backfill @startup) and stage-driven jobs
(market_caps, market_data) are excluded — they resume on boot by construction.
ai_picks_* self-cover with domain-aware boot checks and are excluded too.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.jobs.registry import JobRegistry
from app.jobs.runner import get_job_status, run_job_async

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# Eligible jobs in dependency order (universe first: everything keys off it).
CATCHUP_JOB_KEYS: list[str] = [
    "job.stock_universe",
    "job.ticker_indicators",
    "job.ticker_scores",
    "job.ticker_daily_update",
    "job.fundamentals",
    "job.vacuum",
    "job.full_fair_value",
    "job.watchlist_fair_value",
    "job.results_calendar",
]

# Fire-time grace: a success within this window after a scheduled fire
# counts as "that fire ran" (workers start seconds/minutes late).
_MISSED_GRACE_S = 600.0
# Gap between catch-up runs so boot never storms.
_CATCHUP_STAGGER_S = 45.0
# Breathing room after boot for the nightly-pipeline catch-up task to mark
# its stages running (skipped automatically once their statuses flip).
_CATCHUP_INITIAL_DELAY_S = 60.0


def _as_utc(dt: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes — assume UTC (repo convention).
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def prev_fire_ist(cron_expr: str | None, now: datetime) -> datetime | None:
    """Previous scheduled fire time (aware UTC), or None if unschedulable."""
    if not cron_expr or cron_expr == "@startup":
        return None
    try:
        from croniter import croniter

        now_ist = now.astimezone(_IST).replace(tzinfo=None)
        prev_naive = croniter(cron_expr, now_ist).get_prev(datetime)
        return prev_naive.replace(tzinfo=_IST).astimezone(timezone.utc)
    except Exception:
        logger.debug("catchup: unparsable cron %r", cron_expr, exc_info=True)
        return None


def is_missed(cron_expr: str | None, last_success: datetime | None,
              now: datetime, grace_s: float = _MISSED_GRACE_S) -> bool:
    """True when the schedule fired while we were away (or never ran)."""
    prev = prev_fire_ist(cron_expr, now)
    if prev is None:
        return False
    success = _as_utc(last_success)
    if success is None:
        return True
    return success < prev - timedelta(seconds=grace_s)


def catchup_plan(defs: list[tuple[str, str | None]],
                 successes: dict[str, datetime | None],
                 now: datetime) -> list[str]:
    """Pure planning step: ordered job_keys due for catch-up. Testable."""
    return [
        key for key, cron in defs
        if is_missed(cron, successes.get(key), now)
    ]


async def run_missed_catchup() -> dict[str, int]:
    """Run every missed eligible job once, serialized with stagger.

    Called once after the startup pipeline (fire-and-forget task).
    Returns outcome counts. One job's failure never stops the rest.
    """
    from app.backgroundtasks._runtime import _is_job_enabled, _shutdown_event

    total = {"checked": 0, "missed": 0, "completed": 0, "failed": 0, "skipped": 0}
    await asyncio.sleep(_CATCHUP_INITIAL_DELAY_S)
    if _shutdown_event.is_set():
        return total

    now = datetime.now(timezone.utc)
    defs: list[tuple[str, str | None]] = []
    successes: dict[str, datetime | None] = {}
    for key in CATCHUP_JOB_KEYS:
        job_def = JobRegistry.get(key)
        if job_def is None:
            continue
        total["checked"] += 1
        try:
            status = await get_job_status(key)
        except Exception as exc:
            logger.warning("catchup: status read failed for %s: %s", key, exc)
            continue
        if status is not None and status.status == "running":
            total["skipped"] += 1
            continue
        successes[key] = status.last_success_at if status else None
        defs.append((key, job_def.cron_expression))

    due = catchup_plan(defs, successes, now)
    total["missed"] = len(due)
    if due:
        logger.info("catchup: %d missed schedule(s) detected: %s", len(due), ", ".join(due))

    for i, key in enumerate(due):
        if _shutdown_event.is_set():
            break
        if not _is_job_enabled(key):
            total["skipped"] += 1
            continue
        try:
            status = await get_job_status(key)
            if status is not None and status.status == "running":
                total["skipped"] += 1
                continue
            logger.info("catchup: running missed job %s (%d/%d)", key, i + 1, len(due))
            await run_job_async(key)
            total["completed"] += 1
        except Exception as exc:
            logger.exception("catchup: missed job %s failed: %s", key, exc)
            total["failed"] += 1
        if i + 1 < len(due):
            await asyncio.sleep(_CATCHUP_STAGGER_S)
            if _shutdown_event.is_set():
                break

    logger.info("catchup: done — checked=%d missed=%d completed=%d failed=%d skipped=%d",
                total["checked"], total["missed"], total["completed"],
                total["failed"], total["skipped"])
    return total

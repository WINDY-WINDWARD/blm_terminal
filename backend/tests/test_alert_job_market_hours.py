"""Market-hours gating for automatic alert jobs."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.jobs.registry import JobRegistry
from app.jobs.runner import trigger_job
from app.orchestrator import Orchestrator
from app.services.data_sync.market import _is_market_session_at
from app.workers.market_session import (
    _market_hours_wait_seconds,
    _report_market_hours_waiting,
    _wait_for_market_session,
)


IST = ZoneInfo("Asia/Kolkata")


def _ist(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (_ist(2026, 10, 19, 9, 14), False),
        (_ist(2026, 10, 19, 9, 15), True),
        (_ist(2026, 10, 19, 15, 30), True),
        (_ist(2026, 10, 19, 15, 31), False),
        (_ist(2026, 10, 24, 11, 0), False),
        (_ist(2026, 10, 25, 11, 0), False),
    ],
)
def test_market_session_boundaries(when: datetime, expected: bool) -> None:
    assert _is_market_session_at(when) is expected


def test_market_hours_wait_shifts_outside_session_to_next_open() -> None:
    with (
        patch("app.backgroundtasks._runtime._seconds_until_next_cron", return_value=300),
        patch("app.services.data_sync.market._is_market_session_at", return_value=False),
        patch("app.services.data_sync.market._seconds_until_market_open", return_value=3600),
    ):
        wait_secs, shifted = _market_hours_wait_seconds("*/5 9-15 * * 1-5")

    assert wait_secs == 3600
    assert shifted is True


def test_market_hours_wait_keeps_in_session_cron() -> None:
    with (
        patch("app.backgroundtasks._runtime._seconds_until_next_cron", return_value=300),
        patch("app.services.data_sync.market._is_market_session_at", return_value=True),
        patch("app.services.data_sync.market._seconds_until_market_open") as market_open,
    ):
        wait_secs, shifted = _market_hours_wait_seconds("*/5 9-15 * * 1-5")

    assert wait_secs == 300
    assert shifted is False
    market_open.assert_not_called()


def test_report_market_hours_waiting_reports_next_open() -> None:
    with (
        patch("app.workers.market_session._market_hours_wait_seconds", return_value=(3600, True)),
        patch("app.jobs.runner.update_job_status_sync") as update_status,
    ):
        wait_secs = _report_market_hours_waiting("job.notifications", "*/5 9-15 * * 1-5")

    assert wait_secs == 3600
    kwargs = update_status.call_args.kwargs
    assert kwargs["message"] == "Market closed — waiting for next session"
    assert kwargs["next_trigger"] is not None


def test_wait_for_market_session_blocks_until_open() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.return_value = False
    shutdown_event.wait.return_value = False

    with (
        patch("app.services.data_sync.market._is_market_open", side_effect=[False, True]),
        patch("app.services.data_sync.market._seconds_until_market_open", return_value=3600),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.jobs.runner.update_job_status_sync") as update_status,
    ):
        stopped = _wait_for_market_session("job.notifications")

    assert stopped is False
    shutdown_event.wait.assert_called_once_with(timeout=3600)
    assert update_status.call_args.kwargs["message"] == "Market closed — waiting for next session"


def test_wait_for_market_session_stops_on_shutdown() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.return_value = True

    with (
        patch("app.services.data_sync.market._is_market_open", return_value=False),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
    ):
        assert _wait_for_market_session("job.notifications") is True


def test_watchlist_worker_skips_cycle_when_market_wait_stops() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.return_value = False

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.workers.market_session._wait_for_market_session", return_value=True),
        patch("app.workers.notification_cycles._notification_cycle_full") as cycle,
    ):
        from app.workers.notifications import watchlist_notification_worker
        watchlist_notification_worker()

    cycle.assert_not_called()


def test_watchlist_worker_runs_one_cycle_in_session() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.side_effect = [False, True]

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.backgroundtasks._runtime._wait_for_pipeline", return_value=False),
        patch("app.backgroundtasks._runtime._sleep_interruptible", return_value=True),
        patch("app.workers.market_session._wait_for_market_session", return_value=False),
        patch("app.workers.market_session._report_market_hours_waiting", return_value=300),
        patch("app.services.data_sync.market._is_market_open", return_value=True),
        patch("app.workers.notification_cycles._notification_cycle_full") as cycle,
    ):
        from app.workers.notifications import watchlist_notification_worker
        watchlist_notification_worker()

    cycle.assert_called_once()


def test_watchlist_worker_skips_cycle_when_pipeline_wait_crosses_close() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.side_effect = [False, True]

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.backgroundtasks._runtime._wait_for_pipeline", return_value=False),
        patch("app.workers.market_session._wait_for_market_session", return_value=False),
        patch("app.services.data_sync.market._is_market_open", return_value=False),
        patch("app.workers.notification_cycles._notification_cycle_full") as cycle,
    ):
        from app.workers.notifications import watchlist_notification_worker
        watchlist_notification_worker()

    cycle.assert_not_called()


def test_global_scan_worker_skips_cycle_when_market_wait_stops() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.return_value = False

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.workers.market_session._wait_for_market_session", return_value=True),
        patch("app.workers.global_scan_cycle._global_scan_cycle") as cycle,
    ):
        from app.workers.notifications import global_scan_worker
        global_scan_worker()

    cycle.assert_not_called()


def test_global_scan_worker_skips_cycle_when_pipeline_wait_crosses_close() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.side_effect = [False, True]

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.backgroundtasks._runtime._wait_for_pipeline", return_value=False),
        patch("app.workers.market_session._wait_for_market_session", return_value=False),
        patch("app.services.data_sync.market._is_market_open", return_value=False),
        patch("app.workers.global_scan_cycle._global_scan_cycle") as cycle,
    ):
        from app.workers.notifications import global_scan_worker
        global_scan_worker()

    cycle.assert_not_called()


def test_results_calendar_waits_before_first_run_when_closed() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.return_value = False

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.backgroundtasks._runtime._is_first_run", return_value=True),
        patch("app.workers.market_session._wait_for_market_session", return_value=True),
        patch("app.services.data_sync.calendar._results_calendar_sync") as sync,
    ):
        from app.workers.market_calendar import results_calendar_worker
        results_calendar_worker()

    sync.assert_not_called()


def test_results_calendar_scheduled_run_waits_when_closed() -> None:
    shutdown_event = MagicMock()
    shutdown_event.is_set.return_value = False

    with (
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.backgroundtasks._runtime._shutdown_event", shutdown_event),
        patch("app.backgroundtasks._runtime._wait_for_startup_event", return_value=False),
        patch("app.backgroundtasks._runtime._is_first_run", return_value=False),
        patch("app.backgroundtasks._runtime._sleep_interruptible", return_value=False),
        patch("app.workers.market_session._report_market_hours_waiting", return_value=300),
        patch("app.workers.market_session._wait_for_market_session", return_value=True),
        patch("app.services.data_sync.calendar._results_calendar_sync") as sync,
    ):
        from app.workers.market_calendar import results_calendar_worker
        results_calendar_worker()

    sync.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_alert_stage_skips_when_market_closed() -> None:
    orchestrator = Orchestrator()

    with (
        patch("app.services.data_sync.market._is_market_open", return_value=False),
        patch("app.workers.global_scan_cycle._global_scan_cycle") as scan,
        patch("app.workers.notification_cycles._notification_cycle_full") as notify,
        patch("app.jobs.runner.update_job_status", new=AsyncMock()) as update_status,
    ):
        await orchestrator._run_alert_stage("job.pipeline.startup")

    scan.assert_not_called()
    notify.assert_not_called()
    assert "Market closed" in update_status.call_args.kwargs["message"]


@pytest.mark.asyncio
async def test_pipeline_alert_stage_runs_when_market_open() -> None:
    orchestrator = Orchestrator()
    scan = MagicMock()
    notify = MagicMock()

    async def run_now(_executor, fn):
        fn()

    loop = MagicMock()
    loop.run_in_executor.side_effect = run_now

    with (
        patch("app.services.data_sync.market._is_market_open", return_value=True),
        patch("app.backgroundtasks._runtime._is_job_enabled", return_value=True),
        patch("app.workers.global_scan_cycle._global_scan_cycle", scan),
        patch("app.workers.notification_cycles._notification_cycle_full", notify),
        patch("asyncio.get_running_loop", return_value=loop),
    ):
        await orchestrator._run_alert_stage("job.pipeline.startup")

    scan.assert_called_once()
    notify.assert_called_once()


@pytest.mark.asyncio
async def test_manual_alert_job_trigger_bypasses_market_hours() -> None:
    called = []

    async def alert_job() -> None:
        called.append(True)

    job_def = SimpleNamespace(callable=alert_job, is_async=True, name="notifications", category="notifications")
    job_row = SimpleNamespace(
        status="idle",
        job_key="job.notifications",
        name="notifications",
        last_triggered_at=None,
    )
    tasks = []

    with (
        patch("app.jobs.runner.get_job_status", new=AsyncMock(return_value=job_row)),
        patch.object(JobRegistry, "get", return_value=job_def),
        patch("app.jobs.runner._create_job_execution_sync"),
        patch("app.jobs.runner.update_job_status", new=AsyncMock()),
        patch.object(JobRegistry, "set_running"),
        patch("asyncio.create_task", side_effect=lambda coro: tasks.append(coro)),
    ):
        result = await trigger_job("job.notifications")

    assert result["ok"] is True
    await tasks[0]
    assert called == [True]

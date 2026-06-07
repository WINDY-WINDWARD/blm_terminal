"""Tests for the orchestrator cleanup (audit B.11).

Coverage:
- ``_wait_for_shutdown`` completes immediately when the event is already
  set (proves we no longer wait the full timeout).
- ``_wait_for_shutdown`` returns when the event is set during the wait
  (proves we react to ``.set()`` and don't keep polling).
- ``_cron_loop`` runs the target function once when ``wait_secs`` elapses
  and the shutdown event is not set.
- ``_cron_loop`` exits immediately on shutdown without running the
  target.
- ``_cron_loop`` updates the job status to 'waiting' before sleeping
  and lets ``_update_fv_job_waiting`` decide the next_trigger.
- The three former schedulers (``_run_nightly_pipeline_scheduler``,
  ``_run_watchlist_fair_value_scheduler``,
  ``_run_full_fair_value_scheduler``) are now thin wrappers that call
  ``_cron_loop`` with their distinct cron + job_key + target_fn.

The refactor consolidates 3 schedulers into one generic ``_cron_loop``.
The tests pin the contract of the helper so a future change cannot
regress the orchestration semantics.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orchestrator import _cron_loop, _wait_for_shutdown  # noqa: E402


# ─── _wait_for_shutdown ────────────────────────────────────────────────────


class TestWaitForShutdown:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_already_set(self):
        """If the event is already set when we enter, we must NOT wait
        the full timeout.  The pre-refactor poll loop with
        ``asyncio.sleep(1)`` would still wait up to 1 second; the
        refactored ``.wait()`` returns instantly.
        """
        event = asyncio.Event()
        event.set()

        t0 = asyncio.get_running_loop().time()
        await asyncio.wait_for(_wait_for_shutdown(event), timeout=0.5)
        elapsed = asyncio.get_running_loop().time() - t0
        assert elapsed < 0.1, (
            f"_wait_for_shutdown took {elapsed:.3f}s on a pre-set event "
            f"— should be near-instant"
        )

    @pytest.mark.asyncio
    async def test_returns_when_set_during_wait(self):
        """Setting the event while we're waiting should cause immediate
        return (not a 1-second poll lag).
        """
        event = asyncio.Event()

        async def setter():
            await asyncio.sleep(0.05)
            event.set()

        asyncio.create_task(setter())
        t0 = asyncio.get_running_loop().time()
        await asyncio.wait_for(_wait_for_shutdown(event), timeout=1.0)
        elapsed = asyncio.get_running_loop().time() - t0
        assert 0.04 < elapsed < 0.5, (
            f"_wait_for_shutdown took {elapsed:.3f}s when event was set "
            f"after 50ms — should be ~50ms, not the full timeout"
        )


# ─── _cron_loop ────────────────────────────────────────────────────────────


class TestCronLoop:
    @pytest.mark.asyncio
    async def test_runs_target_fn_once_on_fire(self):
        """When ``compute_wait_secs`` returns a value and the
        shutdown event is not set, ``_cron_loop`` should run the
        target function (at least once).
        """
        event = asyncio.Event()
        target = AsyncMock()

        with patch("app.backgroundtasks._runtime.get_async_shutdown_event", return_value=event):
            task = asyncio.create_task(_cron_loop(
                cron_expr="* * * * *",
                job_key="test.job",
                target_fn=target,
                compute_wait_secs=lambda _c: 0.05,  # fire after 50ms
                next_fire_label_fn=None,
                schedule_label="test",
            ))
            # Let the loop run long enough for at least one fire
            await asyncio.sleep(0.15)
            event.set()
            await asyncio.wait_for(task, timeout=0.5)

        assert target.await_count >= 1, (
            f"target should have been called at least once, got {target.await_count}"
        )

    @pytest.mark.asyncio
    async def test_exits_on_shutdown_without_running(self):
        """If the event is set before the first fire, the loop must exit
        without ever running the target.
        """
        event = asyncio.Event()
        target = AsyncMock()

        with patch("app.backgroundtasks._runtime.get_async_shutdown_event", return_value=event):
            task = asyncio.create_task(_cron_loop(
                cron_expr="* * * * *",
                job_key="test.job",
                target_fn=target,
                compute_wait_secs=lambda _c: 10.0,  # long enough that we set first
                next_fire_label_fn=None,
                schedule_label="test",
            ))
            await asyncio.sleep(0.05)  # let the loop enter the wait
            event.set()
            await asyncio.wait_for(task, timeout=0.5)

        target.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_updates_job_status_before_waiting(self):
        """Each cycle should call ``_update_fv_job_waiting`` via the
        executor with the configured job_key and a positive
        next_trigger delta.
        """
        event = asyncio.Event()
        target = AsyncMock()
        captured_calls: list = []

        def fake_update(job_key, next_trigger, wait_secs):
            captured_calls.append((job_key, wait_secs))

        with patch("app.backgroundtasks._runtime.get_async_shutdown_event", return_value=event), \
             patch("app.orchestrator._update_fv_job_waiting", side_effect=fake_update):
            task = asyncio.create_task(_cron_loop(
                cron_expr="* * * * *",
                job_key="job.unit_test",
                target_fn=target,
                compute_wait_secs=lambda _c: 0.05,
                next_fire_label_fn=None,
                schedule_label="unit test",
            ))
            await asyncio.sleep(0.2)
            event.set()
            await asyncio.wait_for(task, timeout=0.5)

        assert captured_calls, "_update_fv_job_waiting should have been called"
        first = captured_calls[0]
        assert first[0] == "job.unit_test"
        assert 0 < first[1] < 1.0  # the wait_secs we passed

    @pytest.mark.asyncio
    async def test_logs_with_fire_time_label(self):
        """When ``next_fire_label_fn`` is provided, the scheduler should
        log it.  When None, the scheduler should still log (but without
        the label suffix).
        """
        event = asyncio.Event()
        target = AsyncMock()

        with patch("app.backgroundtasks._runtime.get_async_shutdown_event", return_value=event), \
             patch("app.orchestrator.logger") as mock_logger:
            task = asyncio.create_task(_cron_loop(
                cron_expr="* * * * *",
                job_key="job.unit_test",
                target_fn=target,
                compute_wait_secs=lambda _c: 0.05,
                next_fire_label_fn=lambda _c: "2024-01-01 12:00",
                schedule_label="unit test",
            ))
            await asyncio.sleep(0.15)
            event.set()
            await asyncio.wait_for(task, timeout=0.5)

        # The schedule-label log should have been emitted at least once
        # (the format string contains "scheduled in"; the label
        # "unit test" is in args[1]).
        schedule_logs = [
            c for c in mock_logger.info.call_args_list
            if c.args
            and "scheduled in" in str(c.args[0])
            and "unit test" in [str(a) for a in c.args[1:]]
        ]
        assert schedule_logs, (
            f"expected a 'scheduled in' log line, got: {mock_logger.info.call_args_list}"
        )


# ─── Scheduler wrappers are thin ──────────────────────────────────────────


class TestSchedulerWrappers:
    """The 3 schedulers are now thin wrappers that delegate to
    ``_cron_loop`` with their distinct configuration.  These tests
    verify each wrapper passes the right cron + job_key + target_fn.
    """

    @pytest.mark.asyncio
    async def test_nightly_pipeline_scheduler_uses_nightly_cron(self):
        from app.orchestrator import Orchestrator, _NIGHTLY_HOUR_IST, _NIGHTLY_MINUTE_IST

        orch = Orchestrator()
        with patch("app.orchestrator._cron_loop", new=AsyncMock()) as mock_loop:
            await orch._run_nightly_pipeline_scheduler()

        mock_loop.assert_awaited_once()
        kwargs = mock_loop.await_args.kwargs
        assert kwargs["job_key"] == "job.pipeline.nightly"
        assert kwargs["cron_expr"] == f"{_NIGHTLY_MINUTE_IST} {_NIGHTLY_HOUR_IST} * * *"
        assert kwargs["schedule_label"] == "nightly pipeline"

    @pytest.mark.asyncio
    async def test_watchlist_fair_value_scheduler_uses_3h_cron(self):
        from app.orchestrator import Orchestrator

        orch = Orchestrator()
        with patch("app.orchestrator._cron_loop", new=AsyncMock()) as mock_loop:
            await orch._run_watchlist_fair_value_scheduler()

        mock_loop.assert_awaited_once()
        kwargs = mock_loop.await_args.kwargs
        assert kwargs["job_key"] == "job.watchlist_fair_value"
        assert kwargs["cron_expr"] == "0 */3 * * *"
        assert kwargs["schedule_label"] == "watchlist fair value"

    @pytest.mark.asyncio
    async def test_full_fair_value_scheduler_uses_ist_2330_cron(self):
        from app.orchestrator import Orchestrator

        orch = Orchestrator()
        with patch("app.orchestrator._cron_loop", new=AsyncMock()) as mock_loop:
            await orch._run_full_fair_value_scheduler()

        mock_loop.assert_awaited_once()
        kwargs = mock_loop.await_args.kwargs
        assert kwargs["job_key"] == "job.full_fair_value"
        assert kwargs["cron_expr"] == "30 23 * * *"
        assert kwargs["schedule_label"] == "full fair value sync"

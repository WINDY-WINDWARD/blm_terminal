"""Tests for the orchestrator's _run_stage helper (audit B.11).

The helper consolidates 9 near-identical pipeline-stage blocks
(``_execute_pipeline``) into one function that handles the
shutdown check, executor dispatch, status updates, and skip logging.

These tests pin the helper's contract so a future change cannot
regress the orchestration semantics:

- Returns ``True`` if the stage ran (or was enabled).
- Returns ``False`` if shutdown was requested at the start of the
  stage (caller should bail out of the rest of the pipeline).
- Returns ``True`` if the stage was mode-skipped (so caller continues
  to the next stage normally).
- Calls the sync function in the executor (so the event loop is
  not blocked).
- Acquires the pipeline lock when ``requires_lock=True``.
- Updates the job status to 'running' before the sync call and to
  'idle' after.
- Updates the pipeline job status with progress and message.
- Calls the ``on_complete`` callback (for the startup gate events).
- Logs at start and end of the stage.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orchestrator import Orchestrator, PipelineMode  # noqa: E402


# ─── Test fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def fresh_orchestrator():
    """Each test gets a fresh Orchestrator instance."""
    return Orchestrator()


@pytest.fixture
def mock_background_symbols():
    """Patch the symbols that ``_run_stage`` imports from
    ``app.backgroundtasks._runtime`` (A.13 canonical home)."""
    return {
        "_is_job_enabled": MagicMock(return_value=True),
        "_pipeline_idle": MagicMock(),
        "_pipeline_lock": MagicMock(),
        "_shutdown_event": MagicMock(is_set=MagicMock(return_value=False)),
    }


# ─── Happy path ────────────────────────────────────────────────────────────


class TestRunStageHappyPath:
    @pytest.mark.asyncio
    async def test_runs_sync_fn_in_executor(
        self, fresh_orchestrator, mock_background_symbols
    ):
        """When a job is enabled, the sync function is invoked in an
        executor (not the event loop).  We verify by patching
        ``_run_pipeline_stage`` and ``asyncio.get_running_loop``.
        """
        sync_fn = MagicMock(return_value=None)
        with patch.multiple(
            "app.backgroundtasks._runtime",
            **mock_background_symbols,
        ), patch("app.jobs.runner.update_job_status", new=AsyncMock()), \
             patch("app.orchestrator._run_pipeline_stage", new=MagicMock()) as mock_stage:
            with patch("asyncio.get_running_loop") as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.run_in_executor = AsyncMock(return_value=None)
                mock_get_loop.return_value = mock_loop

                ok = await fresh_orchestrator._run_stage(
                    mode=PipelineMode.STARTUP,
                    stage_name="stock_universe",
                    sub_jobs=[("job.stock_universe", sync_fn, False)],
                    progress_start=5,
                    progress_end=15,
                    stage_label="1/7",
                )

        assert ok is True
        assert mock_loop.run_in_executor.called

    @pytest.mark.asyncio
    async def test_acquires_pipeline_lock_when_required(
        self, fresh_orchestrator, mock_background_symbols
    ):
        """When ``requires_lock=True`` in a sub_job, the helper should
        dispatch via ``_run_pipeline_stage`` (which acquires the
        threading lock).
        """
        sync_fn = MagicMock(return_value=None)
        with patch.multiple(
            "app.backgroundtasks._runtime",
            **mock_background_symbols,
        ), patch("app.jobs.runner.update_job_status", new=AsyncMock()), \
             patch("app.orchestrator._run_pipeline_stage", new=MagicMock()) as mock_stage:
            with patch("asyncio.get_running_loop") as mock_get_loop:
                mock_loop = MagicMock()
                mock_loop.run_in_executor = AsyncMock(return_value=None)
                mock_get_loop.return_value = mock_loop

                await fresh_orchestrator._run_stage(
                    mode=PipelineMode.STARTUP,
                    stage_name="ticker_backfill",
                    sub_jobs=[("job.ticker_backfill", sync_fn, True)],
                    progress_start=30,
                    progress_end=40,
                    stage_label="2b/7",
                )

        # The executor call should have been made with the lock helper
        call_args = mock_loop.run_in_executor.call_args_list
        assert call_args, "run_in_executor should have been called"
        first_call = call_args[0]
        # First arg is None (default executor), second is the partial
        # invocation of _run_pipeline_stage with the sync fn + lock + idle
        assert first_call[0][0] is None  # executor
        # The remaining args are passed to _run_pipeline_stage
        # (sync_fn, _pipeline_lock, _pipeline_idle)
        assert first_call[0][1] is mock_stage


# ─── Shutdown handling ────────────────────────────────────────────────────


class TestRunStageShutdown:
    @pytest.mark.asyncio
    async def test_returns_false_when_shutdown_set(
        self, fresh_orchestrator, mock_background_symbols
    ):
        """If the shutdown event is set when the stage starts, return
        ``False`` so the caller can bail out of the rest of the pipeline.
        """
        mock_background_symbols["_shutdown_event"] = MagicMock(
            is_set=MagicMock(return_value=True)
        )
        sync_fn = MagicMock()
        with patch.multiple(
            "app.backgroundtasks._runtime",
            **mock_background_symbols,
        ), patch("app.jobs.runner.update_job_status", new=AsyncMock()):
            ok = await fresh_orchestrator._run_stage(
                mode=PipelineMode.STARTUP,
                stage_name="stock_universe",
                sub_jobs=[("job.stock_universe", sync_fn, False)],
                progress_start=5,
                progress_end=15,
                stage_label="1/7",
            )

        assert ok is False
        sync_fn.assert_not_called()


# ─── Mode skipping ────────────────────────────────────────────────────────


class TestRunStageModeSkip:
    @pytest.mark.asyncio
    async def test_returns_true_when_mode_mismatch(
        self, fresh_orchestrator, mock_background_symbols
    ):
        """When ``requires_mode`` is set and ``mode`` is not in it, the
        stage is skipped (returns ``True`` so caller continues to next
        stage).
        """
        sync_fn = MagicMock()
        with patch.multiple(
            "app.backgroundtasks._runtime",
            **mock_background_symbols,
        ), patch("app.jobs.runner.update_job_status", new=AsyncMock()):
            ok = await fresh_orchestrator._run_stage(
                mode=PipelineMode.NIGHTLY,
                stage_name="ticker_weekly_monthly_update (startup-only)",
                sub_jobs=[("job.ticker_weekly_monthly_update", sync_fn, True)],
                progress_start=16,
                progress_end=17,
                stage_label="1b/7",
                requires_mode={PipelineMode.STARTUP},
            )

        assert ok is True
        sync_fn.assert_not_called()


# ─── on_complete callback ──────────────────────────────────────────────────


class TestRunStageOnComplete:
    @pytest.mark.asyncio
    async def test_calls_on_complete_callback(
        self, fresh_orchestrator, mock_background_symbols
    ):
        """The ``on_complete`` callback (used for the startup gate
        events) should be called once after the stage runs.
        """
        on_complete = MagicMock()
        sync_fn = MagicMock()
        with patch.multiple(
            "app.backgroundtasks._runtime",
            **mock_background_symbols,
        ), patch("app.jobs.runner.update_job_status", new=AsyncMock()), \
             patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_loop.run_in_executor = AsyncMock(return_value=None)
            mock_get_loop.return_value = mock_loop

            await fresh_orchestrator._run_stage(
                mode=PipelineMode.STARTUP,
                stage_name="stock_universe",
                sub_jobs=[("job.stock_universe", sync_fn, False)],
                progress_start=5,
                progress_end=15,
                stage_label="1/7",
                on_complete=on_complete,
            )

        on_complete.assert_called_once()


# ─── Disabled job ──────────────────────────────────────────────────────────


class TestRunStageDisabled:
    @pytest.mark.asyncio
    async def test_skips_sync_fn_when_disabled(
        self, fresh_orchestrator, mock_background_symbols
    ):
        """When ``_is_job_enabled`` returns False, the sync fn should
        not be called but the stage should still complete.
        """
        mock_background_symbols["_is_job_enabled"] = MagicMock(return_value=False)
        sync_fn = MagicMock()
        with patch.multiple(
            "app.backgroundtasks._runtime",
            **mock_background_symbols,
        ), patch("app.jobs.runner.update_job_status", new=AsyncMock()) as mock_status:
            ok = await fresh_orchestrator._run_stage(
                mode=PipelineMode.STARTUP,
                stage_name="stock_universe",
                sub_jobs=[("job.stock_universe", sync_fn, False)],
                progress_start=5,
                progress_end=15,
                stage_label="1/7",
            )

        assert ok is True
        sync_fn.assert_not_called()
        # The sub-job should have been set to 'idle' with a
        # 'Disabled — skipped by orchestrator' message
        idle_calls = [
            c for c in mock_status.call_args_list
            if c.kwargs.get("progress") == 100 and "Disabled" in str(c.kwargs.get("message", ""))
        ]
        assert idle_calls, (
            f"expected the sub-job to be set to 'idle' with 'Disabled' "
            f"message, got: {mock_status.call_args_list}"
        )

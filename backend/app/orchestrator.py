"""Background task orchestrator.

Coordinates all background workers and enforces the correct pipeline execution
order for startup and nightly sync runs:

  Stage 1 → stock_universe
  Stage 2a → ticker_daily_update   (nightly only)
  Stage 2b → ticker_backfill       (both modes; gap-fill / full history)
  Stage 3  → ticker_indicators
  Stage 4  → ticker_scores
  Stage 5a → ticker_weekly_monthly_update  (nightly only; W/M candle backfill)
  Stage 5b → ticker_weekly_monthly_indicators  (nightly only; W/M indicator recompute)
  Stage 6  → global_scan + watchlist_notif  (concurrent, one immediate cycle)
  Stage 7  → market_data                    (always; last stage — sets startup gate)

Independent workers (news, results calendar, fair value,
ticker_intraday_hourly_update, ticker_intraday_hourly_indicators, vacuum) are
started immediately and self-manage their own cron schedules — the orchestrator
does not sequence them.  vacuum_worker runs Sunday 04:00 to reclaim space from
news/intraday retention deletes.

The orchestrator also owns the nightly pipeline trigger (23:00 IST) and the
Morningstar fair value schedulers, previously scattered across main.py and
backgroundtasks.py.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# IST timezone constant
_IST = ZoneInfo("Asia/Kolkata")

# Nightly pipeline trigger time (IST)
_NIGHTLY_HOUR_IST = 23
_NIGHTLY_MINUTE_IST = 0


class PipelineMode(enum.Enum):
    STARTUP = "startup"
    NIGHTLY = "nightly"


class Orchestrator:
    """Central coordinator for all background tasks.

    Usage (from main.py lifespan)::

        orchestrator = Orchestrator()
        await orchestrator.start()
        # ... app runs ...
        await orchestrator.stop()
    """

    def __init__(self) -> None:
        self._asyncio_tasks: list[asyncio.Task] = []
        self._pipeline_running = False
        self._pipeline_lock = asyncio.Lock()  # asyncio-side guard (not the threading one)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all background workers and kick off the startup pipeline.

        Called from main.py lifespan after DB migrations complete.
        """
        # Imports kept lazy to avoid module-load-time circular imports.
        # A.13: migrated from ``app.backgroundtasks`` shim to canonical
        # homes — ``app.backgroundtasks._runtime`` (events + lifecycle
        # helpers), ``app.workers.lifecycle`` (start/stop), and
        # ``app.services.fair_value`` (Morningstar sync functions).
        from app.backgroundtasks._runtime import (_is_first_run,
            _set_first_run_complete, get_async_shutdown_event,
            reset_async_shutdown_event)
        from app.services.fair_value import (_should_trigger_full_sync,
            sync_all_fair_values, sync_watchlist_fair_values)
        from app.services.morningstar_client import init_client
        from app.workers.lifecycle import start_all_workers

        # Init Morningstar client (was in main.py)
        await init_client()

        # Register all jobs and spawn all worker daemon threads.
        # start_all_workers() still handles the threading.Event gates for the
        # workers' own first-run logic. The orchestrator runs the pipeline
        # concurrently via the same _sync functions, so the gate events will
        # be set by whichever path completes first.
        await start_all_workers()

        # Register the two pipeline-level jobs (must happen after start_all_workers
        # has called register_all_jobs() + sync_all_jobs_to_db())
        await self._register_pipeline_jobs()

        # Morningstar: immediate sync on first run
        if _is_first_run("morningstar") and await _should_trigger_full_sync():
            logger.info("Orchestrator: triggering immediate Morningstar full sync (first run + stale)")
            self._asyncio_tasks.append(asyncio.create_task(sync_all_fair_values(), name="morningstar-full-sync"))
            self._asyncio_tasks.append(asyncio.create_task(sync_watchlist_fair_values(), name="morningstar-watchlist-sync"))
            _set_first_run_complete("morningstar")

        # Morningstar schedulers (replaces the ones previously in main.py)
        self._asyncio_tasks.append(
            asyncio.create_task(self._run_watchlist_fair_value_scheduler(), name="watchlist-fv-scheduler")
        )
        self._asyncio_tasks.append(
            asyncio.create_task(self._run_nightly_pipeline_scheduler(), name="nightly-pipeline-scheduler")
        )

        self._asyncio_tasks.append(
            asyncio.create_task(self._run_full_fair_value_scheduler(), name="full-fv-scheduler")
        )

        # Market data scheduler — starts after pipeline Stage 7 sets the gate
        self._asyncio_tasks.append(
            asyncio.create_task(self._run_market_data_scheduler(), name="market-data-scheduler")
        )

        # Kick off the startup pipeline in a background asyncio task so lifespan
        # can continue (MCP session manager must start before yield).
        self._asyncio_tasks.append(
            asyncio.create_task(self._run_startup_pipeline(), name="startup-pipeline")
        )

        logger.info("Orchestrator started — startup pipeline queued, nightly scheduler active at %02d:%02d IST",
                    _NIGHTLY_HOUR_IST, _NIGHTLY_MINUTE_IST)

    async def stop(self) -> None:
        """Cancel all orchestrator-owned asyncio tasks and stop all workers."""
        from app.backgroundtasks._runtime import set_async_shutdown_event
        from app.services.morningstar_client import close_client
        from app.services.ai_summarizer import ai_summarizer
        from app.services.nse_client import nse_client
        from app.services.screener_client import screener_client
        from app.services.news_fetcher import news_fetcher
        from app.workers.lifecycle import stop_all_workers

        logger.info("Orchestrator: shutting down...")

        set_async_shutdown_event()

        for task in self._asyncio_tasks:
            task.cancel()
        if self._asyncio_tasks:
            await asyncio.gather(*self._asyncio_tasks, return_exceptions=True)
        self._asyncio_tasks.clear()

        stop_all_workers(timeout=10.0)

        await ai_summarizer.close()
        await nse_client.close()
        await screener_client.close()
        await news_fetcher.close()
        await close_client()

        logger.info("Orchestrator: shutdown complete")

    async def run_pipeline(self, mode: PipelineMode) -> None:
        """Execute the full ordered pipeline for the given mode.

        This is safe to call manually (e.g. via trigger_job API) as it acquires
        an asyncio-level lock to prevent concurrent pipeline runs.

        Scan and notification workers are paused automatically via the existing
        threading _pipeline_lock/_pipeline_idle mechanism, and triggered for one
        immediate cycle once stage 4 (ticker_scores) completes.
        """
        from app.backgroundtasks._runtime import _is_job_enabled

        pipeline_job_key = (
            "job.pipeline.startup" if mode == PipelineMode.STARTUP else "job.pipeline.nightly"
        )

        if not _is_job_enabled(pipeline_job_key):
            logger.info("Orchestrator.run_pipeline(%s): %s disabled, skipping", mode.value, pipeline_job_key)
            return

        if self._pipeline_lock.locked():
            logger.warning("Orchestrator.run_pipeline(%s): another pipeline is already running, skipping", mode.value)
            return

        async with self._pipeline_lock:
            self._pipeline_running = True
            try:
                await self._execute_pipeline(mode)
            finally:
                self._pipeline_running = False

    # ------------------------------------------------------------------
    # Internal: pipeline execution
    # ------------------------------------------------------------------

    async def _run_stage(
        self,
        mode: PipelineMode,
        stage_name: str,
        sub_jobs: list,
        *,
        progress_start: int,
        progress_end: int,
        stage_label: str,
        requires_mode=None,
        on_complete=None,
    ) -> bool:
        """Run one pipeline stage (audit B.11).

        Encapsulates the pattern shared by every stage of
        ``_execute_pipeline``:

        1. Bail if ``_shutdown_event`` is set.
        2. Skip if ``requires_mode`` is set and ``mode`` is not in it.
        3. For each ``(job_key, sync_fn, requires_lock)`` in ``sub_jobs``:
           - if ``_is_job_enabled(job_key)``: write 'running' status,
             run ``sync_fn`` in an executor (acquiring the pipeline
             lock when ``requires_lock``), then write 'idle' status.
           - else: write 'skipped' status, log a skip.
        4. Call ``on_complete`` (used to set the startup gate events).
        5. Log 'complete'.
        6. Update the pipeline job status to ``progress_end``.

        Returns ``True`` if the stage ran (or was mode-skipped), ``False``
        if shutdown was requested during this stage (caller should bail
        out of the rest of the pipeline).
        """
        from app.backgroundtasks._runtime import (_is_job_enabled,
            _pipeline_idle, _pipeline_lock, _shutdown_event)
        from app.jobs.runner import update_job_status

        if requires_mode is not None and mode not in requires_mode:
            return True

        if _shutdown_event.is_set():
            return False

        pipeline_job_key = (
            "job.pipeline.startup" if mode == PipelineMode.STARTUP else "job.pipeline.nightly"
        )

        logger.info("Orchestrator [%s] Stage %s: %s", mode.value, stage_label, stage_name)

        any_enabled = False
        for job_key, sync_fn, requires_lock in sub_jobs:
            if _is_job_enabled(job_key):
                any_enabled = True
                await update_job_status(pipeline_job_key, "running", progress=progress_start,
                                        message=f"Stage {stage_label}: {stage_name}...")
                await update_job_status(job_key, "running", progress=0,
                                        message=f"{stage_name} (orchestrator)...")
                loop = asyncio.get_running_loop()
                if requires_lock:
                    await loop.run_in_executor(
                        None, _run_pipeline_stage, sync_fn, _pipeline_lock, _pipeline_idle,
                    )
                else:
                    await loop.run_in_executor(None, sync_fn)
                await update_job_status(job_key, "idle", progress=100,
                                        message=f"{stage_name} complete")
            else:
                await update_job_status(job_key, "idle", progress=100,
                                        message=f"Disabled — skipped by orchestrator")
                logger.info(
                    "Orchestrator [%s] Stage %s skipped: %s disabled",
                    mode.value, stage_label, job_key,
                )

        # If the stage ran (or was enabled for at least one sub-job),
        # write the per-stage "starting" message; if it was entirely
        # disabled, write the "skipped" message.  This mirrors the
        # original inline behaviour.
        if any_enabled:
            await update_job_status(pipeline_job_key, "running", progress=progress_end,
                                    message=f"Stage {stage_label} complete — {stage_name} done")
        else:
            await update_job_status(pipeline_job_key, "running", progress=progress_end,
                                    message=f"Stage {stage_label} skipped — {stage_name} disabled")

        if on_complete is not None:
            on_complete()

        logger.info("Orchestrator [%s] Stage %s complete", mode.value, stage_label)
        return True

    async def _execute_pipeline(self, mode: PipelineMode) -> None:
        """Execute the full ordered pipeline (audit B.11: uses ``_run_stage``).

        The body is a linear list of ``_run_stage`` calls.  Each stage
        configures (mode, jobs, lock, gate) and the helper handles the
        shutdown check, executor dispatch, status updates, and skip
        logging.  This is the result of consolidating 9 near-identical
        stage blocks (~270 LOC) into 1 helper + ~120 LOC of stage
        configuration.
        """
        # A.13: imports migrated from ``app.backgroundtasks`` shim to
        # canonical homes — gate events from ``_runtime``, sync
        # functions from ``app.services.data_sync.<domain>``, scan /
        # notification cycles from ``app.workers.<domain>``.
        from app.backgroundtasks._runtime import (_shutdown_event,
            _startup_market_data_done, _startup_pipeline_done,
            _startup_stock_universe_done, _startup_ticker_backfill_done,
            _startup_ticker_indicators_done, _startup_ticker_scores_done)
        from app.jobs.runner import update_job_status
        from app.services.data_sync.backfill import _ticker_backfill_sync
        from app.services.data_sync.daily import _ticker_daily_update_sync
        from app.services.data_sync.indicators import (_ticker_indicators_sync,
            _ticker_intraday_indicators_sync)
        from app.services.data_sync.intraday import (
            _ticker_intraday_hourly_stale_check_sync, _ticker_intraday_update_sync)
        from app.services.data_sync.market import _market_data_sync
        from app.services.data_sync.scores import _ticker_scores_sync
        from app.services.data_sync.universe import _stock_universe_sync
        from app.workers.global_scan_cycle import _global_scan_cycle
        from app.workers.notification_cycles import _notification_cycle_full

        pipeline_job_key = (
            "job.pipeline.startup" if mode == PipelineMode.STARTUP else "job.pipeline.nightly"
        )

        logger.info("Orchestrator: starting %s pipeline", mode.value)
        await update_job_status(pipeline_job_key, "running", progress=0,
                                message=f"Starting {mode.value} pipeline...")

        async def _run_or_bail(stage_kwargs):
            """Call ``_run_stage`` and bail out of the pipeline if it
            returns ``False`` (i.e. shutdown was requested)."""
            ok = await self._run_stage(mode, **stage_kwargs)
            if not ok:
                return False
            return True

        try:
            # ── Stage 1: stock universe (always) ──────────────────────────
            if not await _run_or_bail(dict(
                stage_name="stock_universe",
                sub_jobs=[("job.stock_universe", _stock_universe_sync, False)],
                progress_start=5, progress_end=15, stage_label="1/8",
                on_complete=_startup_stock_universe_done.set,
            )):
                return

            # ── Stage 1b: W/M candle backfill (startup only) ──────────────
            if not await _run_or_bail(dict(
                stage_name="ticker_weekly_monthly_update (universe scope)",
                sub_jobs=[(
                    "job.ticker_weekly_monthly_update",
                    lambda: _ticker_intraday_update_sync(
                        ["W", "M"], scope="universe", smart=True,
                        job_key="job.ticker_weekly_monthly_update",
                    ),
                    True,
                )],
                progress_start=16, progress_end=17, stage_label="1b/8",
                requires_mode={PipelineMode.STARTUP},
            )):
                return

            # ── Stage 1c: W/M indicator compute (startup only) ────────────
            if not await _run_or_bail(dict(
                stage_name="ticker_weekly_monthly_indicators (universe scope)",
                sub_jobs=[(
                    "job.ticker_weekly_monthly_indicators",
                    lambda: _ticker_intraday_indicators_sync(["W", "M"]),
                    True,
                )],
                progress_start=17, progress_end=18, stage_label="1c/8",
                requires_mode={PipelineMode.STARTUP},
            )):
                return

            # ── Stage 2a: daily update / bhavcopy (nightly only) ──────────
            if not await _run_or_bail(dict(
                stage_name="ticker_daily_update",
                sub_jobs=[("job.ticker_daily_update", _ticker_daily_update_sync, True)],
                progress_start=18, progress_end=28, stage_label="2a/8",
                requires_mode={PipelineMode.NIGHTLY},
            )):
                return

            # ── Stage 2b: backfill (always) ───────────────────────────────
            if not await _run_or_bail(dict(
                stage_name="ticker_backfill",
                sub_jobs=[("job.ticker_backfill", _ticker_backfill_sync, False)],
                progress_start=30, progress_end=40, stage_label="2b/8",
                on_complete=_startup_ticker_backfill_done.set,
            )):
                return

            # ── Stage 2c: hourly 1h stale-check (always) ──────────────────
            if not await _run_or_bail(dict(
                stage_name="ticker_intraday_hourly_stale_check",
                sub_jobs=[(
                    "job.ticker_intraday_hourly_stale_check",
                    _ticker_intraday_hourly_stale_check_sync,
                    True,
                )],
                progress_start=42, progress_end=48, stage_label="2c/8",
            )):
                return

            # ── Stage 3: indicators (always) ──────────────────────────────
            if not await _run_or_bail(dict(
                stage_name="ticker_indicators",
                sub_jobs=[("job.ticker_indicators", _ticker_indicators_sync, True)],
                progress_start=50, progress_end=62, stage_label="3/8",
                on_complete=_startup_ticker_indicators_done.set,
            )):
                return

            # ── Stage 4: scores (always) ──────────────────────────────────
            if not await _run_or_bail(dict(
                stage_name="ticker_scores",
                sub_jobs=[("job.ticker_scores", _ticker_scores_sync, True)],
                progress_start=64, progress_end=74, stage_label="4/8",
                on_complete=_startup_ticker_scores_done.set,
            )):
                return

            # ── Stage 5a: W/M candle refresh (nightly only) ───────────────
            if mode == PipelineMode.NIGHTLY:
                now_utc = datetime.now(timezone.utc)
                wm_from_ts_overrides = {
                    "W": int((now_utc - timedelta(days=30)).timestamp()),
                    "M": int((now_utc - timedelta(days=90)).timestamp()),
                }
                if not await _run_or_bail(dict(
                    stage_name="ticker_weekly_monthly_update (all universe)",
                    sub_jobs=[(
                        "job.ticker_weekly_monthly_update",
                        lambda: _ticker_intraday_update_sync(
                            ["W", "M"], scope="universe",
                            from_ts_overrides=wm_from_ts_overrides,
                            job_key="job.ticker_weekly_monthly_update",
                        ),
                        True,
                    )],
                    progress_start=76, progress_end=82, stage_label="5a/8",
                    requires_mode={PipelineMode.NIGHTLY},
                )):
                    return

                # ── Stage 5b: W/M indicators (nightly only) ─────────────
                if not await _run_or_bail(dict(
                    stage_name="ticker_weekly_monthly_indicators",
                    sub_jobs=[(
                        "job.ticker_weekly_monthly_indicators",
                        lambda: _ticker_intraday_indicators_sync(["W", "M"]),
                        True,
                    )],
                    progress_start=84, progress_end=88, stage_label="5b/8",
                    requires_mode={PipelineMode.NIGHTLY},
                )):
                    return

            # ── Stage 6: scan + notif (always) — concurrent via gather ────
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 6: scan + notif", mode.value)
            await update_job_status(pipeline_job_key, "running", progress=88,
                                    message="Stage 6/8: Running scan and notifications...")
            from app.backgroundtasks._runtime import _is_job_enabled
            stage6_tasks = []
            if _is_job_enabled("job.global_scan"):
                loop = asyncio.get_running_loop()
                stage6_tasks.append(loop.run_in_executor(None, _global_scan_cycle))
            if _is_job_enabled("job.notifications"):
                loop = asyncio.get_running_loop()
                stage6_tasks.append(loop.run_in_executor(None, _notification_cycle_full))
            if stage6_tasks:
                await asyncio.gather(*stage6_tasks)
            logger.info("Orchestrator [%s] Stage 6 complete", mode.value)

            # ── Stage 7: market_data (always) — last stage ──────────────
            if not await _run_or_bail(dict(
                stage_name="market_data",
                sub_jobs=[("job.market_data", _market_data_sync, False)],
                progress_start=92, progress_end=98, stage_label="7/8",
                on_complete=_startup_market_data_done.set,
            )):
                return

            now = datetime.now(timezone.utc)
            next_trig: datetime | None = None
            if mode == PipelineMode.NIGHTLY:
                wait = _seconds_until_next_cron_ist(f"{_NIGHTLY_MINUTE_IST} {_NIGHTLY_HOUR_IST} * * *")
                next_trig = now + timedelta(seconds=wait)

            # Release the startup pipeline gate so pipeline-managed daemon
            # workers (daily_update, scores, indicators) can enter their cron loops.
            _startup_pipeline_done.set()

            await update_job_status(pipeline_job_key, "idle", progress=100,
                                    message=f"{mode.value.capitalize()} pipeline complete",
                                    last_completed=now, next_trigger=next_trig)
            logger.info("Orchestrator: %s pipeline finished successfully", mode.value)

        except Exception:
            logger.exception("Orchestrator: %s pipeline failed", mode.value)
            await update_job_status(pipeline_job_key, "failed",
                                    message=f"{mode.value.capitalize()} pipeline failed",
                                    last_completed=datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Internal: pipeline runners
    # ------------------------------------------------------------------

    async def _register_pipeline_jobs(self) -> None:
        """Register the two pipeline-level synthetic jobs with the JobRegistry and DB."""
        from app.jobs.registry import JobRegistry, JobDefinition
        from app.jobs.runner import sync_job_to_db

        async def _run_startup() -> None:
            await self.run_pipeline(PipelineMode.STARTUP)

        async def _run_nightly() -> None:
            await self.run_pipeline(PipelineMode.NIGHTLY)

        pipeline_jobs = [
            JobDefinition(
                job_key="job.pipeline.startup",
                name="pipeline_startup",
                description="Full ordered pipeline: universe → backfill → indicators → scores → scan/notif → market_data",
                category="pipeline",
                cron_expression="@startup",
                callable=_run_startup,
                is_async=True,
            ),
            JobDefinition(
                job_key="job.pipeline.nightly",
                name="pipeline_nightly",
                description="Nightly ordered pipeline: universe → daily_update → backfill → indicators → scores → scan/notif → market_data",
                category="pipeline",
                cron_expression=f"{_NIGHTLY_MINUTE_IST} {_NIGHTLY_HOUR_IST} * * *",
                callable=_run_nightly,
                is_async=True,
            ),
        ]
        for job in pipeline_jobs:
            JobRegistry.register(job)
            await sync_job_to_db(job.job_key)
            logger.info("Orchestrator: registered pipeline job %s", job.job_key)

    async def _run_startup_pipeline(self) -> None:
        """Run the startup pipeline once, then exit."""
        try:
            await self.run_pipeline(PipelineMode.STARTUP)
        except Exception:
            logger.exception("Orchestrator: startup pipeline task raised an unhandled exception")

    async def _run_market_data_scheduler(self) -> None:
        """Run market data sync every 5 min during market hours; sleep when closed.

        Waits for the startup pipeline Stage 7 (which sets
        ``_startup_market_data_done``) before entering the scheduling loop,
        so the first market data sync always runs as part of the startup
        pipeline rather than independently.
        """
        from app.backgroundtasks._runtime import (
            _is_job_enabled,
            _seconds_until_next_cron,
            _startup_market_data_done,
            get_async_shutdown_event,
        )
        from app.jobs.runner import update_job_status
        from app.services.data_sync.market import (
            _is_market_open,
            _market_data_sync,
            _seconds_until_market_open,
        )

        shutdown_event = get_async_shutdown_event()

        # Wait for startup pipeline Stage 7 to complete before entering loop
        logger.info("market_data_scheduler: waiting for startup pipeline Stage 7")
        while not _startup_market_data_done.is_set():
            try:
                await asyncio.wait_for(
                    _wait_for_shutdown(shutdown_event), timeout=1.0
                )
                return  # shutdown requested while waiting
            except asyncio.TimeoutError:
                pass

        if not _is_job_enabled("job.market_data"):
            logger.info("market_data_scheduler: disabled")
            return

        logger.info("market_data_scheduler: entering main loop")

        while not shutdown_event.is_set():
            now_utc = datetime.now(timezone.utc)

            if _is_market_open():
                # During market hours: use */5 cron schedule
                wait_secs = _seconds_until_next_cron("*/5 * * * *")
                next_trigger = now_utc + timedelta(seconds=wait_secs)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, _update_fv_job_waiting, "job.market_data",
                    next_trigger, wait_secs,
                )
                try:
                    await asyncio.wait_for(
                        _wait_for_shutdown(shutdown_event), timeout=wait_secs,
                    )
                    break
                except asyncio.TimeoutError:
                    pass
                if shutdown_event.is_set():
                    break

                # Re-check market is still open before fetching
                if _is_market_open():
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, _market_data_sync)
            else:
                # Market closed: sleep until next market open
                wait_secs = _seconds_until_market_open()
                next_trigger = now_utc + timedelta(seconds=wait_secs)
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, _update_fv_job_waiting, "job.market_data",
                    next_trigger, wait_secs,
                )
                try:
                    await asyncio.wait_for(
                        _wait_for_shutdown(shutdown_event), timeout=wait_secs,
                    )
                    break
                except asyncio.TimeoutError:
                    pass

        logger.info("market_data_scheduler: stopped")

    async def _run_nightly_pipeline_scheduler(self) -> None:
        """Asyncio loop: sleep until 23:00 IST each day then run the nightly pipeline."""
        nightly_cron = f"{_NIGHTLY_MINUTE_IST} {_NIGHTLY_HOUR_IST} * * *"
        await _cron_loop(
            cron_expr=nightly_cron,
            job_key="job.pipeline.nightly",
            target_fn=lambda: self.run_pipeline(PipelineMode.NIGHTLY),
            compute_wait_secs=_seconds_until_next_cron_ist,
            next_fire_label_fn=_next_fire_time_ist,
            schedule_label="nightly pipeline",
        )

    async def _run_watchlist_fair_value_scheduler(self) -> None:
        """Asyncio loop: run watchlist fair value sync every 3 hours."""
        from app.backgroundtasks._runtime import _seconds_until_next_cron
        from app.services.fair_value import sync_watchlist_fair_values

        await _cron_loop(
            cron_expr="0 */3 * * *",
            job_key="job.watchlist_fair_value",
            target_fn=sync_watchlist_fair_values,
            compute_wait_secs=_seconds_until_next_cron,
            next_fire_label_fn=None,
            schedule_label="watchlist fair value",
        )

    async def _run_full_fair_value_scheduler(self) -> None:
        """Asyncio loop: run full universe fair value sync daily at 23:30 IST."""
        from app.services.fair_value import sync_all_fair_values

        await _cron_loop(
            cron_expr="30 23 * * *",  # 23:30 IST
            job_key="job.full_fair_value",
            target_fn=sync_all_fair_values,
            compute_wait_secs=_seconds_until_next_cron_ist,
            next_fire_label_fn=_next_fire_time_ist,
            schedule_label="full fair value sync",
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
orchestrator = Orchestrator()


# ---------------------------------------------------------------------------
# Helpers (module-level, not methods)
# ---------------------------------------------------------------------------

def _run_pipeline_stage(
    sync_fn,
    pipeline_lock: threading.Lock,
    pipeline_idle: threading.Event,
) -> None:
    """Acquire the threading pipeline lock, clear _pipeline_idle, run *sync_fn*, then restore idle.

    Called from run_in_executor so it executes in a thread pool worker.
    This mirrors the pattern used by ticker_daily_update_worker,
    ticker_indicators_worker, and ticker_scores_worker for their cron cycles.
    """
    with pipeline_lock:
        pipeline_idle.clear()
        try:
            sync_fn()
        finally:
            pipeline_idle.set()


async def _wait_for_shutdown(shutdown_event: asyncio.Event) -> None:
    """Coroutine that completes only when the shutdown event is set.

    Audit B.11: replaced the ``asyncio.sleep(1)`` poll loop with a
    direct ``await shutdown_event.wait()`` — fires immediately on
    ``.set()`` and uses zero CPU while waiting.  Behaviour is
    equivalent for the callers (they wrap this in ``asyncio.wait`` /
    ``asyncio.gather`` to race it against a job execution).
    """
    await shutdown_event.wait()


async def _cron_loop(
    cron_expr: str,
    job_key: str,
    target_fn,
    *,
    compute_wait_secs,
    next_fire_label_fn=None,
    schedule_label: str,
) -> None:
    """Generic cron-driven job loop (audit B.11).

    Replaces three near-identical schedulers
    (``_run_nightly_pipeline_scheduler``,
    ``_run_watchlist_fair_value_scheduler``,
    ``_run_full_fair_value_scheduler``) with a single body.  Each
    scheduler is now a 7-line configuration of this helper.

    Behaviour:
        loop forever (until ``shutdown_event`` is set):
            1. ``wait_secs = compute_wait_secs(cron_expr)``
            2. write a 'waiting' status to the jobs table
            3. ``asyncio.wait_for(_wait_for_shutdown, wait_secs)``
               — returns early on shutdown, raises TimeoutError on
               next fire
            4. on TimeoutError: run ``await target_fn()`` and repeat
            5. on early return: exit

    ``target_fn`` is awaited; pass ``lambda: sync_blocking_fn()`` if
    the underlying work is synchronous.  Exceptions in ``target_fn``
    are NOT caught here — the caller's task will fail and the
    orchestrator's broader error handler will log it.
    """
    from app.backgroundtasks._runtime import get_async_shutdown_event

    shutdown_event = get_async_shutdown_event()
    while not shutdown_event.is_set():
        wait_secs = compute_wait_secs(cron_expr)
        next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
        if next_fire_label_fn is not None:
            logger.info(
                "Orchestrator: %s scheduled in %.0f s (%s)",
                schedule_label, wait_secs, next_fire_label_fn(cron_expr),
            )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _update_fv_job_waiting, job_key, next_trigger, wait_secs,
        )
        try:
            await asyncio.wait_for(
                _wait_for_shutdown(shutdown_event), timeout=wait_secs,
            )
            break
        except asyncio.TimeoutError:
            pass
        if shutdown_event.is_set():
            break
        await target_fn()
    logger.info("Orchestrator: %s scheduler stopped", schedule_label)


def _seconds_until_next_cron_ist(cron_expr: str) -> float:
    """Return seconds from now until the next fire of *cron_expr*, evaluated in IST."""
    from croniter import croniter
    now_ist = datetime.now(_IST).replace(tzinfo=None)  # croniter works with naive datetimes
    return (croniter(cron_expr, now_ist).get_next(datetime) - now_ist).total_seconds()


def _next_fire_time_ist(cron_expr: str) -> str:
    """Return a human-readable next fire time string in IST."""
    from croniter import croniter
    now_ist = datetime.now(_IST).replace(tzinfo=None)
    next_dt = croniter(cron_expr, now_ist).get_next(datetime)
    return next_dt.strftime("%Y-%m-%d %H:%M")


def _update_fv_job_waiting(
    job_key: str,
    next_trigger: datetime,
    wait_secs: float,
) -> None:
    """Set a fair-value job to 'waiting' with next_trigger in the DB."""
    from app.jobs.runner import update_job_status_sync
    update_job_status_sync(
        job_key, "waiting", progress=100,
        message=f"Next run in {wait_secs / 3600:.1f}h",
        next_trigger=next_trigger,
    )

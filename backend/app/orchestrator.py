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

Independent workers (news, market data, results calendar, fair value,
ticker_intraday_hourly_update, ticker_intraday_hourly_indicators) are
started immediately and self-manage their own cron schedules — the orchestrator
does not sequence them.

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

import pytz

logger = logging.getLogger(__name__)

# IST timezone constant
_IST = pytz.timezone("Asia/Kolkata")

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
        # Import here to avoid circular imports at module load time
        from app.backgroundtasks import (
            start_all_workers,
            reset_async_shutdown_event,
            get_async_shutdown_event,
            sync_all_fair_values,
            sync_watchlist_fair_values,
            _is_first_run,
            _set_first_run_complete,
            _should_trigger_full_sync,
        )
        from app.services.morningstar_client import init_client

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

        # Kick off the startup pipeline in a background asyncio task so lifespan
        # can continue (MCP session manager must start before yield).
        self._asyncio_tasks.append(
            asyncio.create_task(self._run_startup_pipeline(), name="startup-pipeline")
        )

        logger.info("Orchestrator started — startup pipeline queued, nightly scheduler active at %02d:%02d IST",
                    _NIGHTLY_HOUR_IST, _NIGHTLY_MINUTE_IST)

    async def stop(self) -> None:
        """Cancel all orchestrator-owned asyncio tasks and stop all workers."""
        from app.backgroundtasks import (
            set_async_shutdown_event,
            stop_all_workers,
        )
        from app.services.morningstar_client import close_client
        from app.services.ai_summarizer import ai_summarizer
        from app.services.nse_client import nse_client
        from app.services.screener_client import screener_client
        from app.services.news_fetcher import news_fetcher

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
        from app.backgroundtasks import _is_job_enabled

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

    async def _execute_pipeline(self, mode: PipelineMode) -> None:
        from app.backgroundtasks import (
            _is_job_enabled,
            _stock_universe_sync,
            _ticker_backfill_sync,
            _ticker_daily_update_sync,
            _ticker_intraday_hourly_stale_check_sync,
            _ticker_indicators_sync,
            _ticker_scores_sync,
            _ticker_intraday_update_sync,
            _ticker_intraday_indicators_sync,
            _global_scan_cycle,
            _notification_cycle_full,
            _startup_stock_universe_done,
            _startup_ticker_backfill_done,
            _startup_ticker_indicators_done,
            _startup_ticker_scores_done,
            _pipeline_lock,
            _pipeline_idle,
            _shutdown_event,
        )
        from app.jobs.runner import update_job_status

        pipeline_job_key = (
            "job.pipeline.startup" if mode == PipelineMode.STARTUP else "job.pipeline.nightly"
        )

        logger.info("Orchestrator: starting %s pipeline", mode.value)
        await update_job_status(pipeline_job_key, "running", progress=0,
                                message=f"Starting {mode.value} pipeline...")

        loop = asyncio.get_running_loop()

        try:
            # ── Stage 1: Stock Universe ────────────────────────────────────
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 1: stock_universe", mode.value)
            if _is_job_enabled("job.stock_universe"):
                await update_job_status(pipeline_job_key, "running", progress=5,
                                        message="Stage 1/7: Syncing stock universe...")
                await loop.run_in_executor(None, _stock_universe_sync)
            else:
                await update_job_status(pipeline_job_key, "running", progress=15,
                                        message="Stage 1/7 skipped — job.stock_universe disabled")
                logger.info("Orchestrator [%s] Stage 1 skipped: job.stock_universe disabled", mode.value)
            # Set gate so worker cron loops can proceed even when skipped
            _startup_stock_universe_done.set()
            logger.info("Orchestrator [%s] Stage 1 complete", mode.value)
            if _is_job_enabled("job.stock_universe"):
                await update_job_status(pipeline_job_key, "running", progress=15,
                                        message="Stage 1/7 complete — stock universe synced")

            # ── Stage 2 (nightly only): Daily update / bhavcopy ───────────
            if mode == PipelineMode.NIGHTLY:
                if _shutdown_event.is_set():
                    return
                logger.info("Orchestrator [%s] Stage 2a: ticker_daily_update", mode.value)
                if _is_job_enabled("job.ticker_daily_update"):
                    await update_job_status(pipeline_job_key, "running", progress=18,
                                            message="Stage 2a/7: Downloading bhavcopy...")
                    # Acquire pipeline lock so scan/notif workers pause
                    await loop.run_in_executor(None, _run_pipeline_stage,
                                               _ticker_daily_update_sync, _pipeline_lock, _pipeline_idle)
                else:
                    await update_job_status(pipeline_job_key, "running", progress=28,
                                            message="Stage 2a/7 skipped — job.ticker_daily_update disabled")
                    logger.info("Orchestrator [%s] Stage 2a skipped: job.ticker_daily_update disabled", mode.value)
                logger.info("Orchestrator [%s] Stage 2a complete", mode.value)
                if _is_job_enabled("job.ticker_daily_update"):
                    await update_job_status(pipeline_job_key, "running", progress=28,
                                            message="Stage 2a/7 complete — bhavcopy downloaded")

            # ── Stage 2b: Backfill ─────────────────────────────────────────
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 2b: ticker_backfill", mode.value)
            if _is_job_enabled("job.ticker_backfill"):
                await update_job_status(pipeline_job_key, "running", progress=30,
                                        message="Stage 2b/7: Backfilling OHLCV history...")
                await loop.run_in_executor(None, _ticker_backfill_sync)
            else:
                await update_job_status(pipeline_job_key, "running", progress=40,
                                        message="Stage 2b/7 skipped — job.ticker_backfill disabled")
                logger.info("Orchestrator [%s] Stage 2b skipped: job.ticker_backfill disabled", mode.value)
            _startup_ticker_backfill_done.set()
            logger.info("Orchestrator [%s] Stage 2b complete", mode.value)
            if _is_job_enabled("job.ticker_backfill"):
                await update_job_status(pipeline_job_key, "running", progress=40,
                                        message="Stage 2b/7 complete — backfill done")

            # ── Stage 2c: Hourly 1h stale-check ────────────────────────────
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 2c: ticker_intraday_hourly_stale_check", mode.value)
            if _is_job_enabled("job.ticker_intraday_hourly_stale_check"):
                await update_job_status(pipeline_job_key, "running", progress=42,
                                        message="Stage 2c/7: Checking 1h intraday gaps...")
                await loop.run_in_executor(None, _run_pipeline_stage,
                                           _ticker_intraday_hourly_stale_check_sync, _pipeline_lock, _pipeline_idle)
            else:
                await update_job_status(pipeline_job_key, "running", progress=48,
                                        message="Stage 2c/7 skipped — job.ticker_intraday_hourly_stale_check disabled")
                logger.info("Orchestrator [%s] Stage 2c skipped: job.ticker_intraday_hourly_stale_check disabled", mode.value)
            logger.info("Orchestrator [%s] Stage 2c complete", mode.value)
            if _is_job_enabled("job.ticker_intraday_hourly_stale_check"):
                await update_job_status(pipeline_job_key, "running", progress=48,
                                        message="Stage 2c/7 complete — 1h candles reconciled")

            # ── Stage 3: Indicators ────────────────────────────────────────
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 3: ticker_indicators", mode.value)
            if _is_job_enabled("job.ticker_indicators"):
                await update_job_status(pipeline_job_key, "running", progress=50,
                                        message="Stage 3/7: Computing indicators...")
                # Acquire pipeline lock — indicators modify data read by scan/notif
                await loop.run_in_executor(None, _run_pipeline_stage,
                                           _ticker_indicators_sync, _pipeline_lock, _pipeline_idle)
            else:
                await update_job_status(pipeline_job_key, "running", progress=62,
                                        message="Stage 3/7 skipped — job.ticker_indicators disabled")
                logger.info("Orchestrator [%s] Stage 3 skipped: job.ticker_indicators disabled", mode.value)
            _startup_ticker_indicators_done.set()
            logger.info("Orchestrator [%s] Stage 3 complete", mode.value)
            if _is_job_enabled("job.ticker_indicators"):
                await update_job_status(pipeline_job_key, "running", progress=62,
                                        message="Stage 3/7 complete — indicators computed")

            # ── Stage 4: Scores ────────────────────────────────────────────
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 4: ticker_scores", mode.value)
            if _is_job_enabled("job.ticker_scores"):
                await update_job_status(pipeline_job_key, "running", progress=64,
                                        message="Stage 4/7: Computing momentum scores...")
                # Acquire pipeline lock — scores modify data read by scan/notif
                await loop.run_in_executor(None, _run_pipeline_stage,
                                           _ticker_scores_sync, _pipeline_lock, _pipeline_idle)
            else:
                await update_job_status(pipeline_job_key, "running", progress=74,
                                        message="Stage 4/7 skipped — job.ticker_scores disabled")
                logger.info("Orchestrator [%s] Stage 4 skipped: job.ticker_scores disabled", mode.value)
            _startup_ticker_scores_done.set()
            logger.info("Orchestrator [%s] Stage 4 complete", mode.value)
            if _is_job_enabled("job.ticker_scores"):
                await update_job_status(pipeline_job_key, "running", progress=74,
                                        message="Stage 4/7 complete — scores computed")

            # ── Stage 5 (nightly only): Weekly + Monthly candles ─────────────
            if mode == PipelineMode.NIGHTLY:
                if _shutdown_event.is_set():
                    return
                logger.info("Orchestrator [%s] Stage 5a: ticker_weekly_monthly_update", mode.value)
                if _is_job_enabled("job.ticker_weekly_monthly_update"):
                    await update_job_status(pipeline_job_key, "running", progress=76,
                                            message="Stage 5a/7: Backfilling W/M candles...")
                    await loop.run_in_executor(None, _run_pipeline_stage,
                                               lambda: _ticker_intraday_update_sync(["W", "M"]),
                                               _pipeline_lock, _pipeline_idle)
                else:
                    await update_job_status(pipeline_job_key, "running", progress=82,
                                            message="Stage 5a/7 skipped — job.ticker_weekly_monthly_update disabled")
                    logger.info("Orchestrator [%s] Stage 5a skipped: job.ticker_weekly_monthly_update disabled", mode.value)
                logger.info("Orchestrator [%s] Stage 5a complete", mode.value)
                if _is_job_enabled("job.ticker_weekly_monthly_update"):
                    await update_job_status(pipeline_job_key, "running", progress=82,
                                            message="Stage 5a/7 complete — W/M candles synced")

                if _shutdown_event.is_set():
                    return
                logger.info("Orchestrator [%s] Stage 5b: ticker_weekly_monthly_indicators", mode.value)
                if _is_job_enabled("job.ticker_weekly_monthly_indicators"):
                    await update_job_status(pipeline_job_key, "running", progress=84,
                                            message="Stage 5b/7: Computing W/M indicators...")
                    await loop.run_in_executor(None, _run_pipeline_stage,
                                               lambda: _ticker_intraday_indicators_sync(["W", "M"]),
                                               _pipeline_lock, _pipeline_idle)
                else:
                    await update_job_status(pipeline_job_key, "running", progress=88,
                                            message="Stage 5b/7 skipped — job.ticker_weekly_monthly_indicators disabled")
                    logger.info("Orchestrator [%s] Stage 5b skipped: job.ticker_weekly_monthly_indicators disabled", mode.value)
                logger.info("Orchestrator [%s] Stage 5b complete", mode.value)
                if _is_job_enabled("job.ticker_weekly_monthly_indicators"):
                    await update_job_status(pipeline_job_key, "running", progress=88,
                                            message="Stage 5b/7 complete — W/M indicators computed")

            # ── Stage 6: Scan + Notif (immediate cycle) ────────────────────
            # Pipeline is now idle (_pipeline_idle already set by the lock helper).
            # Trigger one immediate cycle of both scan and notif concurrently.
            if _shutdown_event.is_set():
                return
            logger.info("Orchestrator [%s] Stage 6: scan + notif", mode.value)
            await update_job_status(pipeline_job_key, "running", progress=90,
                                    message="Stage 6/7: Running scan and notifications...")
            stage6_tasks = []
            if _is_job_enabled("job.global_scan"):
                stage6_tasks.append(loop.run_in_executor(None, _global_scan_cycle))
            else:
                logger.info("Orchestrator [%s] Stage 6 scan skipped: job.global_scan disabled", mode.value)
            if _is_job_enabled("job.notifications"):
                stage6_tasks.append(loop.run_in_executor(None, _notification_cycle_full))
            else:
                logger.info("Orchestrator [%s] Stage 6 notifications skipped: job.notifications disabled", mode.value)
            if stage6_tasks:
                await asyncio.gather(*stage6_tasks)
            else:
                await update_job_status(pipeline_job_key, "running", progress=95,
                                        message="Stage 6/7 skipped — scan and notifications disabled")
            logger.info("Orchestrator [%s] Stage 6 complete", mode.value)

            now = datetime.now(timezone.utc)
            next_trig: datetime | None = None
            if mode == PipelineMode.NIGHTLY:
                wait = _seconds_until_next_cron_ist(f"{_NIGHTLY_MINUTE_IST} {_NIGHTLY_HOUR_IST} * * *")
                next_trig = now + timedelta(seconds=wait)

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
                description="Full ordered pipeline: universe → backfill → indicators → scores → scan/notif",
                category="pipeline",
                cron_expression="@startup",
                callable=_run_startup,
                is_async=True,
            ),
            JobDefinition(
                job_key="job.pipeline.nightly",
                name="pipeline_nightly",
                description="Nightly ordered pipeline: universe → daily_update → backfill → indicators → scores → scan/notif",
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

    async def _run_nightly_pipeline_scheduler(self) -> None:
        """Asyncio loop: sleep until 23:00 IST each day then run the nightly pipeline."""
        from app.backgroundtasks import get_async_shutdown_event

        shutdown_event = get_async_shutdown_event()
        nightly_cron = f"{_NIGHTLY_MINUTE_IST} {_NIGHTLY_HOUR_IST} * * *"

        while not shutdown_event.is_set():
            wait_secs = _seconds_until_next_cron_ist(nightly_cron)
            next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
            logger.info(
                "Orchestrator: nightly pipeline scheduled in %.0f s (%s IST)",
                wait_secs,
                _next_fire_time_ist(nightly_cron),
            )
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                _update_fv_job_waiting,
                "job.pipeline.nightly",
                next_trigger,
                wait_secs,
            )
            try:
                await asyncio.wait_for(
                    _wait_for_shutdown(shutdown_event),
                    timeout=wait_secs,
                )
                break
            except asyncio.TimeoutError:
                pass

            if shutdown_event.is_set():
                break

            logger.info("Orchestrator: nightly pipeline triggered (23:00 IST)")
            await self.run_pipeline(PipelineMode.NIGHTLY)

        logger.info("Orchestrator: nightly pipeline scheduler stopped")

    async def _run_watchlist_fair_value_scheduler(self) -> None:
        """Asyncio loop: run watchlist fair value sync every 3 hours."""
        from app.backgroundtasks import (
            get_async_shutdown_event,
            _seconds_until_next_cron,
            sync_watchlist_fair_values,
        )

        shutdown_event = get_async_shutdown_event()
        wfv_cron = "0 */3 * * *"

        while not shutdown_event.is_set():
            wait_secs = _seconds_until_next_cron(wfv_cron)
            next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                _update_fv_job_waiting,
                "job.watchlist_fair_value",
                next_trigger,
                wait_secs,
            )

            try:
                await asyncio.wait_for(
                    _wait_for_shutdown(shutdown_event),
                    timeout=wait_secs,
                )
                break
            except asyncio.TimeoutError:
                pass

            if shutdown_event.is_set():
                break
            await sync_watchlist_fair_values()

        logger.info("Orchestrator: watchlist fair value scheduler stopped")

    async def _run_full_fair_value_scheduler(self) -> None:
        """Asyncio loop: run full universe fair value sync daily at 23:30 IST."""
        from app.backgroundtasks import get_async_shutdown_event, sync_all_fair_values
        from app.jobs.runner import update_job_status_sync

        shutdown_event = get_async_shutdown_event()
        fv_cron = "30 23 * * *"  # 23:30 IST

        while not shutdown_event.is_set():
            wait_secs = _seconds_until_next_cron_ist(fv_cron)
            next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
            logger.info(
                "Orchestrator: full fair value sync scheduled in %.0f s (%s IST)",
                wait_secs, _next_fire_time_ist(fv_cron),
            )

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                _update_fv_job_waiting,
                "job.full_fair_value",
                next_trigger,
                wait_secs,
            )

            try:
                await asyncio.wait_for(
                    _wait_for_shutdown(shutdown_event),
                    timeout=wait_secs,
                )
                break
            except asyncio.TimeoutError:
                pass

            if shutdown_event.is_set():
                break
            await sync_all_fair_values()

        logger.info("Orchestrator: full fair value scheduler stopped")


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
    """Coroutine that completes only when the shutdown event is set."""
    while not shutdown_event.is_set():
        await asyncio.sleep(1)


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

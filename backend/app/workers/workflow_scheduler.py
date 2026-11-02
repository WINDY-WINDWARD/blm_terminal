"""Daemon worker and scheduler for automated AI workflows."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models.ai_workflow import AiWorkflow, AiWorkflowRun
from app.services.workflow_runner import run_workflow
from app.services.workflow_schedule import next_run, next_runs, slot_key

logger = logging.getLogger(__name__)

JOB_KEY = "job.ai_workflows_scheduler"
SWEEP_SECONDS = 30
# A slot that is only slightly late is normal scheduling jitter, not a miss.
# Slots older than this are handled by catch_up_missed instead of enqueue_due_runs.
CATCH_UP_GRACE_SECONDS = 120


async def recover_stale_runs(now_utc: datetime) -> int:
    """Recover runs stuck in 'running' state older than 20 minutes as 'failed'."""
    cutoff = now_utc - timedelta(minutes=20)
    count = 0
    async with AsyncSessionLocal() as db:
        stmt = select(AiWorkflowRun).where(
            AiWorkflowRun.status == "running",
            AiWorkflowRun.started_at < cutoff,
        )
        runs = (await db.execute(stmt)).scalars().all()
        for run in runs:
            run.status = "failed"
            run.error = "interrupted"
            run.finished_at = now_utc
            if run.started_at:
                run.duration_ms = max(0, int((now_utc - run.started_at).total_seconds() * 1000))
            count += 1
        if count > 0:
            await db.commit()
    return count


async def catch_up_missed(now_utc: datetime) -> int:
    """Catch up or skip missed slots for enabled non-deleted workflows."""
    count = 0
    grace_cutoff = now_utc - timedelta(seconds=CATCH_UP_GRACE_SECONDS)
    async with AsyncSessionLocal() as db:
        stmt = select(AiWorkflow).where(
            AiWorkflow.is_enabled == True,
            AiWorkflow.deleted_at.is_(None),
            AiWorkflow.next_run_at.is_not(None),
            AiWorkflow.next_run_at <= grace_cutoff,
        )
        workflows = (await db.execute(stmt)).scalars().all()

        for wf in workflows:
            if not wf.next_run_at:
                continue

            if wf.schedule_type == "once":
                late_hrs = (now_utc - wf.next_run_at).total_seconds() / 3600.0
                run_status = "queued" if (wf.catch_up_enabled and late_hrs <= wf.catch_up_window_hours) else "skipped"
                db.add(
                    AiWorkflowRun(
                        workflow_id=wf.id,
                        user_id=wf.user_id,
                        trigger="catch_up",
                        status=run_status,
                        skip_reason=None if run_status == "queued" else "missed_window",
                        scheduled_for=wf.next_run_at,
                        slot_key=slot_key(wf.id, wf.next_run_at),
                        name_snapshot=wf.name,
                        prompt_snapshot=wf.prompt,
                    )
                )
                wf.is_enabled = False
                wf.next_run_at = None
                try:
                    await db.commit()
                    count += 1
                except IntegrityError:
                    await db.rollback()
                continue

            current_slot_k = slot_key(wf.id, wf.next_run_at)
            existing_run = (
                await db.execute(
                    select(AiWorkflowRun).where(
                        AiWorkflowRun.workflow_id == wf.id,
                        AiWorkflowRun.slot_key == current_slot_k,
                    )
                )
            ).scalars().first()

            if existing_run:
                continue

            try:
                future_runs = next_runs(wf.cron_expression, wf.timezone, wf.next_run_at, count=50)
            except Exception as e:
                logger.warning("Failed computing next_runs for workflow %d: %s", wf.id, e)
                continue

            subsequent = [dt for dt in future_runs if dt <= now_utc]

            if not subsequent:
                lateness_hrs = (now_utc - wf.next_run_at).total_seconds() / 3600.0
                catchable = wf.catch_up_enabled and lateness_hrs <= wf.catch_up_window_hours
                run_record = AiWorkflowRun(
                    workflow_id=wf.id,
                    user_id=wf.user_id,
                    trigger="catch_up",
                    status="queued" if catchable else "skipped",
                    skip_reason=None if catchable else "missed_window",
                    scheduled_for=wf.next_run_at,
                    slot_key=current_slot_k,
                    name_snapshot=wf.name,
                    prompt_snapshot=wf.prompt,
                )
                db.add(run_record)
                try:
                    wf.next_run_at = next_run(wf.cron_expression, wf.timezone, now_utc)
                except Exception:
                    pass
                try:
                    await db.commit()
                    count += 1
                except IntegrityError:
                    await db.rollback()
                continue

            all_slots = ([wf.next_run_at] + subsequent)[:50]

            # Write "skipped" run with skip_reason "missed_window" for all except the last
            for slot in all_slots[:-1]:
                slot_k = slot_key(wf.id, slot)
                skipped_run = AiWorkflowRun(
                    workflow_id=wf.id,
                    user_id=wf.user_id,
                    trigger="catch_up",
                    status="skipped",
                    skip_reason="missed_window",
                    scheduled_for=slot,
                    slot_key=slot_k,
                    name_snapshot=wf.name,
                    prompt_snapshot=wf.prompt,
                )
                db.add(skipped_run)

            # For the last slot, write "catch_up" or "skipped"
            last_slot = all_slots[-1]
            last_slot_k = slot_key(wf.id, last_slot)
            last_lateness_hrs = (now_utc - last_slot).total_seconds() / 3600.0

            if wf.catch_up_enabled and last_lateness_hrs <= wf.catch_up_window_hours:
                last_run = AiWorkflowRun(
                    workflow_id=wf.id,
                    user_id=wf.user_id,
                    trigger="catch_up",
                    status="queued",
                    scheduled_for=last_slot,
                    slot_key=last_slot_k,
                    name_snapshot=wf.name,
                    prompt_snapshot=wf.prompt,
                )
            else:
                last_run = AiWorkflowRun(
                    workflow_id=wf.id,
                    user_id=wf.user_id,
                    trigger="catch_up",
                    status="skipped",
                    skip_reason="missed_window",
                    scheduled_for=last_slot,
                    slot_key=last_slot_k,
                    name_snapshot=wf.name,
                    prompt_snapshot=wf.prompt,
                )
            db.add(last_run)

            # Set next_run_at to the next future occurrence
            try:
                wf.next_run_at = next_run(wf.cron_expression, wf.timezone, now_utc)
            except Exception as e:
                logger.warning("Failed advancing next_run_at for workflow %d: %s", wf.id, e)

            try:
                await db.commit()
                count += len(all_slots)
            except IntegrityError:
                await db.rollback()

    return count


async def enqueue_due_runs(now_utc: datetime) -> int:
    """Enqueue scheduled runs for enabled workflows whose next_run_at is due."""
    count = 0
    async with AsyncSessionLocal() as db:
        stmt = select(AiWorkflow).where(
            AiWorkflow.is_enabled == True,
            AiWorkflow.deleted_at.is_(None),
            AiWorkflow.next_run_at.is_not(None),
            AiWorkflow.next_run_at <= now_utc,
        )
        workflows = (await db.execute(stmt)).scalars().all()

        for wf in workflows:
            if not wf.next_run_at:
                continue

            scheduled_slot = wf.next_run_at
            sk = slot_key(wf.id, scheduled_slot)

            active_check = await db.execute(
                select(AiWorkflowRun).where(
                    AiWorkflowRun.workflow_id == wf.id,
                    AiWorkflowRun.status.in_(["queued", "running"]),
                )
            )
            is_active = active_check.scalars().first() is not None

            if is_active:
                run_record = AiWorkflowRun(
                    workflow_id=wf.id,
                    user_id=wf.user_id,
                    trigger="schedule",
                    status="skipped",
                    skip_reason="still_running",
                    scheduled_for=scheduled_slot,
                    slot_key=sk,
                    name_snapshot=wf.name,
                    prompt_snapshot=wf.prompt,
                )
            else:
                run_record = AiWorkflowRun(
                    workflow_id=wf.id,
                    user_id=wf.user_id,
                    trigger="schedule",
                    status="queued",
                    scheduled_for=scheduled_slot,
                    slot_key=sk,
                    name_snapshot=wf.name,
                    prompt_snapshot=wf.prompt,
                )
            db.add(run_record)

            # Advance next_run_at
            if wf.schedule_type == "once":
                wf.is_enabled = False
                wf.next_run_at = None
            else:
                try:
                    wf.next_run_at = next_run(wf.cron_expression, wf.timezone, scheduled_slot)
                except Exception as e:
                    logger.warning("Failed advancing next_run_at for workflow %d: %s", wf.id, e)

            try:
                await db.commit()
                count += 1
            except IntegrityError:
                await db.rollback()

    return count


async def execute_pending() -> int:
    """Execute up to 5 queued runs sequentially and schedule retries on failure."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    executed_count = 0

    async with AsyncSessionLocal() as db:
        stmt = (
            select(AiWorkflowRun)
            .where(
                AiWorkflowRun.status == "queued",
                AiWorkflowRun.scheduled_for <= now_utc,
            )
            .order_by(AiWorkflowRun.created_at)
            .limit(5)
        )
        pending_runs = (await db.execute(stmt)).scalars().all()
        run_items = [(r.id, r.workflow_id, r.attempt, r.trigger, r.name_snapshot, r.prompt_snapshot, r.user_id) for r in pending_runs]

    for run_id, workflow_id, attempt, trigger, name_snapshot, prompt_snapshot, user_id in run_items:
        outcome = await run_workflow(workflow_id, run_id)
        executed_count += 1

        if outcome.startswith("error:"):
            async with AsyncSessionLocal() as db:
                wf = await db.get(AiWorkflow, workflow_id)
                # After a failure with attempt < 3 and workflow.allow_write_tools False, insert one queued retry run
                if wf and not wf.allow_write_tools and attempt < 3:
                    retry_now = datetime.now(timezone.utc).replace(tzinfo=None)
                    delay_mins = [5, 15, 30][attempt]
                    retry_scheduled_for = retry_now + timedelta(minutes=delay_mins)
                    retry_slot_key = f"{workflow_id}:retry{attempt + 1}:{int(retry_now.timestamp())}"

                    retry_run = AiWorkflowRun(
                        workflow_id=workflow_id,
                        user_id=user_id,
                        trigger=trigger,
                        status="queued",
                        attempt=attempt + 1,
                        scheduled_for=retry_scheduled_for,
                        slot_key=retry_slot_key,
                        name_snapshot=name_snapshot,
                        prompt_snapshot=prompt_snapshot,
                    )
                    db.add(retry_run)
                    try:
                        await db.commit()
                    except IntegrityError:
                        await db.rollback()

    return executed_count


async def run_sweep_once() -> str:
    """Execute a single sweep of the AI workflows scheduler."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    stale_count = await recover_stale_runs(now_utc)
    catchup_count = await catch_up_missed(now_utc)
    enqueued_count = await enqueue_due_runs(now_utc)
    executed_count = await execute_pending()
    return (
        f"Sweep completed: {stale_count} stale recovered, "
        f"{catchup_count} missed processed, "
        f"{enqueued_count} enqueued, "
        f"{executed_count} executed"
    )


def workflow_scheduler_worker() -> None:
    """Daemon thread for the AI workflows scheduler worker."""
    from app.backgroundtasks._runtime import (
        _is_job_enabled,
        _report_job_waiting,
        _run_async,
        _shutdown_event,
        _sleep_interruptible,
    )
    from app.jobs.runner import update_job_status_sync
    from app.workers.lifecycle import _startup_pipeline_done

    _startup_pipeline_done.wait()
    logger.info("AI Workflows Scheduler daemon started.")

    try:
        if _is_job_enabled(JOB_KEY):
            update_job_status_sync(JOB_KEY, "running", progress=10, message="Executing initial sweep...")
            summary = _run_async(run_sweep_once())
            logger.info("AI Workflows Scheduler initial sweep: %s", summary)
            update_job_status_sync(
                JOB_KEY, "completed", progress=100, message=summary, last_completed=datetime.now(timezone.utc)
            )
    except Exception as exc:
        logger.error("AI Workflows Scheduler initial sweep error: %s", exc, exc_info=True)
        update_job_status_sync(JOB_KEY, "failed", progress=0, message="Initial sweep failed", error=str(exc)[:512])

    while not _shutdown_event.is_set():
        if not _is_job_enabled(JOB_KEY):
            update_job_status_sync(JOB_KEY, "waiting", progress=0, message="Disabled")
            if _sleep_interruptible(SWEEP_SECONDS):
                break
            continue

        _report_job_waiting(JOB_KEY, "*/1 * * * *", message="Waiting for next sweep...")
        if _sleep_interruptible(SWEEP_SECONDS):
            break

        if not _shutdown_event.is_set():
            try:
                update_job_status_sync(JOB_KEY, "running", progress=10, message="Running sweep...")
                summary = _run_async(run_sweep_once())
                update_job_status_sync(
                    JOB_KEY, "completed", progress=100, message=summary, last_completed=datetime.now(timezone.utc)
                )
            except Exception as exc:
                logger.error("AI Workflows Scheduler sweep error: %s", exc, exc_info=True)
                update_job_status_sync(JOB_KEY, "failed", progress=0, message="Sweep failed", error=str(exc)[:512])

    update_job_status_sync(JOB_KEY, "idle", progress=0, message="Stopped")

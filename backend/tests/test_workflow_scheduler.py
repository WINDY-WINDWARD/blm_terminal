"""Scheduler-level tests for AI workflow catch-up and due-run enqueueing.

Covers the two behaviours that protect against double runs and stale slots:
- coalesced catch-up (many missed slots -> one run, the rest recorded as skipped)
- idempotent enqueue (a second sweep does not duplicate the slot)
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - populate Base.metadata
from app.config import settings
from app.database import Base
from app.models.ai_workflow import AiWorkflow, AiWorkflowRun
from app.models.user import User
from app.workers import workflow_scheduler as sched


def _scratch_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="blm_workflow_sched_"))


@pytest.fixture
async def session_factory(monkeypatch):
    scratch = _scratch_dir()
    db_file = scratch / "sched_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(sched, "AsyncSessionLocal", factory)

    async with factory() as session:
        session.add(User(id=1, username="alice", hashed_password="x", is_admin=False))
        await session.commit()

    yield factory
    await engine.dispose()
    shutil.rmtree(scratch, ignore_errors=True)


async def _add_workflow(factory, **overrides) -> int:
    fields = {
        "user_id": 1,
        "name": "Morning Briefing",
        "prompt": "Brief me on my watchlist.",
        "schedule_type": "daily",
        "cron_expression": "0 10 * * *",
        "timezone": "Asia/Kolkata",
        "time_of_day": "10:00",
        "mode": "research",
        "is_enabled": True,
        "catch_up_enabled": True,
        "catch_up_window_hours": 12,
        "next_run_at": datetime(2026, 11, 1, 4, 30),
    }
    fields.update(overrides)
    async with factory() as session:
        wf = AiWorkflow(**fields)
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _runs(factory, workflow_id: int) -> list[AiWorkflowRun]:
    async with factory() as session:
        rows = await session.execute(
            select(AiWorkflowRun)
            .where(AiWorkflowRun.workflow_id == workflow_id)
            .order_by(AiWorkflowRun.scheduled_for)
        )
        return list(rows.scalars().all())


async def test_catch_up_coalesces_missed_slots_into_one_run(session_factory):
    wf_id = await _add_workflow(session_factory)

    created = await sched.catch_up_missed(datetime(2026, 11, 5, 9, 0))
    assert created == 5

    runs = await _runs(session_factory, wf_id)
    queued = [r for r in runs if r.status == "queued"]
    skipped = [r for r in runs if r.status == "skipped"]

    assert len(queued) == 1
    assert queued[0].trigger == "catch_up"
    assert queued[0].scheduled_for == datetime(2026, 11, 5, 4, 30)
    assert len(skipped) == 4
    assert all(r.skip_reason == "missed_window" for r in skipped)
    assert all(r.trigger == "catch_up" for r in skipped)

    async with session_factory() as session:
        wf = await session.get(AiWorkflow, wf_id)
        assert wf is not None
        assert wf.next_run_at == datetime(2026, 11, 6, 4, 30)


async def test_catch_up_skips_every_slot_outside_the_window(session_factory):
    wf_id = await _add_workflow(
        session_factory,
        catch_up_window_hours=2,
        next_run_at=datetime(2026, 11, 1, 4, 30),
    )

    await sched.catch_up_missed(datetime(2026, 11, 6, 9, 0))

    runs = await _runs(session_factory, wf_id)
    assert runs
    assert all(r.status == "skipped" for r in runs)
    assert all(r.skip_reason == "missed_window" for r in runs)


async def test_catch_up_ignores_disabled_workflows(session_factory):
    await _add_workflow(session_factory, is_enabled=False)

    created = await sched.catch_up_missed(datetime(2026, 11, 5, 9, 0))

    assert created == 0


async def test_enqueue_due_runs_is_idempotent_per_slot(session_factory):
    wf_id = await _add_workflow(session_factory, next_run_at=datetime(2026, 11, 5, 4, 30))

    first = await sched.enqueue_due_runs(datetime(2026, 11, 5, 5, 0))
    second = await sched.enqueue_due_runs(datetime(2026, 11, 5, 5, 0))

    assert first == 1
    assert second == 0

    runs = await _runs(session_factory, wf_id)
    assert len(runs) == 1
    assert runs[0].status == "queued"
    assert runs[0].trigger == "schedule"
    assert runs[0].slot_key == sched.slot_key(wf_id, datetime(2026, 11, 5, 4, 30))
    assert runs[0].prompt_snapshot == "Brief me on my watchlist."


async def test_enqueue_due_runs_records_overlap_as_skipped(session_factory):
    wf_id = await _add_workflow(session_factory, next_run_at=datetime(2026, 11, 5, 4, 30))

    async with session_factory() as session:
        session.add(
            AiWorkflowRun(
                workflow_id=wf_id,
                user_id=1,
                trigger="schedule",
                status="running",
                scheduled_for=datetime(2026, 11, 4, 4, 30),
                slot_key=sched.slot_key(wf_id, datetime(2026, 11, 4, 4, 30)),
                name_snapshot="Morning Briefing",
                prompt_snapshot="Brief me on my watchlist.",
            )
        )
        await session.commit()

    await sched.enqueue_due_runs(datetime(2026, 11, 5, 5, 0))

    runs = await _runs(session_factory, wf_id)
    newest = runs[-1]
    assert newest.status == "skipped"
    assert newest.skip_reason == "still_running"


async def test_once_workflow_disables_itself_after_enqueue(session_factory):
    wf_id = await _add_workflow(
        session_factory,
        schedule_type="once",
        cron_expression="30 4 5 11 *",
        once_at=datetime(2026, 11, 5, 4, 30),
        next_run_at=datetime(2026, 11, 5, 4, 30),
    )
    await sched.enqueue_due_runs(datetime(2026, 11, 5, 5, 0))

    async with session_factory() as session:
        wf = await session.get(AiWorkflow, wf_id)
        assert wf is not None
        assert wf.is_enabled is False
        assert wf.next_run_at is None


async def test_catch_up_single_missed_slot_inside_window_enqueues_run(session_factory):
    wf_id = await _add_workflow(
        session_factory,
        catch_up_enabled=True,
        catch_up_window_hours=12,
        next_run_at=datetime(2026, 11, 1, 4, 30),
    )

    created = await sched.catch_up_missed(datetime(2026, 11, 1, 6, 0))
    assert created == 1

    runs = await _runs(session_factory, wf_id)
    assert len(runs) == 1
    assert runs[0].trigger == "catch_up"
    assert runs[0].status == "queued"
    assert runs[0].skip_reason is None
    assert runs[0].scheduled_for == datetime(2026, 11, 1, 4, 30)

    async with session_factory() as session:
        wf = await session.get(AiWorkflow, wf_id)
        assert wf is not None
        assert wf.next_run_at == datetime(2026, 11, 2, 4, 30)


async def test_catch_up_single_missed_slot_disabled_catch_up_skips_run(session_factory):
    wf_id = await _add_workflow(
        session_factory,
        catch_up_enabled=False,
        catch_up_window_hours=12,
        next_run_at=datetime(2026, 11, 1, 4, 30),
    )

    created = await sched.catch_up_missed(datetime(2026, 11, 1, 6, 0))
    assert created == 1

    runs = await _runs(session_factory, wf_id)
    assert len(runs) == 1
    assert runs[0].trigger == "catch_up"
    assert runs[0].status == "skipped"
    assert runs[0].skip_reason == "missed_window"
    assert runs[0].scheduled_for == datetime(2026, 11, 1, 4, 30)

    async with session_factory() as session:
        wf = await session.get(AiWorkflow, wf_id)
        assert wf is not None
        assert wf.next_run_at == datetime(2026, 11, 2, 4, 30)


@pytest.mark.asyncio
async def test_execute_pending_waits_for_warmup(monkeypatch):
    """Queued runs stay queued while the provider stack is still warming up."""
    executed: list[tuple] = []

    async def _fake_execute(*args, **kwargs):
        executed.append(args)
        return "ok"

    monkeypatch.setattr(sched, "provider_warmup_remaining", lambda: 30.0)
    monkeypatch.setattr(sched, "provider_stack_ready", lambda: True)
    monkeypatch.setattr(sched, "_execute_and_maybe_retry", _fake_execute)

    assert await sched.execute_pending() == 0
    assert executed == []


@pytest.mark.asyncio
async def test_execute_pending_waits_for_provider_proxy(monkeypatch):
    """A stopped provider proxy parks the queue instead of failing every run."""
    executed: list[tuple] = []

    async def _fake_execute(*args, **kwargs):
        executed.append(args)
        return "ok"

    monkeypatch.setattr(sched, "provider_warmup_remaining", lambda: 0.0)
    monkeypatch.setattr(sched, "provider_stack_ready", lambda: False)
    monkeypatch.setattr(sched, "_execute_and_maybe_retry", _fake_execute)

    assert await sched.execute_pending() == 0
    assert executed == []


@pytest.mark.asyncio
async def test_execute_run_leaves_run_queued_when_provider_never_ready(monkeypatch):
    """A manual run is not started against a provider stack that never comes up."""

    async def _not_ready(timeout=sched.PROVIDER_WAIT_TIMEOUT_SECONDS):
        return False

    monkeypatch.setattr(sched, "wait_for_provider_stack", _not_ready)

    assert await sched.execute_run(4242) == "skipped:provider-not-ready"

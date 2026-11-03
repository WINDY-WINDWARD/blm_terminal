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
async def test_execute_pending_leaves_queue_when_provider_never_starts(monkeypatch):
    """A provider that will not come up parks the queue instead of failing runs."""

    async def _not_ready(timeout=sched.PROVIDER_WAIT_TIMEOUT_SECONDS):
        return False

    async def _fake_execute(*args, **kwargs):
        raise AssertionError("no run should start while the provider is down")

    monkeypatch.setattr(sched, "ensure_provider_stack_ready", _not_ready)
    monkeypatch.setattr(sched, "_execute_and_maybe_retry", _fake_execute)

    assert await sched.execute_pending() == 0


@pytest.mark.asyncio
async def test_ensure_provider_stack_ready_starts_a_stopped_proxy(monkeypatch):
    """A scheduled run must start the proxy instead of waiting for a user request."""
    from app.services import proxy_supervisor, route_registry

    calls = {"ensure": 0}

    class _Supervisor:
        is_running = False

        async def ensure_started(self):
            calls["ensure"] += 1
            self.is_running = True

    supervisor = _Supervisor()

    async def _active_route():
        return "oauth:antigravity"

    monkeypatch.setattr(sched, "provider_warmup_remaining", lambda: 0.0)
    monkeypatch.setattr(proxy_supervisor, "get_proxy_supervisor", lambda: supervisor)
    monkeypatch.setattr(route_registry, "resolve_active_route_id", _active_route)

    assert await sched.ensure_provider_stack_ready(timeout=5) is True
    assert calls["ensure"] == 1


@pytest.mark.asyncio
async def test_ensure_provider_stack_ready_reports_timeout(monkeypatch):
    """A proxy that fails to start returns False so the run stays queued."""
    from app.services import proxy_supervisor, route_registry

    class _Supervisor:
        is_running = False

        async def ensure_started(self):
            raise RuntimeError("proxy missing")

    async def _active_route():
        return "oauth:antigravity"

    monkeypatch.setattr(sched, "provider_warmup_remaining", lambda: 0.0)
    monkeypatch.setattr(proxy_supervisor, "get_proxy_supervisor", lambda: _Supervisor())
    monkeypatch.setattr(route_registry, "resolve_active_route_id", _active_route)

    assert await sched.ensure_provider_stack_ready(timeout=1) is False


@pytest.mark.asyncio
async def test_ensure_provider_stack_ready_skips_the_proxy_for_direct_routes(monkeypatch):
    """A direct route never needs the local proxy."""
    from app.services import proxy_supervisor, route_registry

    class _Supervisor:
        is_running = False

        async def ensure_started(self):
            raise AssertionError("direct routes must not start the proxy")

    async def _active_route():
        return "direct:aistudio"

    monkeypatch.setattr(sched, "provider_warmup_remaining", lambda: 0.0)
    monkeypatch.setattr(proxy_supervisor, "get_proxy_supervisor", lambda: _Supervisor())
    monkeypatch.setattr(route_registry, "resolve_active_route_id", _active_route)

    assert await sched.ensure_provider_stack_ready(timeout=1) is True


@pytest.mark.asyncio
async def test_execute_run_leaves_run_queued_when_provider_never_ready(monkeypatch):
    """A manual run is not started against a provider stack that never comes up."""

    async def _not_ready(timeout=sched.PROVIDER_WAIT_TIMEOUT_SECONDS):
        return False

    monkeypatch.setattr(sched, "ensure_provider_stack_ready", _not_ready)

    assert await sched.execute_run(4242) == "skipped:provider-not-ready"


async def test_enqueue_due_runs_does_not_let_a_queued_run_block_the_slot(session_factory):
    """A waiting queued run must not turn the next scheduled slot into a skip."""
    wf_id = await _add_workflow(session_factory, next_run_at=datetime(2026, 11, 5, 4, 30))

    async with session_factory() as session:
        session.add(
            AiWorkflowRun(
                workflow_id=wf_id,
                user_id=1,
                trigger="manual",
                status="queued",
                scheduled_for=datetime(2026, 11, 4, 4, 30),
                slot_key=f"{wf_id}:manual",
            )
        )
        await session.commit()

    assert await sched.enqueue_due_runs(datetime(2026, 11, 5, 5, 0)) == 1

    runs = await _runs(session_factory, wf_id)
    scheduled = [r for r in runs if r.trigger == "schedule"]
    assert len(scheduled) == 1
    assert scheduled[0].status == "queued"
    assert scheduled[0].skip_reason is None


async def test_recover_stale_runs_skips_a_queued_run_that_never_started(session_factory):
    """A queued run that was never claimed must not block its workflow forever."""
    wf_id = await _add_workflow(session_factory)

    async with session_factory() as session:
        session.add(
            AiWorkflowRun(
                workflow_id=wf_id,
                user_id=1,
                trigger="manual",
                status="queued",
                scheduled_for=datetime(2026, 11, 2, 16, 0),
                slot_key=f"{wf_id}:stale",
                created_at=datetime(2026, 11, 2, 16, 0),
            )
        )
        await session.commit()

    recovered = await sched.recover_stale_runs(datetime(2026, 11, 3, 0, 0))

    assert recovered == 1
    runs = await _runs(session_factory, wf_id)
    assert runs[0].status == "skipped"
    assert runs[0].skip_reason == "never_started"
    assert runs[0].finished_at == datetime(2026, 11, 3, 0, 0)


async def test_recover_stale_runs_fails_a_run_that_died_while_running(session_factory):
    """A run whose process died mid-flight is marked failed."""
    wf_id = await _add_workflow(session_factory)

    async with session_factory() as session:
        session.add(
            AiWorkflowRun(
                workflow_id=wf_id,
                user_id=1,
                trigger="schedule",
                status="running",
                scheduled_for=datetime(2026, 11, 2, 16, 0),
                slot_key=f"{wf_id}:running",
                started_at=datetime(2026, 11, 2, 16, 0),
            )
        )
        await session.commit()

    recovered = await sched.recover_stale_runs(datetime(2026, 11, 3, 0, 0))

    assert recovered == 1
    runs = await _runs(session_factory, wf_id)
    assert runs[0].status == "failed"
    assert runs[0].error == "interrupted"

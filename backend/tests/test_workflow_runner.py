"""Tests for AI workflow runner.

Covers:
1. A run that fails at model resolution still ends with session_id set and exactly 2 ChatMessageRecords (user + ⚠ assistant).
2. map_legacy_model_to_route with an unknown pinned model returns the active route's model, not the stale id.
3. A successful run writes the user message before the assistant message.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.database import Base
from app.models.ai_chat import ChatMessageRecord, ChatSession
from app.models.ai_workflow import AiWorkflow, AiWorkflowRun
from app.models.user import User
from app.services.route_registry import map_legacy_model_to_route
import app.services.workflow_runner as runner_mod


def _scratch_dir() -> Path:
    path = Path(__file__).resolve().parent / "_tmp_workflow_runner" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
async def runner_db(monkeypatch):
    scratch = _scratch_dir()
    db_file = scratch / "wf_runner_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.services.workflow_runner.AsyncSessionLocal", session_factory)

    async with session_factory() as session:
        session.add(User(id=1, username="alice", hashed_password="x", is_admin=False))
        await session.commit()

    try:
        yield SimpleNamespace(
            session_factory=session_factory,
            engine=engine,
        )
    finally:
        await engine.dispose()
        shutil.rmtree(scratch, ignore_errors=True)


def test_map_legacy_model_to_route_unknown_model():
    """map_legacy_model_to_route with an unknown pinned model returns the active route's model, not the stale id."""
    # When a model string is empty or None, it returns the active route's default model
    route_id = "direct:aistudio"
    default_model = map_legacy_model_to_route("", route_id, preserve_qualified=True)
    assert default_model == "blm:direct:aistudio/gemini-2.5-flash"

    # When given a retired/stale qualified model from another route and preserve_qualified=False
    stale_model = "blm:oauth:retired-route/retired-model"
    remapped = map_legacy_model_to_route(stale_model, route_id, preserve_qualified=False)
    assert remapped == "blm:direct:aistudio/retired-model"

    # For empty/None with oauth:codex
    codex_default = map_legacy_model_to_route(None, "oauth:codex", preserve_qualified=True)
    assert codex_default == "blm:oauth:codex/gpt-4o"


@pytest.mark.asyncio
async def test_workflow_runner_failure_at_model_resolution(runner_db, monkeypatch):
    """A run that fails at model resolution still ends with session_id set and exactly 2 ChatMessageRecords (user + ⚠ assistant)."""
    async with runner_db.session_factory() as session:
        wf = AiWorkflow(
            user_id=1,
            name="Model Resolution Failing Workflow",
            prompt="Analyze portfolio allocation",
            schedule_type="manual",
            cron_expression="0 0 * * *",
            model="stale-model",
            is_enabled=True,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        run = AiWorkflowRun(
            workflow_id=wf.id,
            user_id=1,
            trigger="manual",
            scheduled_for=now,
            slot_key="manual-test-run-fail-res",
            status="pending",
            prompt_snapshot=wf.prompt,
            name_snapshot=wf.name,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        wf_id = wf.id
        run_id = run.id

    # If stream_chat_completion fails due to invalid/failed model resolution in stream
    async def fake_stream_error(*args, **kwargs):
        raise RuntimeError("AI provider error: model resolution failed for route")
        yield

    monkeypatch.setattr(runner_mod, "stream_chat_completion", fake_stream_error)

    res = await runner_mod.run_workflow(wf_id, run_id)
    assert res.startswith("error:")

    async with runner_db.session_factory() as session:
        run_row = await session.get(AiWorkflowRun, run_id)
        assert run_row is not None
        assert run_row.status == "failed"
        assert run_row.session_id is not None
        assert "model resolution failed" in (run_row.error or "")

        # Verify chat messages: user + ⚠ assistant
        stmt = (
            select(ChatMessageRecord)
            .where(ChatMessageRecord.session_id == run_row.session_id)
            .order_by(ChatMessageRecord.id.asc())
        )
        messages = (await session.execute(stmt)).scalars().all()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Analyze portfolio allocation"
        assert messages[1].role == "assistant"
        assert messages[1].content == f"⚠ {run_row.error}"


@pytest.mark.asyncio
async def test_workflow_runner_failure_leaves_evidence(runner_db, monkeypatch):
    """A run that fails during execution still ends with session_id set and exactly 2 ChatMessageRecords (user + ⚠ assistant)."""
    async with runner_db.session_factory() as session:
        wf = AiWorkflow(
            user_id=1,
            name="Failing Workflow",
            prompt="Run analysis on NIFTY",
            schedule_type="manual",
            cron_expression="0 0 * * *",
            model="unknown-legacy-model",
            is_enabled=True,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        run = AiWorkflowRun(
            workflow_id=wf.id,
            user_id=1,
            trigger="manual",
            scheduled_for=now,
            slot_key="manual-test-run-1",
            status="pending",
            prompt_snapshot=wf.prompt,
            name_snapshot=wf.name,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        wf_id = wf.id
        run_id = run.id

    # Simulate an error during stream_chat_completion (e.g. provider resolution / model execution failure)
    async def fake_stream_error(*args, **kwargs):
        raise RuntimeError("Provider connection failed for model")
        yield  # Make it an async generator

    monkeypatch.setattr(runner_mod, "stream_chat_completion", fake_stream_error)

    res = await runner_mod.run_workflow(wf_id, run_id)
    assert res.startswith("error:")

    async with runner_db.session_factory() as session:
        run_row = await session.get(AiWorkflowRun, run_id)
        assert run_row is not None
        assert run_row.status == "failed"
        assert run_row.session_id is not None
        assert "Provider connection failed" in (run_row.error or "")

        # Verify chat messages
        stmt = (
            select(ChatMessageRecord)
            .where(ChatMessageRecord.session_id == run_row.session_id)
            .order_by(ChatMessageRecord.id.asc())
        )
        messages = (await session.execute(stmt)).scalars().all()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Run analysis on NIFTY"
        assert messages[1].role == "assistant"
        assert messages[1].content == f"⚠ {run_row.error}"


@pytest.mark.asyncio
async def test_workflow_runner_success_writes_user_before_assistant(runner_db, monkeypatch):
    """A successful run writes the user message before the assistant message."""
    async with runner_db.session_factory() as session:
        wf = AiWorkflow(
            user_id=1,
            name="Success Workflow",
            prompt="Generate market overview",
            schedule_type="manual",
            cron_expression="0 0 * * *",
            model=None,
            is_enabled=True,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        run = AiWorkflowRun(
            workflow_id=wf.id,
            user_id=1,
            trigger="manual",
            scheduled_for=now,
            slot_key="manual-test-run-2",
            status="pending",
            prompt_snapshot=wf.prompt,
            name_snapshot=wf.name,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        wf_id = wf.id
        run_id = run.id

    messages_during_stream = []

    async def fake_stream_success(*args, **kwargs):
        # Inspect database during streaming to verify user message was already committed
        async with runner_db.session_factory() as inner_session:
            stmt = select(ChatMessageRecord).order_by(ChatMessageRecord.id.asc())
            msgs = (await inner_session.execute(stmt)).scalars().all()
            messages_during_stream.extend([(m.role, m.content) for m in msgs])

        yield json.dumps({"type": "token", "text": "Market is "})
        yield json.dumps({"type": "token", "text": "bullish today."})

    monkeypatch.setattr(runner_mod, "stream_chat_completion", fake_stream_success)

    res = await runner_mod.run_workflow(wf_id, run_id)
    assert res == "ok"

    # Verify user message was already persisted before the assistant generated chunks
    assert len(messages_during_stream) == 1
    assert messages_during_stream[0] == ("user", "Generate market overview")

    async with runner_db.session_factory() as session:
        run_row = await session.get(AiWorkflowRun, run_id)
        assert run_row is not None
        assert run_row.status == "succeeded"
        assert run_row.session_id is not None
        assert run_row.output_text == "Market is bullish today."

        # Verify chat session row
        chat_sess = await session.get(ChatSession, run_row.session_id)
        assert chat_sess is not None
        assert chat_sess.model.startswith("blm:")

        # Verify messages in DB
        stmt = (
            select(ChatMessageRecord)
            .where(ChatMessageRecord.session_id == run_row.session_id)
            .order_by(ChatMessageRecord.id.asc())
        )
        messages = (await session.execute(stmt)).scalars().all()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Generate market overview"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Market is bullish today."

"""Tests for workflow and custom prompt AI tools: tool registration,
CRUD, read-only updates, authentication enforcement, user isolation,
and SSE card extraction.
"""

from __future__ import annotations

import json
from typing import AsyncGenerator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.auth import current_user_id
from app.database import Base, _set_sqlite_pragma
from app.models.ai_workflow import AiCustomPrompt, AiWorkflow, AiWorkflowRun
from app.models.user import User


@pytest.fixture
async def mem_db() -> AsyncGenerator[dict, None]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @sa.event.listens_for(eng.sync_engine, "connect")
    def _on_connect(dbapi_con, _):
        _set_sqlite_pragma(dbapi_con, _)

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as session:
        session.add_all([
            User(id=1, username="user1", hashed_password="pw1", is_admin=False),
            User(id=2, username="user2", hashed_password="pw2", is_admin=False),
        ])
        await session.commit()

    import app.services.workflow_ai_tools as tools_mod

    real_factory = tools_mod.AsyncSessionLocal
    tools_mod.AsyncSessionLocal = Session
    token = current_user_id.set(1)
    try:
        yield {"Session": Session}
    finally:
        tools_mod.AsyncSessionLocal = real_factory
        current_user_id.reset(token)
    await eng.dispose()


class TestToolRegistration:
    NAMES = {
        "create_workflow",
        "manage_workflows",
        "create_custom_prompt",
        "manage_custom_prompts",
    }

    def test_openai_shape(self):
        from app.services.ai_chat_service import BLM_TOOLS

        names = {t["function"]["name"] for t in BLM_TOOLS}
        assert self.NAMES <= names

        cw = next(t["function"] for t in BLM_TOOLS if t["function"]["name"] == "create_workflow")
        assert set(cw["parameters"]["required"]) == {"name", "prompt", "schedule_type"}
        assert "schedule a briefing at 10" in cw["description"]

        mw = next(t["function"] for t in BLM_TOOLS if t["function"]["name"] == "manage_workflows")
        assert "action" in mw["parameters"]["required"]
        assert mw["parameters"]["properties"]["action"]["enum"] == [
            "list", "pause", "resume", "delete", "run", "update"
        ]

        cp = next(t["function"] for t in BLM_TOOLS if t["function"]["name"] == "create_custom_prompt")
        assert set(cp["parameters"]["required"]) == {"title", "tag", "description", "prompt"}

        mp = next(t["function"] for t in BLM_TOOLS if t["function"]["name"] == "manage_custom_prompts")
        assert "action" in mp["parameters"]["required"]
        assert mp["parameters"]["properties"]["action"]["enum"] == ["list", "delete", "update"]

    def test_anthropic_shape(self):
        from app.services.ai_chat_service import BLM_TOOLS_ANTHROPIC

        names = {t["name"] for t in BLM_TOOLS_ANTHROPIC}
        assert self.NAMES <= names

    def test_dispatch_callable(self):
        import app.services.workflow_ai_tools as tools_mod

        for name in self.NAMES:
            assert callable(getattr(tools_mod, name))


class TestWorkflowAiTools:
    async def test_create_workflow_writes_row_and_returns_card(self, mem_db):
        from app.services.workflow_ai_tools import create_workflow

        res = await create_workflow(
            name="Daily Briefing",
            prompt="Summarize morning news and gainers",
            schedule_type="daily",
            time_of_day="09:15",
            symbols=["RELIANCE", "TCS"],
        )

        assert res["ok"] is True
        wf_id = res["workflow_id"]
        assert wf_id > 0
        assert res["next_run_at"] is not None

        card = res["workflow_card"]
        assert card["id"] == wf_id
        assert card["name"] == "Daily Briefing"
        assert card["status"] == "created"
        assert card["symbols"] == ["RELIANCE", "TCS"]
        assert "09:15" in card["schedule_label"]
        assert card["next_run_at"] == res["next_run_at"]

        Session = mem_db["Session"]
        async with Session() as session:
            rows = (await session.execute(sa.select(AiWorkflow))).scalars().all()
            assert len(rows) == 1
            row = rows[0]
            assert row.name == "Daily Briefing"
            assert row.user_id == 1
            assert row.is_enabled is True
            assert row.deleted_at is None
            assert json.loads(row.symbols_json) == ["RELIANCE", "TCS"]

    async def test_manage_workflows_update_proposed_no_db_write(self, mem_db):
        from app.services.workflow_ai_tools import create_workflow, manage_workflows

        created = await create_workflow(
            name="Original Workflow",
            prompt="Original Prompt",
            schedule_type="daily",
            time_of_day="09:00",
        )
        wf_id = created["workflow_id"]

        Session = mem_db["Session"]
        async with Session() as session:
            wf_before = (
                await session.execute(sa.select(AiWorkflow).where(AiWorkflow.id == wf_id))
            ).scalar_one()
            orig_name = wf_before.name
            orig_prompt = wf_before.prompt
            orig_tod = wf_before.time_of_day
            orig_updated = wf_before.updated_at

        res = await manage_workflows(
            action="update",
            workflow_id=wf_id,
            name="Updated Workflow",
            time_of_day="14:30",
        )

        assert res["ok"] is True
        assert res["proposed"] is True
        assert "Edit proposed. The user must click Apply." in res["instruction"]

        card = res["workflow_card"]
        assert card["id"] == wf_id
        assert card["status"] == "proposed"
        assert card["changes"] == {"name": "Updated Workflow", "time_of_day": "14:30"}
        assert card["previous"] == {
            "name": orig_name,
            "prompt": orig_prompt,
            "schedule_type": "daily",
            "time_of_day": orig_tod,
            "days_of_week": None,
        }
        assert "14:30" in card["schedule_label"]

        async with Session() as session:
            wf_after = (
                await session.execute(sa.select(AiWorkflow).where(AiWorkflow.id == wf_id))
            ).scalar_one()
            assert wf_after.name == orig_name
            assert wf_after.prompt == orig_prompt
            assert wf_after.time_of_day == orig_tod
            assert wf_after.updated_at == orig_updated

    async def test_create_custom_prompt_writes_row(self, mem_db):
        from app.services.workflow_ai_tools import create_custom_prompt

        res = await create_custom_prompt(
            title="Valuation Model",
            tag="valuation",
            description="Run DCF valuation",
            prompt="Analyze {{symbol}} using discounted cash flow.",
            mode="research",
        )

        assert res["ok"] is True
        p_id = res["prompt_id"]
        card = res["prompt_card"]
        assert card["id"] == p_id
        assert card["title"] == "Valuation Model"
        assert card["tag"] == "valuation"
        assert card["description"] == "Run DCF valuation"
        assert card["prompt"] == "Analyze {{symbol}} using discounted cash flow."
        assert card["mode"] == "research"
        assert card["status"] == "created"

        Session = mem_db["Session"]
        async with Session() as session:
            rows = (
                await session.execute(
                    sa.select(AiCustomPrompt).where(AiCustomPrompt.deleted_at.is_(None))
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].sort_order == 0

        res2 = await create_custom_prompt(
            title="Second Prompt",
            tag="ideas",
            description="Find ideas",
            prompt="Scan high volume stocks",
        )
        assert res2["ok"] is True

        async with Session() as session:
            p2 = (
                await session.execute(
                    sa.select(AiCustomPrompt).where(AiCustomPrompt.id == res2["prompt_id"])
                )
            ).scalar_one()
            assert p2.sort_order == 1

    async def test_manage_custom_prompts_update_not_writing(self, mem_db):
        from app.services.workflow_ai_tools import (
            create_custom_prompt,
            manage_custom_prompts,
        )

        created = await create_custom_prompt(
            title="Initial Title",
            tag="original_tag",
            description="Initial desc",
            prompt="Initial prompt",
        )
        p_id = created["prompt_id"]

        Session = mem_db["Session"]
        async with Session() as session:
            p_before = (
                await session.execute(
                    sa.select(AiCustomPrompt).where(AiCustomPrompt.id == p_id)
                )
            ).scalar_one()
            orig_title = p_before.title
            orig_tag = p_before.tag
            orig_prompt = p_before.prompt
            orig_updated = p_before.updated_at

        res = await manage_custom_prompts(
            action="update",
            prompt_id=p_id,
            title="Proposed New Title",
            prompt="Proposed New Prompt",
        )

        assert res["ok"] is True
        assert res["proposed"] is True
        assert "Edit proposed. The user must click Apply." in res["instruction"]

        card = res["prompt_card"]
        assert card["id"] == p_id
        assert card["status"] == "proposed"
        assert card["changes"] == {
            "title": "Proposed New Title",
            "prompt": "Proposed New Prompt",
        }
        assert card["previous"] == {
            "title": orig_title,
            "tag": orig_tag,
            "description": "Initial desc",
            "prompt": orig_prompt,
        }

        async with Session() as session:
            p_after = (
                await session.execute(
                    sa.select(AiCustomPrompt).where(AiCustomPrompt.id == p_id)
                )
            ).scalar_one()
            assert p_after.title == orig_title
            assert p_after.tag == orig_tag
            assert p_after.prompt == orig_prompt
            assert p_after.updated_at == orig_updated

    async def test_unauthenticated_call_raises(self, mem_db):
        from app.services.workflow_ai_tools import (
            create_custom_prompt,
            create_workflow,
            manage_custom_prompts,
            manage_workflows,
        )

        token = current_user_id.set(None)
        try:
            with pytest.raises(RuntimeError, match="No authenticated user"):
                await create_workflow(name="X", prompt="Y", schedule_type="daily")

            with pytest.raises(RuntimeError, match="No authenticated user"):
                await manage_workflows(action="list")

            with pytest.raises(RuntimeError, match="No authenticated user"):
                await create_custom_prompt(
                    title="X", tag="t", description="d", prompt="p"
                )

            with pytest.raises(RuntimeError, match="No authenticated user"):
                await manage_custom_prompts(action="list")
        finally:
            current_user_id.reset(token)

    async def test_user_isolation(self, mem_db):
        from app.services.workflow_ai_tools import (
            create_custom_prompt,
            create_workflow,
            manage_custom_prompts,
            manage_workflows,
        )

        wf = await create_workflow(name="U1 WF", prompt="Prompt", schedule_type="daily")
        pr = await create_custom_prompt(
            title="U1 Prompt", tag="t", description="d", prompt="p"
        )

        current_user_id.set(2)

        wf_list = await manage_workflows(action="list")
        assert wf_list["ok"] is True
        assert wf_list["workflows"] == []

        pr_list = await manage_custom_prompts(action="list")
        assert pr_list["ok"] is True
        assert pr_list["prompts"] == []

        with pytest.raises(ValueError, match="not found"):
            await manage_workflows(action="pause", workflow_id=wf["workflow_id"])

        with pytest.raises(ValueError, match="not found"):
            await manage_workflows(
                action="update", workflow_id=wf["workflow_id"], name="Hack"
            )

        with pytest.raises(ValueError, match="not found"):
            await manage_custom_prompts(action="delete", prompt_id=pr["prompt_id"])

        with pytest.raises(ValueError, match="not found"):
            await manage_custom_prompts(
                action="update", prompt_id=pr["prompt_id"], title="Hack"
            )

    async def test_manage_workflows_mutations(self, mem_db):
        from app.services.workflow_ai_tools import create_workflow, manage_workflows

        wf = await create_workflow(
            name="Mutation Test",
            prompt="Test Prompt",
            schedule_type="daily",
            time_of_day="10:00",
        )
        wf_id = wf["workflow_id"]

        paused = await manage_workflows(action="pause", workflow_id=wf_id)
        assert paused["ok"] is True
        assert paused["is_enabled"] is False

        resumed = await manage_workflows(action="resume", workflow_id=wf_id)
        assert resumed["ok"] is True
        assert resumed["is_enabled"] is True
        assert resumed["next_run_at"] is not None

        run_res = await manage_workflows(action="run", workflow_id=wf_id)
        assert run_res["ok"] is True
        assert run_res["status"] == "queued"
        assert run_res["run_id"] > 0

        run_again = await manage_workflows(action="run", workflow_id=wf_id)
        assert run_again["ok"] is False
        assert "already queued" in run_again["error"]

        deleted = await manage_workflows(action="delete", workflow_id=wf_id)
        assert deleted["ok"] is True

        listing = await manage_workflows(action="list")
        assert all(w["id"] != wf_id for w in listing["workflows"])


class TestCardEvents:
    async def test_workflow_and_prompt_card_split_from_llm_payload(self, monkeypatch):
        import app.services.ai_chat_service as svc

        async def _fake_execute(name, args):
            if name == "create_workflow":
                return {
                    "ok": True,
                    "workflow_id": 12,
                    "next_run_at": "2026-11-01T09:00:00",
                    "workflow_card": {
                        "id": 12,
                        "name": "Briefing",
                        "schedule_label": "Every day at 09:00 IST",
                        "status": "created",
                    },
                }
            if name == "create_custom_prompt":
                return {
                    "ok": True,
                    "prompt_id": 44,
                    "prompt_card": {
                        "id": 44,
                        "title": "Valuation",
                        "status": "created",
                    },
                }
            if name == "manage_workflows":
                return {"ok": True, "workflows": []}
            return {}

        monkeypatch.setattr(svc, "_execute_tool", _fake_execute)

        events, msgs = await svc._run_tools_parallel(
            [{"name": "create_workflow", "args": {"name": "Briefing"}, "id": "tc1"}],
            set(),
            session_id=1,
        )
        assert len(events) == 2
        e0 = json.loads(events[0])
        e1 = json.loads(events[1])
        assert e0["type"] == "tool_result"
        assert e1["type"] == "workflow_card"
        assert e1["name"] == "Briefing"
        content = json.loads(msgs[0]["content"])
        assert "workflow_card" not in content
        assert content["ok"] is True

        events_pr, msgs_pr = await svc._run_tools_parallel(
            [{"name": "create_custom_prompt", "args": {"title": "Valuation"}, "id": "tc2"}],
            set(),
            session_id=1,
        )
        assert len(events_pr) == 2
        pr0 = json.loads(events_pr[0])
        pr1 = json.loads(events_pr[1])
        assert pr0["type"] == "tool_result"
        assert pr1["type"] == "prompt_card"
        assert pr1["title"] == "Valuation"
        content_pr = json.loads(msgs_pr[0]["content"])
        assert "prompt_card" not in content_pr
        assert content_pr["ok"] is True

        events_list, _ = await svc._run_tools_parallel(
            [{"name": "manage_workflows", "args": {"action": "list"}, "id": "tc3"}],
            set(),
            session_id=1,
        )
        assert len(events_list) == 1
        assert json.loads(events_list[0])["type"] == "tool_result"

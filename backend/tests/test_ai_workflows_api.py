"""API-level tests for AI workflows and custom prompts.

Covers user-scoped REST endpoints for:
- Workflows CRUD, prompt-only vs schedule PATCH, pagination, preview, run, catch-up, summary
- Workflow runs listing, read, read-all
- Custom prompts CRUD, used tracking, pagination
- User isolation: second user receives 404 or empty sets
"""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - populate Base.metadata
from app.auth import current_user_id
from app.config import settings
from app.database import Base, get_db
from app.models.ai_workflow import AiCustomPrompt, AiWorkflow, AiWorkflowRun
from app.models.user import User
from main import app


def _scratch_dir() -> Path:
    path = Path(__file__).resolve().parent / "_tmp_workflows" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
async def api_env(monkeypatch):
    import main as main_mod

    monkeypatch.setattr(main_mod, "LAUNCH_TOKEN", "test-token")

    scratch = _scratch_dir()
    db_file = scratch / "wf_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.database.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.workers.workflow_scheduler.AsyncSessionLocal", session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                User(id=1, username="alice", hashed_password="x", is_admin=False),
                User(id=2, username="bob", hashed_password="x", is_admin=False),
            ]
        )
        await session.commit()

    active_user = SimpleNamespace(user_id=1)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Also patch current_user_id ContextVar
    current_user_id.set(1)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://test",
            headers={"x-blm-token": "test-token"},
        ) as client:
            yield SimpleNamespace(
                client=client,
                active_user=active_user,
                session_factory=session_factory,
                engine=engine,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
        shutil.rmtree(scratch, ignore_errors=True)


def _set_user(env, uid: int):
    env.active_user.user_id = uid
    current_user_id.set(uid)


@pytest.mark.asyncio
async def test_workflow_preview(api_env):
    payload = {
        "schedule_type": "daily",
        "time_of_day": "14:30",
        "timezone": "Asia/Kolkata",
    }
    resp = await api_env.client.post("/api/ai/workflows/preview", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cron_expression"] == "30 14 * * *"
    assert "Every day at 14:30" in data["schedule_label"]
    assert len(data["next_runs"]) == 3


@pytest.mark.asyncio
async def test_workflow_crud_and_patch_recomputation(api_env):
    _set_user(api_env, 1)

    # 1. Create workflow
    create_payload = {
        "name": "Daily Market Digest",
        "prompt": "Summarize market movements",
        "schedule_type": "daily",
        "time_of_day": "09:15",
        "symbols": ["RELIANCE", "TCS"],
        "allow_write_tools": False,
        "catch_up_enabled": True,
    }
    resp = await api_env.client.post("/api/ai/workflows", json=create_payload)
    assert resp.status_code == 201, resp.text
    wf = resp.json()
    wf_id = wf["id"]
    orig_next_run = wf["next_run_at"]
    assert orig_next_run is not None
    assert wf["name"] == "Daily Market Digest"
    assert wf["symbols"] == ["RELIANCE", "TCS"]
    assert wf["catch_up_window_hours"] == 12  # default for daily

    # 2. Prompt-only PATCH leaves next_run_at unchanged
    patch_prompt = {"prompt": "Updated summary prompt instructions", "name": "Renamed Digest"}
    resp = await api_env.client.patch(f"/api/ai/workflows/{wf_id}", json=patch_prompt)
    assert resp.status_code == 200, resp.text
    patched = resp.json()
    assert patched["next_run_at"] == orig_next_run
    assert patched["name"] == "Renamed Digest"
    assert patched["prompt"] == "Updated summary prompt instructions"

    # 3. Schedule PATCH recomputes next_run_at
    patch_schedule = {"time_of_day": "16:00"}
    resp = await api_env.client.patch(f"/api/ai/workflows/{wf_id}", json=patch_schedule)
    assert resp.status_code == 200, resp.text
    patched_sched = resp.json()
    assert patched_sched["time_of_day"] == "16:00"
    assert patched_sched["cron_expression"] == "0 16 * * *"
    assert patched_sched["next_run_at"] != orig_next_run

    # 4. User scoping: User 2 cannot see or edit workflow of User 1
    _set_user(api_env, 2)
    resp = await api_env.client.patch(f"/api/ai/workflows/{wf_id}", json={"name": "Hacked"})
    assert resp.status_code == 404

    resp = await api_env.client.delete(f"/api/ai/workflows/{wf_id}")
    assert resp.status_code == 404

    resp = await api_env.client.get("/api/ai/workflows")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["total"] == 0
    assert len(res_data["items"]) == 0

    # 5. Back to User 1, soft delete
    _set_user(api_env, 1)
    del_resp = await api_env.client.delete(f"/api/ai/workflows/{wf_id}")
    assert del_resp.status_code == 204

    # Now User 1 gets 404 because deleted_at is set
    del_check = await api_env.client.patch(f"/api/ai/workflows/{wf_id}", json={"name": "Post-delete"})
    assert del_check.status_code == 404


@pytest.mark.asyncio
async def test_workflows_pagination_and_summary(api_env):
    _set_user(api_env, 1)

    for i in range(5):
        resp = await api_env.client.post(
            "/api/ai/workflows",
            json={
                "name": f"Workflow {i}",
                "prompt": f"Prompt {i}",
                "schedule_type": "daily",
                "time_of_day": f"0{i}:00",
            },
        )
        assert resp.status_code == 201

    resp = await api_env.client.get("/api/ai/workflows?limit=2&offset=0")
    assert resp.status_code == 200
    p1 = resp.json()
    assert p1["total"] == 5
    assert len(p1["items"]) == 2
    assert p1["limit"] == 2
    assert p1["offset"] == 0
    assert p1["has_more"] is True

    resp2 = await api_env.client.get("/api/ai/workflows?limit=2&offset=4")
    assert resp2.status_code == 200
    p2 = resp2.json()
    assert p2["total"] == 5
    assert len(p2["items"]) == 1
    assert p2["has_more"] is False

    # Summary
    summary_resp = await api_env.client.get("/api/ai/workflows/summary")
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert summary["armed"] == 5
    assert summary["running"] == 0
    assert summary["unread"] == 0
    assert summary["next_run_at"] is not None


@pytest.mark.asyncio
async def test_workflow_runs_and_read_endpoints(api_env):
    _set_user(api_env, 1)

    wf_resp = await api_env.client.post(
        "/api/ai/workflows",
        json={
            "name": "Run Test WF",
            "prompt": "Test prompt",
            "schedule_type": "hourly",
        },
    )
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    # Trigger manual run
    run_resp = await api_env.client.post(f"/api/ai/workflows/{wf_id}/run")
    assert run_resp.status_code == 200, run_resp.text
    run_data = run_resp.json()
    run_id = run_data["id"]
    assert run_data["status"] == "queued"
    assert run_data["trigger"] == "manual"
    assert run_data["is_read"] is False

    # Trigger again immediately -> 409 Conflict
    conflict_resp = await api_env.client.post(f"/api/ai/workflows/{wf_id}/run")
    assert conflict_resp.status_code == 409

    # List runs
    runs_list_resp = await api_env.client.get("/api/ai/workflow-runs")
    assert runs_list_resp.status_code == 200
    runs_res = runs_list_resp.json()
    assert runs_res["total"] == 1
    assert runs_res["items"][0]["id"] == run_id

    # User 2 scoping for runs
    _set_user(api_env, 2)
    u2_runs = await api_env.client.get("/api/ai/workflow-runs")
    assert u2_runs.json()["total"] == 0

    u2_read = await api_env.client.post(f"/api/ai/workflow-runs/{run_id}/read")
    assert u2_read.status_code == 404

    # User 1 marks single run read
    _set_user(api_env, 1)
    read_resp = await api_env.client.post(f"/api/ai/workflow-runs/{run_id}/read")
    assert read_resp.status_code == 200
    assert read_resp.json()["ok"] is True

    # Mark all read
    read_all_resp = await api_env.client.post("/api/ai/workflow-runs/read-all")
    assert read_all_resp.status_code == 200
    assert read_all_resp.json()["updated"] == 0  # Already read


@pytest.mark.asyncio
async def test_catch_up_endpoint(api_env):
    _set_user(api_env, 1)
    resp = await api_env.client.post("/api/ai/workflows/catch-up")
    assert resp.status_code == 200
    data = resp.json()
    assert "processed" in data
    assert "enqueued" in data


@pytest.mark.asyncio
async def test_custom_prompts_crud_and_used(api_env):
    _set_user(api_env, 1)

    # 1. Create prompts
    p1_resp = await api_env.client.post(
        "/api/ai/prompts",
        json={
            "title": "Technical Analysis",
            "tag": "tech-analyst",
            "description": "Analyzes RSI and MACD",
            "prompt": "Evaluate the technicals for given stock",
            "icon": "📈",
            "mode": "research",
        },
    )
    assert p1_resp.status_code == 201
    p1 = p1_resp.json()
    assert p1["sort_order"] == 0
    assert p1["use_count"] == 0

    p2_resp = await api_env.client.post(
        "/api/ai/prompts",
        json={
            "title": "Earnings Deep Dive",
            "tag": "earnings",
            "prompt": "Extract quarterly highlights",
            "mode": "research",
        },
    )
    assert p2_resp.status_code == 201
    p2 = p2_resp.json()
    assert p2["sort_order"] == 1

    # 2. List prompts with pagination
    list_resp = await api_env.client.get("/api/ai/prompts?limit=1&offset=0")
    assert list_resp.status_code == 200
    l_data = list_resp.json()
    assert l_data["total"] == 2
    assert len(l_data["items"]) == 1
    assert l_data["has_more"] is True

    # 3. Mark used
    p1_id = p1["id"]
    used_resp = await api_env.client.post(f"/api/ai/prompts/{p1_id}/used")
    assert used_resp.status_code == 200
    assert used_resp.json()["use_count"] == 1
    assert used_resp.json()["last_used_at"] is not None

    # 4. Partial update (PATCH)
    patch_resp = await api_env.client.patch(
        f"/api/ai/prompts/{p1_id}",
        json={"title": "Updated Technical Analysis"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Updated Technical Analysis"

    # 5. User 2 scoping: 404 for User 2
    _set_user(api_env, 2)
    u2_patch = await api_env.client.patch(f"/api/ai/prompts/{p1_id}", json={"title": "Hacked"})
    assert u2_patch.status_code == 404

    u2_delete = await api_env.client.delete(f"/api/ai/prompts/{p1_id}")
    assert u2_delete.status_code == 404

    # 6. Delete prompt for User 1
    _set_user(api_env, 1)
    del_resp = await api_env.client.delete(f"/api/ai/prompts/{p1_id}")
    assert del_resp.status_code == 204

    get_after = await api_env.client.patch(f"/api/ai/prompts/{p1_id}", json={"title": "Test"})
    assert get_after.status_code == 404

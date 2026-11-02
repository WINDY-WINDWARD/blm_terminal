"""API-level tests for widget tour persistence.

Covers:
- Unauthenticated request rejected (401)
- Empty list for fresh user
- Idempotent write / upsert
- Unknown command rejected with HTTP 400
- Second user isolation
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - populate Base.metadata
from app.auth import get_current_user
from app.config import settings
from app.database import Base, get_db
from app.models.user import User
from app.models.widget_tour import WidgetTour
from main import app


def _scratch_dir() -> Path:
    path = Path(__file__).resolve().parent / "_tmp_widget_tours" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
async def tour_env(monkeypatch):
    import main as main_mod

    monkeypatch.setattr(main_mod, "LAUNCH_TOKEN", "test-token")
    monkeypatch.setenv("BLM_WRITE_QUEUE_DISABLED", "1")

    scratch = _scratch_dir()
    db_file = scratch / "test.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Sync sessionmaker for router writes in write_queue bypass
    sync_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    test_sync_session = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
    monkeypatch.setattr("app.routers.widget_tours._SyncSessionLocal", test_sync_session)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all(
            [
                User(id=1, username="alice", hashed_password="x", is_admin=False),
                User(id=2, username="bob", hashed_password="x", is_admin=False),
            ]
        )
        await session.commit()

    auth = SimpleNamespace(user_id=1)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    async def override_get_current_user():
        if auth.user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        return User(
            id=auth.user_id,
            username=f"user{auth.user_id}",
            hashed_password="x",
            is_admin=False,
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://test",
            headers={"x-blm-token": "test-token"},
        ) as client:
            yield SimpleNamespace(
                client=client,
                auth=auth,
                session_factory=session_factory,
                scratch=scratch,
                db_file=db_file,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)
        await engine.dispose()
        sync_engine.dispose()
        shutil.rmtree(scratch, ignore_errors=True)


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(tour_env):
    tour_env.auth.user_id = None

    get_resp = await tour_env.client.get("/api/widget-tours")
    assert get_resp.status_code == 401

    post_resp = await tour_env.client.post("/api/widget-tours", json={"command": "CHART"})
    assert post_resp.status_code == 401


@pytest.mark.asyncio
async def test_empty_list(tour_env):
    resp = await tour_env.client.get("/api/widget-tours")
    assert resp.status_code == 200
    assert resp.json() == {"seen": {}}


@pytest.mark.asyncio
async def test_idempotent_write(tour_env):
    # First write
    post1 = await tour_env.client.post("/api/widget-tours", json={"command": "CHART"})
    assert post1.status_code == 200
    d1 = post1.json()
    assert d1["command"] == "CHART"
    assert isinstance(d1["seen_at"], int)

    # Check list has it
    get1 = await tour_env.client.get("/api/widget-tours")
    assert get1.status_code == 200
    assert get1.json()["seen"]["CHART"] == d1["seen_at"]

    # Second write for same command (idempotent upsert)
    post2 = await tour_env.client.post("/api/widget-tours", json={"command": "CHART"})
    assert post2.status_code == 200
    d2 = post2.json()
    assert d2["command"] == "CHART"
    assert d2["seen_at"] >= d1["seen_at"]

    # Verify only 1 row exists in DB for (user_id=1, command=CHART)
    async with tour_env.session_factory() as session:
        res = await session.execute(
            select(WidgetTour).where(
                WidgetTour.user_id == 1,
                WidgetTour.widget_command == "CHART",
            )
        )
        rows = res.scalars().all()
        assert len(rows) == 1
        assert rows[0].seen_at == d2["seen_at"]


@pytest.mark.asyncio
async def test_unknown_command_rejected(tour_env):
    # Unknown command
    resp = await tour_env.client.post("/api/widget-tours", json={"command": "NONEXISTENT"})
    assert resp.status_code == 400

    # Old retired SCRIPTS command
    resp_scripts = await tour_env.client.post("/api/widget-tours", json={"command": "SCRIPTS"})
    assert resp_scripts.status_code == 400


@pytest.mark.asyncio
async def test_second_user_isolation(tour_env):
    # User 1 marks CHART
    await tour_env.client.post("/api/widget-tours", json={"command": "CHART"})

    # Switch to User 2
    tour_env.auth.user_id = 2

    # User 2 sees empty
    get_user2 = await tour_env.client.get("/api/widget-tours")
    assert get_user2.status_code == 200
    assert get_user2.json() == {"seen": {}}

    # User 2 marks WATCH
    await tour_env.client.post("/api/widget-tours", json={"command": "WATCH"})
    get_user2_after = await tour_env.client.get("/api/widget-tours")
    assert "WATCH" in get_user2_after.json()["seen"]
    assert "CHART" not in get_user2_after.json()["seen"]

    # Switch back to User 1
    tour_env.auth.user_id = 1
    get_user1 = await tour_env.client.get("/api/widget-tours")
    assert "CHART" in get_user1.json()["seen"]
    assert "WATCH" not in get_user1.json()["seen"]

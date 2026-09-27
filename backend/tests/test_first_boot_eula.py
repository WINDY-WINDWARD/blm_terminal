"""Tests for the mandatory EULA endpoints (GET /api/eula-status, POST /api/eula/accept).

Isolated throwaway SQLite file per test, same pattern as test_auth_setup.py —
the app lifespan is bypassed (httpx ASGITransport), no migrations/workers.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — populate Base.metadata
from app.database import Base, get_db
from app.models.system_config import SystemConfig
from main import app

EULA_KEY = "app.eula_accepted"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    """Yield (client, session_factory) bound to a fresh DB file.

    The launch-token guard on the real app fail-closes every non-/health
    request with 401, so arm a known token and send it on every request."""
    import main as main_mod

    monkeypatch.setattr(main_mod, "LAUNCH_TOKEN", "test-token")

    db_file = tmp_path / "eula_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="https://test",
            headers={"x-blm-token": "test-token"},
        ) as ac:
            yield ac, session_factory
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


async def test_status_not_accepted_on_fresh_db(env):
    client, _ = env
    resp = await client.get("/api/eula-status")
    assert resp.status_code == 200
    assert resp.json() == {"accepted": False, "version": "eula-v1", "accepted_at": None}


async def test_accept_records_and_status_reads_accepted(env):
    client, _ = env
    r = await client.post("/api/eula/accept", json={"version": "eula-v1"})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert body["version"] == "eula-v1"
    assert isinstance(body["accepted_at"], int)

    s = await client.get("/api/eula-status")
    assert s.json()["accepted"] is True
    assert s.json()["accepted_at"] == body["accepted_at"]


async def test_accept_idempotent(env):
    client, _ = env
    first = await client.post("/api/eula/accept", json={"version": "eula-v1"})
    second = await client.post("/api/eula/accept", json={"version": "eula-v1"})
    assert first.status_code == 200 and second.status_code == 200


async def test_accept_version_mismatch_rejected(env):
    client, _ = env
    r = await client.post("/api/eula/accept", json={"version": "eula-v0"})
    assert r.status_code == 409
    s = await client.get("/api/eula-status")
    assert s.json()["accepted"] is False


async def test_tampered_row_reprompts(env):
    """Hand-edited/wrong-version/missing rows must read as NOT accepted."""
    client, session_factory = env
    await client.post("/api/eula/accept", json={"version": "eula-v1"})

    # Wrong version stored.
    async with session_factory() as session:
        await session.execute(
            update(SystemConfig).where(SystemConfig.key == EULA_KEY).values(value="eula-v9|123")
        )
        await session.commit()
    assert (await client.get("/api/eula-status")).json()["accepted"] is False

    # Garbage stored.
    async with session_factory() as session:
        await session.execute(
            update(SystemConfig).where(SystemConfig.key == EULA_KEY).values(value="junk")
        )
        await session.commit()
    assert (await client.get("/api/eula-status")).json()["accepted"] is False

    # Row deleted entirely.
    async with session_factory() as session:
        await session.execute(delete(SystemConfig).where(SystemConfig.key == EULA_KEY))
        await session.commit()
    assert (await client.get("/api/eula-status")).json()["accepted"] is False


async def test_first_boot_flag_still_works(env):
    """EULA additions must not disturb the existing first-boot endpoints."""
    client, _ = env
    r = await client.get("/api/first-boot")
    assert r.status_code == 200
    assert r.json() == {"onboarding_completed": False}
    await client.post("/api/first-boot/complete")
    r2 = await client.get("/api/first-boot")
    assert r2.json() == {"onboarding_completed": True}

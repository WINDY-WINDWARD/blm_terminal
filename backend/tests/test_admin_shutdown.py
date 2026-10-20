"""Tests for admin-only graceful shutdown endpoints."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import create_access_token, get_password_hash
from app.database import Base, get_db
from app.models.user import User
import main
from main import app


@pytest.fixture
async def setup_db(tmp_path):
    """Set up an isolated test SQLite database with user tables."""
    db_file = tmp_path / "test_shutdown.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Insert admin and non-admin users
    async with session_factory() as session:
        admin = User(
            id=1,
            username="admin_user",
            hashed_password=get_password_hash("adminpass123"),
            is_admin=True,
        )
        regular = User(
            id=2,
            username="regular_user",
            hashed_password=get_password_hash("userpass123"),
            is_admin=False,
        )
        session.add_all([admin, regular])
        await session.commit()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_shutdown_routes_mounted(setup_db):
    """Ensure shutdown endpoints exist and are reachable."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Without launch token or auth, should return 401
        resp1 = await client.post("/api/admin/shutdown")
        assert resp1.status_code != 404, "/api/admin/shutdown is not mounted"

        resp2 = await client.post("/admin/shutdown")
        assert resp2.status_code != 404, "/admin/shutdown is not mounted"

        resp3 = await client.post("/system/shutdown")
        assert resp3.status_code != 404, "/system/shutdown is not mounted"


@pytest.mark.asyncio
async def test_shutdown_allowed_with_host_launch_token(setup_db, monkeypatch):
    """Electron host caller with valid x-blm-token can trigger shutdown."""
    test_token = "test-launch-token-12345"
    monkeypatch.setattr(main, "LAUNCH_TOKEN", test_token)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/shutdown",
            headers={"x-blm-token": test_token},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "shutting_down"}


@pytest.mark.asyncio
async def test_shutdown_allowed_for_admin_user(setup_db, monkeypatch):
    """Authenticated admin user can trigger shutdown."""
    test_token = "test-launch-token-12345"
    monkeypatch.setattr(main, "LAUNCH_TOKEN", test_token)

    admin_jwt = create_access_token({"sub": "admin_user"})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/shutdown",
            headers={
                "x-blm-token": test_token,
                "Authorization": f"Bearer {admin_jwt}",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "shutting_down"}


@pytest.mark.asyncio
async def test_shutdown_rejected_for_non_admin_user(setup_db, monkeypatch):
    """Authenticated non-admin user is rejected with 403 Forbidden."""
    test_token = "test-launch-token-12345"
    monkeypatch.setattr(main, "LAUNCH_TOKEN", test_token)

    regular_jwt = create_access_token({"sub": "regular_user"})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/shutdown",
            headers={
                "x-blm-token": test_token,
                "Authorization": f"Bearer {regular_jwt}",
            },
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_shutdown_rejected_without_launch_token(setup_db, monkeypatch):
    """Request without valid launch token is rejected with 401 Unauthorized."""
    monkeypatch.setattr(main, "LAUNCH_TOKEN", "armed-secret-token")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/shutdown",
            headers={"x-blm-token": "wrong-token"},
        )
        assert resp.status_code == 401

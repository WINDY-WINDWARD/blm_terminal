"""Tests for first-boot admin setup endpoints (POST /api/auth/setup).

Uses an isolated throwaway SQLite file per test with the full ORM schema —
never touches the production ``data.db``. The app lifespan is bypassed
entirely (httpx ASGITransport), so no migrations or background workers run.
"""

import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — populate Base.metadata
from app.database import Base, get_db
from app.models.user import User
from app.models.watchlist import Watchlist
from main import app


@pytest.fixture
async def client(tmp_path):
    """Yield an httpx client bound to the app with get_db pointed at a fresh DB file."""
    db_file = tmp_path / "setup_test.db"
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
        async with AsyncClient(transport=transport, base_url="https://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


async def test_setup_status_true_on_empty_db(client):
    resp = await client.get("/api/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json() == {"needs_setup": True}


async def test_setup_creates_admin_and_logs_in(client):
    resp = await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "StrongPass123!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "access_token" in resp.cookies

    # Token cookie authenticates as the new admin
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert me.json()["is_admin"] is True

    # Setup is now single-use
    status_resp = await client.get("/api/auth/setup-status")
    assert status_resp.json() == {"needs_setup": False}

    again = await client.post(
        "/api/auth/setup",
        json={"username": "someone", "password": "AnotherPass123!"},
    )
    assert again.status_code == 403
    assert again.json()["detail"] == "Setup already completed"


async def test_setup_provisions_default_watchlist(client):
    await client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "StrongPass123!"},
    )
    me = (await client.get("/api/auth/me")).json()
    wls = await client.get("/api/watchlists")
    assert wls.status_code == 200
    names = [w["name"] for w in wls.json()]
    assert names.count("Default") == 1
    assert me["id"] == 1


async def test_setup_validation(client):
    short_pw = await client.post(
        "/api/auth/setup", json={"username": "admin", "password": "short"}
    )
    assert short_pw.status_code == 422

    short_user = await client.post(
        "/api/auth/setup", json={"username": "ab", "password": "LongEnough123!"}
    )
    assert short_user.status_code == 422

    # Failed attempts must not consume the single-use setup
    assert (await client.get("/api/auth/setup-status")).json() == {"needs_setup": True}


async def test_login_works_after_setup(client):
    await client.post(
        "/api/auth/setup",
        json={"username": "chief", "password": "ChiefPass123!"},
    )
    # Fresh client without cookies -> form login works with the new creds
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as fresh:
        login = await fresh.post(
            "/api/auth/login",
            data={"username": "chief", "password": "ChiefPass123!"},
        )
        assert login.status_code == 200
        assert login.json()["access_token"]

        bad = await fresh.post(
            "/api/auth/login",
            data={"username": "chief", "password": "wrong-password"},
        )
        assert bad.status_code == 401


def test_ensure_admin_user_is_noop_on_empty_db(tmp_path, monkeypatch):
    """_ensure_admin_user must never write a default credential."""
    from app.config import settings

    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, "
        "hashed_password TEXT, is_admin BOOLEAN, created_at DATETIME)"
    )
    conn.close()
    monkeypatch.setattr(settings, "db_path", str(db_file))

    from main import _ensure_admin_user

    assert _ensure_admin_user() is None

    conn = sqlite3.connect(str(db_file))
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()
    assert count == 0

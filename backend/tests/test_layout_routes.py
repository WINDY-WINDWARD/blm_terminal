"""Tests for user layout backend APIs including tombstones and passive sync rules."""

from typing import AsyncGenerator
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import get_current_user
from app.database import Base, get_db, _set_sqlite_pragma
from app.models.user import User
import app.models  # noqa: F401


@pytest.fixture
async def layout_db_session() -> AsyncGenerator[AsyncSession, None]:
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
        u1 = User(id=1, username="user1", hashed_password="pw1", is_admin=False)
        u2 = User(id=2, username="user2", hashed_password="pw2", is_admin=False)
        session.add_all([u1, u2])
        await session.commit()
        yield session

    await eng.dispose()


@pytest.fixture
def current_user_holder():
    class UserHolder:
        def __init__(self):
            self.user = User(id=1, username="user1", hashed_password="pw1", is_admin=False)

    return UserHolder()


@pytest.fixture
def app(layout_db_session: AsyncSession, current_user_holder):
    app = FastAPI()
    from app.routers.layout import router as layout_router

    app.include_router(layout_router, prefix="/api")

    async def _override_get_db():
        yield layout_db_session

    async def _override_get_current_user():
        return current_user_holder.user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestLayoutRoutes:
    def test_list_empty_layouts(self, client):
        resp = client.get("/api/layouts")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_get_layout(self, client):
        payload = {
            "name": "default-view",
            "activePanels": {"panel-1": "CHART", "panel-2": "WATCH"},
            "panelCount": 4,
            "mergedGroups": {},
            "savedAt": 1700000000000,
        }
        res_put = client.put("/api/layouts/default-view", json=payload)
        assert res_put.status_code == 200
        data = res_put.json()
        assert data["name"] == "default-view"
        assert data["panelCount"] == 4

        res_get = client.get("/api/layouts")
        assert res_get.status_code == 200
        items = res_get.json()
        assert len(items) == 1
        assert items[0]["name"] == "default-view"

    def test_overwrite_layout_explicit(self, client):
        p1 = {
            "name": "trading",
            "activePanels": {"panel-1": "CHART"},
            "panelCount": 2,
            "mergedGroups": {},
            "savedAt": 1700000000000,
        }
        client.put("/api/layouts/trading", json=p1)

        p2 = {
            "name": "trading",
            "activePanels": {"panel-1": "CHART", "panel-2": "POS"},
            "panelCount": 2,
            "mergedGroups": {"panel-1": {"panels": ["panel-1", "panel-2"], "primary": "panel-1"}},
            "savedAt": 1700000005000,
        }
        res_put = client.put("/api/layouts/trading", json=p2)
        assert res_put.status_code == 200
        data = res_put.json()
        assert data["savedAt"] == 1700000005000

    def test_passive_bulk_sync_server_always_wins(self, client):
        # Server layout exists
        server_layout = {
            "name": "trading",
            "activePanels": {"panel-1": "CHART"},
            "panelCount": 2,
            "mergedGroups": {},
            "savedAt": 1000,
        }
        client.put("/api/layouts/trading", json=server_layout)

        # Local has different payload and higher timestamp
        local_layout = {
            "name": "trading",
            "activePanels": {"panel-1": "NEWS"},
            "panelCount": 4,
            "mergedGroups": {},
            "savedAt": 9000,
        }

        # Bulk sync (passive sync)
        res = client.post("/api/layouts/bulk-sync", json=[local_layout])
        assert res.status_code == 200
        data = res.json()
        active = data["layouts"]
        assert len(active) == 1
        # Server wins: payload must be server's original CHART/2, not local's NEWS/4
        assert active[0]["activePanels"]["panel-1"] == "CHART"
        assert active[0]["panelCount"] == 2

    def test_delete_creates_tombstone_and_bulk_sync_respects_it(self, client):
        client.put(
            "/api/layouts/to-delete",
            json={"name": "to-delete", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        res_del = client.delete("/api/layouts/to-delete")
        assert res_del.status_code == 200
        assert res_del.json() == {"ok": True}

        # GET /api/layouts excludes tombstoned rows
        res_get = client.get("/api/layouts")
        assert res_get.json() == []

        # Bulk sync with stale local copy must NOT recreate the layout
        stale_local = [
            {"name": "to-delete", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 200}
        ]
        res_sync = client.post("/api/layouts/bulk-sync", json=stale_local)
        assert res_sync.status_code == 200
        body = res_sync.json()
        assert body["layouts"] == []
        assert len(body["tombstones"]) == 1
        assert body["tombstones"][0]["name"] == "to-delete"

    def test_explicit_put_revives_tombstone(self, client):
        client.put(
            "/api/layouts/revive-me",
            json={"name": "revive-me", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        client.delete("/api/layouts/revive-me")

        # Explicit PUT revives tombstone
        revived = {
            "name": "revive-me",
            "activePanels": {"panel-1": "AI"},
            "panelCount": 4,
            "mergedGroups": {},
            "savedAt": 500,
        }
        res_put = client.put("/api/layouts/revive-me", json=revived)
        assert res_put.status_code == 200
        assert res_put.json()["activePanels"]["panel-1"] == "AI"

        res_get = client.get("/api/layouts")
        assert len(res_get.json()) == 1
        assert res_get.json()[0]["name"] == "revive-me"

    def test_user_isolation(self, client, current_user_holder):
        client.put(
            "/api/layouts/u1-layout",
            json={"name": "u1-layout", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        client.delete("/api/layouts/u1-layout")  # Tombstone created for user 1

        # Switch to User 2
        current_user_holder.user = User(id=2, username="user2", hashed_password="pw2", is_admin=False)

        res_list = client.get("/api/layouts")
        assert res_list.status_code == 200
        assert res_list.json() == []

        # User 2 bulk sync returns empty tombstones for user 2
        res_sync = client.post("/api/layouts/bulk-sync", json=[])
        assert res_sync.json()["tombstones"] == []

    def test_rename_layout(self, client):
        client.put(
            "/api/layouts/old-name",
            json={"name": "old-name", "activePanels": {"panel-1": "CHART"}, "panelCount": 2, "mergedGroups": {}, "savedAt": 1000},
        )

        res_rename = client.patch("/api/layouts/old-name/rename", json={"newName": "new-name"})
        assert res_rename.status_code == 200
        assert res_rename.json()["name"] == "new-name"

        res_list = client.get("/api/layouts")
        assert len(res_list.json()) == 1
        assert res_list.json()[0]["name"] == "new-name"

    def test_rename_conflict(self, client):
        client.put(
            "/api/layouts/l1",
            json={"name": "l1", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        client.put(
            "/api/layouts/l2",
            json={"name": "l2", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 200},
        )

        res = client.patch("/api/layouts/l1/rename", json={"newName": "l2"})
        assert res.status_code == 409

    def test_name_length_limit(self, client):
        long_name = "a" * 65
        res = client.put(
            f"/api/layouts/{long_name}",
            json={"name": long_name, "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        assert res.status_code == 422

    def test_rename_into_tombstone_replaces_it(self, client):
        # Create a layout, delete it (tombstone), then rename another into it
        client.put(
            "/api/layouts/target",
            json={"name": "target", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        client.delete("/api/layouts/target")  # Create tombstone

        # Create another layout
        client.put(
            "/api/layouts/source",
            json={"name": "source", "activePanels": {"panel-1": "CHART"}, "panelCount": 2, "mergedGroups": {}, "savedAt": 200},
        )

        # Rename source into target (replacing the tombstone)
        res_rename = client.patch("/api/layouts/source/rename", json={"newName": "target"})
        assert res_rename.status_code == 200
        data = res_rename.json()
        assert data["name"] == "target"
        assert data["activePanels"]["panel-1"] == "CHART"

        # Verify source no longer exists, target is now active
        res_list = client.get("/api/layouts")
        names = [l["name"] for l in res_list.json()]
        assert "target" in names
        assert "source" not in names

    def test_explicit_put_revives_and_overwrites_tombstone(self, client):
        # Create, delete, then explicitly save to same name with different content
        client.put(
            "/api/layouts/revive",
            json={"name": "revive", "activePanels": {"panel-1": "NEWS"}, "panelCount": 4, "mergedGroups": {}, "savedAt": 100},
        )
        client.delete("/api/layouts/revive")

        # Explicit PUT with different content
        revived = {
            "name": "revive",
            "activePanels": {"panel-1": "CHART", "panel-2": "ORDER"},
            "panelCount": 4,
            "mergedGroups": {"group-1": {"primary": "panel-1", "panels": ["panel-1", "panel-2"]}},
            "savedAt": 500,
        }
        res = client.put("/api/layouts/revive", json=revived)
        assert res.status_code == 200
        data = res.json()
        assert data["activePanels"]["panel-2"] == "ORDER"
        assert data["savedAt"] == 500

        # Verify no tombstones remain
        res_sync = client.post("/api/layouts/bulk-sync", json=[])
        assert len(res_sync.json()["tombstones"]) == 0

    def test_delete_missing_layout_returns_success(self, client):
        # Deleting a layout that doesn't exist should return 200 OK
        res = client.delete("/api/layouts/nonexistent")
        assert res.status_code == 200
        assert res.json() == {"ok": True}

    def test_tombstone_survives_passive_sync_when_local_has_stale_copy(self, client):
        # Create a layout, delete it (tombstone), then bulk sync with stale local copy
        client.put(
            "/api/layouts/stale",
            json={"name": "stale", "activePanels": {}, "panelCount": 2, "mergedGroups": {}, "savedAt": 100},
        )
        res_del = client.delete("/api/layouts/stale")
        assert res_del.status_code == 200

        # Bulk sync with stale local copy
        stale_copy = [
            {"name": "stale", "activePanels": {"panel-1": "CHART"}, "panelCount": 2, "mergedGroups": {}, "savedAt": 999}
        ]
        res_sync = client.post("/api/layouts/bulk-sync", json=stale_copy)
        assert res_sync.status_code == 200
        data = res_sync.json()

        # Server wins: tombstone is returned, layout is not recreated
        assert len(data["layouts"]) == 0
        assert len(data["tombstones"]) == 1
        assert data["tombstones"][0]["name"] == "stale"

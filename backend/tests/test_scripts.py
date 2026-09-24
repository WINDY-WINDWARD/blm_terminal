"""Tests for Script Lab backend (validation, CRUD, revisions, chart state, migration)."""

from typing import AsyncGenerator

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import get_current_user
from app.database import Base, get_db, _set_sqlite_pragma
from app.models.user import User
import app.models  # noqa: F401
from app.schemas.script import validate_script
from app.services.script_seeds import SEEDS

VALID = SEEDS[0][2]


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
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
        yield session

    await eng.dispose()


@pytest.fixture
def current_user_holder():
    class UserHolder:
        def __init__(self):
            self.user = User(id=1, username="user1", hashed_password="pw1", is_admin=False)

    return UserHolder()


@pytest.fixture
def app(db_session: AsyncSession, current_user_holder):
    app = FastAPI()
    from app.routers.scripts import router as scripts_router

    app.include_router(scripts_router, prefix="/api")

    async def _override_get_db():
        yield db_session

    async def _override_get_current_user():
        return current_user_holder.user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _code(header: dict, body: str = "function calculate(ctx) { return { a: ctx.bars.map(function(){ return 1; }) }; }") -> str:
    import json
    return f"// @blm-script {json.dumps(header)}\n{body}"


def _good_header(**over) -> dict:
    h = {
        "name": "T", "version": 1,
        "params": [{"key": "p", "type": "int", "default": 5, "min": 1, "max": 9}],
        "outputs": [{"id": "a", "kind": "line"}],
    }
    h.update(over)
    return h


class TestValidate:
    def test_seed_valid(self):
        for _, _, code in SEEDS:
            manifest, errors = validate_script(code)
            assert errors == [], code[:60]
            assert manifest is not None and manifest.version == 1

    def test_missing_header(self):
        _, errors = validate_script("function calculate(ctx) { return {}; }")
        assert any(e.startswith("E_MANIFEST_JSON") for e in errors)

    def test_bad_json_header(self):
        _, errors = validate_script("// @blm-script {not json}\nfunction calculate(ctx) { return {}; }")
        assert any(e.startswith("E_MANIFEST_JSON") for e in errors)

    def test_version_2_rejected(self):
        _, errors = validate_script(_code(_good_header(version=2)))
        assert any("requires spec v2" in e for e in errors)

    def test_v2_kind_rejected(self):
        _, errors = validate_script(_code(_good_header(alerts=[{"id": "x"}])))
        assert any(e.startswith("E_V2_KIND") for e in errors)

    def test_unreferenced_param(self):
        _, errors = validate_script(_code(_good_header()))
        assert any(e.startswith("E_PARAM") for e in errors)

    def test_dup_param_keys(self):
        h = _good_header(params=[
            {"key": "p", "type": "int", "default": 1},
            {"key": "p", "type": "int", "default": 2},
        ])
        _, errors = validate_script(_code(h))
        assert any("duplicate param" in e for e in errors)

    def test_band_bad_refs(self):
        h = _good_header(
            params=[],
            outputs=[{"id": "b", "kind": "band", "upper": "nope", "lower": "alsono"}],
        )
        _, errors = validate_script(_code(h, "function calculate(ctx) { return { b: 1 }; }"))
        assert any("band" in e for e in errors)

    def test_async_banned(self):
        _, errors = validate_script(_code(
            _good_header(params=[]),
            "async function calculate(ctx) { return { a: [] }; }",
        ))
        assert any(e.startswith("E_STATIC") for e in errors)

    def test_eval_function_banned(self):
        for body in (
            'function calculate(ctx) { return eval("1"); }',
            'function calculate(ctx) { const F = Function("return 1"); return { a: [] }; }',
        ):
            _, errors = validate_script(_code(_good_header(params=[]), body))
            assert any(e.startswith("E_STATIC") for e in errors), body

    def test_missing_calculate(self):
        _, errors = validate_script(_code(_good_header(params=[]), "function nope() { return {}; }"))
        assert any("calculate" in e for e in errors)

    def test_size_cap(self):
        big = "x" * (65 * 1024)
        _, errors = validate_script(_code(_good_header(params=[]), f"function calculate(ctx) {{ return {{ a: [] }}; }} /* {big} */"))
        assert any(e.startswith("E_LIMIT") for e in errors)

    def test_too_many_outputs(self):
        h = _good_header(
            params=[],
            outputs=[{"id": f"o{i}", "kind": "line"} for i in range(9)],
        )
        _, errors = validate_script(_code(h, "function calculate(ctx) { return {}; }"))
        assert any("outputs" in e or "E_MANIFEST_SCHEMA" in e for e in errors)


class TestCrud:
    def test_list_seeds_builtins(self, client):
        items = client.get("/api/scripts").json()
        assert len(items) == 5
        assert all(i["is_builtin"] for i in items)

    def test_create_and_get(self, client):
        code = SEEDS[0][2].replace('"SMA-20/50"', '"Mine"')
        r = client.post("/api/scripts", json={"name": "Mine", "code": code})
        assert r.status_code == 201, r.text
        detail = r.json()
        assert detail["head_rev_no"] == 1
        assert detail["head"]["manifest"]["name"] == "Mine"
        g = client.get(f"/api/scripts/{detail['id']}").json()
        assert len(g["history"]) == 1

    def test_name_uniqueness(self, client):
        code = SEEDS[0][2].replace('"SMA-20/50"', '"Dup"')
        assert client.post("/api/scripts", json={"name": "Dup", "code": code}).status_code == 201
        r = client.post("/api/scripts", json={"name": "Dup", "code": code})
        assert r.status_code == 409

    def test_user_isolation(self, client, current_user_holder):
        code = SEEDS[0][2].replace('"SMA-20/50"', '"Priv"')
        sid = client.post("/api/scripts", json={"name": "Priv", "code": code}).json()["id"]
        current_user_holder.user = User(id=2, username="user2", hashed_password="pw2", is_admin=False)
        assert client.get(f"/api/scripts/{sid}").status_code == 404
        assert client.get("/api/scripts").json() != []

    def test_rename_and_soft_delete(self, client):
        code = SEEDS[0][2].replace('"SMA-20/50"', '"Tmp"')
        sid = client.post("/api/scripts", json={"name": "Tmp", "code": code}).json()["id"]
        assert client.post(f"/api/scripts/{sid}/rename", json={"name": "Tmp2"}).json()["name"] == "Tmp2"
        assert client.post(f"/api/scripts/{sid}/delete").json() == {"ok": True}
        assert client.get(f"/api/scripts/{sid}").status_code == 404
        assert all(i["name"] != "Tmp2" for i in client.get("/api/scripts").json())

    def test_builtin_protected(self, client):
        builtin = client.get("/api/scripts").json()[0]["id"]
        assert client.post(f"/api/scripts/{builtin}/delete").status_code == 403
        assert client.post(f"/api/scripts/{builtin}/rename", json={"name": "X"}).status_code == 403

    def test_revise_and_rollback(self, client):
        v1 = SEEDS[0][2].replace('"SMA-20/50"', '"Evo"')
        sid = client.post("/api/scripts", json={"name": "Evo", "code": v1}).json()["id"]
        v2 = v1.replace("ctx.params.len1", "ctx.params.len1").replace('"default":20', '"default":30')
        r = client.post(f"/api/scripts/{sid}/revise", json={"code": v2, "note": "tune"})
        assert r.status_code == 200, r.text
        assert r.json()["head_rev_no"] == 2
        rb = client.post(f"/api/scripts/{sid}/rollback", json={"rev_no": 1}).json()
        assert rb["head_rev_no"] == 1
        assert len(rb["history"]) == 2  # history preserved

    def test_revise_migrates_chart_params(self, client):
        v1 = SEEDS[0][2].replace('"SMA-20/50"', '"Mig"')
        sid = client.post("/api/scripts", json={"name": "Mig", "code": v1}).json()["id"]
        st = client.post("/api/chart-state?panel_id=panel-1",
                         json={"script_id": sid, "param_values": {"len1": 7, "len2": 60}}).json()
        assert st["param_values"] == {"len1": 7, "len2": 60}
        # Revise dropping len2, adding len3.
        v2 = v1.replace(
            '"params":[',
            '"params":[{"key":"len3","label":"Extra","type":"int","default":5,"min":1,"max":9},',
        ).replace(
            ',{"key":"len2","label":"Slow length","type":"int","default":50,"min":2,"max":200}', ""
        ).replace("ctx.params.len2", "ctx.params.len3")
        r = client.post(f"/api/scripts/{sid}/revise", json={"code": v2})
        assert r.status_code == 200, r.text
        rows = client.get("/api/chart-state?panel_id=panel-1").json()
        assert rows[0]["param_values"] == {"len1": 7}  # len2 dropped, len1 kept

    def test_rollback_migrates_chart_params(self, client):
        v1 = SEEDS[0][2].replace('"SMA-20/50"', '"RBM"')
        sid = client.post("/api/scripts", json={"name": "RBM", "code": v1}).json()["id"]
        # Revise swapping len2 for len3 (mirrors test_revise_migrates_chart_params),
        # then store a value for len3 (valid against rev 2).
        v2 = v1.replace(
            '"params":[',
            '"params":[{"key":"len3","label":"Extra","type":"int","default":5,"min":1,"max":9},',
        ).replace(
            ',{"key":"len2","label":"Slow length","type":"int","default":50,"min":2,"max":200}', ""
        ).replace("ctx.params.len2", "ctx.params.len3")
        r = client.post(f"/api/scripts/{sid}/revise", json={"code": v2})
        assert r.status_code == 200, r.text
        client.post("/api/chart-state?panel_id=panel-1",
                    json={"script_id": sid, "param_values": {"len1": 7, "len3": 5}})
        # Rollback to rev 1 (no len3): stored values migrate, len3 dropped.
        rb = client.post(f"/api/scripts/{sid}/rollback", json={"rev_no": 1})
        assert rb.status_code == 200, rb.text
        rows = client.get("/api/chart-state?panel_id=panel-1").json()
        assert rows[0]["param_values"] == {"len1": 7}
        # The reviewer's sequence: rollback-then-disable must not 422.
        off = client.post("/api/chart-state?panel_id=panel-1",
                          json={"script_id": sid, "enabled": False,
                                "param_values": rows[0]["param_values"]})
        assert off.status_code == 200, off.text


class TestChartState:
    def test_set_get_rejects_unknown_params(self, client):
        code = SEEDS[0][2].replace('"SMA-20/50"', '"CS"')
        sid = client.post("/api/scripts", json={"name": "CS", "code": code}).json()["id"]
        bad = client.post("/api/chart-state?panel_id=p1",
                          json={"script_id": sid, "param_values": {"nope": 1}})
        assert bad.status_code == 422
        ok = client.post("/api/chart-state?panel_id=p1",
                         json={"script_id": sid, "enabled": False, "param_values": {"len1": 10}})
        assert ok.json()["enabled"] is False
        rows = client.get("/api/chart-state?panel_id=p1").json()
        assert rows[0]["param_values"] == {"len1": 10}

    def test_omitted_params_keep_existing(self, client):
        code = SEEDS[0][2].replace('"SMA-20/50"', '"Keep"')
        sid = client.post("/api/scripts", json={"name": "Keep", "code": code}).json()["id"]
        client.post("/api/chart-state?panel_id=p2",
                    json={"script_id": sid, "param_values": {"len1": 33}})
        # Omitted param_values = keep (AI-accept re-enable path).
        kept = client.post("/api/chart-state?panel_id=p2",
                           json={"script_id": sid, "enabled": True}).json()
        assert kept["param_values"] == {"len1": 33}
        # Explicit empty dict still replaces (opt-out wipe).
        wiped = client.post("/api/chart-state?panel_id=p2",
                            json={"script_id": sid, "param_values": {}}).json()
        assert wiped["param_values"] == {}


class TestTransport:
    def test_export_import_roundtrip(self, client):
        code = SEEDS[1][2].replace('"EMA cross + markers"', '"RT"')
        sid = client.post("/api/scripts", json={"name": "RT", "code": code}).json()["id"]
        env = client.get(f"/api/scripts/{sid}/export").json()
        assert env["kind"] == "blm-script-export" and env["version"] == 1
        env["name"] = "RT-copy"
        r = client.post("/api/scripts/import", json={"payload": env})
        assert r.status_code == 201, r.text
        assert r.json()["head"]["code"] == code

    def test_import_rejects_bad_envelope(self, client):
        assert client.post("/api/scripts/import", json={"payload": {"kind": "nope"}}).status_code == 422

    def test_validate_endpoint(self, client):
        r = client.post("/api/scripts/validate", json={"code": VALID}).json()
        assert r["valid"] is True and r["name"] == "SMA-20/50"
        bad = client.post("/api/scripts/validate", json={"code": "no header"}).json()
        assert bad["valid"] is False and bad["errors"]


class TestMigration:
    def test_revision_chain(self):
        import importlib.util
        from pathlib import Path
        path = Path("alembic/versions/h66666666666_add_script_lab_tables.py")
        spec = importlib.util.spec_from_file_location("h66666666666_script_lab", path)
        assert spec is not None and spec.loader is not None
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        assert m.revision == "h66666666666"
        assert m.down_revision == "g55555555555"

    def test_up_down_on_scratch_db(self, tmp_path, monkeypatch):
        import sqlite3
        db_path = tmp_path / "scratch.db"
        con0 = sqlite3.connect(db_path)
        con0.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), "
            "hashed_password VARCHAR(255), is_admin BOOLEAN)"
        )
        con0.execute("CREATE TABLE chat_sessions (id INTEGER PRIMARY KEY)")
        con0.commit()
        con0.close()
        # env.py rebuilds the URL from settings — point settings at scratch.
        from app.config import settings
        monkeypatch.setattr(settings, "db_path", str(db_path))
        from alembic.config import Config
        from alembic import command as alembic_command

        cfg = Config("alembic.ini")
        # stamp at our parent then upgrade just our revision, then downgrade it.
        alembic_command.stamp(cfg, "g55555555555")
        alembic_command.upgrade(cfg, "+1")
        con = sqlite3.connect(db_path)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"saved_scripts", "script_revisions", "script_chart_state"} <= tables
        alembic_command.downgrade(cfg, "-1")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "saved_scripts" not in tables
        con.close()

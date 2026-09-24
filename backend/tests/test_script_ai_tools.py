"""Tests for Script Lab AI tools (Phase 4a): tool registration, Script-mode
prompt, CRUD through the tool layer, user isolation, and SSE script_card
extraction."""

import json
from typing import AsyncGenerator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import current_user_id
from app.database import Base, _set_sqlite_pragma
from app.models.user import User
import app.models  # noqa: F401
from app.services.script_seeds import SEEDS

VALID = SEEDS[0][2]


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
        # FK target for revision chat_session_id attribution.
        from app.models.ai_chat import ChatSession
        session.add(ChatSession(id=77, user_id=1))
        await session.commit()

    import app.services.script_ai_tools as tools_mod

    real_factory = tools_mod.AsyncSessionLocal
    tools_mod.AsyncSessionLocal = Session
    token = current_user_id.set(1)
    try:
        yield {"Session": Session}
    finally:
        tools_mod.AsyncSessionLocal = real_factory
        current_user_id.reset(token)
    await eng.dispose()


def _set_user(uid: int):
    current_user_id.set(uid)


class TestScriptModePrompt:
    def test_research_mode_has_no_script_prompt(self):
        from app.services.ai_chat_service import _get_system_prompt
        assert "Script Lab Mode" not in _get_system_prompt("RELIANCE", "NSE", None)
        assert "Script Lab Mode" not in _get_system_prompt("RELIANCE", "NSE", None, "research")

    def test_script_mode_appends_prompt(self):
        from app.services.ai_chat_service import _get_system_prompt
        prompt = _get_system_prompt("TCS", "NSE", None, "script")
        assert "Script Lab Mode" in prompt
        assert "validate_script_code" in prompt
        assert "calculate(ctx)" in prompt
        assert "TCS" in prompt  # base context preserved

    def test_persona_and_script_compose(self):
        from app.services.ai_chat_service import _get_system_prompt
        prompt = _get_system_prompt("INFY", "NSE", "value", "script")
        assert "Graham" in prompt  # persona kept
        assert "Script Lab Mode" in prompt


class TestToolRegistration:
    NAMES = {"list_scripts", "get_script", "validate_script_code", "create_script", "revise_script"}

    def test_openai_shape(self):
        from app.services.ai_chat_service import BLM_TOOLS
        assert self.NAMES <= {t["function"]["name"] for t in BLM_TOOLS}

    def test_anthropic_shape(self):
        from app.services.ai_chat_service import BLM_TOOLS_ANTHROPIC
        assert self.NAMES <= {t["name"] for t in BLM_TOOLS_ANTHROPIC}

    def test_dispatch(self):
        from app.services.ai_chat_service import _execute_tool  # noqa: F401
        import app.services.script_ai_tools as tools_mod
        for name in self.NAMES:
            assert callable(getattr(tools_mod, name if name != "validate_script_code" else "validate_script_code"))


class TestValidateTool:
    async def test_valid_seed(self, mem_db):
        from app.services.script_ai_tools import validate_script_code
        out = await validate_script_code(VALID)
        assert out["valid"] is True and out["errors"] == []

    async def test_invalid_code(self, mem_db):
        from app.services.script_ai_tools import validate_script_code
        out = await validate_script_code("no header here")
        assert out["valid"] is False and out["errors"]


class TestToolFlow:
    async def test_create_list_get_revise(self, mem_db):
        from app.services.script_ai_tools import (
            create_script, get_script, list_scripts, revise_script,
        )
        created = await create_script(
            name="AI Tool Flow", code=VALID, description="via tools",
            note="v1", chat_session_id=77,
        )
        assert created["rev_no"] == 1
        assert created["script_card"] == {
            "action": "created", "script_id": created["script_id"],
            "name": "AI Tool Flow", "rev_no": 1,
        }
        assert "script_card" in created  # card travels with the result pre-SSE

        items = await list_scripts()
        assert any(i["script_id"] == created["script_id"] for i in items)

        detail = await get_script(created["script_id"])
        assert detail["head_rev_no"] == 1
        assert detail["code"] == VALID
        assert detail["name"] == "AI Tool Flow"  # row name from the argument
        assert detail["manifest"]["name"] == "SMA-20/50"  # manifest name from code header

        v2 = VALID.replace('"default":20', '"default":30')
        assert v2 != VALID
        revised = await revise_script(created["script_id"], code=v2, note="tune", chat_session_id=77)
        assert revised["rev_no"] == 2
        assert revised["script_card"]["action"] == "revised"
        detail2 = await get_script(created["script_id"])
        assert detail2["head_rev_no"] == 2
        assert detail2["rev_nos"] == [1, 2]

        # chat_session_id attributed on the new revision row
        Session = mem_db["Session"]
        async with Session() as session:
            from app.models.script import ScriptRevision
            rev2 = (
                await session.execute(
                    sa.select(ScriptRevision).where(
                        ScriptRevision.script_id == created["script_id"],
                        ScriptRevision.rev_no == 2,
                    )
                )
            ).scalar_one()
            assert rev2.chat_session_id == 77

    async def test_user_isolation(self, mem_db):
        from app.services.script_ai_tools import create_script, get_script, list_scripts
        created = await create_script(name="Private", code=VALID)
        _set_user(2)
        try:
            assert await list_scripts() != []  # builtins seeded for user 2
            assert all(i["script_id"] != created["script_id"] for i in await list_scripts())
            with pytest.raises(Exception):
                await get_script(created["script_id"])
        finally:
            _set_user(1)

    async def test_duplicate_name_rejected(self, mem_db):
        from app.services.script_ai_tools import create_script
        await create_script(name="Dup", code=VALID)
        with pytest.raises(Exception):
            await create_script(name="Dup", code=VALID)

    async def test_revise_builtin_forbidden(self, mem_db):
        from app.services.script_ai_tools import list_scripts, revise_script
        builtin = next(i for i in await list_scripts() if i["is_builtin"])
        with pytest.raises(Exception):
            await revise_script(builtin["script_id"], code=VALID)


class TestCardEvent:
    async def test_card_split_from_llm_payload(self, monkeypatch):
        import app.services.ai_chat_service as svc

        seen = {}

        async def _fake_execute(name, args):
            seen.update(args)
            return {
                "script_id": 5, "name": "Card", "rev_no": 2,
                "outputs": ["a"], "params": ["p"],
                "script_card": {"action": "revised", "script_id": 5, "name": "Card", "rev_no": 2},
            }

        monkeypatch.setattr(svc, "_execute_tool", _fake_execute)
        events, msgs = await svc._run_tools_parallel(
            [{"name": "revise_script", "args": {"script_id": 5, "code": "x"}, "id": "c1"}],
            set(), session_id=9,
        )
        # session attribution injected for mutation tools
        assert seen.get("chat_session_id") == 9
        # one tool_result + one script_card event
        by_type = [json.loads(e).get("type") for e in events]
        assert by_type == ["tool_result", "script_card"]
        card = json.loads(events[1])
        assert (card["action"], card["script_id"], card["rev_no"]) == ("revised", 5, 2)
        # LLM payload carries the outcome but not the card
        content = json.loads(msgs[0]["content"])
        assert content["rev_no"] == 2 and "script_card" not in content

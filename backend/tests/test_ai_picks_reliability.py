"""Catch-up decisions, prompt/tool parity, and freshness rules for AI picks.

Covers Final Plan sections 1 (reliability) and 5 (tests). DB-touching paths
are exercised through fakes; the live scheduler behavior is asserted via the
pure decision helpers with explicit dates.
"""
from datetime import datetime, timezone

from app.services.ai_chat_service import BLM_TOOLS
from app.workers import ai_picks_worker as w


# --- Catch-up decision matrix (§1.1-1.2, §5) ---------------------------------

def test_morning_due_when_never_succeeded():
    assert w._morning_due(None, "2026-09-21") is True


def test_morning_due_when_failed_yesterday_but_not_today():
    assert w._morning_due("2026-09-20", "2026-09-21") is True


def test_morning_not_due_when_succeeded_today():
    assert w._morning_due("2026-09-21", "2026-09-21") is False


def test_evening_due_past_close_with_unevaluated_picks():
    assert w._evening_due(None, "2026-09-21", True, True) is True


def test_evening_not_due_without_picks():
    # App was off all day: morning runner covers it, skip silently.
    assert w._evening_due(None, "2026-09-21", False, True) is False


def test_evening_not_due_before_close():
    assert w._evening_due(None, "2026-09-21", True, False) is False


def test_evening_not_due_when_already_evaluated():
    assert w._evening_due("2026-09-21", "2026-09-21", True, True) is False


def test_today_ist_str_and_past_market_hours():
    # 10:00 UTC = 15:30 IST -> exactly at close boundary
    at_close = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    assert w._today_ist_str(at_close) == "2026-09-21"
    assert w._past_market_hours(at_close) is True
    morning = datetime(2026, 9, 21, 2, 0, tzinfo=timezone.utc)  # 07:30 IST
    assert w._past_market_hours(morning) is False
    # 18:30 UTC = midnight IST next day
    midnight = datetime(2026, 9, 21, 18, 30, tzinfo=timezone.utc)
    assert w._today_ist_str(midnight) == "2026-09-22"


# --- Prompt/tool parity: every tool named in prompts must be callable (§4) ---

def _prompt_tool_names():
    import re
    names = set()
    for prompt in (w.HUNTER_PROMPT, w.VERIFIER_PROMPT, w.EVALUATOR_PROMPT):
        names.update(re.findall(r"`([a-z][a-z0-9_]+)`", prompt))
    return names


def test_prompt_tools_all_advertised():
    """Guards the get_upcoming_events-class mismatch: named => in BLM_TOOLS."""
    advertised = {t["function"]["name"] for t in BLM_TOOLS}
    # Non-tool backtick terms used prose-wise in prompts (tiers, field names).
    prose = {"low", "medium", "high", "last_updated"}
    missing = {n for n in _prompt_tool_names() - prose if n not in advertised}
    assert not missing, f"prompt names tools not in BLM_TOOLS: {missing}"


def test_events_tools_advertised():
    advertised = {t["function"]["name"] for t in BLM_TOOLS}
    assert "get_upcoming_events" in advertised
    assert "get_recent_announcements" in advertised


def test_no_duplicate_tool_names():
    """Antigravity rejects duplicate function declarations with 400."""
    names = [t["function"]["name"] for t in BLM_TOOLS]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate tool declarations: {dupes}"


# --- Freshness rule wording present in all three prompts (§3) -----------------

def test_freshness_rules_present():
    for prompt in (w.HUNTER_PROMPT, w.VERIFIER_PROMPT, w.EVALUATOR_PROMPT):
        assert "last_updated" in prompt
        assert "48 hours" in prompt


def test_hunter_owns_news_fetching():
    assert "get_global_news" in w.HUNTER_PROMPT
    assert "get_company_news" in w.HUNTER_PROMPT
    assert "NO news" in w.HUNTER_PROMPT


def test_verifier_repulls_news_independently():
    assert "get_company_news" in w.VERIFIER_PROMPT
    assert "never trust" in w.VERIFIER_PROMPT.lower()


# --- Task 2: Evaluator reliability, failure atomicity, and session isolation ---

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
import pytest

from app.database import Base
from app.models.ai_picks import AIPick, AIPickTrace, PickStatus, PickDirection
from app.models.system_config import SystemConfig


@pytest.fixture(autouse=True)
def _isolate_job_progress(monkeypatch):
    """Isolate progress reporting so background update_job_status tasks are not scheduled."""
    monkeypatch.setattr("app.jobs.runner.report_progress", lambda *args, **kwargs: None)


@pytest.fixture
async def memory_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield session_maker
    await engine.dispose()


async def test_call_evaluator_provider_failure_returns_error_and_preserves_hold(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))

    async def fail_agent_loop(*args, **kwargs):
        raise RuntimeError("Provider 503 Service Unavailable")

    monkeypatch.setattr(w, "_run_agent_loop_retry", fail_agent_loop)

    pick_data = {"symbol": "TATAMOTORS", "entry": 900.0, "notes": []}
    res = await w._call_evaluator(pick_data, "test-context")

    assert isinstance(res, tuple) and len(res) == 2, "_call_evaluator must return (evaluation, error)"
    eval_data, error = res
    assert eval_data.get("action") == "HOLD"
    assert error is not None
    assert "503" in error or "Provider" in error

    async with memory_db() as db:
        traces = (await db.execute(select(AIPickTrace).where(AIPickTrace.symbol == "TATAMOTORS"))).scalars().all()
        assert len(traces) == 1
        assert traces[0].status == "FAILED"
        assert traces[0].error_message is not None


async def test_call_evaluator_parse_failure_records_failed_trace_and_hold(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_run_agent_loop_retry", AsyncMock(return_value="<evaluation>invalid json content</evaluation>"))

    pick_data = {"symbol": "INFY", "entry": 1500.0, "notes": []}
    res = await w._call_evaluator(pick_data, "test-context")

    assert isinstance(res, tuple) and len(res) == 2
    eval_data, error = res
    assert eval_data.get("action") == "HOLD"
    assert error is not None
    assert "unparseable" in error.lower() or "parsing" in error.lower()

    async with memory_db() as db:
        traces = (await db.execute(select(AIPickTrace).where(AIPickTrace.symbol == "INFY"))).scalars().all()
        assert len(traces) == 1
        assert traces[0].status == "FAILED"
        assert traces[0].error_message is not None


async def test_call_evaluator_non_object_output_treated_as_parse_failure(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_run_agent_loop_retry", AsyncMock(return_value='<evaluation>[{"action": "BUY"}]</evaluation>'))

    pick_data = {"symbol": "RELIANCE", "entry": 2800.0, "notes": []}
    res = await w._call_evaluator(pick_data, "test-context")

    assert isinstance(res, tuple) and len(res) == 2
    eval_data, error = res
    assert eval_data.get("action") == "HOLD"
    assert error is not None
    assert "object" in error.lower() or "dict" in error.lower()

    async with memory_db() as db:
        traces = (await db.execute(select(AIPickTrace).where(AIPickTrace.symbol == "RELIANCE"))).scalars().all()
        assert len(traces) == 1
        assert traces[0].status == "FAILED"
        assert traces[0].error_message is not None


async def test_call_evaluator_success_returns_clean_evaluation_and_success_trace(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    valid_eval = '<evaluation>{"action": "HOLD", "note": "Strong bounce", "verdict": "WAIT"}</evaluation>'
    monkeypatch.setattr(w, "_run_agent_loop_retry", AsyncMock(return_value=valid_eval))

    pick_data = {"symbol": "SBIN", "entry": 750.0, "notes": []}
    res = await w._call_evaluator(pick_data, "test-context")

    assert isinstance(res, tuple) and len(res) == 2
    eval_data, error = res
    assert error is None
    assert eval_data.get("action") == "HOLD"
    assert eval_data.get("verdict") == "WAIT"

    async with memory_db() as db:
        traces = (await db.execute(select(AIPickTrace).where(AIPickTrace.symbol == "SBIN"))).scalars().all()
        assert len(traces) == 1
        assert traces[0].status == "SUCCESS"
        assert traces[0].error_message is None


async def test_concurrent_evaluator_traces_use_distinct_sessions(memory_db, monkeypatch):
    created_sessions = []
    real_session_maker = memory_db

    def tracking_session_factory():
        session = real_session_maker()
        created_sessions.append(session)
        return session

    monkeypatch.setattr(w, "AsyncSessionLocal", tracking_session_factory)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_fetch_market_context", AsyncMock(return_value="test-market-context"))

    valid_eval = '<evaluation>{"action": "HOLD", "note": "All good"}</evaluation>'
    monkeypatch.setattr(w, "_run_agent_loop_retry", AsyncMock(return_value=valid_eval))

    async with real_session_maker() as init_db:
        init_db.add(AIPick(symbol="SYM1", direction=PickDirection.LONG, entry_price=100.0, take_profit=110.0, stop_loss=95.0, status=PickStatus.NEW, notes=[]))
        init_db.add(AIPick(symbol="SYM2", direction=PickDirection.LONG, entry_price=200.0, take_profit=220.0, stop_loss=190.0, status=PickStatus.NEW, notes=[]))
        await init_db.commit()

    created_sessions.clear()
    res = await w.run_loop_3(late=False)
    assert res is True

    assert len(created_sessions) >= 3, f"Expected outer loop session + 2 evaluator sessions, got {len(created_sessions)}"
    outer_session = created_sessions[0]
    eval_sessions = created_sessions[1:3]
    assert eval_sessions[0] is not eval_sessions[1], "Evaluator tasks must use distinct sessions"
    assert eval_sessions[0] is not outer_session, "Evaluator task must not share outer loop session"
    assert eval_sessions[1] is not outer_session, "Evaluator task must not share outer loop session"


async def test_loop_3_and_evening_run_provider_failure_atomicity(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_fetch_market_context", AsyncMock(return_value="market-context"))

    async with memory_db() as db:
        pick = AIPick(
            symbol="TCS",
            direction=PickDirection.LONG,
            entry_price=3500.0,
            take_profit=3800.0,
            stop_loss=3300.0,
            status=PickStatus.NEW,
            notes=[],
        )
        db.add(pick)
        await db.commit()

    async def fail_agent_loop(*args, **kwargs):
        raise RuntimeError("Connection to LLM provider failed")

    monkeypatch.setattr(w, "_run_agent_loop_retry", fail_agent_loop)

    job_status_updates = []
    success_marks = []
    progress_reports = []
    monkeypatch.setattr("app.jobs.runner.report_progress", lambda *a, **k: progress_reports.append((a, k)))
    monkeypatch.setattr("app.jobs.runner.update_job_status_sync", lambda *a, **k: job_status_updates.append((a, k)))
    monkeypatch.setattr("app.jobs.runner.mark_job_success_sync", lambda *a, **k: success_marks.append((a, k)))

    loop_res = await w.run_loop_3(late=False)
    assert loop_res is False, "run_loop_3 must return False when evaluator fails"

    # Verify failure progress was reported at < 100 (e.g. 95) so report_progress does not map it to idle
    failure_reports = [(a, k) for a, k in progress_reports if "Evaluator failed" in str(a) or "Evaluator failed" in str(k)]
    assert len(failure_reports) > 0, "Expected a failure progress report"
    reported_pct = failure_reports[0][0][1] if len(failure_reports[0][0]) > 1 else failure_reports[0][1].get("percent")
    assert reported_pct < 100, f"Failure progress must report < 100 (got {reported_pct}) to avoid mapping to idle"
    assert reported_pct == 95, f"Expected 95% on failure, got {reported_pct}"

    await asyncio.to_thread(w._execute_evening_run, False)

    assert not any("job.ai_picks_evening" in str(a) for a, _ in success_marks), "mark_job_success_sync must NOT be called on failure"
    failed_statuses = [k for a, k in job_status_updates if len(a) > 1 and a[1] == "failed" or k.get("status") == "failed"]
    assert len(failed_statuses) > 0, "_execute_evening_run must report job as failed"

    async with memory_db() as db:
        db_pick = (await db.execute(select(AIPick).where(AIPick.symbol == "TCS"))).scalar_one()
        assert db_pick.status == PickStatus.NEW
        assert db_pick.notes == [], "Pick notes must NOT be modified when evaluation fails"
        last_eval = await w._get_config_value(db, w._LAST_EVAL_KEY)
        assert last_eval is None, "_LAST_EVAL_KEY must not be advanced on failure"


async def test_loop_3_and_evening_run_parse_failure_atomicity_with_multiple_picks(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_fetch_market_context", AsyncMock(return_value="market-context"))

    async with memory_db() as db:
        db.add(AIPick(symbol="P1_VALID", direction=PickDirection.LONG, entry_price=100.0, take_profit=110.0, stop_loss=95.0, status=PickStatus.NEW, notes=[]))
        db.add(AIPick(symbol="P2_BAD", direction=PickDirection.LONG, entry_price=200.0, take_profit=220.0, stop_loss=190.0, status=PickStatus.NEW, notes=[]))
        await db.commit()

    async def mock_agent_loop(messages, model, system_prompt, label="", **kwargs):
        if "P1_VALID" in label:
            return '<evaluation>{"action": "HOLD", "note": "All looks fine"}</evaluation>'
        return '<evaluation>[{"action": "HOLD"}]</evaluation>'

    monkeypatch.setattr(w, "_run_agent_loop_retry", mock_agent_loop)

    job_status_updates = []
    success_marks = []
    monkeypatch.setattr("app.jobs.runner.update_job_status_sync", lambda *a, **k: job_status_updates.append((a, k)))
    monkeypatch.setattr("app.jobs.runner.mark_job_success_sync", lambda *a, **k: success_marks.append((a, k)))

    loop_res = await w.run_loop_3(late=False)
    assert loop_res is False, "run_loop_3 must return False when any evaluator fails"

    await asyncio.to_thread(w._execute_evening_run, False)

    assert not any("job.ai_picks_evening" in str(a) for a, _ in success_marks)

    async with memory_db() as db:
        p1 = (await db.execute(select(AIPick).where(AIPick.symbol == "P1_VALID"))).scalar_one()
        p2 = (await db.execute(select(AIPick).where(AIPick.symbol == "P2_BAD"))).scalar_one()
        assert p1.notes == [], "Atomic rollback: P1 notes must not be modified when another pick fails"
        assert p2.notes == [], "P2 notes must not be modified"
        last_eval = await w._get_config_value(db, w._LAST_EVAL_KEY)
        assert last_eval is None, "_LAST_EVAL_KEY must not be advanced"


async def test_loop_3_and_evening_run_success_commits_and_advances_marker(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_fetch_market_context", AsyncMock(return_value="market-context"))
    monkeypatch.setattr(w, "_today_ist_str", lambda *args: "2026-10-22")

    async with memory_db() as db:
        pick = AIPick(
            symbol="WIPRO",
            direction=PickDirection.LONG,
            entry_price=500.0,
            take_profit=550.0,
            stop_loss=480.0,
            status=PickStatus.NEW,
            notes=[],
        )
        db.add(pick)
        await db.commit()

    valid_eval = '<evaluation>{"action": "HOLD", "note": "Consolidating neatly", "verdict": "WAIT"}</evaluation>'
    monkeypatch.setattr(w, "_run_agent_loop_retry", AsyncMock(return_value=valid_eval))

    job_status_updates = []
    success_marks = []
    monkeypatch.setattr("app.jobs.runner.update_job_status_sync", lambda *a, **k: job_status_updates.append((a, k)))
    monkeypatch.setattr("app.jobs.runner.mark_job_success_sync", lambda *a, **k: success_marks.append((a, k)))

    loop_res = await w.run_loop_3(late=False)
    assert loop_res is True

    await asyncio.to_thread(w._execute_evening_run, False)

    assert any("job.ai_picks_evening" in str(a) for a, _ in success_marks), "mark_job_success_sync must be called on success"

    async with memory_db() as db:
        db_pick = (await db.execute(select(AIPick).where(AIPick.symbol == "WIPRO"))).scalar_one()
        assert len(db_pick.notes) > 0, "Pick notes must be updated on successful evaluation"
        last_eval = await w._get_config_value(db, w._LAST_EVAL_KEY)
        assert last_eval == "2026-10-22", "_LAST_EVAL_KEY must be set to today on success"


async def test_hunter_failure_skips_verifier_and_marks_morning_failed(memory_db, monkeypatch):
    monkeypatch.setattr(w, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(w, "_fetch_market_context", AsyncMock(return_value="market-context"))
    monkeypatch.setattr(w, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))
    monkeypatch.setattr(w, "_call_hunter", AsyncMock(return_value=([], "Hunter API failed after retries: timeout")))
    verifier_mock = AsyncMock()
    monkeypatch.setattr(w, "_call_verifier", verifier_mock)

    outcome = await w.run_loop_1_and_2(late=False)
    assert outcome.startswith("error:"), "run_loop_1_and_2 must return error when hunter fails"
    assert "timeout" in outcome
    verifier_mock.assert_not_called()

    job_status_updates = []
    success_marks = []
    monkeypatch.setattr("app.jobs.runner.update_job_status_sync", lambda *a, **k: job_status_updates.append((a, k)))
    monkeypatch.setattr("app.jobs.runner.mark_job_success_sync", lambda *a, **k: success_marks.append((a, k)))

    await asyncio.to_thread(w._execute_morning_run, False)

    verifier_mock.assert_not_called()
    assert not any("job.ai_picks_morning" in str(a) for a, _ in success_marks)
    failed_updates = [k for a, k in job_status_updates if len(a) > 1 and a[1] == "failed" or k.get("status") == "failed"]
    assert len(failed_updates) > 0, "Morning run must report failed when hunter fails"

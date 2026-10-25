import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.ai_picks import AIPick, AIPickTrace
from app.services.llm_provider import (
    _friendly_gateway_error,
    _friendly_network_error,
    _run_openai_loop,
)
from app.services.morningstar_client import MorningstarClient
from app.services.redaction import redact_mapping, redact_text
import app.workers.ai_picks_worker as ai_worker


@pytest.fixture
def isolate_progress(monkeypatch):
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


@pytest.mark.asyncio
async def test_antigravity_http_failure_excludes_raw_body_and_logs_safe_fields(caplog, monkeypatch):
    sentinel = "SECRET_SENTINEL_ANTIGRAVITY_BODY_XYZ999"

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 503
            self.headers = {}

        async def aread(self):
            return f'{{"error": "service unavailable", "secret": "{sentinel}"}}'.encode("utf-8")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=MockStreamResponse())
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: mock_client)

    caplog.set_level(logging.DEBUG)
    events = []
    async for item in _run_openai_loop(
        messages=[{"role": "user", "content": "hi"}],
        model="gemini-3.8-flash-high",
        api_key="fake-key",
        tools=[],
        tool_executor=None,
        api_label="Proxy (direct:gemini)",
        base_url="http://127.0.0.1:8123/v1",
        retry_429=False,
    ):
        events.append(json.loads(item))

    # Sentinel must NOT appear in logged output
    assert sentinel not in caplog.text, "Raw response body leaked in logs"

    # User-facing error must not leak raw body or secret
    err_events = [e for e in events if e.get("type") == "error"]
    assert len(err_events) == 1
    err_msg = err_events[0].get("message", "")
    assert sentinel not in err_msg, "Raw response body leaked in user-facing error"
    assert "503" in err_msg, "Safe status code 503 should be retained in user message"


@pytest.mark.asyncio
async def test_antigravity_timeout_excludes_exception_details_and_logs_safe_fields(caplog, monkeypatch):
    sentinel = "SECRET_SENTINEL_TIMEOUT_URL_TOKEN_1111"

    class MockFailingClient:
        def stream(self, *args, **kwargs):
            raise httpx.ReadTimeout(f"Read timed out on https://api.google.com?token={sentinel}")

    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: MockFailingClient())

    caplog.set_level(logging.DEBUG)
    events = []
    async for item in _run_openai_loop(
        messages=[{"role": "user", "content": "hi"}],
        model="gemini-3.8-flash-high",
        api_key="fake-key",
        tools=[],
        tool_executor=None,
        api_label="Proxy (direct:gemini)",
        base_url="http://127.0.0.1:8123/v1",
        retry_429=False,
    ):
        events.append(json.loads(item))

    assert sentinel not in caplog.text, "Secret leaked in timeout log"
    assert "route=Proxy (direct:gemini)" in caplog.text or "Proxy (direct:gemini)" in caplog.text
    assert "error_class=ReadTimeout" in caplog.text

    err_events = [e for e in events if e.get("type") == "error"]
    assert len(err_events) == 1
    err_msg = err_events[0].get("message", "")
    assert sentinel not in err_msg, "Secret leaked in user-facing error message"
    assert err_events[0].get("error_class") == "ReadTimeout"


def test_friendly_gateway_error_redacts_raw_bodies_and_retains_safe_status():
    sentinel = "SECRET_SENTINEL_RAW_GATEWAY_BODY_2222"

    # FreeTierError
    msg = _friendly_gateway_error("Zen Provider", 429, f"FreeTierError: rate limited {sentinel}")
    assert sentinel not in msg
    assert "(Raw:" not in msg
    assert "free tier" in msg.lower() or "opencode" in msg.lower()

    # Model unavailable
    msg = _friendly_gateway_error("Zen Provider", 404, f"Model is unavailable: {sentinel}")
    assert sentinel not in msg
    assert "(Raw:" not in msg
    assert "unavailable" in msg.lower()

    # 500 internal server error
    msg = _friendly_gateway_error("Zen Provider", 500, f"Internal server error: {sentinel}")
    assert sentinel not in msg
    assert "(Raw:" not in msg
    assert "internal error" in msg.lower()

    # Quota with reset
    msg = _friendly_gateway_error("Zen Provider", 429, f"Resource exhausted. Resets in 14h20m. Token={sentinel}")
    assert sentinel not in msg
    assert "14h20m" in msg
    assert "quota" in msg.lower()

    # 401 Unauthorized
    msg = _friendly_gateway_error("Antigravity API", 401, f"Unauthorized token: {sentinel}")
    assert sentinel not in msg
    assert "401" in msg
    assert "reconnect" in msg.lower()

    # Generic 503
    msg = _friendly_gateway_error("Antigravity API", 503, f"Upstream blown: {sentinel}")
    assert sentinel not in msg
    assert msg.startswith("Antigravity API 503")


def test_friendly_network_error_redacts_credentials_and_retains_error_class():
    sentinel = "SECRET_SENTINEL_NETWORK_3333"
    exc = httpx.ConnectError(f"Failed connecting to https://host.com/v1?token={sentinel}")
    msg = _friendly_network_error("OpenCode", exc)
    assert sentinel not in msg
    assert msg.startswith("OpenCode network error (ConnectError)")


@pytest.mark.asyncio
async def test_morningstar_token_extraction_does_not_log_token_fragments(caplog):
    sentinel_acc = "SENTINEL_MS_ACCESS_TOKEN_4444_SECRET"
    sentinel_rt = "SENTINEL_MS_REALTIME_TOKEN_5555_SECRET"

    html = f"""
    <html>
      <head>
        <meta name="accessToken" content="{sentinel_acc}">
        <meta name="realTimeToken" content="{sentinel_rt}">
      </head>
    </html>
    """
    client = MorningstarClient()
    caplog.set_level(logging.INFO)
    tokens = await client._extract_tokens_from_html(html)

    assert tokens.get("access_token") == sentinel_acc
    assert tokens.get("X-Api-Realtime-E") == sentinel_rt

    # Ensure neither full token nor prefix/fragment is logged
    assert sentinel_acc not in caplog.text
    assert sentinel_rt not in caplog.text
    assert sentinel_acc[:15] not in caplog.text
    assert sentinel_rt[:15] not in caplog.text
    assert "Found accessToken" in caplog.text
    assert "Found realtimeToken" in caplog.text


@pytest.mark.asyncio
async def test_morningstar_fair_value_does_not_log_response_bodies_or_credentials(caplog, monkeypatch):
    sentinel_body = "SENTINEL_MS_FAIRVALUE_BODY_SECRET_6666"

    client = MorningstarClient()
    monkeypatch.setattr(client, "_ensure_tokens", AsyncMock(return_value={"access_token": "t", "X-Api-Realtime-E": "rt"}))

    class MockResp401:
        status_code = 401
        text = f"401 Unauthorized with secret: {sentinel_body}"
        def json(self):
            return {}

    class MockResp200BadJson:
        status_code = 200
        text = f"Invalid json body with secret: {sentinel_body}"
        def json(self):
            raise ValueError("bad json")

    responses = [MockResp401(), MockResp200BadJson()]
    idx = 0
    async def mock_get(*args, **kwargs):
        nonlocal idx
        r = responses[idx]
        idx = min(idx + 1, len(responses) - 1)
        return r

    mock_http_client = MagicMock()
    mock_http_client.get = mock_get
    monkeypatch.setattr("app.services.morningstar_client._get_client", AsyncMock(return_value=mock_http_client))

    caplog.set_level(logging.DEBUG)
    res = await client._get_fair_value_impl("0P0000BEC4")
    assert res is None
    assert sentinel_body not in caplog.text, "Morningstar response body leaked in logs"


@pytest.mark.asyncio
async def test_ai_picks_parsing_failure_does_not_log_raw_model_content(caplog, memory_db, monkeypatch, isolate_progress):
    monkeypatch.setattr(ai_worker, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(ai_worker, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))

    hunter_sentinel = "SENTINEL_HUNTER_RAW_OUTPUT_7777"
    verifier_sentinel = "SENTINEL_VERIFIER_RAW_OUTPUT_8888"
    eval_sentinel = "SENTINEL_EVALUATOR_RAW_OUTPUT_9999"

    caplog.set_level(logging.DEBUG)

    # 1. Hunter parsing failure
    monkeypatch.setattr(ai_worker, "_run_agent_loop_retry", AsyncMock(return_value=f"Not json {hunter_sentinel}"))
    async with memory_db() as db:
        picks, err = await ai_worker._call_hunter(db)
        assert err is not None
        worker_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app.workers"))
        assert hunter_sentinel not in worker_logs, "Hunter raw content leaked in log"
        assert "Raw content:" not in worker_logs
        assert hunter_sentinel not in err, "Hunter raw content leaked in error message"
        assert "unparseable" in err.lower() or "json" in err.lower()

    # 2. Verifier parsing failure
    monkeypatch.setattr(ai_worker, "_run_agent_loop_retry", AsyncMock(return_value=f"Not json {verifier_sentinel}"))
    async with memory_db() as db:
        picks, err = await ai_worker._call_verifier(db, [{"symbol": "TEST"}])
        assert err is not None
        worker_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app.workers"))
        assert verifier_sentinel not in worker_logs, "Verifier raw content leaked in log"
        assert "Raw content:" not in worker_logs
        assert verifier_sentinel not in err, "Verifier raw content leaked in error message"
        assert "unparseable" in err.lower() or "json" in err.lower()

    # 3. Evaluator parsing failure
    monkeypatch.setattr(ai_worker, "_run_agent_loop_retry", AsyncMock(return_value=f"Not json {eval_sentinel}"))
    eval_data, err = await ai_worker._call_evaluator({"symbol": "TEST", "entry": 100.0, "notes": []})
    assert err is not None
    worker_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app.workers"))
    assert eval_sentinel not in worker_logs, "Evaluator raw content leaked in log"
    assert "Raw content:" not in worker_logs
    assert eval_sentinel not in err, "Evaluator raw content leaked in error message"
    assert "unparseable" in err.lower() or "json" in err.lower()


@pytest.mark.asyncio
async def test_ai_picks_api_failure_redacts_credentials_in_logs_and_traces(caplog, memory_db, monkeypatch, isolate_progress):
    monkeypatch.setattr(ai_worker, "AsyncSessionLocal", memory_db)
    monkeypatch.setattr(ai_worker, "get_dynamic_models", AsyncMock(return_value=("hunter-m", "verifier-m")))

    sentinel_key = "sk-ant-SECRETKEY123456789"

    async def fail_loop(*args, **kwargs):
        raise RuntimeError(f"Provider 503 error with authorization bearer {sentinel_key}")

    monkeypatch.setattr(ai_worker, "_run_agent_loop_retry", fail_loop)
    caplog.set_level(logging.DEBUG)

    eval_data, err = await ai_worker._call_evaluator({"symbol": "TEST", "entry": 100.0, "notes": []})
    assert err is not None
    assert sentinel_key not in caplog.text, "Credential leaked in AI Picks error log"
    assert sentinel_key not in eval_data.get("note", ""), "Credential leaked in pick note"
    assert sentinel_key not in err, "Credential leaked in returned error string"
    assert "503" in err or "RuntimeError" in err or "Provider" in err

    # Check trace
    async with memory_db() as db:
        traces = (await db.execute(select(AIPickTrace).where(AIPickTrace.symbol == "TEST"))).scalars().all()
        assert len(traces) == 1
        assert traces[0].status == "FAILED"
        assert sentinel_key not in (traces[0].error_message or ""), "Credential leaked in AIPickTrace"


def test_ai_picks_job_execution_exception_redacts_credentials(caplog, monkeypatch):
    sentinel_pass = "SECRET_DB_PASSWORD_XYZ555"

    monkeypatch.setattr("app.backgroundtasks._runtime._run_async", MagicMock(side_effect=Exception(f"DB connection failure: password={sentinel_pass}")))
    status_updates = []
    monkeypatch.setattr(
        "app.jobs.runner.update_job_status_sync",
        lambda job_id, status, **kwargs: status_updates.append((job_id, status, kwargs)),
    )

    caplog.set_level(logging.DEBUG)

    ai_worker._execute_morning_run(late=False)
    assert sentinel_pass not in caplog.text, "Secret leaked in Morning run exception log"
    assert len(status_updates) > 0
    last_update = status_updates[-1]
    assert sentinel_pass not in str(last_update), "Secret leaked in Morning job status update"

    status_updates.clear()
    ai_worker._execute_evening_run(late=False)
    assert sentinel_pass not in caplog.text, "Secret leaked in Evening run exception log"
    assert len(status_updates) > 0
    last_update = status_updates[-1]
    assert sentinel_pass not in str(last_update), "Secret leaked in Evening job status update"


# --- Shared redaction module -------------------------------------------------


def test_redact_text_masks_every_rule_family():
    text = (
        "Bearer abc.def-ghi sk-abcdef123456 "
        "client_secret=abc123 password=hunter2 "
        "?token=tok123&api_key=key456 SENTINEL_APP_SECRET_VALUE "
        "SECRET_VALUE_SENTINEL"
    )
    out = redact_text(text)

    for leaked in (
        "abc.def-ghi",
        "sk-abcdef123456",
        "abc123",
        "hunter2",
        "tok123",
        "key456",
        "SENTINEL_APP_SECRET_VALUE",
        "SECRET_VALUE_SENTINEL",
    ):
        assert leaked not in out, f"{leaked} leaked through redact_text"


def test_redact_text_strip_query_removes_the_whole_query():
    out = redact_text("callback failed at http://127.0.0.1/cb?code=abc&state=def", strip_query=True)
    assert out == "callback failed at http://127.0.0.1/cb"


def test_redact_text_limit_and_default():
    long_text = "x" * 400
    truncated = redact_text(long_text, limit=300)
    assert truncated == ("x" * 300) + "..."
    assert redact_text(long_text) == long_text
    assert redact_text(None, default="fallback") == "fallback"


def test_redact_mapping_redacts_nested_lists_and_headers():
    payload = {
        "api_key": "k",
        "nested": {"password": "p", "ok": 1},
        "items": [{"token": "t"}],
        "headers": {"Authorization": "Bearer x", "X-Other": "y"},
    }
    out = redact_mapping(payload)

    assert out["api_key"] == "[REDACTED]"
    assert out["nested"] == {"password": "[REDACTED]", "ok": 1}
    assert out["items"] == [{"token": "[REDACTED]"}]
    assert out["headers"] == {"Authorization": "[REDACTED]", "X-Other": "[REDACTED]"}


def test_redaction_wrappers_delegate_to_shared_module():
    from app.services.oauth_session_manager import redact_oauth_error
    from app.services.proxy_supervisor import redact_sensitive_data

    assert redact_oauth_error(None) == "OAuth authorization failed"
    assert redact_oauth_error("failed at http://x/cb?code=abc") == "failed at http://x/cb"
    assert redact_sensitive_data({"access_token": "abc"}) == {"access_token": "[REDACTED]"}

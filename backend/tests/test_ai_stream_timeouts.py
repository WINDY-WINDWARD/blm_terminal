import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from app.services import llm_provider
from app.workers import ai_picks_worker


class FakeByteStream(httpx.AsyncByteStream):
    def __init__(self, lines: list[str], delays: list[float] | None = None):
        self.lines = lines
        self.delays = delays or [0.0] * len(lines)

    async def __aiter__(self):
        for line, delay in zip(self.lines, self.delays):
            if delay > 0:
                await asyncio.sleep(delay)
            yield (line + "\n").encode("utf-8")


def _make_sse_response(lines: list[str], delays: list[float] | None = None, status_code: int = 200) -> httpx.Response:
    req = httpx.Request("POST", "http://fake-llm/v1/chat/completions")
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": "text/event-stream"},
        stream=FakeByteStream(lines, delays),
        request=req,
    )


@pytest.fixture(autouse=True)
def mock_proxy_supervisor(monkeypatch):
    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "cpa-test-key"))
    mock_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: mock_supervisor)
    return mock_supervisor


@pytest.mark.asyncio
async def test_httpx_timeout_configuration():
    """Verify default HTTPX timeouts: connect 15s, write 60s, pool 15s, read 330s."""
    timeout = getattr(llm_provider, "_SHARED_STREAM_TIMEOUT", None) or getattr(llm_provider, "_DEFAULT_STREAM_TIMEOUT", None)
    assert timeout is not None, "Explicit stream timeout constant must be defined"
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 15.0
    assert timeout.write == 60.0
    assert timeout.pool == 15.0
    assert timeout.read == 330.0


@pytest.mark.asyncio
async def test_stream_deadlines_constants():
    """Verify deadlines: 240s first delta, 300s idle delta, 600s total cap."""
    assert getattr(llm_provider, "_FIRST_DELTA_DEADLINE", None) == 240.0
    assert getattr(llm_provider, "_IDLE_DELTA_DEADLINE", None) == 300.0
    assert getattr(llm_provider, "_TOTAL_STREAM_CAP", None) == 600.0


@pytest.mark.asyncio
async def test_first_delta_timeout_ignores_keepalive_comments(monkeypatch):
    """Keepalive comments (: ping) should NOT count as meaningful deltas and first-delta timeout must trigger."""
    lines = [
        ": keepalive 1",
        "",
        ": keepalive 2",
        ": ping",
        "",
        ": keepalive 3",
    ]
    delays = [0.01, 0.01, 0.02, 0.02, 0.02, 0.05]

    class _Ctx:
        async def __aenter__(self):
            return _make_sse_response(lines, delays)
        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _Ctx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    events = []
    async for chunk in llm_provider._run_openai_loop(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        api_key="sk-test",
        tools=[],
        tool_executor=AsyncMock(),
        base_url="http://127.0.0.1:8123/v1",
        first_delta_deadline=0.03,
        idle_delta_deadline=1.0,
    ):
        events.append(json.loads(chunk))

    assert any(e.get("type") == "error" for e in events), f"Expected error event in {events}"
    error_evt = next(e for e in events if e.get("type") == "error")
    assert error_evt.get("error_class") in ("FirstDeltaTimeout", "ReadTimeout", "TimeoutError")
    assert events[-1] == {"type": "done"}

@pytest.mark.asyncio
async def test_delayed_meaningful_output_before_deadline_succeeds(monkeypatch):
    """A stream delivering first meaningful content after a nonzero delay but before
    the configured first-delta deadline completes successfully without a timeout error.
    """
    valid_chunk1 = json.dumps({"choices": [{"delta": {"content": "Delayed "}}]})
    valid_chunk2 = json.dumps({"choices": [{"delta": {"content": "output"}}]})
    lines = [
        ": keepalive 1",
        "",
        ": keepalive 2",
        f"data: {valid_chunk1}",
        "",
        f"data: {valid_chunk2}",
        "data: [DONE]",
    ]
    # Nonzero delay before first meaningful delta arrives: 0.02 + 0.02 + 0.02 = 0.06s
    delays = [0.02, 0.0, 0.02, 0.02, 0.0, 0.01, 0.0]

    class _Ctx:
        async def __aenter__(self):
            return _make_sse_response(lines, delays)

        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _Ctx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    events = []
    async for chunk in llm_provider._run_openai_loop(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        api_key="sk-test",
        tools=[],
        tool_executor=AsyncMock(),
        base_url="http://127.0.0.1:8123/v1",
        first_delta_deadline=0.25,
        idle_delta_deadline=1.0,
    ):
        events.append(json.loads(chunk))

    # Assert no timeout or other error occurred
    assert not any(e.get("type") == "error" for e in events), f"Expected no error, got: {events}"

    # Assert meaningful content was emitted
    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == 2
    assert token_events[0]["text"] == "Delayed "
    assert token_events[1]["text"] == "output"
    assert "".join(e["text"] for e in token_events) == "Delayed output"

    # Assert stream completed successfully with done
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_idle_delta_timeout_after_meaningful_output(monkeypatch):
    """After first meaningful delta arrives, idle timeout between deltas triggers if stream stalls."""
    valid_chunk = json.dumps({"choices": [{"delta": {"content": "Hello"}}]})
    lines = [
        f"data: {valid_chunk}",
        "",
        ": keepalive after content",
        "",
        ": keepalive still stalled",
    ]
    delays = [0.01, 0.0, 0.05, 0.0, 0.05]

    class _Ctx:
        async def __aenter__(self):
            return _make_sse_response(lines, delays)
        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _Ctx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    events = []
    async for chunk in llm_provider._run_openai_loop(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-4o",
        api_key="sk-test",
        tools=[],
        tool_executor=AsyncMock(),
        base_url="http://127.0.0.1:8123/v1",
        first_delta_deadline=1.0,
        idle_delta_deadline=0.03,
    ):
        events.append(json.loads(chunk))

    token_events = [e for e in events if e.get("type") == "token"]
    assert len(token_events) == 1
    assert token_events[0]["text"] == "Hello"

    error_evt = next((e for e in events if e.get("type") == "error"), None)
    assert error_evt is not None
    assert error_evt.get("error_class") in ("IdleDeltaTimeout", "ReadTimeout", "TimeoutError")
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_transport_read_timeout_error_plus_done(monkeypatch):
    """When HTTPX raises ReadTimeout, loop must emit categorized error and done, and log safely."""
    class _FailingCtx:
        async def __aenter__(self):
            raise httpx.ReadTimeout("The read operation timed out")
        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _FailingCtx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    events = []
    async for chunk in llm_provider._run_openai_loop(
        messages=[{"role": "user", "content": "secret-prompt"}],
        model="gpt-4o",
        api_key="super-secret-key",
        tools=[],
        tool_executor=AsyncMock(),
        base_url="http://127.0.0.1:8123/v1",
    ):
        events.append(json.loads(chunk))

    assert len(events) == 2
    assert events[0]["type"] == "error"
    assert events[0]["error_class"] == "ReadTimeout"
    assert events[1] == {"type": "done"}


@pytest.mark.asyncio
async def test_structured_logs_never_leak_prompts_or_credentials(monkeypatch, caplog):
    """Structured logs must record route/model, stage, elapsed, error class, but never prompts or keys."""
    class _FailingCtx:
        async def __aenter__(self):
            raise httpx.ReadTimeout("Connection read timeout")
        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _FailingCtx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    secret_key = "sk-super-confidential-credential"
    secret_prompt = "CONFIDENTIAL_USER_PORTFOLIO_QUERY"

    with caplog.at_level(logging.DEBUG):
        events = []
        async for chunk in llm_provider._run_openai_loop(
            messages=[{"role": "user", "content": secret_prompt}],
            model="gemini-3.8-flash-high",
            api_key=secret_key,
            tools=[],
            tool_executor=AsyncMock(),
            base_url="http://127.0.0.1:8123/v1",
            api_label="Antigravity API",
        ):
            events.append(json.loads(chunk))

    logged_text = caplog.text
    assert secret_key not in logged_text, "Credentials leaked in log!"
    assert secret_prompt not in logged_text, "User prompt leaked in log!"
    assert "Stream timeout error:" in logged_text
    assert "route=Antigravity API" in logged_text
    assert "model=gemini-3.8-flash-high" in logged_text
    assert "error_class=ReadTimeout" in logged_text


@pytest.mark.asyncio
async def test_ai_picks_worker_does_not_repeat_read_timeout(monkeypatch):
    """Within one AI Picks run, ReadTimeout must not be retried."""
    attempts = 0

    async def mock_agent_loop(messages, model, system_prompt, label="Agent"):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("Antigravity API error [ReadTimeout]: stream timed out")

    monkeypatch.setattr(ai_picks_worker, "_run_agent_loop", mock_agent_loop)

    with pytest.raises(RuntimeError) as exc_info:
        await ai_picks_worker._run_agent_loop_retry(
            messages=[{"role": "user", "content": "analyze"}],
            model="gemini-3.8-flash-high",
            system_prompt=None,
            label="HUNTER",
            attempts=3,
        )

    assert "ReadTimeout" in str(exc_info.value)
    assert attempts == 1, f"ReadTimeout should abort retries, but executed {attempts} attempts"


@pytest.mark.asyncio
async def test_summarizer_surfaces_stream_failure(monkeypatch):
    """Summarizer must raise when stream emits error or fails."""
    from app.services.ai_summarizer import AISummarizer

    async def _failing_stream(*args, **kwargs):
        yield json.dumps({"type": "error", "error_class": "ReadTimeout", "message": "Timed out"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "stream_chat_completion", _failing_stream)
    monkeypatch.setattr("app.services.ai_summarizer.stream_chat_completion", _failing_stream)

    svc = AISummarizer()
    with pytest.raises(RuntimeError) as exc_info:
        await svc.summarize("Summarize market data for NIFTY")

    assert "Timed out" in str(exc_info.value) or "LLM API call failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_chat_service_surfaces_stream_failure(monkeypatch):
    """Chat service stream must yield error and done when upstream stream fails."""
    from app.services.ai_chat_service import run_chat_agent

    async def _failing_stream(*args, **kwargs):
        yield json.dumps({"type": "error", "error_class": "ReadTimeout", "message": "Stream timed out"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr("app.services.ai_chat_service.stream_chat_completion", _failing_stream)

    chunks = []
    async for chunk in run_chat_agent(
        messages=[{"role": "user", "content": "hello"}],
        symbol="TCS",
        exchange="NSE",
        model="gemini-3.8-flash-high",
    ):
        chunks.append(json.loads(chunk))

    assert any(c.get("type") == "error" for c in chunks)
    err = next(c for c in chunks if c.get("type") == "error")
    assert "Stream timed out" in err.get("message")
    assert chunks[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_evaluator_surfaces_stream_failure(monkeypatch):
    """Evaluator call must return error and not mark success when stream fails."""
    async def mock_agent_loop_retry(messages, model, system_prompt, label="", **kwargs):
        raise RuntimeError("Antigravity API error [ReadTimeout]: read timed out")

    monkeypatch.setattr(ai_picks_worker, "_run_agent_loop_retry", mock_agent_loop_retry)

    pick_data = {"symbol": "INFY", "entry_price": 1500.0}
    eval_data, error = await ai_picks_worker._call_evaluator(pick_data, "context")

    assert error is not None
    assert "ReadTimeout" in error or "read timed out" in error
    assert eval_data.get("action") == "HOLD"


@pytest.mark.asyncio
async def test_stream_chat_completion_oauth_route_forwards_stream_deadlines(monkeypatch):
    """Verify stream_chat_completion with oauth:* route enforces 240s first-delta and 300s idle deadlines."""
    route_id = "oauth:google-antigravity"
    model_id = "gemini-3.8-flash-high"
    qualified_model = f"blm:{route_id}/{model_id}"

    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "cpa-test-key"))
    mock_supervisor.request_sync = MagicMock()

    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[model_id]))

    trackers: list[llm_provider.StreamDeadlineTracker] = []
    orig_tracker_init = llm_provider.StreamDeadlineTracker.__init__

    def _spy_tracker_init(self, *args, **kwargs):
        orig_tracker_init(self, *args, **kwargs)
        trackers.append(self)

    monkeypatch.setattr(llm_provider.StreamDeadlineTracker, "__init__", _spy_tracker_init)

    # 1. Normal response: verifies deadlines forwarded into StreamDeadlineTracker
    valid_chunk = json.dumps({"choices": [{"delta": {"content": "OAuth response"}}]})
    sse_lines = [f"data: {valid_chunk}", "data: [DONE]"]

    class _SuccessCtx:
        async def __aenter__(self):
            return _make_sse_response(sse_lines)

        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _SuccessCtx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "test prompt"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert len(trackers) == 1
    assert trackers[0].first_delta_deadline == 240.0
    assert trackers[0].idle_delta_deadline == 300.0
    assert trackers[0].total_stream_cap == 600.0
    assert any(e.get("type") == "token" and e.get("text") == "OAuth response" for e in events)
    assert events[-1] == {"type": "done"}

    # 2. Timeout response: verifies categorized error and done emission
    class _FailingCtx:
        async def __aenter__(self):
            raise httpx.ReadTimeout("Antigravity socket read timeout")

        async def __aexit__(self, *a):
            pass

    mock_client.stream.return_value = _FailingCtx()
    fail_events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "failing prompt"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        fail_events.append(json.loads(chunk))

    assert any(e.get("type") == "error" and e.get("error_class") == "ReadTimeout" for e in fail_events)
    assert fail_events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_stream_chat_completion_direct_route_forwards_stream_deadlines(monkeypatch):
    """Verify stream_chat_completion with direct:* route enforces 240s first-delta and 300s idle deadlines."""
    route_id = "direct:openai"
    model_id = "gpt-4o-mini"
    qualified_model = f"blm:{route_id}/{model_id}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[model_id]))
    monkeypatch.setattr(llm_provider, "get_dynamic_ai_api_key", AsyncMock(return_value="sk-test-direct-key"))

    trackers: list[llm_provider.StreamDeadlineTracker] = []
    orig_tracker_init = llm_provider.StreamDeadlineTracker.__init__

    def _spy_tracker_init(self, *args, **kwargs):
        orig_tracker_init(self, *args, **kwargs)
        trackers.append(self)

    monkeypatch.setattr(llm_provider.StreamDeadlineTracker, "__init__", _spy_tracker_init)

    # 1. Normal response: verifies deadlines forwarded into StreamDeadlineTracker
    valid_chunk = json.dumps({"choices": [{"delta": {"content": "Direct response"}}]})
    sse_lines = [f"data: {valid_chunk}", "data: [DONE]"]

    class _SuccessCtx:
        async def __aenter__(self):
            return _make_sse_response(sse_lines)

        async def __aexit__(self, *a):
            pass

    mock_client = MagicMock()
    mock_client.stream.return_value = _SuccessCtx()
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "test prompt"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert len(trackers) == 1
    assert trackers[0].first_delta_deadline == 240.0
    assert trackers[0].idle_delta_deadline == 300.0
    assert trackers[0].total_stream_cap == 600.0
    assert any(e.get("type") == "token" and e.get("text") == "Direct response" for e in events)
    assert events[-1] == {"type": "done"}

    # 2. Timeout response: verifies categorized error and done emission
    class _FailingCtx:
        async def __aenter__(self):
            raise httpx.ReadTimeout("Direct provider read timeout")

        async def __aexit__(self, *a):
            pass

    mock_client.stream.return_value = _FailingCtx()
    fail_events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "failing prompt"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        fail_events.append(json.loads(chunk))

    assert any(e.get("type") == "error" and e.get("error_class") == "ReadTimeout" for e in fail_events)
    assert fail_events[-1] == {"type": "done"}


@pytest.mark.parametrize(
    ("route_id", "model_id"),
    [
        ("direct:openai", "gpt-4o-mini"),
        ("direct:nvidia", "nvidia/test-model"),
    ],
)
@pytest.mark.asyncio
async def test_direct_routes_forward_deadline_values_and_keep_nvidia_shared_timeout(
    monkeypatch, route_id, model_id
):
    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[model_id]))
    monkeypatch.setattr(llm_provider, "get_dynamic_ai_api_key", AsyncMock(return_value="sk-test-key"))

    captured_kwargs = {}

    async def _loop_stub(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _loop_stub)

    async for _ in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "test prompt"}],
        model=f"blm:{route_id}/{model_id}",
        tools=[],
        tool_executor=AsyncMock(),
    ):
        pass

    assert captured_kwargs["first_delta_deadline"] == 240.0
    assert captured_kwargs["idle_delta_deadline"] == 300.0
    assert captured_kwargs["total_stream_cap"] == 600.0


def test_stream_deadline_tracker_classifies_earlier_total_cap(monkeypatch):
    current_time = 1000.0
    monkeypatch.setattr(llm_provider.time, "monotonic", lambda: current_time)
    tracker = llm_provider.StreamDeadlineTracker(
        api_label="Test API",
        model="test-model",
        first_delta_deadline=520.0,
        idle_delta_deadline=300.0,
        total_stream_cap=600.0,
    )

    current_time = 1500.0
    tracker.record_meaningful_delta()
    current_time = 1550.0
    timeout_seconds, timeout_class = tracker.next_timeout()

    assert timeout_seconds == pytest.approx(50.0)
    assert timeout_class == "TotalStreamTimeout"

    current_time = 2000.0
    first_delta_tracker = llm_provider.StreamDeadlineTracker(
        api_label="Test API",
        model="test-model",
        first_delta_deadline=240.0,
        idle_delta_deadline=300.0,
        total_stream_cap=100.0,
    )
    current_time = 2020.0
    timeout_seconds, timeout_class = first_delta_tracker.next_timeout()

    assert timeout_seconds == pytest.approx(80.0)
    assert timeout_class == "TotalStreamTimeout"


@pytest.mark.asyncio
async def test_ai_picks_empty_stream_error_uses_agent_label(monkeypatch):
    async def empty_stream(**kwargs):
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(ai_picks_worker, "stream_chat_completion", empty_stream)

    with pytest.raises(RuntimeError, match="Hunter stream produced empty content"):
        await ai_picks_worker._run_agent_loop_retry(
            messages=[],
            model="test-model",
            system_prompt=None,
            label="Hunter",
            attempts=1,
        )


@pytest.mark.asyncio
async def test_ai_picks_provider_error_is_not_labeled_antigravity(monkeypatch):
    async def error_stream(**kwargs):
        yield json.dumps({
            "type": "error",
            "error_class": "UpstreamError",
            "message": "Direct OpenAI rejected the request",
        })

    monkeypatch.setattr(ai_picks_worker, "stream_chat_completion", error_stream)

    with pytest.raises(RuntimeError, match=r"AI provider error \[UpstreamError\]: Direct OpenAI"):
        await ai_picks_worker._run_agent_loop_retry(
            messages=[],
            model="test-model",
            system_prompt=None,
            label="Verifier",
            attempts=1,
        )


@pytest.mark.asyncio
async def test_stream_chat_completion_nvidia_no_scalar_httpx_timeout_override(monkeypatch):
    """Verify that NVIDIA route does not set a scalar request_timeout=300.0 override,
    allowing the shared HTTPX client timeout configuration to govern the connection.
    """
    route_id = "direct:nvidia"
    model_id = "meta/llama-3.1-70b-instruct"
    qualified_model = f"blm:{route_id}/{model_id}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[model_id]))
    monkeypatch.setattr(llm_provider, "get_dynamic_ai_api_key", AsyncMock(return_value="nv-test-key"))

    captured_calls = []

    async def _dummy_openai_loop(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        yield json.dumps({"type": "token", "text": "ok"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _dummy_openai_loop)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert len(captured_calls) == 1
    call_kwargs = captured_calls[0]["kwargs"]
    assert call_kwargs.get("request_timeout") is None, (
        f"NVIDIA route must not pass scalar request_timeout override, got {call_kwargs.get('request_timeout')}"
    )
    assert call_kwargs.get("first_delta_deadline") == llm_provider._FIRST_DELTA_DEADLINE
    assert call_kwargs.get("idle_delta_deadline") == llm_provider._IDLE_DELTA_DEADLINE
    assert call_kwargs.get("total_stream_cap") == llm_provider._TOTAL_STREAM_CAP


@pytest.mark.asyncio
async def test_proxy_stream_timeout_closes_abandoned_stream_and_done_on_empty(monkeypatch):
    """Verify that when first event times out, the abandoned stream is closed before restarting,
    and if the second stream produces no events (first is None), a done event is yielded."""
    route_id = "oauth:google-antigravity"
    model_id = "gemini-3.8-flash-high"
    qualified_model = f"blm:{route_id}/{model_id}"

    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "key-1"))
    mock_supervisor.recover = AsyncMock(return_value=("127.0.0.1", 8318, "key-2"))
    mock_supervisor.request_sync = MagicMock()

    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[model_id]))
    monkeypatch.setattr(llm_provider, "_PROXY_FIRST_EVENT_TIMEOUT", 0.05)

    stream1_closed = False
    stream2_closed = False

    class MockStream1:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(1.0)
            return json.dumps({"type": "token", "text": "never"})

        async def aclose(self):
            nonlocal stream1_closed
            stream1_closed = True

    class MockStream2:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            nonlocal stream2_closed
            stream2_closed = True

    streams = [MockStream1(), MockStream2()]

    def mock_open_stream(*args, **kwargs):
        return streams.pop(0)

    monkeypatch.setattr(llm_provider, "_run_openai_loop", mock_open_stream)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hello"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert stream1_closed is True
    mock_supervisor.recover.assert_awaited_once_with(
        "first_event_timeout", preserve_oauth_flow=True
    )
    assert events == [{"type": "done"}]



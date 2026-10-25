import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services import direct_proxy_routes
from app.services import llm_provider


@pytest.mark.asyncio
@pytest.mark.parametrize("route_id", direct_proxy_routes.SUPPORTED_ROUTE_IDS)
async def test_all_supported_direct_routes_proxy_to_loopback(monkeypatch, route_id):
    spec = direct_proxy_routes.get_direct_route(route_id)
    default_models = spec.models or ("test-upstream-model",)
    upstream = default_models[0]
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "client-key"))
    fake_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    captured_kwargs = {}

    async def _mock_openai_loop(*args, **kwargs):
        captured_kwargs["args"] = args
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "token", "text": "hello"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _mock_openai_loop)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert captured_kwargs["base_url"] == "http://127.0.0.1:8123/v1"
    expected_prefix = direct_proxy_routes.direct_proxy_prefix(route_id)
    assert captured_kwargs["args"][1] == f"{expected_prefix}/{upstream}"
    fake_supervisor.ensure_started.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("route_id", ["direct:copilot", "direct:claude-code"])
async def test_unsupported_direct_routes_fail_without_starting_supervisor(monkeypatch, route_id):
    spec = direct_proxy_routes.get_direct_route(route_id)
    upstream = "test-model"
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert len(events) == 2
    assert events[0]["type"] == "error"
    assert events[0]["message"] == spec.unavailable_reason
    assert events[1]["type"] == "done"
    fake_supervisor.ensure_started.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_completion_no_fallback_on_runtime_error(monkeypatch):
    route_id = "direct:groq"
    upstream = "llama-3.3-70b-versatile"
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "client-key"))
    fake_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    call_count = 0

    async def _failing_openai_loop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("CLIProxyAPI crashed")
        yield  # make it an async generator

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _failing_openai_loop)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert call_count == 1
    assert len(events) == 2
    assert events[0]["type"] == "error"
    assert events[0]["message"] == "Inference stream failed (connection error). Try again."
    assert events[1]["type"] == "done"


@pytest.mark.asyncio
async def test_oauth_and_endpoint_routes_use_db_proxy_prefix_when_present(monkeypatch):
    route_id = "oauth:google-antigravity"
    upstream = "gemini-3.8-flash-high"
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "client-key"))
    fake_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    # Mock DB query to return custom proxy_prefix "custom-cpa-prefix"
    class FakeResult:
        def scalar_one_or_none(self):
            return "custom-cpa-prefix"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def execute(self, stmt):
            return FakeResult()

    monkeypatch.setattr("app.database.AsyncSessionLocal", lambda: FakeSession())

    captured_model = None

    async def _mock_openai_loop(*args, **kwargs):
        nonlocal captured_model
        captured_model = args[1]
        yield json.dumps({"type": "token", "text": "ok"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _mock_openai_loop)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert captured_model == f"custom-cpa-prefix/{upstream}"


def test_loopback_proxy_base_url_rejects_non_loopback():
    assert llm_provider._loopback_proxy_base_url("127.0.0.1", 8123) == "http://127.0.0.1:8123/v1"
    assert llm_provider._loopback_proxy_base_url("localhost", 8123) == "http://localhost:8123/v1"
    assert llm_provider._loopback_proxy_base_url("::1", 8123) == "http://[::1]:8123/v1" if False else "http://::1:8123/v1"

    with pytest.raises(RuntimeError, match="CLIProxyAPI must listen on loopback"):
        llm_provider._loopback_proxy_base_url("192.168.1.100", 8123)

    with pytest.raises(RuntimeError, match="CLIProxyAPI must listen on loopback"):
        llm_provider._loopback_proxy_base_url("api.groq.com", 443)


@pytest.mark.asyncio
async def test_run_openai_loop_none_base_url_raises_before_network():
    with pytest.raises(RuntimeError, match="No base_url provided to _run_openai_loop"):
        async for _ in llm_provider._run_openai_loop(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            api_key="key",
            tools=[],
            tool_executor=AsyncMock(),
            base_url=None,
        ):
            pass


@pytest.mark.asyncio
async def test_run_openai_loop_non_loopback_base_url_raises_and_no_request(monkeypatch):
    mock_client = MagicMock()
    mock_client.stream = MagicMock(side_effect=AssertionError("Network call attempted for non-loopback base_url!"))
    monkeypatch.setattr(llm_provider, "_get_shared_client", lambda: mock_client)

    with pytest.raises(RuntimeError, match="base_url host must be loopback"):
        async for _ in llm_provider._run_openai_loop(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
            api_key="key",
            tools=[],
            tool_executor=AsyncMock(),
            base_url="https://api.openai.com/v1",
        ):
            pass

    mock_client.stream.assert_not_called()


@pytest.mark.asyncio
async def test_stream_chat_completion_sanitizes_stream_exception(monkeypatch):
    route_id = "direct:groq"
    upstream = "llama-3.3-70b-versatile"
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "client-key"))
    fake_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    sentinel = "SECRET-LEAK-123"
    leak_url = "https://sensitive-upstream.provider.internal/v1/auth?token=abc"

    async def _failing_openai_loop(*args, **kwargs):
        raise RuntimeError(f"Connection failure: {sentinel} at {leak_url}")
        yield  # make async generator

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _failing_openai_loop)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert len(events) == 2
    assert events[0]["type"] == "error"
    error_msg = events[0]["message"]
    assert sentinel not in error_msg
    assert "http://" not in error_msg and "https://" not in error_msg
    assert error_msg == "Inference stream failed (connection error). Try again."
    assert events[1] == {"type": "done"}


@pytest.mark.asyncio
async def test_wedged_sidecar_restarts_and_retries(monkeypatch):
    """A sidecar that accepts the request but never emits is replaced, not waited on."""
    import asyncio

    route_id = "direct:openai"
    upstream = "gpt-4o-mini"
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))
    monkeypatch.setattr(llm_provider, "_PROXY_FIRST_EVENT_TIMEOUT", 0.05)

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "k1"))
    fake_supervisor.recover = AsyncMock(return_value=("127.0.0.1", 9123, "k2"))
    fake_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    calls = {"n": 0}
    base_urls: list[str] = []

    async def _mock_openai_loop(*args, **kwargs):
        calls["n"] += 1
        base_urls.append(kwargs["base_url"])
        if calls["n"] == 1:
            await asyncio.sleep(3600)
        yield json.dumps({"type": "token", "text": "ok"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _mock_openai_loop)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert [e["type"] for e in events] == ["token", "done"]
    assert calls["n"] == 2
    fake_supervisor.recover.assert_awaited_once_with(
        "first_event_timeout", preserve_oauth_flow=True
    )
    assert base_urls == ["http://127.0.0.1:8123/v1", "http://127.0.0.1:9123/v1"]


@pytest.mark.asyncio
async def test_wedged_sidecar_restart_failure_emits_terminal_events(monkeypatch):
    """If recovery fails the user still gets a sanitized error and done event."""
    import asyncio

    route_id = "direct:openai"
    upstream = "gpt-4o-mini"
    qualified_model = f"blm:{route_id}/{upstream}"

    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value=route_id))
    monkeypatch.setattr(llm_provider, "_is_route_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=[upstream]))
    monkeypatch.setattr(llm_provider, "_PROXY_FIRST_EVENT_TIMEOUT", 0.05)

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "k1"))
    fake_supervisor.restart = AsyncMock(side_effect=RuntimeError("secret /v1/token"))
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    async def _hang(*args, **kwargs):
        await asyncio.sleep(3600)
        yield json.dumps({"type": "token", "text": "never"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _hang)

    events = []
    async for chunk in llm_provider.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model=qualified_model,
        tools=[],
        tool_executor=AsyncMock(),
    ):
        events.append(json.loads(chunk))

    assert [e["type"] for e in events] == ["error", "done"]
    assert "secret" not in events[0]["message"]

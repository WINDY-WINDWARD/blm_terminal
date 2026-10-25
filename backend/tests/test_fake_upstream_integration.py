"""Integration harness for custom endpoint multi-key failover and proxy tool-call continuation.

Test Architecture & Verification:
---------------------------------
1. Real Custom-Endpoint Multi-Key Failover (401 & 429):
   - Starts an in-process fake OpenAI-compatible HTTP upstream server on a free loopback port.
   - Exercises real configuration serialization via `materialize_custom_endpoints` and
     `generate_proxy_config`.
   - Spawns the vendored CLIProxyAPI binary (v8.0.39) on an ephemeral loopback port.
   - If the binary is absent (e.g. non-packaged CI), tests cleanly skip via `pytest.skip`.
   - Dispatches requests via BLM Terminal's real `stream_chat_completion` client loop.
   - Key 1 returns HTTP 401 Unauthorized (or HTTP 429 Too Many Requests).
   - CLIProxyAPI catches the error, marks Key 1 in cooldown, and fails over to Key 2.
   - Key 2 returns HTTP 200 with an SSE chat-completion stream.
   - Proves upstream saw Key 1 rejected and Key 2 serve the request, BLM streamed the response
     seamlessly, and proxy traces recorded the upstream interaction.

2. Tool-Call Continuation Through the Proxy:
   - Exercises BLM's genuine multi-turn `stream_chat_completion` tool-calling continuation loop.
   - Request 1 sends prompt and tool definitions -> proxy returns tool_calls payload.
   - BLM executes `tool_executor` and constructs the continuation request containing accumulated
     history: user message, assistant tool call message, and tool result message with matching `tool_call_id`.
   - Request 2 sends the continuation request -> returns final completion tokens.
   - Proves BLM's execution loop coordinates multi-turn tool calling and preserves session affinity.
"""

import asyncio
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.llm_provider import (
    clear_proxy_traces,
    get_proxy_traces,
    record_proxy_trace,
    stream_chat_completion,
)
from app.services.provider_vault import ProviderVault
from app.services.proxy_supervisor import (
    find_free_loopback_port,
    generate_proxy_config,
    materialize_custom_endpoints,
    resolve_cliproxy_bin,
)


class MockStreamingResponse:
    """Mocked httpx streaming response yielding line-by-line SSE chunks for tool testing."""

    def __init__(self, status_code: int, lines: list[str], headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._lines = lines
        self.headers = httpx.Headers(headers or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def aread(self) -> bytes:
        return "\n".join(self._lines).encode("utf-8")

    async def aiter_lines(self) -> AsyncGenerator[str, None]:
        for line in self._lines:
            yield line


def _check_cliproxy_binary_available() -> Path:
    """Check if CLIProxyAPI binary is present, skipping the test cleanly if absent."""
    try:
        bin_path = resolve_cliproxy_bin()
        if not bin_path.exists():
            pytest.skip(f"CLIProxyAPI binary not found at {bin_path}; skipping real-proxy test")
        return bin_path
    except FileNotFoundError:
        pytest.skip("CLIProxyAPI binary not found; skipping real-proxy test")


@pytest.mark.asyncio
async def test_custom_endpoint_multikey_failover_401_to_success():
    """Verify real CLIProxyAPI failover from 401 Unauthorized to backup key via fake upstream.

    End-to-End Workflow:
    - Starts fake HTTP upstream recording incoming Authorization headers.
    - Materializes custom endpoint with Key 1 and Key 2 via `materialize_custom_endpoints`.
    - Generates proxy configuration via `generate_proxy_config` and launches real `cliproxyapi`.
    - Dispatches prompt through BLM's `stream_chat_completion`.
    - Upstream returns 401 for the first key attempted.
    - CLIProxyAPI catches the 401, places that key into cooldown, and dispatches Key 2.
    - Upstream returns 200 with an SSE stream for Key 2.
    - Asserts upstream received both keys, BLM streamed tokens, and subsequent requests bypass
      the cooldown-restricted primary key.
    """
    bin_path = _check_cliproxy_binary_available()
    clear_proxy_traces()

    requests_seen: list[str] = []
    first_key_seen: list[str] = []

    class FakeUpstream401Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            auth = self.headers.get("Authorization", "")
            requests_seen.append(auth)
            content_len = int(self.headers.get("Content-Length", 0))
            self.rfile.read(content_len)

            if not first_key_seen:
                # First attempt -> reject with HTTP 401
                first_key_seen.append(auth)
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Primary key invalid", "code": 401}}')
            elif auth in first_key_seen:
                # Still using rejected key
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Primary key still rejected", "code": 401}}')
            else:
                # Backup key -> succeed with HTTP 200 SSE stream
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(
                    b'data: {"choices": [{"delta": {"content": "Failover from 401 succeeded!"}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n'
                )

        def log_message(self, format, *args):
            pass

    upstream_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream401Handler)
    upstream_port = upstream_server.server_port
    upstream_thread = threading.Thread(target=upstream_server.serve_forever, daemon=True)
    upstream_thread.start()

    # In-memory DB and vault for materialize_custom_endpoints
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    vault = ProviderVault()
    vault._state = "available"
    vault._secrets = {
        "custom_endpoint/ep-401/key1": "sk-ep-primary-401-key",
        "custom_endpoint/ep-401/key2": "sk-ep-backup-401-key",
    }
    vault._endpoint_headers = {}
    vault.get_secret = AsyncMock(side_effect=lambda ref: vault._secrets.get(ref))
    vault.get_endpoint_headers = AsyncMock(return_value={})

    async with Session() as s:
        route = AIProviderRoute(
            id="endpoint:ep-401",
            kind="endpoint",
            provider="custom",
            display_label="Failover 401 Endpoint",
            enabled=True,
            proxy_prefix="endpoint-ep-401",
            config_json=json.dumps({
                "base_url": f"http://127.0.0.1:{upstream_port}/v1",
                "models": ["mock-model-401"],
            }),
        )
        s.add(route)
        cred1 = AIProviderCredential(
            id="cred-401-1",
            route_id="endpoint:ep-401",
            kind="custom_endpoint_key",
            proxy_credential_name="key1",
            masked_identity="sk-...1",
            enabled=True,
            priority=1,
            weight=1,
            vault_reference="custom_endpoint/ep-401/key1",
        )
        cred2 = AIProviderCredential(
            id="cred-401-2",
            route_id="endpoint:ep-401",
            kind="custom_endpoint_key",
            proxy_credential_name="key2",
            masked_identity="sk-...2",
            enabled=True,
            priority=2,
            weight=1,
            vault_reference="custom_endpoint/ep-401/key2",
        )
        s.add_all([cred1, cred2])
        await s.commit()

        # Real helper call
        endpoints = await materialize_custom_endpoints(vault, s)

    proxy_port = find_free_loopback_port()
    client_key = "test-client-key-401"
    mgmt_key = "test-mgmt-key-401"

    tmpdir = tempfile.mkdtemp(prefix="cliproxy-401-test-")
    auth_dir = os.path.join(tmpdir, "auth")
    os.makedirs(auth_dir, exist_ok=True)

    cfg_str = generate_proxy_config(
        host="127.0.0.1",
        port=proxy_port,
        client_key=client_key,
        management_key=mgmt_key,
        auth_dir=auth_dir,
        custom_endpoints=endpoints,
    )
    cfg_file = os.path.join(tmpdir, "config.yaml")
    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write(cfg_str)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    proc = subprocess.Popen(
        [str(bin_path), "--config", cfg_file],
        cwd=tmpdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )

    try:
        # Poll readiness
        ready = False
        for _ in range(50):
            await asyncio.sleep(0.1)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"http://127.0.0.1:{proxy_port}/healthz")
                    if resp.status_code == 200:
                        ready = True
                        break
            except Exception:
                pass
        assert ready, "CLIProxyAPI failed to reach /healthz readiness"

        mock_supervisor = MagicMock()
        mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", proxy_port, client_key))

        async def noop_executor(calls):
            return [], []

        with (
            patch("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor),
            patch("app.services.llm_provider.resolve_active_route_id", AsyncMock(return_value="endpoint:ep-401")),
            patch("app.services.llm_provider.get_route_models", AsyncMock(return_value=["mock-model-401"])),
        ):
            chunks: list[str] = []
            async for chunk in stream_chat_completion(
                messages=[{"role": "user", "content": "Analyze asset volatility"}],
                model="blm:endpoint:ep-401/mock-model-401",
                tools=[],
                tool_executor=noop_executor,
                session_id="session-real-401",
            ):
                chunks.append(chunk)

            # 1. Assert upstream observed failover: first key rejected 401, second key accepted
            assert len(requests_seen) == 2, f"Expected 2 requests, got {len(requests_seen)}: {requests_seen}"
            assert requests_seen[0] != requests_seen[1], "Expected different API keys on retry"
            assert any("Failover from 401 succeeded!" in c for c in chunks)

            # 2. Verify trace ring recorded trace attribution
            traces = get_proxy_traces()
            assert any(t["upstream_model"] == "mock-model-401" for t in traces)

            # 3. Subsequent request uses backup key immediately because primary is in cooldown
            requests_seen.clear()
            chunks_subsequent: list[str] = []
            async for chunk in stream_chat_completion(
                messages=[{"role": "user", "content": "Followup query"}],
                model="blm:endpoint:ep-401/mock-model-401",
                tools=[],
                tool_executor=noop_executor,
                session_id="session-real-401-part2",
            ):
                chunks_subsequent.append(chunk)

            assert len(requests_seen) == 1, f"Expected 1 request (backup only), got {len(requests_seen)}"
            assert requests_seen[0] != first_key_seen[0], "Subsequent request should use backup key"
            assert any("Failover from 401 succeeded!" in c for c in chunks_subsequent)

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        upstream_server.shutdown()
        upstream_server.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_custom_endpoint_multikey_failover_429_to_success():
    """Verify real CLIProxyAPI failover from 429 Too Many Requests to backup key via fake upstream."""
    bin_path = _check_cliproxy_binary_available()
    clear_proxy_traces()

    requests_seen: list[str] = []
    first_key_seen: list[str] = []

    class FakeUpstream429Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            auth = self.headers.get("Authorization", "")
            requests_seen.append(auth)
            content_len = int(self.headers.get("Content-Length", 0))
            self.rfile.read(content_len)

            if not first_key_seen:
                # First attempt -> reject with HTTP 429 Too Many Requests
                first_key_seen.append(auth)
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Rate limit exceeded", "code": 429}}')
            elif auth in first_key_seen:
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": {"message": "Rate limit still active", "code": 429}}')
            else:
                # Backup key -> succeed with HTTP 200 SSE stream
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(
                    b'data: {"choices": [{"delta": {"content": "Recovered from 429 limit!"}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n'
                )

        def log_message(self, format, *args):
            pass

    upstream_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream429Handler)
    upstream_port = upstream_server.server_port
    upstream_thread = threading.Thread(target=upstream_server.serve_forever, daemon=True)
    upstream_thread.start()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    vault = ProviderVault()
    vault._state = "available"
    vault._secrets = {
        "custom_endpoint/ep-429/key1": "sk-ep-primary-429-key",
        "custom_endpoint/ep-429/key2": "sk-ep-backup-429-key",
    }
    vault._endpoint_headers = {}
    vault.get_secret = AsyncMock(side_effect=lambda ref: vault._secrets.get(ref))
    vault.get_endpoint_headers = AsyncMock(return_value={})

    async with Session() as s:
        route = AIProviderRoute(
            id="endpoint:ep-429",
            kind="endpoint",
            provider="custom",
            display_label="Failover 429 Endpoint",
            enabled=True,
            proxy_prefix="endpoint-ep-429",
            config_json=json.dumps({
                "base_url": f"http://127.0.0.1:{upstream_port}/v1",
                "models": ["mock-model-429"],
            }),
        )
        s.add(route)
        cred1 = AIProviderCredential(
            id="cred-429-1",
            route_id="endpoint:ep-429",
            kind="custom_endpoint_key",
            proxy_credential_name="key1",
            masked_identity="sk-...1",
            enabled=True,
            priority=1,
            weight=1,
            vault_reference="custom_endpoint/ep-429/key1",
        )
        cred2 = AIProviderCredential(
            id="cred-429-2",
            route_id="endpoint:ep-429",
            kind="custom_endpoint_key",
            proxy_credential_name="key2",
            masked_identity="sk-...2",
            enabled=True,
            priority=2,
            weight=1,
            vault_reference="custom_endpoint/ep-429/key2",
        )
        s.add_all([cred1, cred2])
        await s.commit()

        endpoints = await materialize_custom_endpoints(vault, s)

    proxy_port = find_free_loopback_port()
    client_key = "test-client-key-429"
    mgmt_key = "test-mgmt-key-429"

    tmpdir = tempfile.mkdtemp(prefix="cliproxy-429-test-")
    auth_dir = os.path.join(tmpdir, "auth")
    os.makedirs(auth_dir, exist_ok=True)

    cfg_str = generate_proxy_config(
        host="127.0.0.1",
        port=proxy_port,
        client_key=client_key,
        management_key=mgmt_key,
        auth_dir=auth_dir,
        custom_endpoints=endpoints,
    )
    cfg_file = os.path.join(tmpdir, "config.yaml")
    with open(cfg_file, "w", encoding="utf-8") as f:
        f.write(cfg_str)

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    proc = subprocess.Popen(
        [str(bin_path), "--config", cfg_file],
        cwd=tmpdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creation_flags,
    )

    try:
        ready = False
        for _ in range(50):
            await asyncio.sleep(0.1)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"http://127.0.0.1:{proxy_port}/healthz")
                    if resp.status_code == 200:
                        ready = True
                        break
            except Exception:
                pass
        assert ready, "CLIProxyAPI failed to reach /healthz readiness"

        mock_supervisor = MagicMock()
        mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", proxy_port, client_key))

        async def noop_executor(calls):
            return [], []

        with (
            patch("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor),
            patch("app.services.llm_provider.resolve_active_route_id", AsyncMock(return_value="endpoint:ep-429")),
            patch("app.services.llm_provider.get_route_models", AsyncMock(return_value=["mock-model-429"])),
        ):
            chunks: list[str] = []
            async for chunk in stream_chat_completion(
                messages=[{"role": "user", "content": "Analyze market momentum"}],
                model="blm:endpoint:ep-429/mock-model-429",
                tools=[],
                tool_executor=noop_executor,
                session_id="session-real-429",
            ):
                chunks.append(chunk)

            assert len(requests_seen) == 2, f"Expected 2 requests, got {len(requests_seen)}: {requests_seen}"
            assert requests_seen[0] != requests_seen[1], "Expected different API keys on 429 failover"
            assert any("Recovered from 429 limit!" in c for c in chunks)

            traces = get_proxy_traces()
            assert any(t["upstream_model"] == "mock-model-429" for t in traces)

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        upstream_server.shutdown()
        upstream_server.server_close()
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.asyncio
async def test_tool_call_continuation_through_proxy(monkeypatch):
    """Verify tool-call continuation loop through the proxy:

    Turn 1: User prompt -> Proxy returns tool_calls response for `get_stock_quote(symbol='TCS')`.
    BLM executes tool_executor and generates status event and tool message.
    Turn 2 (Continuation): BLM sends continuation request to proxy containing accumulated messages:
    - User message
    - Assistant message with tool_calls
    - Tool message with matching tool_call_id
    Proxy returns final completion text -> BLM streams completion tokens.
    """
    clear_proxy_traces()

    captured_requests: list[dict[str, Any]] = []

    class ToolContinuationClient:
        def __init__(self):
            self.iteration = 0

        def stream(self, method: str, url: str, **kwargs):
            import copy
            payload = copy.deepcopy(kwargs.get("json"))
            headers = kwargs.get("headers")
            captured_requests.append({
                "iteration": self.iteration,
                "method": method,
                "url": url,
                "json": payload,
                "headers": headers,
            })
            self.iteration += 1

            if self.iteration == 1:
                tc_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "id": "call_tcs_101",
                                "type": "function",
                                "function": {
                                    "name": "get_stock_quote",
                                    "arguments": json.dumps({"symbol": "TCS"}),
                                },
                            }]
                        },
                        "finish_reason": None,
                    }]
                }
                lines = [
                    f"data: {json.dumps(tc_chunk)}",
                    'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
                    'data: [DONE]',
                ]
                return MockStreamingResponse(200, lines, {"X-CPA-TRACE-ID": "trace-tool-call-1"})
            else:
                lines = [
                    'data: {"choices": [{"delta": {"content": "Tata Consultancy Services (TCS) is currently trading at ₹3,550.00."}, "finish_reason": null}]}',
                    'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
                    'data: [DONE]',
                ]
                return MockStreamingResponse(200, lines, {"X-CPA-TRACE-ID": "trace-tool-continuation-2"})

    tool_client = ToolContinuationClient()

    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: tool_client)
    monkeypatch.setattr(
        "app.services.llm_provider.resolve_active_route_id",
        AsyncMock(return_value="oauth:codex"),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.get_route_models",
        AsyncMock(return_value=["gpt-4o"]),
    )

    tool_calls_executed: list[dict[str, Any]] = []

    async def mock_tool_executor(tool_calls: list[dict[str, Any]]):
        statuses = []
        tool_messages = []
        for tc in tool_calls:
            tool_calls_executed.append(tc)
            name = tc.get("name")
            args = tc.get("args") or {}
            call_id = tc.get("id")

            statuses.append(json.dumps({"type": "tool_status", "name": name, "status": "executed", "result": {"price": 3550.0}}))
            tool_messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps({"symbol": args.get("symbol"), "price": 3550.0, "currency": "INR"}),
            })
        return statuses, tool_messages

    tools = [{
        "type": "function",
        "function": {
            "name": "get_stock_quote",
            "description": "Fetch real-time stock quote for Indian NSE/BSE equities",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    }]

    yielded_chunks: list[str] = []
    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "What is the stock price of TCS?"}],
        model="blm:oauth:codex/gpt-4o",
        tools=tools,
        tool_executor=mock_tool_executor,
        session_id="chat-session-tools-77",
    ):
        yielded_chunks.append(chunk)

    assert len(captured_requests) == 2, f"Expected 2 requests (initial + continuation), got {len(captured_requests)}"

    req1 = captured_requests[0]
    req2 = captured_requests[1]

    assert req1["url"] == "http://127.0.0.1:8317/v1/chat/completions"
    assert req1["headers"]["Authorization"] == "Bearer test-client-key"
    assert req1["headers"]["X-Session-Id"] == "chat-session-tools-77"
    assert len(req1["json"]["messages"]) == 1
    assert req1["json"]["messages"][0]["content"] == "What is the stock price of TCS?"
    assert "tools" in req1["json"]

    assert req2["url"] == "http://127.0.0.1:8317/v1/chat/completions"
    assert req2["headers"]["Authorization"] == "Bearer test-client-key"
    assert req2["headers"]["X-Session-Id"] == "chat-session-tools-77"
    assert len(req2["json"]["messages"]) == 3
    assert req2["json"]["messages"][0]["role"] == "user"
    assert req2["json"]["messages"][1]["role"] == "assistant"
    assert "tool_calls" in req2["json"]["messages"][1]
    assert req2["json"]["messages"][2]["role"] == "tool"
    assert req2["json"]["messages"][2]["tool_call_id"] == "call_tcs_101"
    assert "3550.0" in req2["json"]["messages"][2]["content"]

    assert len(tool_calls_executed) == 1
    assert tool_calls_executed[0]["name"] == "get_stock_quote"
    assert tool_calls_executed[0]["args"] == {"symbol": "TCS"}

    assert any("tool_call" in str(c) for c in yielded_chunks)
    assert any("tool_status" in str(c) for c in yielded_chunks)
    assert any("Tata Consultancy Services (TCS) is currently trading at" in str(c) for c in yielded_chunks)

    traces = get_proxy_traces()
    assert len(traces) >= 2
    assert any(t["trace_id"] == "trace-tool-continuation-2" for t in traces)

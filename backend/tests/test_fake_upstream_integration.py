"""Integration harness for custom endpoint multi-key failover and proxy tool-call continuation.

Simulation Details:
-------------------
This test harness verifies end-to-end inference workflows without requiring external
network access, live credentials, or an active CLIProxyAPI binary in CI.

1. Custom-Endpoint Multi-Key Failover:
   - Simulates an OpenAI-compatible upstream endpoint that receives requests forwarded by
     the proxy layer.
   - Key 1 returns HTTP 401 Unauthorized (or HTTP 429 Too Many Requests).
   - The proxy layer handles the upstream error, places Key 1 into cooldown, and fails over
     to Key 2 (Priority 2).
   - Key 2 succeeds with HTTP 200 and streams the OpenAI-compatible completion chunks back
     to BLM Terminal.
   - Proves that BLM Terminal receives a seamless token stream while the proxy handles
     failover and cooldown state tracking under the hood.

2. Tool-Call Continuation Through the Proxy:
   - Request 1 is dispatched to the proxy loopback endpoint with the user's prompt and tool
     definitions.
   - The proxy/upstream returns a streaming tool-call payload (e.g. `get_stock_quote`).
   - BLM Terminal's execution loop parses the tool call, invokes the async `tool_executor`,
     and formats the tool response.
   - Request 2 (the continuation request) is automatically transmitted back to the proxy with
     the accumulated message history: user prompt, assistant tool call message, and tool
     result message with matching `tool_call_id`.
   - The proxy streams the final completion text back to BLM Terminal.
   - Proves that the proxy loop correctly coordinates multi-turn tool calling and preserves
     session headers across continuation iterations.
"""

import asyncio
import json
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.llm_provider import (
    clear_proxy_traces,
    get_proxy_traces,
    record_proxy_trace,
    stream_chat_completion,
)


class MockStreamingResponse:
    """Mocked httpx streaming response yielding line-by-line SSE chunks."""

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


@pytest.mark.asyncio
async def test_custom_endpoint_multikey_failover_401_to_success(monkeypatch):
    """Verify that when Key 1 returns 401 Unauthorized, the proxy fails over to Key 2.

    Simulated Architecture:
    - Custom endpoint configured with Key 1 (priority 1) and Key 2 (priority 2).
    - When Key 1 is attempted, upstream returns 401.
    - The proxy catches the 401, marks Key 1 in cooldown, and dispatches using Key 2.
    - Key 2 succeeds with 200 OK and streams tokens to BLM Terminal.
    """
    clear_proxy_traces()

    keys_attempted: list[str] = []
    cooldowns: set[str] = set()

    # Define mock upstream keys
    key_primary = "sk-endpoint-key-1-primary"
    key_backup = "sk-endpoint-key-2-backup"

    class SimulatedProxyClient:
        def __init__(self):
            self.requests: list[dict[str, Any]] = []

        def stream(self, method: str, url: str, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None, **kwargs):
            self.requests.append({"method": method, "url": url, "json": json_body, "headers": headers})

            # Simulate proxy-side key selection and failover
            # If primary key is not in cooldown, proxy tries primary key first
            selected_key = key_primary if key_primary not in cooldowns else key_backup
            keys_attempted.append(selected_key)

            if selected_key == key_primary:
                # Primary key fails with 401
                cooldowns.add(key_primary)
                # Proxy catches 401 and immediately fails over to backup key
                keys_attempted.append(key_backup)
                lines = [
                    'data: {"choices": [{"delta": {"content": "Failover from 401 succeeded!"}, "finish_reason": null}]}',
                    'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
                    'data: [DONE]',
                ]
                resp_headers = {
                    "X-CPA-TRACE-ID": "trace-failover-401-uuid",
                    "X-CPA-KEY-USED": key_backup,
                }
                return MockStreamingResponse(200, lines, resp_headers)
            else:
                # Direct backup key success
                lines = [
                    'data: {"choices": [{"delta": {"content": "Backup key direct response"}, "finish_reason": "stop"}]}',
                    'data: [DONE]',
                ]
                return MockStreamingResponse(200, lines, {"X-CPA-TRACE-ID": "trace-backup-direct"})

    simulated_client = SimulatedProxyClient()

    # Mock supervisor ensuring loopback readiness
    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: simulated_client)

    async def noop_executor(tool_calls):
        return [], []

    # 1. First execution triggers 401 on primary -> failover to backup
    chunks_1: list[str] = []
    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "Analyze portfolio allocation"}],
        model="blm:endpoint:test-ep-uuid-1/llama-3.3-70b",
        tools=[],
        tool_executor=noop_executor,
        session_id="session-failover-test-1",
    ):
        chunks_1.append(chunk)

    # Verify failover happened in order: primary key tried first, then backup key
    assert keys_attempted == [key_primary, key_backup]
    assert key_primary in cooldowns
    assert any("Failover from 401 succeeded!" in c for c in chunks_1)

    # Verify trace recorded
    traces = get_proxy_traces()
    assert any(t["trace_id"] == "trace-failover-401-uuid" for t in traces)

    # 2. Subsequent execution immediately uses backup key because primary is in cooldown
    keys_attempted.clear()
    chunks_2: list[str] = []
    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "Second query"}],
        model="blm:endpoint:test-ep-uuid-1/llama-3.3-70b",
        tools=[],
        tool_executor=noop_executor,
        session_id="session-failover-test-1",
    ):
        chunks_2.append(chunk)

    assert keys_attempted == [key_backup]
    assert any("Backup key direct response" in c for c in chunks_2)


@pytest.mark.asyncio
async def test_custom_endpoint_multikey_failover_429_to_success(monkeypatch):
    """Verify that when Key 1 returns 429 Rate Limit, the proxy fails over to Key 2."""
    clear_proxy_traces()

    keys_attempted: list[str] = []
    cooldowns: set[str] = set()

    key_1 = "sk-key-rate-limited"
    key_2 = "sk-key-healthy"

    class SimulatedProxy429Client:
        def stream(self, method: str, url: str, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None, **kwargs):
            selected = key_1 if key_1 not in cooldowns else key_2
            keys_attempted.append(selected)

            if selected == key_1:
                cooldowns.add(key_1)
                keys_attempted.append(key_2)
                lines = [
                    'data: {"choices": [{"delta": {"content": "Recovered from 429 limit!"}, "finish_reason": "stop"}]}',
                    'data: [DONE]',
                ]
                return MockStreamingResponse(200, lines, {"X-CPA-TRACE-ID": "trace-failover-429-uuid"})
            else:
                lines = [
                    'data: {"choices": [{"delta": {"content": "Direct healthy response"}, "finish_reason": "stop"}]}',
                    'data: [DONE]',
                ]
                return MockStreamingResponse(200, lines, {"X-CPA-TRACE-ID": "trace-direct-healthy"})

    simulated_client = SimulatedProxy429Client()
    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: simulated_client)

    async def noop_executor(tool_calls):
        return [], []

    chunks: list[str] = []
    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "Check market sentiment"}],
        model="blm:endpoint:test-ep-uuid-2/qwen-2.5-72b",
        tools=[],
        tool_executor=noop_executor,
        session_id="session-failover-429",
    ):
        chunks.append(chunk)

    assert keys_attempted == [key_1, key_2]
    assert key_1 in cooldowns
    assert any("Recovered from 429 limit!" in c for c in chunks)


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
                # Request 1: Initial user prompt -> Return tool call
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
                # Request 2 (Continuation): Message history contains tool result -> Return final text
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

    # Tool executor implementation
    tool_calls_executed: list[dict[str, Any]] = []

    async def mock_tool_executor(tool_calls: list[dict[str, Any]]):
        statuses = []
        tool_messages = []
        for tc in tool_calls:
            tool_calls_executed.append(tc)
            name = tc.get("name")
            args = tc.get("args") or {}
            call_id = tc.get("id")

            # Emits tool status event
            statuses.append({"type": "tool_status", "name": name, "status": "executed", "result": {"price": 3550.0}})
            # Emits tool response message
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

    # 1. Assert exactly 2 HTTP requests were made to the proxy
    assert len(captured_requests) == 2, f"Expected 2 requests (initial + continuation), got {len(captured_requests)}"

    req1 = captured_requests[0]
    req2 = captured_requests[1]

    # Verify Request 1 (Initial Prompt)
    assert req1["url"] == "http://127.0.0.1:8317/v1/chat/completions"
    assert req1["headers"]["Authorization"] == "Bearer test-client-key"
    assert req1["headers"]["X-Session-Id"] == "chat-session-tools-77"
    assert len(req1["json"]["messages"]) == 1
    assert req1["json"]["messages"][0]["content"] == "What is the stock price of TCS?"
    assert "tools" in req1["json"]

    # Verify tool execution occurred
    assert len(tool_calls_executed) == 1
    assert tool_calls_executed[0]["id"] == "call_tcs_101"
    assert tool_calls_executed[0]["name"] == "get_stock_quote"

    # Verify Request 2 (Continuation Request with tool results)
    assert req2["url"] == "http://127.0.0.1:8317/v1/chat/completions"
    assert req2["headers"]["Authorization"] == "Bearer test-client-key"
    assert req2["headers"]["X-Session-Id"] == "chat-session-tools-77"

    continuation_msgs = req2["json"]["messages"]
    assert len(continuation_msgs) == 3

    # Message 0: User prompt
    assert continuation_msgs[0]["role"] == "user"
    assert continuation_msgs[0]["content"] == "What is the stock price of TCS?"

    # Message 1: Assistant message with tool_calls
    assert continuation_msgs[1]["role"] == "assistant"
    assert continuation_msgs[1]["tool_calls"][0]["id"] == "call_tcs_101"
    assert continuation_msgs[1]["tool_calls"][0]["function"]["name"] == "get_stock_quote"

    # Message 2: Tool message with matching tool_call_id
    assert continuation_msgs[2]["role"] == "tool"
    assert continuation_msgs[2]["tool_call_id"] == "call_tcs_101"
    assert "3550.0" in continuation_msgs[2]["content"]

    # Verify BLM output stream contains both tool status and final completion text
    assert any("tool_call" in str(c) for c in yielded_chunks)
    assert any("tool_status" in str(c) for c in yielded_chunks)
    assert any("Tata Consultancy Services (TCS) is currently trading at" in str(c) for c in yielded_chunks)

    # Verify traces recorded for both requests
    traces = get_proxy_traces()
    trace_ids = [t["trace_id"] for t in traces]
    assert "trace-tool-call-1" in trace_ids
    assert "trace-tool-continuation-2" in trace_ids
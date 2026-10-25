import pytest
import json
import httpx
from unittest.mock import patch, AsyncMock
from typing import Any

from app.services.ai_chat_service import run_chat_agent
from app.services.llm_provider import _run_openai_loop

class MockResponse:
    def __init__(self, status_code, chunks=None, text=""):
        self.status_code = status_code
        self._chunks = chunks or []
        self._text = text
        
    async def aread(self):
        return self._text.encode("utf-8")
        
    async def aiter_lines(self):
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_run_openai_loop_text():
    messages = [{"role": "user", "content": "Hello"}]
    
    chunks = [
        'data: {"choices": [{"delta": {"content": "Hi"}}]}\n\n',
        'data: {"choices": [{"delta": {"content": " there"}}]}\n\n',
        'data: [DONE]\n\n'
    ]
    
    mock_resp = MockResponse(200, chunks=chunks)
    
    async def dummy_executor(tc): return [], []

    with patch("httpx.AsyncClient.stream", return_value=mock_resp):
        events = []
        async for evt in _run_openai_loop(messages, "gpt-test", "dummy-key", [], dummy_executor, base_url="http://127.0.0.1:8123/v1"):
            events.append(evt)
            
        assert len(events) == 3
        assert json.loads(events[0]) == {"type": "token", "text": "Hi"}
        assert json.loads(events[1]) == {"type": "token", "text": " there"}
        assert json.loads(events[2]) == {"type": "done"}
        
        # Verify message appending
        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Hi there"

@pytest.mark.asyncio
async def test_run_openai_loop_error():
    messages = [{"role": "user", "content": "Hello"}]
    
    mock_resp = MockResponse(401, text="Unauthorized access")
    
    async def dummy_executor(tc): return [], []

    with patch("httpx.AsyncClient.stream", return_value=mock_resp):
        events = []
        async for evt in _run_openai_loop(messages, "gpt-test", "dummy-key", [], dummy_executor, base_url="http://127.0.0.1:8123/v1"):
            events.append(evt)
            
        assert len(events) == 2
        assert "error" in json.loads(events[0])["type"]
        assert "done" in json.loads(events[1])["type"]


@pytest.mark.asyncio
async def test_run_chat_agent_passes_tool_executor_and_forwards_allow_external_route():
    recorded = {}

    async def fake_stream_chat_completion(*args, tool_executor, allow_external_route=False, **kwargs):
        recorded["tool_executor"] = tool_executor
        recorded["allow_external_route"] = allow_external_route
        normalized_tool_call = {
            "id": "call_zen_1",
            "name": "get_stock_quote",
            "args": {"symbol": "AAPL"},
        }
        await tool_executor([normalized_tool_call])
        yield json.dumps({"type": "token", "text": "ok"})
        yield json.dumps({"type": "done"})

    with patch("app.services.ai_chat_service.stream_chat_completion", side_effect=fake_stream_chat_completion), \
         patch("app.services.ai_chat_service._run_tools_parallel", new_callable=AsyncMock) as mock_parallel:
        mock_parallel.return_value = ([], [])
        chunks = []
        async for chunk in run_chat_agent(
            messages=[{"role": "user", "content": "hello"}],
            symbol="AAPL",
            exchange="NASDAQ",
            model="kimi-k2.5",
            session_id="session-test-42",
            user_id=99,
            allow_external_route=True,
        ):
            chunks.append(chunk)

    assert len(chunks) == 2
    assert recorded["allow_external_route"] is True
    assert callable(recorded["tool_executor"])
    mock_parallel.assert_awaited_once()
    call_args, _ = mock_parallel.call_args
    assert call_args[0] == [{"id": "call_zen_1", "name": "get_stock_quote", "args": {"symbol": "AAPL"}}]
    assert isinstance(call_args[1], set)
    assert call_args[2] == "session-test-42"
    assert call_args[3] == 99

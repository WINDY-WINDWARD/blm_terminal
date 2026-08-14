import pytest
import json
import httpx
from unittest.mock import patch, AsyncMock
from typing import Any

from app.services.llm_provider import _run_openai_loop, _run_anthropic_loop

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
        async for evt in _run_openai_loop(messages, "gpt-test", "dummy-key", [], dummy_executor):
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
        async for evt in _run_openai_loop(messages, "gpt-test", "dummy-key", [], dummy_executor):
            events.append(evt)
            
        assert len(events) == 2
        assert "error" in json.loads(events[0])["type"]
        assert "done" in json.loads(events[1])["type"]

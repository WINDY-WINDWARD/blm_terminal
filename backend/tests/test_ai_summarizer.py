"""Tests for the AI summarizer service and router."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import main as main_mod
from main import app
from app.services import llm_provider


@pytest.fixture
def mock_alerts_payload():
    return {
        "symbol": "RELIANCE",
        "alerts": [
            {
                "id": 1,
                "trigger_type": "volume_surge",
                "message": "Traded 2.5x 20-day volume with price above VWAP.",
                "triggered_at": "2026-10-18T09:45:00Z",
                "triggered_date": "2026-10-18",
            },
            {
                "id": 2,
                "trigger_type": "rsi_overbought",
                "message": "RSI reached 72.1 near intraday resistance.",
                "triggered_at": "2026-10-18T10:15:00Z",
                "triggered_date": "2026-10-18",
            },
        ],
        "max_tokens": 2048,
    }


def _digest_json(**overrides: str) -> str:
    payload = {
        "bias": "bullish",
        "summary": (
            "Volume expansion above VWAP supports near-term upside. "
            "The overbought RSI argues for waiting for follow-through rather than chasing."
        ),
        "trigger": "Sustained follow-through above the alert-session high.",
        "invalidation": "Momentum fades and price closes back below VWAP.",
        "risk": "An overbought RSI increases the risk of a failed breakout.",
    }
    payload.update(overrides)
    return f"<digest>{json.dumps(payload)}</digest>"


@pytest.fixture
async def api_client(monkeypatch):
    monkeypatch.setattr(main_mod, "LAUNCH_TOKEN", "test-token")
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"x-blm-token": "test-token"},
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_summarize_alerts_unconfigured(api_client, mock_alerts_payload):
    with patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=False)):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 503
        assert "AI API key is not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_alerts_success(api_client, mock_alerts_payload):
    digest = _digest_json()

    async def mock_stream(*args, **kwargs):
        midpoint = len(digest) // 2
        yield json.dumps({"type": "token", "text": digest[:midpoint]})
        yield json.dumps({"type": "token", "text": digest[midpoint:]})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "summary": (
            "Volume expansion above VWAP supports near-term upside. "
            "The overbought RSI argues for waiting for follow-through rather than chasing."
        ),
        "input_tokens": 0,
        "output_tokens": 0,
        "model": "gemini-3.8-flash-low",
        "bias": "bullish",
        "trigger": "Sustained follow-through above the alert-session high.",
        "invalidation": "Momentum fades and price closes back below VWAP.",
        "risk": "An overbought RSI increases the risk of a failed breakout.",
    }


@pytest.mark.asyncio
async def test_summarize_alerts_collapses_whitespace_in_every_field(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({
            "type": "token",
            "text": _digest_json(
                summary="Line 1.\n\nLine 2.\n  Line 3.",
                trigger="Trigger one.\n Trigger two.",
                invalidation="Invalidation one.\n Invalidation two.",
                risk="Risk one.\n Risk two.",
            ),
        })
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="test-verifier-model")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "Line 1. Line 2. Line 3."
    assert data["trigger"] == "Trigger one. Trigger two."
    assert data["invalidation"] == "Invalidation one. Invalidation two."
    assert data["risk"] == "Risk one. Risk two."


@pytest.mark.asyncio
async def test_summarize_alerts_accepts_json_code_fence(api_client, mock_alerts_payload):
    fenced = f"```json\n{_digest_json()[len('<digest>'):-len('</digest>')]}\n```"

    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": fenced})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="test-verifier-model")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 200
    assert response.json()["bias"] == "bullish"


@pytest.mark.asyncio
async def test_summarize_alerts_ignores_reasoning_and_stale_digest_tags(api_client, mock_alerts_payload):
    noisy_output = "\n".join([
        "```text",
        "<digest>",
        "```text",
        "Reasoning: the model considered a partial {\"summary\": \"unfinished\"",
        "```text",
        "</digest>",
        "```",
        _digest_json(),
    ])

    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": noisy_output})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-high")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 200
    assert response.json()["bias"] == "bullish"
    assert response.json()["trigger"] == "Sustained follow-through above the alert-session high."


@pytest.mark.asyncio
async def test_summarize_alerts_uses_configured_verifier_model(api_client, mock_alerts_payload):
    captured_kwargs = {}

    async def mock_stream(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "token", "text": _digest_json()})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-medium")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 200
    assert response.json()["model"] == "gemini-3.8-flash-medium"
    assert captured_kwargs["model"] == "gemini-3.8-flash-medium"
    assert captured_kwargs["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_summarize_alerts_honors_max_tokens(api_client, mock_alerts_payload):
    captured_kwargs = {}

    async def mock_stream(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "token", "text": _digest_json()})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json={**mock_alerts_payload, "max_tokens": 300})

    assert response.status_code == 200
    assert captured_kwargs["max_tokens"] == 300


@pytest.mark.asyncio
async def test_summarize_alerts_rejects_invalid_json(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "<digest>{not-json}</digest>"})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "LLM returned an invalid alert digest"


@pytest.mark.asyncio
async def test_summarize_alerts_rejects_missing_field(api_client, mock_alerts_payload):
    payload = json.loads(_digest_json()[len("<digest>"):-len("</digest>")])
    payload.pop("risk")

    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": f"<digest>{json.dumps(payload)}</digest>"})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "LLM returned an invalid alert digest"


@pytest.mark.asyncio
async def test_summarize_alerts_rejects_invalid_bias(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": _digest_json(bias="strong-buy")})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "LLM returned an invalid alert digest"


@pytest.mark.asyncio
async def test_summarize_alerts_rejects_empty_output(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "LLM returned an empty summary"


@pytest.mark.asyncio
async def test_summarize_alerts_propagates_stream_error_after_partial_tokens(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Partial alert digest content..."})
        yield json.dumps({"type": "error", "message": "Inference quota exceeded on worker"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 500
    assert "Inference quota exceeded on worker" in response.json()["detail"]


@pytest.mark.asyncio
async def test_antigravity_stream_excludes_thought_text():
    digest = _digest_json()

    class FakeResponse:
        status_code = 200

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield "data: " + json.dumps({
                "response": {
                    "candidates": [{
                        "content": {
                            "parts": [
                                {"text": "private reasoning with <digest>fake</digest>", "thought": True},
                                {"text": digest},
                            ]
                        }
                    }]
                }
            })

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def stream(self, *args, **kwargs):
            return FakeStream()

    async def noop_executor(tool_calls):
        return [], []

    with (
        patch("app.services.llm_provider.get_antigravity_token", AsyncMock(return_value="test-token")),
        patch("app.services.llm_provider._get_antigravity_headers", lambda token: {}),
        patch("app.services.llm_provider._get_shared_client", lambda: FakeClient()),
    ):
        events = [
            json.loads(event)
            async for event in llm_provider._run_antigravity_loop(
                messages=[{"role": "user", "content": "Summarize alerts"}],
                model="gemini-3.8-flash-high",
                tools=[],
                tool_executor=noop_executor,
                max_iter=1,
            )
        ]

    streamed_text = "".join(event.get("text", "") for event in events if event.get("type") == "token")
    assert streamed_text == digest
    assert "private reasoning" not in streamed_text
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_ai_health_ping_success(api_client):
    captured_kwargs = {}

    async def mock_stream(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "token", "text": "OK"})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.get("/api/ai/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "model": "gemini-3.8-flash-low"}
    assert captured_kwargs["max_tokens"] == 32


@pytest.mark.asyncio
async def test_ai_health_ping_failure(api_client):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "error", "message": "Invalid API Key"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.get("/api/ai/health")

    assert response.status_code == 200
    assert response.json() == {"status": "unreachable", "model": None}


@pytest.mark.asyncio
async def test_ai_health_ping_rejects_done_only(api_client):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.get("/api/ai/health")

    assert response.status_code == 200
    assert response.json() == {"status": "unreachable", "model": None}


@pytest.mark.asyncio
async def test_ai_health_ping_rejects_malformed_stream(api_client):
    async def mock_stream(*args, **kwargs):
        yield "not-json"

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.get("/api/ai/health")

    assert response.status_code == 200
    assert response.json() == {"status": "unreachable", "model": None}


@pytest.mark.asyncio
async def test_ai_health_ping_timeout(api_client):
    async def mock_stream(*args, **kwargs):
        await asyncio.sleep(1)
        yield json.dumps({"type": "token", "text": "late"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
        patch("app.services.ai_summarizer._PING_TIMEOUT_SECONDS", 0.01),
    ):
        response = await api_client.get("/api/ai/health")

    assert response.status_code == 200
    assert response.json() == {"status": "unreachable", "model": None}

"""Tests for the AI summarizer service and router."""

import json
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

import main as main_mod
from main import app
from app.services.ai_summarizer import ai_summarizer


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
        "max_tokens": 300,
    }


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
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Reliance is showing sustained upside momentum "})
        yield json.dumps({"type": "token", "text": "led by volume expansion above VWAP, "})
        yield json.dumps({"type": "token", "text": "though an overbought RSI reading near resistance indicates near-term consolidation risk."})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        data = response.json()
        assert "Reliance is showing sustained upside momentum" in data["summary"]
        assert data["model"] == "gemini-3.8-flash-low"


@pytest.mark.asyncio
async def test_summarize_alerts_empty_alerts(api_client):
    with patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)):
        response = await api_client.post(
            "/api/ai/alerts/summarize",
            json={"symbol": "RELIANCE", "alerts": []},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_summarize_alerts_whitespace_collapse(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Line 1 sentence.\n\nLine 2 sentence.\n   Line 3 sentence."})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="test-verifier-model")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        data = response.json()
        assert "\n" not in data["summary"]
        assert data["summary"] == "Line 1 sentence. Line 2 sentence. Line 3 sentence."
        assert data["model"] == "test-verifier-model"


@pytest.mark.asyncio
async def test_summarize_alerts_gemini_verifier_model(api_client, mock_alerts_payload):
    captured_kwargs = {}

    async def mock_stream(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "token", "text": "Gemini alert digest summary."})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-medium")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Gemini alert digest summary."
        assert data["model"] == "gemini-3.8-flash-medium"
        assert captured_kwargs.get("model") == "gemini-3.8-flash-medium"


@pytest.mark.asyncio
async def test_summarize_alerts_honors_max_tokens(api_client, mock_alerts_payload):
    captured_kwargs = {}

    async def mock_stream(*args, **kwargs):
        captured_kwargs.update(kwargs)
        yield json.dumps({"type": "token", "text": "Token-limited summary."})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        assert captured_kwargs.get("max_tokens") == 300


@pytest.mark.asyncio
async def test_summarize_alerts_propagates_stream_error_after_partial_tokens(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Partial alert summary content..."})
        yield json.dumps({"type": "error", "message": "Inference quota exceeded on worker"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 500
        assert "Inference quota exceeded on worker" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_alerts_preserves_token_usage(api_client, mock_alerts_payload):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Summary with reported token usage."})
        yield json.dumps({"type": "usage", "input_tokens": 128, "output_tokens": 42})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        data = response.json()
        assert data["input_tokens"] == 128
        assert data["output_tokens"] == 42


@pytest.mark.asyncio
async def test_ai_health_ping_success(api_client):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "pong"})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.routers.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.get("/api/ai/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["model"] == "gemini-3.8-flash-low"


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
        data = response.json()
        assert data["status"] == "unreachable"
        assert data["model"] is None

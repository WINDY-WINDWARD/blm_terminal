"""Tests for the AI summarizer service and router."""

from unittest.mock import AsyncMock, MagicMock, patch
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
    with patch.object(ai_summarizer, "is_configured", AsyncMock(return_value=False)):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 503
        assert "AI API key is not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_alerts_success(api_client, mock_alerts_payload):
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "Reliance is showing sustained upside momentum led by volume expansion above VWAP, "
        "though an overbought RSI reading near resistance indicates near-term consolidation risk."
    )
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 95
    mock_usage.completion_tokens = 32

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage
    mock_response.model = "test-model"

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with (
        patch.object(ai_summarizer, "is_configured", AsyncMock(return_value=True)),
        patch.object(ai_summarizer, "_get_client", AsyncMock(return_value=mock_client)),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        data = response.json()
        assert "Reliance is showing sustained upside momentum" in data["summary"]
        assert data["input_tokens"] == 95
        assert data["output_tokens"] == 32
        assert data["model"] == "test-model"


@pytest.mark.asyncio
async def test_summarize_alerts_empty_alerts(api_client):
    with patch.object(ai_summarizer, "is_configured", AsyncMock(return_value=True)):
        response = await api_client.post(
            "/api/ai/alerts/summarize",
            json={"symbol": "RELIANCE", "alerts": []},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_summarize_alerts_whitespace_collapse(api_client, mock_alerts_payload):
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "Line 1 sentence.\n\nLine 2 sentence.\n   Line 3 sentence."
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(prompt_tokens=40, completion_tokens=20)
    mock_response.model = "test-model"

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    with (
        patch.object(ai_summarizer, "is_configured", AsyncMock(return_value=True)),
        patch.object(ai_summarizer, "_get_client", AsyncMock(return_value=mock_client)),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)
        assert response.status_code == 200
        data = response.json()
        assert "\n" not in data["summary"]
        assert data["summary"] == "Line 1 sentence. Line 2 sentence. Line 3 sentence."

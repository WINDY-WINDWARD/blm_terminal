"""Tests for the AI summarizer service and router."""

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import main as main_mod
from main import app
from app.services import llm_provider


@pytest.mark.asyncio
async def test_summarizer_allows_configured_external_verifier_model(monkeypatch):
    from app.services.ai_summarizer import AISummarizer

    captured_options = {}

    async def fake_stream_chat_completion(**options):
        captured_options.update(options)
        yield json.dumps({"type": "token", "text": "cross-route summary"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(
        "app.services.ai_summarizer.get_configured_verifier_model",
        AsyncMock(return_value="blm:oauth:codex/gpt-5-codex"),
    )
    monkeypatch.setattr("app.services.ai_summarizer.stream_chat_completion", fake_stream_chat_completion)

    summary, model = await AISummarizer()._generate_summary(
        messages=[{"role": "user", "content": "Summarize"}],
        system_prompt="Return a summary.",
    )

    assert summary == "cross-route summary"
    assert model == "blm:oauth:codex/gpt-5-codex"
    assert captured_options["allow_external_route"] is True


@pytest.mark.asyncio
async def test_summarizer_ping_allows_configured_external_verifier_model(monkeypatch):
    from app.services.ai_summarizer import AISummarizer

    captured_options = {}

    async def fake_stream_chat_completion(**options):
        captured_options.update(options)
        yield json.dumps({"type": "token", "text": "OK"})

    monkeypatch.setattr(
        "app.services.ai_summarizer.is_ai_provider_configured",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.services.ai_summarizer.get_configured_verifier_model",
        AsyncMock(return_value="blm:oauth:codex/gpt-5-codex"),
    )
    monkeypatch.setattr("app.services.ai_summarizer.stream_chat_completion", fake_stream_chat_completion)

    assert await AISummarizer().ping_provider() is True
    assert captured_options["allow_external_route"] is True


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

    assert response.status_code == 502
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

    assert response.status_code == 502
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

    assert response.status_code == 502
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

    assert response.status_code == 502
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

    assert response.status_code == 502
    assert "Inference quota exceeded on worker" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_alerts_validation_error_returns_400(api_client, mock_alerts_payload):
    payload = dict(mock_alerts_payload)
    payload["symbol"] = "   "
    with patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)):
        response = await api_client.post("/api/ai/alerts/summarize", json=payload)

    assert response.status_code == 400
    assert "Symbol cannot be empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_alerts_unexpected_exception_returns_500(api_client, mock_alerts_payload):
    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.routers.ai_summarizer.ai_summarizer.summarize_alerts", AsyncMock(side_effect=TypeError("Unexpected alerts bug"))),
    ):
        response = await api_client.post("/api/ai/alerts/summarize", json=mock_alerts_payload)

    assert response.status_code == 500
    assert "Unexpected error: Unexpected alerts bug" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_success(api_client):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Financial summary of the statement."})
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post(
            "/api/ai/summarize",
            json={"text": "Operating revenue increased by 14% year-over-year.", "max_tokens": 512},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "Financial summary of the statement."
    assert data["model"] == "gemini-3.8-flash-low"


@pytest.mark.asyncio
async def test_summarize_propagates_stream_error_after_partial_tokens(api_client):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "token", "text": "Partial financial summary..."})
        yield json.dumps({"type": "error", "message": "Inference quota exceeded on worker"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post(
            "/api/ai/summarize",
            json={"text": "Quarterly earnings report text.", "max_tokens": 512},
        )

    assert response.status_code == 502
    assert "Inference quota exceeded on worker" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_rejects_empty_output(api_client):
    async def mock_stream(*args, **kwargs):
        yield json.dumps({"type": "done"})

    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low")),
        patch("app.services.ai_summarizer.stream_chat_completion", side_effect=mock_stream),
    ):
        response = await api_client.post(
            "/api/ai/summarize",
            json={"text": "Quarterly earnings report text.", "max_tokens": 512},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "LLM returned an empty summary"


@pytest.mark.asyncio
async def test_summarize_validation_error_returns_400(api_client):
    with patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)):
        response = await api_client.post(
            "/api/ai/summarize",
            json={"text": "   ", "max_tokens": 512},
        )

    assert response.status_code == 400
    assert "Text cannot be empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarize_unexpected_exception_returns_500(api_client):
    with (
        patch("app.services.ai_summarizer.is_ai_provider_configured", AsyncMock(return_value=True)),
        patch("app.routers.ai_summarizer.ai_summarizer.summarize", AsyncMock(side_effect=TypeError("Unexpected type bug"))),
    ):
        response = await api_client.post(
            "/api/ai/summarize",
            json={"text": "Quarterly earnings report text.", "max_tokens": 512},
        )

    assert response.status_code == 500
    assert "Unexpected error: Unexpected type bug" in response.json()["detail"]


@pytest.mark.asyncio
async def test_summarizer_stream_path_goes_through_proxy(monkeypatch):
    """Verify that the summarizer stream path goes through supervisor.ensure_started and _run_openai_loop."""
    from app.services import llm_provider
    from app.services.ai_summarizer import AISummarizer

    fake_supervisor = MagicMock()
    fake_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8123, "test-client-key"))
    fake_supervisor.request_sync = MagicMock()
    monkeypatch.setattr(llm_provider, "get_proxy_supervisor", lambda: fake_supervisor)

    captured = {}

    async def _mock_openai_loop(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        yield json.dumps({"type": "token", "text": "summarizer output"})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(llm_provider, "_run_openai_loop", _mock_openai_loop)
    monkeypatch.setattr("app.services.ai_summarizer.get_configured_verifier_model", AsyncMock(return_value="gemini-3.8-flash-low"))
    monkeypatch.setattr(llm_provider, "resolve_active_route_id", AsyncMock(return_value="direct:groq"))
    monkeypatch.setattr(llm_provider, "get_route_models", AsyncMock(return_value=["gemini-3.8-flash-low"]))

    service = AISummarizer()
    content, used_model = await service._generate_summary(
        messages=[{"role": "user", "content": "Summarize alerts"}],
        system_prompt="system",
    )
    assert content == "summarizer output"
    assert used_model == "gemini-3.8-flash-low"
    fake_supervisor.ensure_started.assert_awaited_once()
    assert captured["kwargs"]["base_url"] == "http://127.0.0.1:8123/v1"


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

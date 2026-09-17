import pytest
from unittest.mock import AsyncMock, patch
import app.routers.ai_chat as ai_chat_mod
from app.routers.ai_chat import fetch_zen_models, get_chat_models


@pytest.mark.asyncio
async def test_zen_models_free_on_top_fallback():
    # Test fallback list when no key
    models = await fetch_zen_models(api_key="")
    assert len(models) > 0
    # First model must be free
    assert models[0]["is_free"] is True
    assert "[FREE]" in models[0]["label"]

    # All free models must precede paid models
    saw_paid = False
    for m in models:
        if m.get("is_free"):
            assert not saw_paid, f"Free model {m['id']} appeared after a paid model"
        else:
            saw_paid = True


@pytest.mark.asyncio
async def test_zen_models_dynamic_fetch():
    mock_payload = {
        "object": "list",
        "data": [
            {"id": "gpt-5", "object": "model"},
            {"id": "deepseek-v4-flash-free", "object": "model"},
            {"id": "claude-sonnet-4-5", "object": "model"},
            {"id": "mimo-v2.5-free", "object": "model"},
        ],
    }

    class MockResponse:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return mock_payload

    # Reset cache
    ai_chat_mod._ZEN_MODELS_CACHE = {"ts": 0.0, "models": []}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MockResponse()
        models = await fetch_zen_models(api_key="test-key")

        assert len(models) == 4
        # Free models first, sorted
        assert models[0]["id"] == "deepseek-v4-flash-free"
        assert models[0]["is_free"] is True
        assert models[1]["id"] == "mimo-v2.5-free"
        assert models[1]["is_free"] is True
        # Paid models next, sorted
        assert models[2]["id"] == "claude-sonnet-4-5"
        assert models[2]["is_free"] is False
        assert models[3]["id"] == "gpt-5"
        assert models[3]["is_free"] is False


@pytest.mark.asyncio
async def test_get_chat_models_for_zen():
    with patch("app.routers.ai_chat.get_dynamic_ai_provider", AsyncMock(return_value="zen")), \
         patch("app.routers.ai_chat.get_dynamic_ai_api_key", AsyncMock(return_value="")):
        models = await get_chat_models()
        assert len(models) > 0
        assert models[0]["is_free"] is True

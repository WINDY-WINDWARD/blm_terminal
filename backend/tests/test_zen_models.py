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
async def test_zen_models_returns_static_fallback_without_network():
    # fetch_zen_models is a legacy stub: it never calls the provider, because
    # the live catalog now comes from GET /ai/routes/models.
    ai_chat_mod._ZEN_MODELS_CACHE = {"ts": 0.0, "models": []}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        models = await fetch_zen_models(api_key="test-key")

    mock_get.assert_not_called()
    assert models == ai_chat_mod.FALLBACK_ZEN_MODELS
    # Free models first, sorted
    assert models[0]["id"] == "deepseek-v4-flash-free"
    assert models[0]["is_free"] is True
    assert any(m["is_free"] is False for m in models)


@pytest.mark.asyncio
async def test_get_chat_models_for_zen():
    with patch("app.routers.ai_chat.get_dynamic_ai_provider", AsyncMock(return_value="zen")), \
         patch("app.routers.ai_chat.get_dynamic_ai_api_key", AsyncMock(return_value="")):
        models = await get_chat_models()

    assert len(models) > 0
    for model in models:
        assert model["id"].startswith("blm:direct:zen-paid/")
        assert model["label"]

"""Tests for direct provider model catalog discovery."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.direct_model_catalog import (
    ProviderCatalogError,
    ProviderCredentialError,
    fetch_live_models,
)


class _FakeResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, payload=None, *, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)
        self._json_ok = payload is not None

    def json(self):
        if not self._json_ok:
            raise ValueError("not json")
        return self._payload


def _mock_get(response):
    return AsyncMock(return_value=response)


async def test_openai_shape_returns_ids_and_drops_embedding():
    payload = {
        "data": [
            {"id": "gpt-5"},
            {"id": "text-embedding-3-large"},
            {"id": "gpt-5-mini", "name": "GPT-5 Mini"},
        ]
    }
    mock_get = _mock_get(_FakeResponse(payload))
    with patch("httpx.AsyncClient.get", new=mock_get):
        models = await fetch_live_models("openai", "k")

    assert [model["id"] for model in models] == ["gpt-5", "gpt-5-mini"]
    assert models[1]["label"] == "GPT-5 Mini"
    assert mock_get.await_args.kwargs["headers"]["Authorization"] == "Bearer k"


async def test_gemini_shape_strips_prefix_and_keeps_generate_content():
    payload = {
        "models": [
            {
                "name": "models/gemini-3.8-flash",
                "displayName": "Gemini 3.8 Flash",
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {
                "name": "models/text-embedding-004",
                "supportedGenerationMethods": ["embedContent"],
            },
            {
                "name": "models/gemini-2.5-pro",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    }
    mock_get = _mock_get(_FakeResponse(payload))
    with patch("httpx.AsyncClient.get", new=mock_get):
        models = await fetch_live_models("aistudio", "secret-key")

    assert [model["id"] for model in models] == [
        "gemini-3.8-flash",
        "gemini-2.5-pro",
    ]
    assert models[0]["label"] == "Gemini 3.8 Flash"
    url = mock_get.await_args.args[0]
    assert "secret-key" not in url
    assert mock_get.await_args.kwargs["headers"]["x-goog-api-key"] == "secret-key"


async def test_anthropic_shape_returns_ids():
    payload = {
        "data": [
            {"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"},
            {"id": "claude-opus-4-1"},
        ]
    }
    mock_get = _mock_get(_FakeResponse(payload))
    with patch("httpx.AsyncClient.get", new=mock_get):
        models = await fetch_live_models("anthropic", "k")

    assert [model["id"] for model in models] == [
        "claude-sonnet-4-5",
        "claude-opus-4-1",
    ]
    assert models[0]["label"] == "Claude Sonnet 4.5"
    assert models[1]["label"] == "claude-opus-4-1"


async def test_zen_paid_keeps_only_chat_type():
    payload = {
        "data": [
            {"id": "gemini-3.8-flash", "type": "chat"},
            {"id": "gemini-nano-banana-2.1", "type": "image"},
            {"id": "claude-sonnet-4-5"},
        ]
    }
    mock_get = _mock_get(_FakeResponse(payload))
    with patch("httpx.AsyncClient.get", new=mock_get):
        models = await fetch_live_models("zen-paid", "k")

    assert [model["id"] for model in models] == [
        "gemini-3.8-flash",
        "claude-sonnet-4-5",
    ]


async def test_status_401_raises_credential_error():
    fake = _FakeResponse(
        {"error": {"message": "Invalid API key provided"}},
        status_code=401,
    )
    with patch("httpx.AsyncClient.get", new=_mock_get(fake)):
        with pytest.raises(ProviderCredentialError, match="Invalid API key provided"):
            await fetch_live_models("openai", "bad-key")


async def test_status_400_with_key_raises_credential_error():
    fake = _FakeResponse(
        {"error": {"message": "bad credentials"}},
        status_code=400,
    )
    with patch("httpx.AsyncClient.get", new=_mock_get(fake)):
        with pytest.raises(ProviderCredentialError, match="bad credentials"):
            await fetch_live_models("anthropic", "bad-key")


async def test_status_400_without_key_raises_catalog_error():
    fake = _FakeResponse(
        {"error": {"message": "bad request"}},
        status_code=400,
    )
    with patch("httpx.AsyncClient.get", new=_mock_get(fake)):
        with pytest.raises(ProviderCatalogError, match="HTTP 400"):
            await fetch_live_models("openai", "")


async def test_connect_timeout_raises_catalog_error():
    mock_get = AsyncMock(side_effect=httpx.ConnectTimeout("boom"))
    with patch("httpx.AsyncClient.get", new=mock_get):
        with pytest.raises(
            ProviderCatalogError, match="Timed out fetching models from openai"
        ):
            await fetch_live_models("openai", "k")


async def test_go_sends_bearer_authorization():
    mock_get = _mock_get(_FakeResponse({"data": [{"id": "gpt-5"}]}))
    with patch("httpx.AsyncClient.get", new=mock_get):
        await fetch_live_models("go", "k")

    assert mock_get.await_args.kwargs["headers"]["Authorization"] == "Bearer k"

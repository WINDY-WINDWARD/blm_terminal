"""Tests for POST /ai/provider-models key handling on direct routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import app.services.direct_model_catalog as catalog
from app.routers.ai_chat import _resolve_provider_models


@pytest.mark.asyncio
async def test_bad_key_raises_401(monkeypatch):
    async def reject(provider: str, api_key: str = "", *, timeout: float = 8.0):
        raise catalog.ProviderCredentialError("Invalid credential")

    monkeypatch.setattr(catalog, "fetch_live_models", reject)

    with pytest.raises(HTTPException) as excinfo:
        await _resolve_provider_models("go", "bogus-key")

    assert excinfo.value.status_code == 401
    assert "Invalid credential" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_missing_key_falls_back_to_default_catalog(monkeypatch):
    async def reject(provider: str, api_key: str = "", *, timeout: float = 8.0):
        raise catalog.ProviderCredentialError("Missing bearer authentication")

    monkeypatch.setattr(catalog, "fetch_live_models", reject)
    monkeypatch.setattr(
        "app.routers.ai_chat.get_dynamic_ai_api_key",
        AsyncMock(return_value=""),
    )

    models = await _resolve_provider_models("zen-paid", "")

    assert models
    assert all(item["id"].startswith("blm:direct:zen-paid/") for item in models)


@pytest.mark.asyncio
async def test_live_catalog_ids_are_route_prefixed(monkeypatch):
    async def live(provider: str, api_key: str = "", *, timeout: float = 8.0):
        assert api_key == "go-key"
        return [{"id": "deepseek-v4.1-flash", "label": "DeepSeek V4.1 Flash"}]

    monkeypatch.setattr(catalog, "fetch_live_models", live)

    models = await _resolve_provider_models("go", "go-key")

    assert models == [
        {
            "id": "blm:direct:go/deepseek-v4.1-flash",
            "label": "DeepSeek V4.1 Flash",
        }
    ]

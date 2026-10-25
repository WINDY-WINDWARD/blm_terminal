"""Tests for mapping legacy direct: routes onto CLIProxyAPI config sections."""

from __future__ import annotations

import json

import pytest
import yaml

from app.services import ai_config
from app.services.direct_proxy_routes import (
    DIRECT_ROUTES,
    SUPPORTED_ROUTE_IDS,
    build_direct_proxy_entries,
    direct_proxy_prefix,
    is_supported_direct_route,
)
from app.services.proxy_supervisor import ProxySupervisor, generate_proxy_config
from app.services.route_registry import compute_oauth_proxy_prefix


KEYS = {
    "aistudio": "AIza-test",
    "anthropic": "sk-ant-api-test",
    "openai": "sk-openai-test",
    "zen-paid": "zen-test",
    "groq": "gsk-test",
    "nvidia": "nvapi-test",
    "openrouter": "or-test",
    "deepseek": "ds-test",
    "xai": "xai-test",
    "together": "tg-test",
    "go": "",
}


def test_prefixes_are_stable_and_match_route_registry():
    for route_id in SUPPORTED_ROUTE_IDS:
        assert direct_proxy_prefix(route_id) == compute_oauth_proxy_prefix(route_id)
        assert direct_proxy_prefix(route_id) == direct_proxy_prefix(route_id)
        assert direct_proxy_prefix(route_id).startswith("blm-")


def test_unsupported_routes_are_not_supported():
    assert not is_supported_direct_route("direct:copilot")
    assert not is_supported_direct_route("direct:claude-code")
    assert DIRECT_ROUTES["direct:copilot"].section is None
    assert "Copilot" in (DIRECT_ROUTES["direct:copilot"].unavailable_reason or "")


@pytest.mark.asyncio
async def test_build_entries_maps_sections_and_omits_default_model_lists(monkeypatch):
    async def fake_key(provider: str) -> str:
        return KEYS.get(provider, "")

    monkeypatch.setattr(ai_config, "get_dynamic_ai_api_key", fake_key)

    entries = await build_direct_proxy_entries()
    by_name = {entry["name"]: entry for entry in entries}

    assert set(by_name) == {
        "aistudio",
        "anthropic",
        "openai",
        "zen-paid",
        "groq",
        "nvidia",
        "openrouter",
        "deepseek",
        "xai",
        "together",
    }
    assert by_name["aistudio"]["section"] == "gemini-api-key"
    assert "models" not in by_name["aistudio"]
    assert by_name["aistudio"]["api-key"] == "AIza-test"
    assert by_name["anthropic"]["section"] == "claude-api-key"
    assert "models" not in by_name["anthropic"]
    assert by_name["openai"]["base-url"] == "https://api.openai.com/v1"
    assert by_name["openai"]["api-key-entries"] == [{"api-key": "sk-openai-test"}]
    assert [model["name"] for model in by_name["openai"]["models"]][:2] == ["gpt-4o", "gpt-4o-mini"]
    assert "copilot" not in by_name
    assert "claude-code" not in by_name


@pytest.mark.asyncio
async def test_missing_key_route_is_skipped(monkeypatch):
    async def fake_key(provider: str) -> str:
        return "" if provider == "go" else KEYS.get(provider, "")

    monkeypatch.setattr(ai_config, "get_dynamic_ai_api_key", fake_key)
    names = {entry["name"] for entry in await build_direct_proxy_entries()}
    assert "go" not in names


def test_generate_config_merges_direct_and_custom_entries():
    config = yaml.safe_load(
        generate_proxy_config(
            host="127.0.0.1",
            port=9999,
            client_key="client",
            management_key="mgmt",
            auth_dir="C:/tmp/auth",
            custom_endpoints=[
                {
                    "name": "custom-one",
                    "prefix": "custom-one",
                    "base-url": "https://example.test/v1",
                    "models": ["m1"],
                    "api-key-entries": [{"api-key": "custom-key"}],
                }
            ],
            direct_providers=[
                {
                    "section": "openai-compatibility",
                    "name": "openai",
                    "prefix": "blm-openai",
                    "base-url": "https://api.openai.com/v1",
                    "models": [{"name": "gpt-4o"}],
                    "api-key-entries": [{"api-key": "sk-test"}],
                },
                {
                    "section": "gemini-api-key",
                    "name": "aistudio",
                    "prefix": "blm-aistudio",
                    "api-key": "AIza-test",
                },
            ],
        )
    )

    compat = config["openai-compatibility"]
    assert [entry["name"] for entry in compat] == ["custom-one", "openai"]
    assert "section" not in json.dumps(config)
    assert config["gemini-api-key"] == [
        {"name": "aistudio", "prefix": "blm-aistudio", "api-key": "AIza-test"}
    ]
    assert "claude-api-key" not in config


def test_generate_config_with_only_direct_entries_creates_no_empty_compat_list():
    config = yaml.safe_load(
        generate_proxy_config(
            host="127.0.0.1",
            port=9999,
            client_key="client",
            management_key="mgmt",
            auth_dir="C:/tmp/auth",
            direct_providers=[
                {
                    "section": "claude-api-key",
                    "name": "anthropic",
                    "prefix": "blm-anthropic",
                    "api-key": "sk-ant-test",
                }
            ],
        )
    )
    assert "openai-compatibility" not in config
    assert config["claude-api-key"][0]["name"] == "anthropic"


@pytest.mark.asyncio
async def test_list_proxy_models_filters_and_strips_prefix(monkeypatch):
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {"id": "blm-openai/gpt-4o"},
                    {"id": "blm-other/gpt-4o"},
                    {"id": "blm-openai/gpt-4o-mini"},
                    {"id": "blm-openai/gpt-4o"},
                ]
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            return None

        async def get(self, *_args, **_kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("app.services.proxy_supervisor.httpx.AsyncClient", FakeClient)

    class Stub:
        async def ensure_started(self):
            return ("127.0.0.1", 1234, "client-key")

    models = await ProxySupervisor.list_proxy_models(Stub(), "blm-openai")
    assert models == ["gpt-4o", "gpt-4o-mini"]


@pytest.mark.asyncio
async def test_list_proxy_models_returns_empty_on_failure(monkeypatch):
    class Stub:
        async def ensure_started(self):
            raise RuntimeError("not running")

    assert await ProxySupervisor.list_proxy_models(Stub(), "blm-openai") == []

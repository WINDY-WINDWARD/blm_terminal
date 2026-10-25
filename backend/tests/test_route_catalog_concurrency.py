"""Tests for route_catalog concurrency, timeouts, and sidecar neutrality."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.route_catalog import (
    _build_model_warning,
    _fetch_live_models,
    _filter_chat_models,
    _persist_cached_models,
    _resolve_oauth_route_models,
    get_all_route_catalogs,
    get_route_models,
    is_chat_capable_model,
)


@pytest.fixture
async def test_db(tmp_path):
    db_file = tmp_path / "test_catalog_concurrency.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_all_route_catalogs_fetches_concurrently(test_db, monkeypatch):
    """Prove that OAuth routes are queried concurrently: two 0.2s fetches take < 0.35s total."""
    async with test_db() as session:
        route1 = AIProviderRoute(
            id="oauth:provider1",
            display_label="Provider 1",
            provider="provider1",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({}),
        )
        route2 = AIProviderRoute(
            id="oauth:provider2",
            display_label="Provider 2",
            provider="provider2",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({}),
        )
        session.add_all([route1, route2])
        cred1 = AIProviderCredential(
            id="c1",
            route_id="oauth:provider1",
            kind="oauth",
            vault_reference="vault:c1",
            proxy_credential_name="cred-1",
            enabled=True,
            status="active",
        )
        cred2 = AIProviderCredential(
            id="c2",
            route_id="oauth:provider2",
            kind="oauth",
            vault_reference="vault:c2",
            proxy_credential_name="cred-2",
            enabled=True,
            status="active",
        )
        session.add_all([cred1, cred2])
        await session.commit()

        async def slow_fetch(route, credentials, live_timeout=5.0):
            await asyncio.sleep(0.2)
            return [f"model-{route.provider}"], False, False

        monkeypatch.setattr("app.services.route_catalog._fetch_live_models", slow_fetch)

        # Mock is_ai_provider_configured so direct routes don't query SQLite repeatedly
        monkeypatch.setattr("app.services.ai_config.is_ai_provider_configured", AsyncMock(return_value=False))

        start = time.perf_counter()
        routes_out, warnings_out = await get_all_route_catalogs(session=session)
        elapsed = time.perf_counter() - start

        # Concurrently, 2 x 0.2s takes ~0.2s (< 0.35s), whereas serial would take >= 0.4s
        assert elapsed < 0.35, f"Expected wall time < 0.35s, got {elapsed:.3f}s"
        assert len(routes_out) == 2
        assert routes_out[0]["route_id"] == "oauth:provider1"
        assert routes_out[1]["route_id"] == "oauth:provider2"
        assert warnings_out == []


@pytest.mark.asyncio
async def test_get_all_route_catalogs_never_calls_ensure_started(test_db, monkeypatch):
    """Monkeypatch ensure_started to raise; get_all_route_catalogs must succeed without calling it."""
    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(side_effect=RuntimeError("ensure_started must NOT be called on read-only catalog path"))
    mock_supervisor.is_running = False
    monkeypatch.setattr("app.services.route_catalog.get_proxy_supervisor", lambda: mock_supervisor)

    async with test_db() as session:
        route = AIProviderRoute(
            id="oauth:provider-test",
            display_label="Provider Test",
            provider="test",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({}),
        )
        session.add(route)
        cred = AIProviderCredential(
            id="c-test",
            route_id="oauth:provider-test",
            kind="oauth",
            vault_reference="vault:test",
            proxy_credential_name="cred-test",
            enabled=True,
            status="active",
        )
        session.add(cred)
        await session.commit()

        routes_out, warnings_out = await get_all_route_catalogs(session=session)

        # supervisor is not running, so sidecar calls are skipped, warning is produced
        assert mock_supervisor.ensure_started.call_count == 0
        assert len(routes_out) == 0
        assert len(warnings_out) == 1
        assert warnings_out[0]["code"] == "model_list_error"


@pytest.mark.asyncio
async def test_get_all_route_catalogs_total_timeout_budget_enforced(test_db, monkeypatch):
    """Fetches exceeding total_timeout degrade to model_list_timeout warnings without raising."""
    async with test_db() as session:
        route = AIProviderRoute(
            id="oauth:hanging-provider",
            display_label="Hanging Provider",
            provider="hanging",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({}),
        )
        session.add(route)
        cred = AIProviderCredential(
            id="c-hang",
            route_id="oauth:hanging-provider",
            kind="oauth",
            vault_reference="vault:hang",
            proxy_credential_name="cred-hang",
            enabled=True,
            status="active",
        )
        session.add(cred)
        await session.commit()

        async def hanging_fetch(route, credentials, live_timeout=5.0):
            await asyncio.sleep(5.0)
            return ["unreachable-model"], False, False

        monkeypatch.setattr("app.services.route_catalog._fetch_live_models", hanging_fetch)

        start = time.perf_counter()
        routes_out, warnings_out = await get_all_route_catalogs(session=session, total_timeout=0.1)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5
        assert len(routes_out) == 0
        assert len(warnings_out) == 1
        assert warnings_out[0]["code"] == "model_list_timeout"
        assert warnings_out[0]["route_id"] == "oauth:hanging-provider"


def test_warning_precedence():
    """Verify warning precedence: timeout outranks error outranks unavailable."""
    w1 = _build_model_warning("r1", any_timeout=True, any_error=True)
    assert w1["code"] == "model_list_timeout"

    w2 = _build_model_warning("r2", any_timeout=False, any_error=True)
    assert w2["code"] == "model_list_error"

    w3 = _build_model_warning("r3", any_timeout=False, any_error=False)
    assert w3["code"] == "model_list_unavailable"


@pytest.mark.asyncio
async def test_get_all_route_catalogs_preserves_database_order(test_db, monkeypatch):
    """OAuth and endpoint routes must be emitted in database order, not grouped by kind."""
    from sqlalchemy import select as sa_select

    async with test_db() as session:
        endpoint_route = AIProviderRoute(
            id="endpoint:custom",
            display_label="Custom Endpoint",
            provider="custom",
            kind="endpoint",
            enabled=True,
            config_json=json.dumps({"models": ["m1"]}),
        )
        oauth_route = AIProviderRoute(
            id="oauth:provider-order",
            display_label="OAuth Provider",
            provider="order",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({}),
        )
        session.add_all([endpoint_route, oauth_route])
        session.add(AIProviderCredential(
            id="c-order",
            route_id="oauth:provider-order",
            kind="oauth",
            vault_reference="vault:order",
            proxy_credential_name="cred-order",
            enabled=True,
            status="active",
        ))
        await session.commit()

        db_order = [
            r.id
            for r in (await session.execute(
                sa_select(AIProviderRoute).where(AIProviderRoute.enabled == True)
            )).scalars().all()
        ]

        async def fast_fetch(route, credentials, live_timeout=5.0):
            return ["model-x"], False, False

        monkeypatch.setattr("app.services.route_catalog._fetch_live_models", fast_fetch)
        monkeypatch.setattr("app.services.ai_config.is_ai_provider_configured", AsyncMock(return_value=False))

        routes_out, _warnings = await get_all_route_catalogs(session=session)

        assert [r["route_id"] for r in routes_out] == db_order
        assert "endpoint:custom" in db_order
        assert "oauth:provider-order" in db_order


def test_filter_chat_models_drops_generated_media_ids():
    """Image-generation models can never serve a chat turn, so they are filtered out."""
    assert is_chat_capable_model("gpt-6-luna") is True
    assert is_chat_capable_model("gpt-image-1") is False
    assert is_chat_capable_model("dall-e-3") is False
    assert is_chat_capable_model("imagen-3.0-generate-001") is False
    assert _filter_chat_models(
        ["gpt-6-luna", "gpt-image-1", "dall-e-3", "gpt-image-1", "imagen-3.0"]
    ) == ["gpt-6-luna"]


@pytest.mark.asyncio
async def test_live_models_drop_image_family_and_persist_clean_cache(test_db, monkeypatch):
    """Live credential models are filtered before they are cached on the route."""
    async with test_db() as session:
        route = AIProviderRoute(
            id="oauth:codex",
            display_label="Codex",
            provider="codex",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({}),
        )
        session.add(route)
        session.add(AIProviderCredential(
            id="c-codex",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="vault:codex",
            proxy_credential_name="codex.json",
            enabled=True,
            status="active",
        ))
        await session.commit()

        mock_supervisor = MagicMock()
        mock_supervisor.is_running = True
        mock_supervisor.get_management_client = MagicMock(return_value=object())
        monkeypatch.setattr("app.services.route_catalog.get_proxy_supervisor", lambda: mock_supervisor)

        async def fake_cred_models(management, name, timeout):
            return ["gpt-6-luna", "gpt-image-1", "dall-e-3"]

        monkeypatch.setattr("app.services.route_catalog._fetch_credential_models", fake_cred_models)

        models, warning = await _resolve_oauth_route_models(route, session)

        assert models == ["gpt-6-luna"]
        assert warning is None
        await session.refresh(route)
        assert json.loads(route.config_json or "{}")["cached_models"] == ["gpt-6-luna"]


@pytest.mark.asyncio
async def test_codex_cached_fallback_filters_image_models(test_db, monkeypatch):
    """A route whose cache predates the filter still lists only chat models."""
    async with test_db() as session:
        route = AIProviderRoute(
            id="oauth:codex",
            display_label="Codex",
            provider="codex",
            kind="oauth",
            enabled=True,
            config_json=json.dumps({"cached_models": ["gpt-6-luna", "gpt-image-1"]}),
        )
        session.add(route)
        session.add(AIProviderCredential(
            id="c-codex-cache",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="vault:codex",
            proxy_credential_name="codex.json",
            enabled=True,
            status="active",
        ))
        await session.commit()

        mock_supervisor = MagicMock()
        mock_supervisor.is_running = False
        monkeypatch.setattr("app.services.route_catalog.get_proxy_supervisor", lambda: mock_supervisor)

        assert await get_route_models("oauth:codex", session=session) == ["gpt-6-luna"]


@pytest.mark.asyncio
async def test_endpoint_with_only_image_models_is_hidden(test_db, monkeypatch):
    """An endpoint whose stored models are all image generators produces no catalog entry."""
    async with test_db() as session:
        session.add(AIProviderRoute(
            id="endpoint:image-only",
            display_label="Image Only",
            provider="custom",
            kind="endpoint",
            enabled=True,
            config_json=json.dumps({"models": ["gpt-image-1", "dall-e-3"]}),
        ))
        await session.commit()

        monkeypatch.setattr("app.services.ai_config.is_ai_provider_configured", AsyncMock(return_value=False))

        routes_out, _warnings = await get_all_route_catalogs(session=session)

        assert [r["route_id"] for r in routes_out] == []


@pytest.mark.asyncio
async def test_direct_route_catalog_filters_image_models(test_db, monkeypatch):
    """Direct routes may also expose generator models; the catalog must drop them."""
    from types import SimpleNamespace

    import app.services.direct_proxy_routes as direct_routes

    spec = SimpleNamespace(
        id="direct:openai",
        display_name="OpenAI",
        provider="openai",
        models=["gpt-6-luna", "gpt-image-1", "dall-e-3"],
        supported=True,
    )
    monkeypatch.setattr(direct_routes, "SUPPORTED_ROUTE_IDS", ["direct:openai"])
    monkeypatch.setattr(direct_routes, "get_direct_route", lambda route_id: spec)
    monkeypatch.setattr(direct_routes, "direct_proxy_prefix", lambda route_id: "blm-direct-openai")
    monkeypatch.setattr("app.services.ai_config.is_ai_provider_configured", AsyncMock(return_value=True))

    async with test_db() as session:
        routes_out, _warnings = await get_all_route_catalogs(session=session)

    assert [r["route_id"] for r in routes_out] == ["direct:openai"]
    assert [m["label"] for m in routes_out[0]["models"]] == ["gpt-6-luna"]

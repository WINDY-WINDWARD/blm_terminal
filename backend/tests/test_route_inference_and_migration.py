"""Tests for route-aware inference, model catalog, and legacy migration (Task 3)."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.ai_chat import ChatSession
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.models.system_config import SystemConfig
from app.services.ai_config import (
    get_configured_verifier_model,
    get_dynamic_ai_api_key,
    get_dynamic_ai_provider,
    is_ai_provider_configured,
)
from app.services.legacy_migration import (
    migrate_legacy_antigravity_tokens,
    migrate_legacy_codex_tokens,
    migrate_legacy_providers_and_models,
    run_all_legacy_migrations,
)
from app.services.llm_provider import (
    clear_proxy_traces,
    get_proxy_traces,
    record_proxy_trace,
    stream_chat_completion,
)
from app.services.route_registry import (
    compute_oauth_proxy_prefix,
    format_route_model_id,
    map_legacy_model_to_route,
    parse_route_model_id,
    resolve_active_route_id,
    seed_oauth_routes,
)


@pytest.fixture
async def async_db(tmp_path):
    db_file = tmp_path / "test_migration.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await seed_oauth_routes(session)
    try:
        yield session_factory
    finally:
        await engine.dispose()


class MockVault:
    def __init__(self):
        self._secrets = {}
        self.fail_mode = False

    async def get_secret(self, key: str):
        return self._secrets.get(key)

    async def set_secret(self, key: str, val):
        if self.fail_mode:
            raise RuntimeError("Vault write error")
        self._secrets[key] = val

    async def set_oauth_auth(self, provider_or_route: str, data):
        if self.fail_mode:
            raise RuntimeError("Vault write error")
        key = f"oauth_auth:{provider_or_route}"
        self._secrets[key] = data

    async def get_oauth_auth(self, provider_or_route: str):
        key = f"oauth_auth:{provider_or_route}"
        return self._secrets.get(key)


def test_route_model_parsing_and_proxy_model_construction():
    route_id, upstream = parse_route_model_id("blm:oauth:codex/gpt-4o")
    assert route_id == "oauth:codex"
    assert upstream == "gpt-4o"

    route_id, upstream = parse_route_model_id("blm:endpoint:custom-uuid-123/meta-llama/Llama-3-70b-instruct")
    assert route_id == "endpoint:custom-uuid-123"
    assert upstream == "meta-llama/Llama-3-70b-instruct"

    prefix = compute_oauth_proxy_prefix("oauth:codex")
    proxy_model = f"{prefix}/{upstream}"
    assert proxy_model.startswith("blm-")
    assert proxy_model.endswith("/meta-llama/Llama-3-70b-instruct")

    with pytest.raises(ValueError):
        parse_route_model_id("invalid-no-blm-prefix")
    with pytest.raises(ValueError):
        parse_route_model_id("blm:no-slash-route")


@pytest.mark.asyncio
async def test_legacy_codex_token_migration_success(async_db):
    vault = MockVault()
    async with async_db() as session:
        session.add(SystemConfig(key="ai.codex_access_token", value="legacy-access-token-jwt"))
        session.add(SystemConfig(key="ai.codex_refresh_token", value="legacy-refresh-token"))
        await session.commit()

        imported = await migrate_legacy_codex_tokens(vault, session)
        assert imported is True

        vault_data = await vault.get_oauth_auth("codex")
        assert vault_data is not None
        assert vault_data["access_token"] == "legacy-access-token-jwt"
        assert vault_data["refresh_token"] == "legacy-refresh-token"

        cred = (
            await session.execute(
                select(AIProviderCredential).where(AIProviderCredential.route_id == "oauth:codex")
            )
        ).scalar_one_or_none()
        assert cred is not None
        assert cred.enabled is True
        assert cred.status == "active"

        cfg_acc = (
            await session.execute(select(SystemConfig).where(SystemConfig.key == "ai.codex_access_token"))
        ).scalar_one_or_none()
        cfg_ref = (
            await session.execute(select(SystemConfig).where(SystemConfig.key == "ai.codex_refresh_token"))
        ).scalar_one_or_none()
        assert cfg_acc is None or not cfg_acc.value
        assert cfg_ref is None or not cfg_ref.value


@pytest.mark.asyncio
async def test_legacy_codex_token_migration_failure_preserves_db_tokens(async_db):
    vault = MockVault()
    vault.fail_mode = True

    async with async_db() as session:
        session.add(SystemConfig(key="ai.codex_access_token", value="precious-token"))
        session.add(SystemConfig(key="ai.codex_refresh_token", value="precious-refresh"))
        await session.commit()

        with pytest.raises(Exception):
            await migrate_legacy_codex_tokens(vault, session)

        cfg_acc = (
            await session.execute(select(SystemConfig).where(SystemConfig.key == "ai.codex_access_token"))
        ).scalar_one_or_none()
        assert cfg_acc is not None and cfg_acc.value == "precious-token"


@pytest.mark.asyncio
async def test_legacy_antigravity_token_migration_success(async_db, tmp_path):
    vault = MockVault()
    creds_file = tmp_path / ".ag_credentials.json"
    creds_file.write_text(
        json.dumps({"refresh_token": "ag-refresh-token-xyz", "access_token": "ag-acc"}),
        encoding="utf-8",
    )

    async with async_db() as session:
        success, reason = await migrate_legacy_antigravity_tokens(vault, session, creds_path=creds_file)
        assert success is True
        assert reason == "imported"

        vault_data = await vault.get_oauth_auth("antigravity")
        assert vault_data is not None
        assert vault_data["refresh_token"] == "ag-refresh-token-xyz"

        cred = (
            await session.execute(
                select(AIProviderCredential).where(AIProviderCredential.route_id == "oauth:antigravity")
            )
        ).scalar_one_or_none()
        assert cred is not None
        assert cred.enabled is True

        assert not creds_file.exists()


@pytest.mark.asyncio
async def test_legacy_antigravity_token_migration_insufficient_leaves_file_untouched(async_db, tmp_path):
    vault = MockVault()
    creds_file = tmp_path / ".ag_credentials.json"
    invalid_payload = json.dumps({"access_token": "no-refresh-here"})
    creds_file.write_text(invalid_payload, encoding="utf-8")

    async with async_db() as session:
        success, reason = await migrate_legacy_antigravity_tokens(vault, session, creds_path=creds_file)
        assert success is False
        assert reason == "relogin_required"

        assert creds_file.exists()
        assert creds_file.read_text(encoding="utf-8") == invalid_payload


@pytest.mark.asyncio
async def test_legacy_providers_and_models_migration(async_db):
    async with async_db() as session:
        session.add(SystemConfig(key="ai.provider", value="gemini"))
        session.add(SystemConfig(key="ai.hunter_model", value="gemini-3.8-flash-high"))
        session.add(SystemConfig(key="ai.verifier_model", value="gemini-3.8-flash-low"))
        chat_sess = ChatSession(
            id=101,
            title="Test Chat",
            model="gemini-3.8-flash-medium",
            user_id="1",
        )
        session.add(chat_sess)
        await session.commit()

        await migrate_legacy_providers_and_models(session)

        prov = (
            await session.execute(select(SystemConfig.value).where(SystemConfig.key == "ai.provider"))
        ).scalar_one()
        assert prov == "oauth:antigravity"

        hunter = (
            await session.execute(select(SystemConfig.value).where(SystemConfig.key == "ai.hunter_model"))
        ).scalar_one()
        assert hunter == "blm:oauth:antigravity/gemini-3.8-flash-high"

        verifier = (
            await session.execute(select(SystemConfig.value).where(SystemConfig.key == "ai.verifier_model"))
        ).scalar_one()
        assert verifier == "blm:oauth:antigravity/gemini-3.8-flash-low"

        updated_sess = (
            await session.execute(select(ChatSession).where(ChatSession.id == 101))
        ).scalar_one()
        assert updated_sess.model == "blm:oauth:antigravity/gemini-3.8-flash-medium"


@pytest.mark.asyncio
async def test_proxy_loop_url_and_session_headers(monkeypatch):
    clear_proxy_traces()

    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    captured_requests = []

    class MockStreamResponse:
        def __init__(self):
            self.status_code = 200
            self.headers = {"X-CPA-TRACE-ID": "cpa-trace-uuid-12345"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "Hello proxy"}, "finish_reason": "stop"}]}'
            yield 'data: [DONE]'

    mock_client = MagicMock()

    def fake_stream(method, url, json=None, headers=None, **kwargs):
        captured_requests.append({"method": method, "url": url, "json": json, "headers": headers})
        return MockStreamResponse()

    mock_client.stream = fake_stream

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: mock_client)
    monkeypatch.setattr(
        "app.services.llm_provider.resolve_active_route_id",
        AsyncMock(return_value="oauth:codex"),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.get_route_models",
        AsyncMock(return_value=["gpt-4o"]),
    )

    chunks = []
    async def noop_executor(tool_calls):
        return [], []

    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "Hi"}],
        model="blm:oauth:codex/gpt-4o",
        tools=[],
        tool_executor=noop_executor,
        session_id="chat-session-42",
    ):
        chunks.append(chunk)

    assert any("Hello proxy" in c for c in chunks)
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req["url"] == "http://127.0.0.1:8317/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer test-client-key"
    assert req["headers"]["X-Session-Id"] == "chat-session-42"

    expected_prefix = compute_oauth_proxy_prefix("oauth:codex")
    assert req["json"]["model"] == f"{expected_prefix}/gpt-4o"

    traces = get_proxy_traces()
    assert len(traces) >= 1
    latest = traces[-1]
    assert latest["trace_id"] == "cpa-trace-uuid-12345"
    assert latest["route_id"] == "oauth:codex"
    assert latest["session_id"] == "chat-session-42"
    assert "Hello proxy" not in str(latest)
    assert "test-client-key" not in str(latest)


@pytest.mark.asyncio
async def test_proxy_loop_suppresses_429_retry(monkeypatch):
    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    attempts = 0

    class Mock429Response:
        def __init__(self):
            self.status_code = 429
            self.headers = {"retry-after": "10"}

        async def __aenter__(self):
            nonlocal attempts
            attempts += 1
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aread(self):
            return b'{"error": "Rate limited by upstream"}'

    mock_client = MagicMock()
    mock_client.stream = lambda method, url, json=None, headers=None, **kwargs: Mock429Response()

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: mock_client)
    monkeypatch.setattr(
        "app.services.llm_provider.resolve_active_route_id",
        AsyncMock(return_value="oauth:codex"),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.get_route_models",
        AsyncMock(return_value=["gpt-4o"]),
    )

    events = []
    async def noop_executor(tool_calls):
        return [], []

    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "Hi"}],
        model="blm:oauth:codex/gpt-4o",
        tools=[],
        tool_executor=noop_executor,
    ):
        events.append(json.loads(chunk))

    assert attempts == 1
    assert any(e.get("type") == "error" for e in events)


@pytest.mark.asyncio
async def test_direct_provider_does_not_call_proxy(monkeypatch):
    mock_supervisor = MagicMock()
    mock_supervisor.ensure_started = AsyncMock()

    captured_requests = []

    class MockDirectStream:
        def __init__(self):
            self.status_code = 200
            self.headers = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aread(self):
            return b""

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "Direct response"}, "finish_reason": "stop"}]}'
            yield 'data: [DONE]'

    mock_client = MagicMock()
    mock_client.stream = lambda method, url, json=None, headers=None, **kwargs: (
        captured_requests.append({"url": url, "headers": headers}) or MockDirectStream()
    )

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_supervisor)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: mock_client)
    monkeypatch.setattr("app.services.llm_provider.get_dynamic_ai_api_key", AsyncMock(return_value="sk-fake-openai"))
    monkeypatch.setattr(
        "app.services.llm_provider.resolve_active_route_id",
        AsyncMock(return_value="direct:openai"),
    )
    monkeypatch.setattr(
        "app.services.llm_provider.get_route_models",
        AsyncMock(return_value=["gpt-4o-mini"]),
    )

    async def noop_executor(tool_calls):
        return [], []

    chunks = []
    async for chunk in stream_chat_completion(
        messages=[{"role": "user", "content": "Hi"}],
        model="blm:direct:openai/gpt-4o-mini",
        tools=[],
        tool_executor=noop_executor,
    ):
        chunks.append(chunk)

    mock_supervisor.ensure_started.assert_not_called()
    assert len(captured_requests) == 1
    assert captured_requests[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured_requests[0]["headers"]["Authorization"] == "Bearer sk-fake-openai"


@pytest.mark.asyncio
async def test_post_provider_models_no_key_in_urls(monkeypatch):
    import main
    monkeypatch.setattr(main, "LAUNCH_TOKEN", "test-token")

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        get_resp = await client.get(
            "/api/ai/provider-models?provider=openai&api_key=sk-secret-query-param",
            headers={"x-blm-token": "test-token"},
        )
        assert get_resp.status_code == 405

        post_resp = await client.post(
            "/api/ai/provider-models",
            json={"provider": "gemini", "api_key": ""},
            headers={"x-blm-token": "test-token"},
        )
        assert post_resp.status_code == 200
        models = post_resp.json()
        assert isinstance(models, list)
        assert any("gemini-3.8-flash" in m.get("id", "") for m in models)
@pytest.mark.asyncio
async def test_chat_models_and_ai_status(monkeypatch, async_db):
    import main
    monkeypatch.setattr(main, "LAUNCH_TOKEN", "test-token")
    from app.services.ai_config import get_dynamic_ai_provider

    # Set active route to oauth:codex with cached models in route row
    async with async_db() as session:
        route = (
            await session.execute(
                select(AIProviderRoute).where(AIProviderRoute.id == "oauth:codex")
            )
        ).scalar_one()
        route.config_json = json.dumps({"cached_models": ["gpt-4o", "gpt-4o-mini"]})
        await session.commit()

    monkeypatch.setattr("app.database.AsyncSessionLocal", async_db)
    monkeypatch.setattr("app.routers.ai_chat.AsyncSessionLocal", async_db)
    monkeypatch.setattr("app.services.ai_config.get_dynamic_ai_provider", AsyncMock(return_value="oauth:codex"))
    monkeypatch.setattr("app.routers.ai_chat.get_dynamic_ai_provider", AsyncMock(return_value="oauth:codex"))
    monkeypatch.setattr("app.services.route_registry.resolve_active_route_id", AsyncMock(return_value="oauth:codex"))
    monkeypatch.setattr("app.routers.ai_chat.resolve_active_route_id", AsyncMock(return_value="oauth:codex"))

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GET /api/ai/chat/models
        models_resp = await client.get("/api/ai/chat/models", headers={"x-blm-token": "test-token"})
        assert models_resp.status_code == 200
        models = models_resp.json()
        assert len(models) >= 2
        # Must be route-qualified!
        for m in models:
            assert m["id"].startswith("blm:oauth:codex/")
            assert not m["id"].startswith("blm:direct:")

        # GET /api/ai/status
        status_resp = await client.get("/api/ai/status", headers={"x-blm-token": "test-token"})
        assert status_resp.status_code == 200
        data = status_resp.json()
        assert data["provider"] == "oauth:codex"
        assert "route_health" in data


@pytest.mark.asyncio
async def test_startup_order_regression_table_creation_before_migration(tmp_path, monkeypatch):
    """Prove that legacy migration fails if run before table creation on a fresh DB, and succeeds after."""
    import sqlite3
    import inspect
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.services.legacy_migration import run_all_legacy_migrations

    db_path = tmp_path / "fresh_unmigrated.db"
    # Create empty sqlite file without provider tables
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE system_config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO system_config VALUES ('ai.codex_access_token', 'test.jwt.token')")
    conn.commit()
    conn.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    vault = MockVault()

    # 1. Before table creation: legacy migration fails to insert into ai_provider_credentials
    async with SessionLocal() as session:
        results = await run_all_legacy_migrations(vault, session)
        assert "codex_error" in results
        assert "no such table" in results["codex_error"].lower()

    # 2. Verify main.py lifespan ordering: _ensure_ai_provider_routes is called before run_all_legacy_migrations
    import main
    lifespan_source = inspect.getsource(main.lifespan)
    pos_table_setup = lifespan_source.find("_ensure_ai_provider_routes")
    pos_legacy_mig = lifespan_source.find("run_all_legacy_migrations")
    assert pos_table_setup != -1
    assert pos_legacy_mig != -1
    assert pos_table_setup < pos_legacy_mig, "Table creation/route seeding must precede legacy migrations!"

    await engine.dispose()


@pytest.mark.asyncio
async def test_chat_models_registered_exactly_once():
    """Prove that /api/ai/chat/models is registered exactly once in the router and OpenAPI."""
    from app.routers.ai_chat import router
    import main

    matching = [
        r for r in router.routes
        if getattr(r, "path", "") == "/ai/chat/models" and "GET" in getattr(r, "methods", set())
    ]
    assert len(matching) == 1, f"Expected exactly 1 GET /ai/chat/models route in router, found {len(matching)}"

    openapi = main.app.openapi()
    assert "/api/ai/chat/models" in openapi.get("paths", {})
    assert "get" in openapi["paths"]["/api/ai/chat/models"]


def test_post_provider_models_signature_and_openapi_has_no_query_key():
    """Prove get_provider_models has only body payload and no api_key query parameter."""
    import inspect
    from app.routers.ai_chat import get_provider_models
    import main

    sig = inspect.signature(get_provider_models)
    params = list(sig.parameters.keys())
    assert params == ["payload"], f"Expected only ['payload'], got {params}"

    openapi = main.app.openapi()
    post_op = openapi.get("paths", {}).get("/api/ai/provider-models", {}).get("post", {})
    parameters = post_op.get("parameters", [])
    query_param_names = [p.get("name") for p in parameters if p.get("in") == "query"]
    assert "api_key" not in query_param_names, "api_key must not be exposed as a query parameter in OpenAPI"


@pytest.mark.asyncio
async def test_legacy_providers_migration_respects_settings_when_db_provider_absent(async_db, monkeypatch):
    """Prove that when ai.provider is absent from SystemConfig, settings.ai_provider is respected without writing a spurious row."""
    from sqlalchemy import delete
    from app.services.legacy_migration import migrate_legacy_providers_and_models
    from app.models.system_config import SystemConfig
    from app.config import settings

    monkeypatch.setattr(settings, "ai_provider", "openai")

    async with async_db() as session:
        # Ensure no ai.provider row exists
        await session.execute(delete(SystemConfig).where(SystemConfig.key == "ai.provider"))
        # Set a hunter model that should be route-qualified to direct:openai
        await session.merge(SystemConfig(key="ai.hunter_model", value="gpt-4o"))
        await session.commit()

        await migrate_legacy_providers_and_models(session)

        # 1. ai.provider must NOT be written spuriously to SystemConfig
        prov_res = await session.execute(select(SystemConfig).where(SystemConfig.key == "ai.provider"))
        assert prov_res.scalar_one_or_none() is None

        # 2. hunter model must be qualified using settings.ai_provider ("direct:openai")
        hunter_res = await session.execute(select(SystemConfig.value).where(SystemConfig.key == "ai.hunter_model"))
        hunter_val = hunter_res.scalar_one()
        assert hunter_val == "blm:direct:openai/gpt-4o"


@pytest.mark.asyncio
async def test_run_all_legacy_migrations_session_rollback_on_failure(async_db, monkeypatch):
    """Prove that a first-stage failure rolls back the session and prevents PendingRollbackError in later stages."""
    from sqlalchemy import text
    from app.services.legacy_migration import run_all_legacy_migrations

    vault = MockVault()

    # Force migrate_legacy_codex_tokens to fail with DB error
    async def failing_codex(v, session):
        await session.execute(text("SELECT * FROM non_existent_table_for_error"))

    monkeypatch.setattr("app.services.legacy_migration.migrate_legacy_codex_tokens", failing_codex)

    async with async_db() as session:
        results = await run_all_legacy_migrations(vault, session)
        assert "codex_error" in results
        assert "no such table" in results["codex_error"].lower()
        # Later stages must NOT fail with PendingRollbackError!
        assert results.get("models_migrated") is True
        assert "models_error" not in results

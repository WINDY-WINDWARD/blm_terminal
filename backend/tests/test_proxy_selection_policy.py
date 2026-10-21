"""Mocked proxy selection policy tests for OAuth priority/weight, sticky sessions, cooldowns, and traces."""

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import main
from app.database import Base, get_db
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.models.user import User
from app.services.llm_provider import (
    clear_proxy_traces,
    get_proxy_traces,
    record_proxy_trace,
    stream_chat_completion,
)
from app.services.provider_vault import ProviderVault
from app.services.proxy_supervisor import (
    ProxyManagementClient,
    ProxySupervisor,
    generate_proxy_config,
    materialize_custom_endpoints,
)
from app.services.route_registry import seed_oauth_routes
from app.auth import get_current_user, get_password_hash


class MockStreamingResponse:
    """Mocked streaming response for proxy calls."""

    def __init__(self, status_code: int, lines: list[str], headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._lines = lines
        self.headers = httpx.Headers(headers or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def aread(self) -> bytes:
        return "\n".join(self._lines).encode("utf-8")

    async def aiter_lines(self) -> AsyncGenerator[str, None]:
        for line in self._lines:
            yield line


@pytest.fixture
async def policy_test_env(tmp_path: Path):
    """Isolated test database, vault, and mocked supervisor/management client."""
    db_file = tmp_path / "test_policy.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    vault_file = tmp_path / "test_vault.enc"
    vault = ProviderVault(vault_path=vault_file, key=b"\x07" * 32)
    await vault.initialize()

    async with session_factory() as session:
        await seed_oauth_routes(session)
        admin = User(
            id=1,
            username="admin_test",
            hashed_password=get_password_hash("pass123"),
            is_admin=True,
        )
        session.add(admin)
        await session.commit()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def override_get_current_user() -> User:
        return User(id=1, username="admin_test", is_admin=True)

    mock_supervisor = ProxySupervisor(vault=vault, runtime_root=tmp_path / "runtime")
    from app.services.proxy_supervisor import SupervisorState
    mock_supervisor._state = SupervisorState.RUNNING
    mock_supervisor._process = MagicMock()
    mock_supervisor._process.poll.return_value = None
    mock_supervisor._auth_dir = tmp_path / "auth"
    mock_supervisor._auth_dir.mkdir()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    mock_mgmt = MagicMock(spec=ProxyManagementClient)
    mock_mgmt.health = AsyncMock(return_value=True)
    mock_mgmt.reset_cooldown = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.patch_config = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.get_credentials = AsyncMock(return_value=[])
    mock_mgmt.get_credential_models = AsyncMock(return_value=["gpt-4o", "gpt-4o-mini"])
    mock_supervisor._management_client = mock_mgmt
    mock_mgmt.update_credential = AsyncMock()
    mock_mgmt.refresh_credential = AsyncMock(return_value={"status": "ok"})
    mock_supervisor.sync_now = AsyncMock(return_value=0)
    mock_supervisor.reload_custom_endpoints = AsyncMock()

    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[get_current_user] = override_get_current_user

    test_token = "test-launch-token-policy"
    orig_launch_token = getattr(main, "LAUNCH_TOKEN", None)
    main.LAUNCH_TOKEN = test_token

    with (
        patch("app.routers.ai_routes.get_provider_vault", return_value=vault),
        patch("app.routers.ai_routes.get_proxy_supervisor", return_value=mock_supervisor),
    ):
        yield {
            "session_factory": session_factory,
            "vault": vault,
            "supervisor": mock_supervisor,
            "mgmt": mock_mgmt,
            "headers": {"x-blm-token": test_token},
        }

    main.LAUNCH_TOKEN = orig_launch_token
    main.app.dependency_overrides.pop(get_db, None)
    main.app.dependency_overrides.pop(get_current_user, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_oauth_account_priority_and_weight_selection(policy_test_env):
    """Verify OAuth account priority and weight updates and proxy config serialization."""
    session_factory = policy_test_env["session_factory"]
    headers = policy_test_env["headers"]
    vault = policy_test_env["vault"]

    # 1. Seed two credentials for oauth:codex
    async with session_factory() as session:
        cred1 = AIProviderCredential(
            id="cred-policy-alpha",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="oauth_auth:alpha",
            proxy_credential_name="codex-alpha",
            masked_identity="account-alpha@example.com",
            priority=2,
            weight=10,
            enabled=True,
            status="active",
        )
        cred2 = AIProviderCredential(
            id="cred-policy-beta",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="oauth_auth:beta",
            proxy_credential_name="codex-beta",
            masked_identity="account-beta@example.com",
            priority=1,
            weight=50,
            enabled=True,
            status="active",
        )
        session.add_all([cred1, cred2])
        await session.commit()

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 2. Patch Account 1 to priority 1 and weight 100
        patch_res = await client.patch(
            "/api/ai/routes/accounts/cred-policy-alpha",
            headers=headers,
            json={"priority": 1, "weight": 100, "enabled": True},
        )
        assert patch_res.status_code == 200
        data = patch_res.json()
        assert data["priority"] == 1
        assert data["weight"] == 100

        # 3. Verify in database
        async with session_factory() as session:
            stmt = select(AIProviderCredential).where(AIProviderCredential.id == "cred-policy-alpha")
            res = await session.execute(stmt)
            updated = res.scalar_one()
            assert updated.priority == 1
            assert updated.weight == 100

        # 4. Disable Account 1
        disable_res = await client.patch(
            "/api/ai/routes/accounts/cred-policy-alpha",
            headers=headers,
            json={"enabled": False},
        )
        assert disable_res.status_code == 200
        assert disable_res.json()["enabled"] is False

    # 5. Verify custom endpoint key priority and weight serialization into proxy config
    async with session_factory() as session:
        ep_route = AIProviderRoute(
            id="endpoint:uuid-policy-test",
            kind="endpoint",
            provider="custom",
            display_label="Policy Test Endpoint",
            enabled=True,
            config_json=json.dumps({
                "base_url": "https://api.test-policy.corp/v1",
                "models": ["llama-3.3-70b"],
            }),
            proxy_prefix="endpoint-uuid-policy-test",
        )
        session.add(ep_route)
        await session.commit()

        key1 = AIProviderCredential(
            id="key-policy-1",
            route_id=ep_route.id,
            kind="custom_endpoint_key",
            vault_reference="endpoint_keys:key1",
            proxy_credential_name="key-policy-1",
            masked_identity="sk-key-1",
            priority=1,
            weight=80,
            enabled=True,
            status="active",
        )
        key2 = AIProviderCredential(
            id="key-policy-2",
            route_id=ep_route.id,
            kind="custom_endpoint_key",
            vault_reference="endpoint_keys:key2",
            proxy_credential_name="key-policy-2",
            masked_identity="sk-key-2",
            priority=3,
            weight=20,
            enabled=True,
            status="active",
        )
        session.add_all([key1, key2])
        await session.commit()

    await vault.set_secret("endpoint_keys:key1", "sk-secret-key-1")
    await vault.set_secret("endpoint_keys:key2", "sk-secret-key-2")

    async with session_factory() as s:
        materialized = await materialize_custom_endpoints(vault, session=s)
        assert len(materialized) == 1
        ep_cfg = materialized[0]
        keys = ep_cfg["api-keys"]
        assert len(keys) == 2
        # Priority 1 key
        assert any(k["priority"] == 1 and k["weight"] == 80 and k["api-key"] == "sk-secret-key-1" for k in keys)
        # Priority 3 key
        assert any(k["priority"] == 3 and k["weight"] == 20 and k["api-key"] == "sk-secret-key-2" for k in keys)

        # Generate config YAML and verify priority/weight flags
        cfg_yaml = generate_proxy_config(
            host="127.0.0.1",
            port=8317,
            client_key="client-token",
            management_key="mgmt-token",
            auth_dir="/fake/auth",
            custom_endpoints=materialized,
        )
        assert "priority: 1" in cfg_yaml
        assert "weight: 80" in cfg_yaml
        assert "priority: 3" in cfg_yaml
        assert "weight: 20" in cfg_yaml


@pytest.mark.asyncio
async def test_proxy_sticky_session_headers(monkeypatch):
    """Verify that inference calls through the proxy preserve sticky X-Session-Id headers across turns."""
    clear_proxy_traces()

    captured_requests: list[dict[str, Any]] = []

    class MockProxyClient:
        def stream(self, method: str, url: str, **kwargs):
            captured_requests.append({
                "method": method,
                "url": url,
                "headers": kwargs.get("headers", {}),
            })
            lines = [
                'data: {"choices": [{"delta": {"content": "Turn response"}, "finish_reason": "stop"}]}',
                'data: [DONE]',
            ]
            return MockStreamingResponse(200, lines, {"X-CPA-TRACE-ID": "trace-sticky-123"})

    proxy_client = MockProxyClient()
    mock_sup = MagicMock()
    mock_sup.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))

    monkeypatch.setattr("app.services.llm_provider.get_proxy_supervisor", lambda: mock_sup)
    monkeypatch.setattr("app.services.llm_provider._get_shared_client", lambda: proxy_client)

    async def noop_executor(tool_calls):
        return [], []

    # Turn 1 with explicit session ID
    session_id = "user-conv-session-alpha-99"
    async for _ in stream_chat_completion(
        messages=[{"role": "user", "content": "First turn"}],
        model="blm:oauth:codex/gpt-4o",
        tools=[],
        tool_executor=noop_executor,
        session_id=session_id,
    ):
        pass

    # Turn 2 with identical session ID
    async for _ in stream_chat_completion(
        messages=[{"role": "user", "content": "Second turn"}],
        model="blm:oauth:codex/gpt-4o",
        tools=[],
        tool_executor=noop_executor,
        session_id=session_id,
    ):
        pass

    assert len(captured_requests) == 2
    assert captured_requests[0]["headers"]["X-Session-Id"] == session_id
    assert captured_requests[1]["headers"]["X-Session-Id"] == session_id

    # Turn 3 without session ID -> Auto-generates blm- prefixed session ID
    captured_requests.clear()
    async for _ in stream_chat_completion(
        messages=[{"role": "user", "content": "Turn with no session"}],
        model="blm:oauth:codex/gpt-4o",
        tools=[],
        tool_executor=noop_executor,
        session_id=None,
    ):
        pass

    assert len(captured_requests) == 1
    generated_session = captured_requests[0]["headers"]["X-Session-Id"]
    assert generated_session.startswith("blm-")


@pytest.mark.asyncio
async def test_cooldown_restore_reset_cooldown_path(policy_test_env):
    """Verify reset_cooldown path clears proxy cooldown, vault snapshot, and DB attribute."""
    session_factory = policy_test_env["session_factory"]
    vault = policy_test_env["vault"]
    mock_mgmt = policy_test_env["mgmt"]
    headers = policy_test_env["headers"]

    # 1. Create credential with cooldown
    cooldown_data = {"status": "cooling", "until": 1900000000, "reason": "Rate limited by upstream"}
    async with session_factory() as session:
        cred = AIProviderCredential(
            id="cred-cooling-test",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="oauth_auth:cooling_test",
            proxy_credential_name="codex-cooling-account",
            masked_identity="cooling-account@example.com",
            priority=1,
            weight=1,
            enabled=True,
            status="cooling",
            cooldown=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(cred)
        await session.commit()

    # 2. Store cooldown snapshot in vault
    await vault.set_cooldown_snapshot("codex-cooling-account", cooldown_data)
    assert (await vault.get_cooldown_snapshot("codex-cooling-account")) is not None

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 3. Call reset-cooldown endpoint
        res = await client.post("/api/ai/routes/accounts/cred-cooling-test/reset-cooldown", headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    # 4. Assert mock management client was invoked with the exact channel name
    mock_mgmt.reset_cooldown.assert_called_with(channel="codex-cooling-account")

    # 5. Assert vault cooldown snapshot was cleared
    assert (await vault.get_cooldown_snapshot("codex-cooling-account")) is None

    # 6. Assert DB cooldown attribute was cleared to None
    async with session_factory() as session:
        stmt = select(AIProviderCredential).where(AIProviderCredential.id == "cred-cooling-test")
        db_res = await session.execute(stmt)
        updated_cred = db_res.scalar_one()
        assert updated_cred.cooldown is None


@pytest.mark.asyncio
async def test_proxy_trace_attribution_and_diagnostics(policy_test_env):
    """Verify proxy trace header capture, attribution to route/model/session, and diagnostics redaction."""
    clear_proxy_traces()
    headers = policy_test_env["headers"]

    # 1. Simulate trace recording during inference
    record_proxy_trace(
        trace_id="cpa-trace-attr-policy-456",
        route_id="oauth:codex",
        session_id="session-trace-verify-1",
        status_code=200,
        upstream_model="gpt-4o",
        duration_ms=145.2,
    )

    # 2. Verify trace ring contents
    traces = get_proxy_traces()
    assert len(traces) >= 1
    target = next((t for t in traces if t["trace_id"] == "cpa-trace-attr-policy-456"), None)
    assert target is not None
    assert target["route_id"] == "oauth:codex"
    assert target["upstream_model"] == "gpt-4o"
    assert target["session_id"] == "session-trace-verify-1"
    assert target["status_code"] == 200
    assert target["duration_ms"] == 145.2

    # 3. Query GET /api/ai/routes/diagnostics and ensure trace is surfaced without secrets
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        diag_res = await client.get("/api/ai/routes/diagnostics", headers=headers)
        assert diag_res.status_code == 200
        data = diag_res.json()
        assert "traces" in data
        proxy_traces = data["traces"]
        assert any(t["trace_id"] == "cpa-trace-attr-policy-456" for t in proxy_traces)

        # 4. Strict redaction check: Ensure no secret keys, bearer tokens, or sensitive values leak
        dumped = json.dumps(data)
        assert "sk-" not in dumped
        assert "Bearer" not in dumped
        assert "test-client-key" not in dumped

"""Comprehensive API tests for AI provider routes, OAuth reconciliation, and custom endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
import time

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import create_access_token, get_current_user, get_password_hash
from app.config import settings
from app.database import Base, get_db
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.models.system_config import SystemConfig
from app.models.user import User
from app.models.watchlist import Watchlist
from app.services.endpoint_validator import (
    mask_api_key,
    mask_identity,
    validate_custom_endpoint_url,
)
from app.services.llm_provider import clear_proxy_traces, record_proxy_trace
from app.services.oauth_session_manager import (
    OAuthSessionManager,
    PendingOAuthSession,
    get_oauth_session_manager,
)
from app.services.provider_vault import (
    ProviderVault,
    VaultState,
    get_provider_vault,
)
from app.services.proxy_supervisor import (
    ProxySupervisor,
    get_proxy_supervisor,
    materialize_custom_endpoints,
)
from app.services.route_registry import (
    DEFAULT_ROUTE_ID,
    DIRECT_PROVIDERS,
    OAUTH_PROVIDERS,
    resolve_active_route_id,
    seed_oauth_routes,
)
import main
from main import app


def complete_oauth_file(environment, provider, identity, extra=None):
    """Simulate CLIProxyAPI v8 completing a flow: the status payload is {"status": "ok"}
    and carries no tokens, so reconciliation must read the credential file that
    appears in the sidecar auth directory."""
    payload = {
        "type": provider,
        "email": identity,
        "access_token": "test_access_token",
        "refresh_token": "test_refresh_token",
    }
    if extra:
        payload.update(extra)
    filename = provider + "-" + identity.split("@", 1)[0] + ".json"

    async def status(state):
        (environment["supervisor"].auth_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
        return {"status": "ok"}

    environment["mgmt"].get_oauth_status.side_effect = status
    return filename


@pytest.fixture
async def test_env(tmp_path: Path):
    """Set up an isolated SQLite database, test vault, and app overrides."""
    # 1. DB setup
    db_file = tmp_path / "test_ai_routes.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    # 2. Vault setup
    vault_file = tmp_path / "test_vault.enc"
    test_key = b"\x01" * 32
    vault = ProviderVault(vault_path=vault_file, key=test_key)
    await vault.initialize()

    # 3. Seed routes and user
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

    # Mock supervisor
    mock_supervisor = ProxySupervisor(vault=vault, runtime_root=tmp_path / "runtime")
    from app.services.proxy_supervisor import SupervisorState
    mock_supervisor._state = SupervisorState.RUNNING
    mock_supervisor._process = MagicMock()
    mock_supervisor._process.poll.return_value = None
    mock_supervisor._auth_dir = tmp_path / "auth"
    mock_supervisor._auth_dir.mkdir()
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))
    mock_mgmt = MagicMock()
    mock_mgmt.start_oauth = AsyncMock(return_value={
        "state": "test_state_123",
        "url": "https://auth.example.com/oauth/authorize",
        "expires_in": 900,
    })
    mock_mgmt.get_oauth_status = AsyncMock(return_value={"status": "wait"})
    mock_mgmt.cancel_oauth_session = AsyncMock(return_value={"status": "cancelled"})
    mock_mgmt.reset_cooldown = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.delete_credential = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.patch_config = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.submit_oauth_callback = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.health = AsyncMock(return_value=True)
    mock_mgmt.get_credentials = AsyncMock(return_value=[])
    mock_supervisor._management_client = mock_mgmt
    mock_mgmt.update_credential = AsyncMock()
    mock_mgmt.refresh_credential = AsyncMock(return_value={"status": "ok"})
    mock_supervisor.sync_now = AsyncMock(return_value=0)
    mock_supervisor.reload_custom_endpoints = AsyncMock()
    mock_supervisor.request_sync = MagicMock()
    mock_supervisor.stop = AsyncMock()

    oauth_mgr = OAuthSessionManager(session_factory=session_factory)

    # Overrides
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    test_token = "test-launch-token-xyz"
    orig_launch_token = getattr(main, "LAUNCH_TOKEN", None)
    main.LAUNCH_TOKEN = test_token

    with (
        patch("app.routers.ai_routes.get_provider_vault", return_value=vault),
        patch("app.services.oauth_session_manager.get_provider_vault", return_value=vault),
        patch("app.routers.ai_routes.get_proxy_supervisor", return_value=mock_supervisor),
        patch("app.services.oauth_session_manager.get_proxy_supervisor", return_value=mock_supervisor),
        patch("app.routers.ai_routes.get_oauth_session_manager", return_value=oauth_mgr),
    ):
        yield {
            "session_factory": session_factory,
            "vault": vault,
            "supervisor": mock_supervisor,
            "mgmt": mock_mgmt,
            "oauth_mgr": oauth_mgr,
            "engine": engine,
            "headers": {"x-blm-token": test_token},
        }

    main.LAUNCH_TOKEN = orig_launch_token

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_authentication_and_route_mounting(test_env, monkeypatch):
    """Verify endpoint authentication enforcement and mounting at both /api and root."""
    transport = httpx.ASGITransport(app=app)

    # 1. Without current user dependency override, verify 401 Unauthorized
    app.dependency_overrides.pop(get_current_user, None)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.get("/api/ai/routes")
        assert resp.status_code == 401

        resp_root = await client.get("/ai/routes")
        assert resp_root.status_code == 401

    # Restore current user override
    app.dependency_overrides[get_current_user] = lambda: User(id=1, username="admin_test", is_admin=True)

    # 2. When launch token is armed, verify missing/invalid x-blm-token is rejected with 401
    monkeypatch.setattr(main, "LAUNCH_TOKEN", "secret-launch-token-123")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # No header
        resp_no_token = await client.get("/api/ai/routes")
        assert resp_no_token.status_code == 401

        # Wrong header
        resp_bad_token = await client.get("/api/ai/routes", headers={"x-blm-token": "wrong"})
        assert resp_bad_token.status_code == 401

        # Correct header
        resp_ok = await client.get("/api/ai/routes", headers={"x-blm-token": "secret-launch-token-123"})
        assert resp_ok.status_code == 200

    monkeypatch.setattr(main, "LAUNCH_TOKEN", test_env["headers"]["x-blm-token"])


@pytest.mark.asyncio
async def test_list_routes_includes_oauth_and_direct(test_env, monkeypatch):
    """Verify GET /ai/routes lists OAuth routes, direct providers, and active route.

    The active route falls back to ``settings.ai_provider`` when the database has
    no override, so pin it here; otherwise a developer's ``.env.local`` changes
    the expected default and makes the suite environment-dependent.
    """
    monkeypatch.setattr(settings, "ai_provider", "aistudio")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.get("/api/ai/routes")
        assert resp.status_code == 200
        data = resp.json()

        assert "routes" in data
        assert data["active_route_id"] == DEFAULT_ROUTE_ID
        assert data["vault_state"] == "available"
        assert data["proxy_status"]["state"] == "running"

        route_ids = {r["id"] for r in data["routes"]}
        for p in OAUTH_PROVIDERS:
            assert f"oauth:{p}" in route_ids

        from app.services.direct_proxy_routes import SUPPORTED_ROUTE_IDS
        for rid in SUPPORTED_ROUTE_IDS:
            assert rid in route_ids
        assert "direct:copilot" not in route_ids
        assert "direct:claude-code" not in route_ids

        # Verify active route has is_active == True
        active_route = next(r for r in data["routes"] if r["id"] == DEFAULT_ROUTE_ID)
        assert active_route["is_active"] is True


@pytest.mark.asyncio
async def test_direct_provider_resilience_when_keyring_fails(test_env, monkeypatch):
    """Verify direct providers remain readable and usable when vault is in KEYRING_UNAVAILABLE state."""
    vault = test_env["vault"]
    vault._state = VaultState.KEYRING_UNAVAILABLE

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.get("/api/ai/routes")
        assert resp.status_code == 200
        data = resp.json()

        assert data["vault_state"] == "keyring_unavailable"
        assert "operating in degraded mode" in (data["recovery_state"] or "")

        # Direct providers remain available and have recovery_state=None
        from app.services.direct_proxy_routes import SUPPORTED_ROUTE_IDS
        direct_routes = [r for r in data["routes"] if r["kind"] == "direct"]
        assert len(direct_routes) == len(SUPPORTED_ROUTE_IDS)
        for dr in direct_routes:
            assert dr["recovery_state"] is None
            assert dr["id"] not in ("direct:copilot", "direct:claude-code")
            assert dr["proxy_prefix"] is not None
            assert dr["health"]["transport"] == "proxy"


@pytest.mark.asyncio
async def test_route_activation_and_validation(test_env):
    """Verify route activation updates SystemConfig and rejects invalid route IDs."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Activate direct provider
        resp1 = await client.post("/api/ai/routes/direct:openai/activate")
        assert resp1.status_code == 200
        assert resp1.json()["active_route_id"] == "direct:openai"

        # Check DB reflects change
        async with test_env["session_factory"]() as s:
            active = await resolve_active_route_id(s)
            assert active == "direct:openai"

        # 2. Activate OAuth provider
        resp2 = await client.post("/api/ai/routes/oauth:codex/activate")
        assert resp2.status_code == 200
        assert resp2.json()["active_route_id"] == "oauth:codex"

        # 3. Reject invalid route formats, unsupported direct routes, and non-existent providers
        bad_copilot = await client.post("/api/ai/routes/direct:copilot/activate")
        assert bad_copilot.status_code == 400
        assert "CLIProxyAPI 8.0.39 has no GitHub Copilot provider" in bad_copilot.json()["detail"]

        bad_claude_code = await client.post("/api/ai/routes/direct:claude-code/activate")
        assert bad_claude_code.status_code == 400

        bad1 = await client.post("/api/ai/routes/invalid_prefix:foo/activate")
        assert bad1.status_code == 400

        bad2 = await client.post("/api/ai/routes/oauth:non_existent_provider/activate")
        assert bad2.status_code == 400

        bad3 = await client.post("/api/ai/routes/endpoint:00000000-0000-0000-0000-000000000000/activate")
        assert bad3.status_code == 404


@pytest.mark.asyncio
async def test_route_settings_update(test_env):
    """Verify PATCH /ai/routes/settings updates global routing parameters."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        patch_payload = {
            "strategy": "round-robin",
            "session_affinity": False,
            "session_affinity_ttl": "30m",
            "request_retry": 5,
            "max_retry_credentials": 2,
            "max_retry_interval": 45,
        }
        resp = await client.patch("/api/ai/routes/settings", json=patch_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["updated_settings"]["ai.routing_strategy"] == "round-robin"
        assert data["updated_settings"]["ai.session_affinity"] == "false"
        assert data["updated_settings"]["ai.request_retry"] == "5"

        # Verify supervisor patch_config was called
        test_env["mgmt"].patch_config.assert_called_with({"routing": {
            "strategy": "round-robin",
            "session-affinity": False,
            "session-affinity-ttl": "30m",
            "retry": {"request-retry": 5, "max-retry-credentials": 2, "max-retry-interval": 45},
        }})


@pytest.mark.asyncio
async def test_custom_endpoint_url_validation_rejections(test_env):
    """Verify custom endpoint creation rejects metadata, injection, userinfo, and invalid schemes."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        invalid_cases = [
            ("http://169.254.169.254/v1", None, "cloud metadata"),
            ("http://metadata.google.internal/v1", None, "cloud metadata"),
            ("http://[fd00:ec2::254]/v1", None, "cloud metadata"),
            ("http://2852039166/v1", None, "link-local"),
            ("http://0xa9fea9fe/v1", None, "link-local"),
            ("http://user:pass@api.openai.com/v1", None, "Userinfo"),
            ("ftp://api.openai.com/v1", None, "scheme"),
            ("http://api.openai.com/v1\r\nInjected: yes", None, "control characters"),
            ("https://api.openai.com/v1", {"Bad\r\nName": "value"}, "control characters"),
            ("https://api.openai.com/v1", {"X-Custom": "val\r\nInject: yes"}, "control characters"),
        ]

        for url, headers, expected_err in invalid_cases:
            payload = {
                "display_label": "Test Bad Endpoint",
                "base_url": url,
                "headers": headers,
            }
            resp = await client.post("/api/ai/routes/endpoints", json=payload)
            assert resp.status_code == 400, f"Expected 400 for URL {url}, got {resp.status_code}: {resp.text}"
            assert expected_err.lower() in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_custom_endpoint_url_validation_warnings(test_env):
    """Verify custom endpoint creation accepts localhost and private networks with warning flags."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Localhost endpoint
        resp_local = await client.post(
            "/api/ai/routes/endpoints",
            json={
                "display_label": "Local Ollama",
                "base_url": "http://localhost:11434/v1",
            },
        )
        assert resp_local.status_code == 200
        flags = resp_local.json()["config"]["warning_flags"]
        assert "localhost_endpoint" in flags

        # 2. Private network endpoint
        resp_priv = await client.post(
            "/api/ai/routes/endpoints",
            json={
                "display_label": "Private vLLM",
                "base_url": "http://10.0.1.50:8000/v1",
            },
        )
        assert resp_priv.status_code == 200
        priv_flags = resp_priv.json()["config"]["warning_flags"]
        assert "private_network_endpoint" in priv_flags

        # 3. Public endpoint (no warning flags)
        resp_pub = await client.post(
            "/api/ai/routes/endpoints",
            json={
                "display_label": "Public Gateway",
                "base_url": "https://api.together.xyz/v1",
            },
        )
        assert resp_pub.status_code == 200
        pub_flags = resp_pub.json()["config"]["warning_flags"]
        assert pub_flags == []


@pytest.mark.asyncio
async def test_custom_endpoint_and_key_crud_lifecycle(test_env):
    """Verify custom endpoint CRUD, key CRUD, proxy materialization, and redaction."""
    transport = httpx.ASGITransport(app=app)
    vault = test_env["vault"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Create custom endpoint with headers and initial keys
        create_payload = {
            "display_label": "Custom Together AI",
            "base_url": "https://api.together.xyz/v1",
            "headers": {"X-Org-Secret": "super_secret_header_val"},
            "models": ["meta-llama/Llama-3-70b-chat-hf"],
            "keys": [
                {"api_key": "sk-together-initial-key-12345", "priority": 1, "weight": 2},
            ],
        }
        create_resp = await client.post("/api/ai/routes/endpoints", json=create_payload)
        assert create_resp.status_code == 200
        ep_data = create_resp.json()
        route_id = ep_data["id"]
        assert route_id.startswith("endpoint:")
        assert ep_data["display_label"] == "Custom Together AI"
        assert len(ep_data["keys"]) == 1
        initial_key_id = ep_data["keys"][0]["id"]

        # REDACTION CHECK: Header values and raw keys must NOT be present
        assert "super_secret_header_val" not in json.dumps(ep_data)
        assert "sk-together-initial-key-12345" not in json.dumps(ep_data)
        assert ep_data["config"]["header_names"] == ["X-Org-Secret"]
        assert ep_data["keys"][0]["masked_identity"].startswith("sk-")

        # Vault check: Secret was stored in vault
        header_val = await vault.get_endpoint_headers(route_id)
        assert header_val == {"X-Org-Secret": "super_secret_header_val"}

        # 2. Get single endpoint (GET /endpoints/{id})
        get_ep_resp = await client.get(f"/api/ai/routes/endpoints/{route_id}")
        assert get_ep_resp.status_code == 200
        assert get_ep_resp.json()["id"] == route_id

        # 3. Add second key (POST /endpoints/{id}/keys)
        add_key_resp = await client.post(
            f"/api/ai/routes/endpoints/{route_id}/keys",
            json={"api_key": "sk-together-second-key-67890", "priority": 2, "weight": 1},
        )
        assert add_key_resp.status_code == 200
        key2_data = add_key_resp.json()
        key2_id = key2_data["id"]
        assert key2_data["masked_identity"].startswith("sk-")
        assert "sk-together-second-key-67890" not in json.dumps(key2_data)

        # 4. List keys (GET /endpoints/{id}/keys)
        list_keys_resp = await client.get(f"/api/ai/routes/endpoints/{route_id}/keys")
        assert list_keys_resp.status_code == 200
        keys_list = list_keys_resp.json()
        assert len(keys_list) == 2
        key_ids = {k["id"] for k in keys_list}
        assert initial_key_id in key_ids
        assert key2_id in key_ids

        # 5. Get single key (GET /endpoints/{id}/keys/{key_id})
        get_key_resp = await client.get(f"/api/ai/routes/endpoints/{route_id}/keys/{key2_id}")
        assert get_key_resp.status_code == 200
        assert get_key_resp.json()["id"] == key2_id

        # Route scoping check: wrong endpoint_id in URL returns 404
        wrong_ep_resp = await client.get(f"/api/ai/routes/endpoints/endpoint:wrong-id/keys/{key2_id}")
        assert wrong_ep_resp.status_code == 404

        # 6. Patch key (PATCH /endpoints/{id}/keys/{key_id})
        patch_key_resp = await client.patch(
            f"/api/ai/routes/endpoints/{route_id}/keys/{key2_id}",
            json={"priority": 5, "weight": 10, "enabled": False},
        )
        assert patch_key_resp.status_code == 200
        patched_data = patch_key_resp.json()
        assert patched_data["priority"] == 5
        assert patched_data["weight"] == 10
        assert patched_data["enabled"] is False

        # 7. Update endpoint (PATCH /endpoints/{id})
        update_ep_resp = await client.patch(
            f"/api/ai/routes/endpoints/{route_id}",
            json={
                "display_label": "Together AI Updated",
                "models": ["meta-llama/Llama-3-70b-chat-hf", "mistralai/Mixtral-8x7B-Instruct-v0.1"],
            },
        )
        assert update_ep_resp.status_code == 200
        assert update_ep_resp.json()["display_label"] == "Together AI Updated"
        assert len(update_ep_resp.json()["models"]) == 2

        # 8. Check CLIProxyAPI materialization
        async with test_env["session_factory"]() as session:
            mat = await materialize_custom_endpoints(vault, session)
            assert len(mat) == 1
            entry = mat[0]
            assert entry["base-url"] == "https://api.together.xyz/v1"
            assert entry["headers"] == {"X-Org-Secret": "super_secret_header_val"}
            # Only enabled keys materialized (key2 was disabled)
            assert len(entry["api-keys"]) == 1
            assert entry["api-keys"][0]["api-key"] == "sk-together-initial-key-12345"

        # 9. Delete key (DELETE /endpoints/{id}/keys/{key_id})
        del_key_resp = await client.delete(f"/api/ai/routes/endpoints/{route_id}/keys/{key2_id}")
        assert del_key_resp.status_code == 200
        assert del_key_resp.json()["status"] == "deleted"

        # 10. Activate endpoint then delete it to verify active route resets to default
        act_resp = await client.post(f"/api/ai/routes/{route_id}/activate")
        assert act_resp.status_code == 200
        assert act_resp.json()["active_route_id"] == route_id

        del_ep_resp = await client.delete(f"/api/ai/routes/endpoints/{route_id}")
        assert del_ep_resp.status_code == 200
        assert del_ep_resp.json()["status"] == "deleted"

        # Active route has been safely restored to DEFAULT_ROUTE_ID
        async with test_env["session_factory"]() as session:
            active_after_del = await resolve_active_route_id(session)
            assert active_after_del == DEFAULT_ROUTE_ID

        # Vault secrets for this endpoint were purged
        assert await vault.get_endpoint_headers(route_id) is None


@pytest.mark.asyncio
async def test_endpoint_model_preview_refresh_test(test_env):
    """Verify endpoint model preview, model refresh, and connectivity test via proxy."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Preview is local only without network calls
        prev_resp = await client.post(
            "/api/ai/routes/endpoints/models/preview",
            json={"base_url": "https://api.openai.com/v1", "api_key": "sk-preview-key"},
        )
        assert prev_resp.status_code == 200
        assert prev_resp.json()["models"] == []
        assert "preview is local" in prev_resp.json()["notice"]

        # Create endpoint to test refresh and connectivity
        create_resp = await client.post(
            "/api/ai/routes/endpoints",
            json={"display_label": "Test Refresh EP", "base_url": "https://api.openai.com/v1"},
        )
        ep_id = create_resp.json()["id"]

        test_env["supervisor"].list_proxy_models = AsyncMock(return_value=["gpt-4o", "gpt-4o-mini"])

        # 2. Refresh via supervisor.list_proxy_models
        ref_resp = await client.post(f"/api/ai/routes/endpoints/{ep_id}/models/refresh")
        assert ref_resp.status_code == 200
        assert ref_resp.json()["models"] == ["gpt-4o", "gpt-4o-mini"]

        # 3. Test connectivity via proxy
        test_resp = await client.post(f"/api/ai/routes/endpoints/{ep_id}/test")
        assert test_resp.status_code == 200
        assert test_resp.json()["status"] == "ok"
        assert "latency_ms" in test_resp.json()
        assert test_resp.json()["models"] == ["gpt-4o", "gpt-4o-mini"]


@pytest.mark.asyncio
async def test_oauth_start_poll_cancel_expiry(test_env):
    """Verify OAuth start, polling, cancellation, and expiration behavior."""
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Start browser flow
        mgmt.start_oauth.return_value = {
            "state": "browser_state_abc",
            "url": "https://claude.ai/oauth/authorize",
            "expires_in": 300,
        }
        start_browser = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "claude", "flow": "browser"},
        )
        assert start_browser.status_code == 200
        b_data = start_browser.json()
        assert b_data["state"] == "browser_state_abc"
        assert b_data["auth_url"] == "https://claude.ai/oauth/authorize"
        assert b_data["flow"] == "browser"

        # 2. Start device flow is rejected with HTTP 400
        start_device = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "codex", "flow": "device"},
        )
        assert start_device.status_code == 400
        assert "Device flow is not supported" in start_device.json()["detail"]

        # Start browser session for subsequent poll & cancel steps
        mgmt.start_oauth.return_value = {
            "state": "device_state_def",
            "url": "https://auth.codex.example/authorize",
            "expires_in": 600,
        }
        start_pending = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "codex"},
        )
        assert start_pending.status_code == 200

        # 3. Poll pending session
        mgmt.get_oauth_status.return_value = {"status": "wait"}
        poll_resp = await client.get("/api/ai/routes/oauth/poll?state=device_state_def")
        assert poll_resp.status_code == 200
        assert poll_resp.json()["status"] == "pending"

        # 4. Cancel session
        cancel_resp = await client.post(
            "/api/ai/routes/oauth/cancel",
            json={"state": "device_state_def"},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        # Subsequent poll returns cancelled
        poll_cancelled = await client.get("/api/ai/routes/oauth/poll?state=device_state_def")
        assert poll_cancelled.status_code == 200
        assert poll_cancelled.json()["status"] == "cancelled"

        # 5. Expiration behavior: create session with past expires_at
        mgr = test_env["oauth_mgr"]
        expired_session = PendingOAuthSession(
            state="expired_state_xyz",
            provider="codex",
            flow="browser",
            replace_account_id=None,
            created_at=0.0,
            expires_at=1.0,
            status="pending",
        )
        mgr._sessions["expired_state_xyz"] = expired_session

        poll_expired = await client.get("/api/ai/routes/oauth/poll?state=expired_state_xyz")
        assert poll_expired.status_code == 200
        assert poll_expired.json()["status"] == "expired"


@pytest.mark.asyncio
async def test_oauth_reauth_identity_match_replaces_account(test_env):
    """Verify reauth replacing account on identity match preserves account ID."""
    transport = httpx.ASGITransport(app=app)
    vault = test_env["vault"]
    mgmt = test_env["mgmt"]

    # 1. Create existing account in DB and vault
    account_id = "test-reauth-account-1"
    vault_ref = "oauth_codex_test_reauth_1"
    async with test_env["session_factory"]() as s:
        cred = AIProviderCredential(
            id=account_id,
            route_id="oauth:codex",
            kind="oauth",
            vault_reference=vault_ref,
            proxy_credential_name="codex_test_reauth",
            masked_identity=mask_identity("alice@example.com"),
            priority=3,
            weight=4,
            enabled=True,
            status="active",
        )
        s.add(cred)
        await s.commit()

    await vault.set_oauth_auth(vault_ref, {"identity": "alice@example.com", "access_token": "old_token"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # Start reauth via account endpoint
        mgmt.start_oauth.return_value = {
            "state": "reauth_state_match",
            "url": "https://auth.example.com",
            "expires_in": 900,
        }
        reauth_start = await client.post(f"/api/ai/routes/accounts/{account_id}/reauth")
        assert reauth_start.status_code == 200

        # Simulate completion with MATCHING identity
        complete_oauth_file(test_env, "codex", "alice@example.com", {"access_token": "new_refreshed_token"})

        poll_resp = await client.get("/api/ai/routes/oauth/poll?state=reauth_state_match")
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        assert data["status"] == "completed"
        assert data["account_id"] == account_id
        assert data["notice"] is None

        # Verify priority and weight preserved and vault auth updated
        async with test_env["session_factory"]() as s:
            res = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
            updated_cred = res.scalar_one()
            assert updated_cred.priority == 3
            assert updated_cred.weight == 4

        updated_auth = await vault.get_oauth_auth(updated_cred.vault_reference.removeprefix("oauth_auth:"))
        assert updated_auth["access_token"] == "new_refreshed_token"


@pytest.mark.asyncio
async def test_oauth_reauth_identity_mismatch_creates_new_account_with_notice(test_env):
    """Verify reauth with different identity does NOT overwrite existing account and adds a new one with notice."""
    transport = httpx.ASGITransport(app=app)
    vault = test_env["vault"]
    mgmt = test_env["mgmt"]

    # 1. Existing account for alice
    account_id = "test-reauth-account-mismatch"
    vault_ref = "oauth_codex_mismatch_ref"
    async with test_env["session_factory"]() as s:
        cred = AIProviderCredential(
            id=account_id,
            route_id="oauth:codex",
            kind="oauth",
            vault_reference=vault_ref,
            proxy_credential_name="codex_orig",
            masked_identity=mask_identity("alice@example.com"),
            priority=2,
            weight=1,
            enabled=True,
            status="active",
        )
        s.add(cred)
        await s.commit()

    await vault.set_oauth_auth(vault_ref, {"identity": "alice@example.com", "access_token": "alice_token"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # Start reauth specifying replace_account_id
        mgmt.start_oauth.return_value = {
            "state": "reauth_state_mismatch",
            "url": "https://auth.example.com",
            "expires_in": 900,
        }
        reauth_start = await client.post(f"/api/ai/routes/accounts/{account_id}/reauth")
        assert reauth_start.status_code == 200

        # Simulate completion with MISMATCHED identity (bob logged in instead)
        complete_oauth_file(test_env, "codex", "bob@example.com", {"access_token": "bob_token"})

        poll_resp = await client.get("/api/ai/routes/oauth/poll?state=reauth_state_mismatch")
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        assert data["status"] == "completed"
        # Must NOT be alice's account ID!
        assert data["account_id"] != account_id
        assert "Reauthentication identity mismatch" in data["notice"]

        # Alice's account was preserved untouched
        async with test_env["session_factory"]() as s:
            res_alice = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
            alice_cred = res_alice.scalar_one()
            assert alice_cred.masked_identity == mask_identity("alice@example.com")

            # Bob's account exists in database
            res_bob = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == data["account_id"]))
            bob_cred = res_bob.scalar_one()
            assert bob_cred.masked_identity == mask_identity("bob@example.com")

        # Alice's vault token was NOT overwritten
        alice_auth = await vault.get_oauth_auth(vault_ref)
        assert alice_auth["access_token"] == "alice_token"


@pytest.mark.asyncio
async def test_account_patch_refresh_test_reset_remove(test_env):
    """Verify account management operations: patch, refresh, test, reset-cooldown, and remove."""
    transport = httpx.ASGITransport(app=app)
    vault = test_env["vault"]

    account_id = "test-account-ops-id"
    vault_ref = "oauth_claude_ops_ref"
    proxy_name = "claude_ops_chan"

    async with test_env["session_factory"]() as s:
        cred = AIProviderCredential(
            id=account_id,
            route_id="oauth:claude",
            kind="oauth",
            vault_reference=vault_ref,
            proxy_credential_name=proxy_name,
            masked_identity=mask_identity("operator@company.com"),
            priority=1,
            weight=1,
            enabled=True,
            status="active",
            cooldown=datetime.now(timezone.utc),
            last_redacted_error="Rate limit exceeded (429)",
        )
        s.add(cred)
        await s.commit()

    await vault.set_cooldown_snapshot(proxy_name, {"status": "cooling", "until": "2026-10-21T12:00:00Z"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Get account
        get_resp = await client.get(f"/api/ai/routes/accounts/{account_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == account_id

        # 2. Patch account
        patch_resp = await client.patch(
            f"/api/ai/routes/accounts/{account_id}",
            json={"priority": 4, "weight": 8, "enabled": False},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["priority"] == 4
        assert patch_resp.json()["weight"] == 8
        assert patch_resp.json()["enabled"] is False

        # 3. Refresh account
        ref_resp = await client.post(f"/api/ai/routes/accounts/{account_id}/refresh")
        assert ref_resp.status_code == 200

        # 4. Test account: a disabled account must not report healthy
        test_env["mgmt"].get_credentials = AsyncMock(return_value=[{"name": proxy_name, "status": "active"}])
        t_resp = await client.post(f"/api/ai/routes/accounts/{account_id}/test")
        assert t_resp.status_code == 200
        assert t_resp.json()["status"] == "error"

        # Re-enable, then the same credential must test healthy
        reenable = await client.patch(f"/api/ai/routes/accounts/{account_id}", json={"enabled": True})
        assert reenable.status_code == 200
        t_ok = await client.post(f"/api/ai/routes/accounts/{account_id}/test")
        assert t_ok.status_code == 200
        assert t_ok.json()["status"] == "ok"
        assert "latency_ms" in t_ok.json()

        # 5. Reset cooldown
        reset_resp = await client.post(f"/api/ai/routes/accounts/{account_id}/reset-cooldown")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["status"] == "ok"

        # Check DB cooldown and error were cleared
        async with test_env["session_factory"]() as s:
            res = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
            c_row = res.scalar_one()
            assert c_row.cooldown is None
            assert c_row.last_redacted_error is None

        # Check vault cooldown snapshot was purged
        assert await vault.get_cooldown_snapshot(proxy_name) is None

        # 6. Remove account
        del_resp = await client.delete(f"/api/ai/routes/accounts/{account_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"

        # Check DB row is gone
        async with test_env["session_factory"]() as s:
            del_check = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
            assert del_check.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_provider_diagnostics_bounds_and_no_secrets(test_env):
    """Verify GET /ai/routes/diagnostics bounds trace ring and contains zero raw secrets."""
    clear_proxy_traces()
    # Add dummy proxy traces
    for i in range(65):
        record_proxy_trace(
            trace_id=f"trace_{i}",
            route_id="oauth:codex",
            session_id=f"sess_{i % 3}",
            status_code=200,
            upstream_model="gpt-4o",
            duration_ms=45.2,
        )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.get("/api/ai/routes/diagnostics")
        assert resp.status_code == 200
        diag = resp.json()

        assert "active_route_id" in diag
        assert "proxy_status" in diag
        assert "vault_state" in diag
        assert "route_count" in diag
        assert "credential_count" in diag

        # Bounded traces check (ring limit is 50)
        traces = diag["traces"]
        assert len(traces) == 50
        assert traces[-1]["trace_id"] == "trace_64"

        # Zero secrets check: verify no auth token, secret key, or prompt content in response
        raw_text = json.dumps(diag).lower()
        assert "secret_key" not in raw_text
        assert "client_key" not in raw_text
        assert "management_key" not in raw_text
        assert "prompt" not in raw_text


@pytest.mark.asyncio
async def test_provider_only_vault_reset_scoping(test_env):
    """Verify POST /ai/routes/vault/reset clears only AI credentials and custom endpoints, preserving all other tables."""
    vault = test_env["vault"]
    transport = httpx.ASGITransport(app=app)

    # 1. Populate custom endpoint, credentials, and unrelated tables (User, Watchlist, SystemConfig direct keys)
    async with test_env["session_factory"]() as s:
        # Custom endpoint
        ep_route = AIProviderRoute(
            id="endpoint:custom-to-delete",
            kind="endpoint",
            provider="custom",
            display_label="Custom To Delete",
            proxy_prefix="blm-test-del",
            enabled=True,
        )
        s.add(ep_route)

        # Custom key credential
        cred = AIProviderCredential(
            id="cred-to-delete",
            route_id="endpoint:custom-to-delete",
            kind="custom_endpoint_key",
            vault_reference="endpoint_key:del:1",
            proxy_credential_name="custom_del",
            masked_identity="sk-...",
        )
        s.add(cred)

        # Set active provider to custom endpoint
        cfg_prov = SystemConfig(key="ai.provider", value="endpoint:custom-to-delete")
        s.add(cfg_prov)

        # Set direct provider API keys
        direct_key = SystemConfig(key="ai.api_key", value="direct_google_key_secret")
        s.add(direct_key)

        # Unrelated table: Watchlist
        wl = Watchlist(id=101, name="My Tech Watchlist")
        s.add(wl)

        await s.commit()

    await vault.set_secret("endpoint_key:del:1", "raw-secret-key-to-delete")
    await vault.set_endpoint_headers("endpoint:custom-to-delete", {"X-Custom": "val"})

    # 2. Call explicit provider-only vault reset
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        reset_resp = await client.post("/api/ai/routes/vault/reset")
        assert reset_resp.status_code == 200
        data = reset_resp.json()
        assert data["status"] == "reset"
        assert data["active_route_id"] == DEFAULT_ROUTE_ID

    # 3. Verify scoping in database
    async with test_env["session_factory"]() as s:
        # Credentials table is EMPTY
        creds_res = await s.execute(select(AIProviderCredential))
        assert len(creds_res.scalars().all()) == 0

        # Custom endpoints are GONE
        ep_res = await s.execute(select(AIProviderRoute).where(AIProviderRoute.kind == "endpoint"))
        assert len(ep_res.scalars().all()) == 0

        # OAuth routes were re-seeded clean
        oauth_res = await s.execute(select(AIProviderRoute).where(AIProviderRoute.kind == "oauth"))
        assert len(oauth_res.scalars().all()) == len(OAUTH_PROVIDERS)

        # Active provider was reset to default
        active_after = await resolve_active_route_id(s)
        assert active_after == DEFAULT_ROUTE_ID

        # DIRECT PROVIDER KEYS WERE PRESERVED
        direct_key_res = await s.execute(select(SystemConfig).where(SystemConfig.key == "ai.api_key"))
        assert direct_key_res.scalar_one().value == "direct_google_key_secret"

        # UNRELATED USER AND WATCHLIST TABLES WERE PRESERVED
        user_res = await s.execute(select(User).where(User.username == "admin_test"))
        assert user_res.scalar_one_or_none() is not None

        wl_res = await s.execute(select(Watchlist).where(Watchlist.id == 101))
        assert wl_res.scalar_one_or_none() is not None

    # Vault secret was cleared
    assert await vault.get_secret("endpoint_key:del:1") is None
    assert await vault.get_endpoint_headers("endpoint:custom-to-delete") is None

@pytest.mark.asyncio
async def test_oauth_callback_flow_and_zero_secret_logging(test_env, caplog):
    """Verify OAuth callback submission forwards to proxy and never logs query strings or token payloads."""
    import logging
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    # Seed pending session
    state = "callback_state_sec_test"
    secret_code = "SECRET_AUTH_CODE_XYZ123456"
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=100.0,
        expires_at=time.time() + 3600.0,
        status="pending",
    )
    mgr._sessions[state] = session

    complete_oauth_file(test_env, "codex", "callback_user@example.com", {"access_token": "SENSITIVE_OAUTH_ACCESS_TOKEN_ABC"})

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
            cb_resp = await client.post(
                f"/api/ai/routes/oauth/callback?state={state}&code={secret_code}",
            )
            assert cb_resp.status_code == 200
            data = cb_resp.json()
            assert data["status"] == "completed"
            assert data["masked_identity"] == mask_identity("callback_user@example.com")

    # Verify supervisor submit_oauth_callback was called
    mgmt.submit_oauth_callback.assert_called_with({"state": state, "code": secret_code})

    # VERIFY ZERO LOGGING of sensitive code or token in logs
    log_text = caplog.text
    assert secret_code not in log_text
    assert "SENSITIVE_OAUTH_ACCESS_TOKEN_ABC" not in log_text


# ---------------------------------------------------------------------------
# Task 4 Review Finding Regression Tests (Fix Round 1)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_oauth_add_flow_mask_collision_no_credential_loss(test_env):
    """Critical 1: Verify that when two different accounts produce colliding masks (e.g. alice@example.com
    and adam@example.com both mask to a***@example.com), the add-flow does not silently overwrite
    the existing credential in the database or vault. Both credentials must be preserved with distinct IDs.
    """
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    vault = test_env["vault"]

    # Step 1: User 'alice@example.com' authenticates via add-flow (replace_account_id=None)
    mgmt.start_oauth.return_value = {
        "state": "state_alice_collision",
        "url": "https://auth.example.com/oauth/authorize",
        "expires_in": 900,
    }
    complete_oauth_file(test_env, "codex", "alice@example.com", {"access_token": "token_alice_secret_111"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        start_alice = await client.post("/api/ai/routes/oauth/start", json={"provider": "codex", "flow": "browser"})
        assert start_alice.status_code == 200
        state_alice = start_alice.json()["state"]

        poll_alice = await client.get(f"/api/ai/routes/oauth/poll?state={state_alice}")
        assert poll_alice.status_code == 200
        alice_data = poll_alice.json()
        assert alice_data["status"] == "completed"
        alice_id = alice_data["account_id"]
        assert alice_data["masked_identity"] == "a***@example.com"

        # Verify alice in vault
        async with test_env["session_factory"]() as s:
            res = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == alice_id))
            alice_cred = res.scalar_one()
            assert alice_cred.masked_identity == "a***@example.com"

        alice_vault = await vault.get_oauth_auth(alice_cred.vault_reference.removeprefix("oauth_auth:"))
        assert alice_vault["access_token"] == "token_alice_secret_111"
        assert alice_vault["email"] == "alice@example.com"

        # Step 2: User 'adam@example.com' authenticates via add-flow (replace_account_id=None)
        # adam masks to EXACT SAME mask 'a***@example.com'
        mgmt.start_oauth.return_value = {
            "state": "state_adam_collision",
            "url": "https://auth.example.com/oauth/authorize",
            "expires_in": 900,
        }
        complete_oauth_file(test_env, "codex", "adam@example.com", {"access_token": "token_adam_secret_222"})

        start_adam = await client.post("/api/ai/routes/oauth/start", json={"provider": "codex", "flow": "browser"})
        assert start_adam.status_code == 200
        state_adam = start_adam.json()["state"]

        poll_adam = await client.get(f"/api/ai/routes/oauth/poll?state={state_adam}")
        assert poll_adam.status_code == 200
        adam_data = poll_adam.json()
        assert adam_data["status"] == "completed"
        adam_id = adam_data["account_id"]
        assert adam_data["masked_identity"] == "a***@example.com"

        # MUST BE A DIFFERENT CREDENTIAL! Not overwritten!
        assert adam_id != alice_id, "Collision caused silent overwrite of alice by adam!"

        # Step 3: Verify BOTH accounts exist in the database with their distinct vault references
        async with test_env["session_factory"]() as s:
            all_creds_res = await s.execute(
                select(AIProviderCredential).where(AIProviderCredential.route_id == "oauth:codex")
            )
            creds = all_creds_res.scalars().all()
            assert len(creds) == 2, f"Expected 2 accounts, found {len(creds)}"
            ids = {c.id for c in creds}
            assert alice_id in ids
            assert adam_id in ids

            alice_c = next(c for c in creds if c.id == alice_id)
            adam_c = next(c for c in creds if c.id == adam_id)

        # Step 4: Verify NO CREDENTIAL LOSS in vault
        alice_vault_check = await vault.get_oauth_auth(alice_c.vault_reference.removeprefix("oauth_auth:"))
        adam_vault_check = await vault.get_oauth_auth(adam_c.vault_reference.removeprefix("oauth_auth:"))

        assert alice_vault_check["access_token"] == "token_alice_secret_111"
        assert alice_vault_check["email"] == "alice@example.com"
        assert adam_vault_check["access_token"] == "token_adam_secret_222"
        assert adam_vault_check["email"] == "adam@example.com"

        # Step 5: If alice logs in again via add-flow, her raw identity matches alice_c, so it updates alice_c without creating a 3rd
        mgmt.start_oauth.return_value = {
            "state": "state_alice_repeat",
            "url": "https://auth.example.com/oauth/authorize",
            "expires_in": 900,
        }
        complete_oauth_file(test_env, "codex", "alice@example.com", {"access_token": "token_alice_secret_v2"})
        start_alice2 = await client.post("/api/ai/routes/oauth/start", json={"provider": "codex", "flow": "browser"})
        state_alice2 = start_alice2.json()["state"]
        poll_alice2 = await client.get(f"/api/ai/routes/oauth/poll?state={state_alice2}")
        assert poll_alice2.status_code == 200
        assert poll_alice2.json()["account_id"] == alice_id

        async with test_env["session_factory"]() as s:
            all_creds_res = await s.execute(
                select(AIProviderCredential).where(AIProviderCredential.route_id == "oauth:codex")
            )
            creds_after = all_creds_res.scalars().all()
            assert len(creds_after) == 2

        alice_vault_updated = await vault.get_oauth_auth(alice_c.vault_reference.removeprefix("oauth_auth:"))
        assert alice_vault_updated["access_token"] == "token_alice_secret_v2"


@pytest.mark.asyncio
async def test_oauth_poll_immediate_failure_and_redaction(test_env):
    """Important 2: Verify poll_session immediately surfaces upstream failed/error/denied states
    with redacted error messages and does not hang until TTL.
    """
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]

    # 1. Upstream returns failed with sensitive URL query params and tokens
    mgmt.start_oauth.return_value = {
        "state": "fail_state_1",
        "url": "https://auth.example.com",
        "expires_in": 900,
    }
    mgmt.get_oauth_status.return_value = {
        "status": "failed",
        "error": "access_denied",
        "error_description": "User denied consent at https://auth.com?code=SECRET123&client_secret=TOPSECRET Bearer sk-sensitive-key-999",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        start_resp = await client.post("/api/ai/routes/oauth/start", json={"provider": "claude", "flow": "browser"})
        state = start_resp.json()["state"]

        poll_resp = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        assert data["status"] == "failed"
        assert "error" in data
        assert "SECRET123" not in data["error"]
        assert "TOPSECRET" not in data["error"]
        assert "sk-sensitive-key-999" not in data["error"]

        # Polling again returns the same cached failed status immediately
        poll_again = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll_again.json()["status"] == "failed"

    # 2. Test replace account flow when upstream fails: credential error recorded
    account_id = "fail_target_account"
    async with test_env["session_factory"]() as s:
        cred = AIProviderCredential(
            id=account_id,
            route_id="oauth:claude",
            kind="oauth",
            vault_reference="vault_ref_fail_target",
            proxy_credential_name="claude_fail_test",
            masked_identity=mask_identity("victim@example.com"),
            priority=1,
            weight=1,
            enabled=True,
            status="active",
        )
        s.add(cred)
        await s.commit()

    mgmt.start_oauth.return_value = {
        "state": "fail_state_replace",
        "url": "https://auth.example.com",
        "expires_in": 900,
    }
    mgmt.get_oauth_status.return_value = {
        "status": "error",
        "error": "invalid_grant",
        "error_description": "OAuth token grant was revoked by provider",
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        start_rep = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "claude", "flow": "browser", "replace_account_id": account_id},
        )
        assert start_rep.status_code == 200
        state_rep = start_rep.json()["state"]

        poll_rep = await client.get(f"/api/ai/routes/oauth/poll?state={state_rep}")
        assert poll_rep.status_code == 200
        assert poll_rep.json()["status"] == "failed"

    # Verify credential was updated with error status and redacted error in DB
    async with test_env["session_factory"]() as s:
        res = await s.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
        updated_cred = res.scalar_one()
        assert updated_cred.status == "error"
        assert "token grant was revoked" in updated_cred.last_redacted_error


@pytest.mark.asyncio
async def test_route_settings_round_trip_and_validation(test_env):
    """Important 3 & Minor 8: Test complete PATCH -> GET round-trip for all persisted settings
    (request_retry, max_retry_credentials, max_retry_interval, strategy, affinity), and verify
    invalid strategies and out-of-bound values are rejected.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # Initial GET: defaults
        get_init = await client.get("/api/ai/routes")
        assert get_init.status_code == 200
        settings = get_init.json()["settings"]
        assert settings["strategy"] == "fill-first"
        assert settings["request_retry"] == 3
        assert settings["max_retry_credentials"] == 0
        assert settings["max_retry_interval"] == 30

        # PATCH all settings
        patch_resp = await client.patch(
            "/api/ai/routes/settings",
            json={
                "strategy": "priority",
                "session_affinity": False,
                "session_affinity_ttl": "45m",
                "request_retry": 5,
                "max_retry_credentials": 4,
                "max_retry_interval": 60,
            },
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "updated"

        # GET to verify round-trip
        get_updated = await client.get("/api/ai/routes")
        assert get_updated.status_code == 200
        s_up = get_updated.json()["settings"]
        assert s_up["strategy"] == "priority"
        assert s_up["session_affinity"] is False
        assert s_up["session_affinity_ttl"] == "45m"
        assert s_up["request_retry"] == 5
        assert s_up["max_retry_credentials"] == 4
        assert s_up["max_retry_interval"] == 60

        # Test validation rejections
        # Invalid strategy
        bad_strat = await client.patch("/api/ai/routes/settings", json={"strategy": "random_picker"})
        assert bad_strat.status_code == 422

        # Negative request_retry
        bad_retry = await client.patch("/api/ai/routes/settings", json={"request_retry": -1})
        assert bad_retry.status_code == 422

        # Out-of-bounds request_retry
        bad_retry_high = await client.patch("/api/ai/routes/settings", json={"request_retry": 999})
        assert bad_retry_high.status_code == 422

        # Out-of-bounds max_retry_credentials
        bad_cred_high = await client.patch("/api/ai/routes/settings", json={"max_retry_credentials": 100})
        assert bad_cred_high.status_code == 422

        # Negative max_retry_interval
        bad_interval = await client.patch("/api/ai/routes/settings", json={"max_retry_interval": -5})
        assert bad_interval.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_test_real_timed_check_success_and_errors(test_env):
    """Important 4: Functional endpoint test with real timed HTTP requests to a local server.
    Verifies success, HTTP error (502), and connection failure without disclosing secrets.
    """
    transport = httpx.ASGITransport(app=app)
    server_status = 200
    last_req_headers = {}

    async def handle_request(reader, writer):
        nonlocal last_req_headers
        req_line = await reader.readline()
        headers = {}
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            dec = line.decode("latin1", errors="ignore")
            if ":" in dec:
                k, v = dec.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        last_req_headers = headers

        body = b'{"data": [{"id": "local-model"}]}' if server_status == 200 else b'{"error": "Upstream unavailable"}'
        writer.write(f"HTTP/1.1 {server_status} {'OK' if server_status == 200 else 'Bad Gateway'}\r\n".encode("latin1"))
        writer.write(b"Content-Type: application/json\r\n")
        writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("latin1"))
        writer.write(body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_request, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
            # Create custom endpoint with an API key in vault
            create_resp = await client.post(
                "/api/ai/routes/endpoints",
                json={
                    "display_label": "Local Functional Test EP",
                    "base_url": base_url,
                    "keys": [{"api_key": "secret-test-key-456", "label": "Main Key"}],
                },
            )
            assert create_resp.status_code == 200
            ep_id = create_resp.json()["id"]

            test_env["supervisor"].list_proxy_models = AsyncMock(return_value=["local-model"])

            # 1. Success path
            t_resp = await client.post(f"/api/ai/routes/endpoints/{ep_id}/test")
            assert t_resp.status_code == 200
            t_data = t_resp.json()
            assert t_data["status"] == "ok"
            assert t_data["latency_ms"] >= 0.0
            assert t_data["models"] == ["local-model"]

            # 2. Proxy error path (no models returned)
            test_env["supervisor"].list_proxy_models = AsyncMock(return_value=[])
            t_err = await client.post(f"/api/ai/routes/endpoints/{ep_id}/test")
            assert t_err.status_code == 200
            err_data = t_err.json()
            assert err_data["status"] == "error"
            assert "No models returned by proxy" in err_data["error"]
            assert err_data["latency_ms"] >= 0.0

            # 3. Supervisor exception path
            test_env["supervisor"].list_proxy_models = AsyncMock(side_effect=RuntimeError("Proxy down"))
            t_dead = await client.post(f"/api/ai/routes/endpoints/{ep_id}/test")
            assert t_dead.status_code == 200
            dead_data = t_dead.json()
            assert dead_data["status"] == "error"
            assert "Proxy test failed" in dead_data["error"]
            assert "secret-test-key-456" not in str(dead_data)
    finally:
        if server:
            server.close()
            await server.wait_closed()


@pytest.mark.asyncio
async def test_account_test_healthy_and_unavailable_paths(test_env):
    """Important 4: Functional account test verifying supervisor health and proxy credential status."""
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    account_id = "test-health-acc"
    proxy_name = "claude_health_pname"

    async with test_env["session_factory"]() as s:
        cred = AIProviderCredential(
            id=account_id,
            route_id="oauth:claude",
            kind="oauth",
            vault_reference="vault_ref_health",
            proxy_credential_name=proxy_name,
            masked_identity=mask_identity("tester@company.com"),
            priority=1,
            weight=1,
            enabled=True,
            status="active",
        )
        s.add(cred)
        await s.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Healthy path
        mgmt.health = AsyncMock(return_value=True)
        mgmt.get_credentials = AsyncMock(return_value=[{"name": proxy_name, "status": "active"}])
        resp_ok = await client.post(f"/api/ai/routes/accounts/{account_id}/test")
        assert resp_ok.status_code == 200
        assert resp_ok.json()["status"] == "ok"
        assert resp_ok.json()["proxy_status"] == "active"
        assert resp_ok.json()["latency_ms"] >= 0.0

        # 2. Credential error in proxy (cooldown)
        mgmt.get_credentials = AsyncMock(return_value=[{"name": proxy_name, "status": "cooldown"}])
        resp_cool = await client.post(f"/api/ai/routes/accounts/{account_id}/test")
        assert resp_cool.status_code == 200
        assert resp_cool.json()["status"] == "error"
        assert "cooldown" in resp_cool.json()["error"]

        # 3. Proxy unhealthy / unreachable
        mgmt.health = AsyncMock(return_value=False)
        resp_unhealthy = await client.post(f"/api/ai/routes/accounts/{account_id}/test")
        assert resp_unhealthy.status_code == 200
        assert resp_unhealthy.json()["status"] == "error"
        assert "unhealthy" in resp_unhealthy.json()["error"]


@pytest.mark.asyncio
async def test_endpoint_model_refresh_authenticated_and_supervisor_reload(test_env, caplog):
    """Important 5: Verify model refresh attaches the enabled endpoint key from vault as Bearer auth,
    calls supervisor.reload_custom_endpoints() after persisting models, and leaks zero secrets in logs.
    """
    import logging
    transport = httpx.ASGITransport(app=app)
    base_url = "https://custom-ep.example.com/v1"
    secret_key = "secret-auth-key-super-confidential"

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
            create_resp = await client.post(
                "/api/ai/routes/endpoints",
                json={
                    "display_label": "Auth Refresh EP",
                    "base_url": base_url,
                    "keys": [{"api_key": secret_key, "label": "Auth Key"}],
                },
            )
            ep_id = create_resp.json()["id"]

            test_env["supervisor"].list_proxy_models = AsyncMock(return_value=["deepseek-ai/deepseek-r1", "qwen/qwen-2.5-72b"])

            # Refresh models
            ref_resp = await client.post(f"/api/ai/routes/endpoints/{ep_id}/models/refresh")
            assert ref_resp.status_code == 200
            models = ref_resp.json()["models"]
            assert models == ["deepseek-ai/deepseek-r1", "qwen/qwen-2.5-72b"]

            # Verify supervisor reload was called
            test_env["supervisor"].reload_custom_endpoints.assert_called()

            # Verify zero secrets in logs or responses
            assert secret_key not in caplog.text
            assert secret_key not in str(ref_resp.json())


@pytest.mark.asyncio
async def test_cross_provider_and_non_oauth_reauth_rejected(test_env):
    """Important 6: Verify cross-provider replace_account_id in start_session and non-OAuth
    reauth_account requests are rejected with clear 400 Bad Request responses.
    """
    transport = httpx.ASGITransport(app=app)
    kimi_acc_id = "kimi_account_123"
    async with test_env["session_factory"]() as s:
        cred_kimi = AIProviderCredential(
            id=kimi_acc_id,
            route_id="oauth:kimi",
            kind="oauth",
            vault_reference="vault_ref_kimi",
            proxy_credential_name="kimi_proxy_name",
            masked_identity=mask_identity("kimi_user@example.com"),
            priority=1,
            weight=1,
            enabled=True,
            status="active",
        )
        s.add(cred_kimi)
        await s.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # 1. Attempt to start OAuth for 'claude' replacing an 'oauth:kimi' account -> 400 Bad Request
        resp_cross = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "claude", "flow": "browser", "replace_account_id": kimi_acc_id},
        )
        assert resp_cross.status_code == 400
        assert "not the requested route" in resp_cross.json()["detail"]

        # 2. Create custom endpoint key credential (kind == 'key')
        ep_resp = await client.post(
            "/api/ai/routes/endpoints",
            json={
                "display_label": "Key EP",
                "base_url": "https://custom.ai.example/v1",
                "keys": [{"api_key": "some-key", "label": "Key 1"}],
            },
        )
        key_id = ep_resp.json()["keys"][0]["id"]

        # Attempt to reauth the endpoint key -> 400 Bad Request
        reauth_key = await client.post(f"/api/ai/routes/accounts/{key_id}/reauth")
        assert reauth_key.status_code == 400
        assert "only OAuth accounts" in reauth_key.json()["detail"]

        # Attempt to start OAuth with the endpoint key as replace_account_id -> 400 Bad Request
        start_key = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "claude", "flow": "browser", "replace_account_id": key_id},
        )
        assert start_key.status_code == 400
        assert "only OAuth accounts" in start_key.json()["detail"]


@pytest.mark.asyncio
async def test_concurrent_oauth_reconciliation_single_execution(test_env):
    """Minor 7: Verify that concurrent poll requests on a completed OAuth flow transition to
    reconciling under lock so only one reconcile path executes, preventing duplicate accounts or races.
    """
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    state = "concurrent_oauth_state"

    mgr = test_env["oauth_mgr"]
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="pending",
    )
    mgr._sessions[state] = session

    complete_oauth_file(test_env, "codex", "concurrent_user@example.com", {"access_token": "tok_concurrent"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # Launch two poll requests concurrently
        task1 = asyncio.create_task(client.get(f"/api/ai/routes/oauth/poll?state={state}"))
        task2 = asyncio.create_task(client.get(f"/api/ai/routes/oauth/poll?state={state}"))

        res1, res2 = await asyncio.gather(task1, task2)
        assert res1.status_code == 200
        assert res2.status_code == 200

        data1 = res1.json()
        data2 = res2.json()

        assert data1["status"] == "completed"
        assert data2["status"] == "completed"
        assert data1["account_id"] == data2["account_id"]

    # Verify only ONE credential was created in DB
    async with test_env["session_factory"]() as s:
        creds_res = await s.execute(
            select(AIProviderCredential).where(AIProviderCredential.route_id == "oauth:codex")
        )
        creds = creds_res.scalars().all()
        matching = [c for c in creds if c.id == data1["account_id"]]
        assert len(matching) == 1


@pytest.mark.asyncio
async def test_update_endpoint_503_when_vault_unavailable(test_env):
    """Minor 9: Verify update_endpoint returns 503 when headers are supplied while vault is unavailable."""
    transport = httpx.ASGITransport(app=app)
    vault = test_env["vault"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # Create endpoint while vault is healthy
        create_resp = await client.post(
            "/api/ai/routes/endpoints",
            json={
                "display_label": "Vault Fail Test EP",
                "base_url": "https://api.test.example/v1",
                "headers": {"X-Init-Header": "init"},
            },
        )
        assert create_resp.status_code == 200
        ep_id = create_resp.json()["id"]

        # Degrade vault
        vault._state = VaultState.KEYRING_UNAVAILABLE

        # Attempt to update headers -> 503 Service Unavailable
        update_resp = await client.patch(
            f"/api/ai/routes/endpoints/{ep_id}",
            json={"headers": {"X-New-Secret-Header": "new_val"}},
        )
        assert update_resp.status_code == 503
        assert "Provider vault is unavailable" in update_resp.json()["detail"]

        # Restore vault state and verify old headers preserved
        vault._state = VaultState.AVAILABLE
        get_ep = await client.get("/api/ai/routes")
        routes = get_ep.json()["routes"]
        ep_summary = next(r for r in routes if r["id"] == ep_id)
        assert ep_summary["config"]["header_names"] == ["X-Init-Header"]


# ===========================================================================
# Task 2 Tests: Loopback OAuth Callback Listener & Browser-Only Enforcement
# ===========================================================================


@pytest.mark.asyncio
async def test_oauth_start_for_all_supported_providers_registers_loopback_callback(test_env):
    """Verify start_oauth for all 8 supported providers derives loopback redirect,
    registers exact host/port/path, and returns callback_mode='loopback'."""
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        for idx, prov in enumerate(OAUTH_PROVIDERS):
            port = 52200 + idx
            state = f"state_{prov}_{idx}"
            redirect_uri = f"http://127.0.0.1:{port}/oauth-{prov}-callback"
            mgmt.start_oauth.return_value = {
                "state": state,
                "url": f"https://auth.{prov}.example/authorize?client_id=cid&redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
                "expires_in": 600,
            }

            resp = await client.post(
                "/api/ai/routes/oauth/start",
                json={"provider": prov},
            )
            assert resp.status_code == 200, f"Failed for provider {prov}: {resp.text}"
            data = resp.json()
            assert data["state"] == state
            assert data["provider"] == prov
            assert data["callback_mode"] == "loopback"
            assert data["callback_url"] == redirect_uri
            assert "user_code" not in data or data["user_code"] is None

            cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
            assert cb_server is not None
            async with cb_server._lock:
                assert state in cb_server._registrations
                reg = cb_server._registrations[state]
                assert reg.port == port
                assert reg.path == f"/oauth-{prov}-callback"

            await cb_server.unregister(state)


@pytest.mark.asyncio
async def test_oauth_loopback_simulated_browser_get_completes_session_and_unregisters(test_env):
    """Verify a simulated browser GET to loopback callback completes the session,
    submits state+code to supervisor, and unregisters listener."""
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    port = 52301
    state = "loopback_test_state_123"
    code = "loopback_auth_code_secret_xyz"
    redirect_uri = f"http://127.0.0.1:{port}/oauth-callback"

    mgmt.start_oauth.return_value = {
        "state": state,
        "url": f"https://auth.antigravity.example/authorize?client_id=ag&redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
        "expires_in": 600,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        start_resp = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "antigravity"},
        )
        assert start_resp.status_code == 200
        assert start_resp.json()["callback_mode"] == "loopback"

        complete_oauth_file(test_env, "antigravity", "browser_user@example.com")

        async with httpx.AsyncClient(trust_env=False) as browser_client:
            browser_resp = await browser_client.get(
                f"http://127.0.0.1:{port}/oauth-callback?state={state}&code={code}"
            )
            assert browser_resp.status_code == 200
            assert "Authorization Successful" in browser_resp.text
            assert code not in browser_resp.text

        mgmt.submit_oauth_callback.assert_called_with({"state": state, "code": code})

        poll_resp = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll_resp.status_code == 200
        assert poll_resp.json()["status"] == "completed"

        cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
        assert cb_server is not None
        async with cb_server._lock:
            assert state not in cb_server._registrations


@pytest.mark.asyncio
async def test_oauth_cancellation_unregisters_callback_listener(test_env):
    """Verify cancelling an OAuth session unregisters its callback listener."""
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    port = 52302
    state = "cancel_test_state_abc"
    redirect_uri = f"http://127.0.0.1:{port}/oauth-callback"

    mgmt.start_oauth.return_value = {
        "state": state,
        "url": f"https://auth.codex.example/authorize?redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
        "expires_in": 600,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        await client.post("/api/ai/routes/oauth/start", json={"provider": "codex"})
        cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
        assert cb_server is not None
        async with cb_server._lock:
            assert state in cb_server._registrations

        cancel_resp = await client.post(
            "/api/ai/routes/oauth/cancel",
            json={"state": state},
        )
        assert cancel_resp.status_code == 200

        async with cb_server._lock:
            assert state not in cb_server._registrations


@pytest.mark.asyncio
async def test_oauth_expiry_unregisters_callback_listener(test_env):
    """Verify session expiration unregisters its callback listener."""
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    port = 52303
    state = "expiry_test_state_def"
    redirect_uri = f"http://127.0.0.1:{port}/oauth-callback"

    mgmt.start_oauth.return_value = {
        "state": state,
        "url": f"https://auth.codex.example/authorize?redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
        "expires_in": 600,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        await client.post("/api/ai/routes/oauth/start", json={"provider": "codex"})
        cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
        assert cb_server is not None
        async with cb_server._lock:
            assert state in cb_server._registrations

        session = mgr._sessions[state]
        session.expires_at = time.time() - 10.0

        poll_resp = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll_resp.status_code == 200
        assert poll_resp.json()["status"] == "expired"

        async with cb_server._lock:
            assert state not in cb_server._registrations


@pytest.mark.asyncio
async def test_oauth_cancel_all_sessions_unregisters_all(test_env):
    """Verify cancel_all_sessions unregisters all pending callback listeners."""
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        for idx in (1, 2):
            port = 52310 + idx
            st = f"multi_state_{idx}"
            r_uri = f"http://127.0.0.1:{port}/oauth-callback"
            mgmt.start_oauth.return_value = {
                "state": st,
                "url": f"https://auth.example/auth?redirect_uri={urllib.parse.quote(r_uri)}&state={st}",
                "expires_in": 600,
            }
            await client.post("/api/ai/routes/oauth/start", json={"provider": "claude"})

        cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
        assert cb_server is not None
        async with cb_server._lock:
            assert len(cb_server._registrations) == 2

        await mgr.cancel_all_sessions()

        async with cb_server._lock:
            assert len(cb_server._registrations) == 0


@pytest.mark.asyncio
async def test_oauth_app_shutdown_unregisters_and_shuts_down_callback_server(test_env):
    """Verify shutdown unregisters all pending sessions and stops callback server."""
    import urllib.parse
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    port = 52320
    state = "shutdown_test_state"
    redirect_uri = f"http://127.0.0.1:{port}/oauth-callback"
    mgmt.start_oauth.return_value = {
        "state": state,
        "url": f"https://auth.example/auth?redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
        "expires_in": 600,
    }

    await mgr.start_session("codex")
    cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
    assert cb_server is not None
    async with cb_server._lock:
        assert state in cb_server._registrations
        assert port in cb_server._servers

    await mgr.shutdown()

    async with cb_server._lock:
        assert len(cb_server._registrations) == 0
        assert len(cb_server._servers) == 0


@pytest.mark.asyncio
async def test_oauth_port_conflict_returns_503_callback_port_unavailable(test_env, caplog):
    """Verify port conflict during listener startup returns HTTP 503 with stable code callback_port_unavailable
    and asserts sensitive OAuth state is absent from all logs."""
    import logging
    import socket
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]

    conflict_port = 52330
    conflict_state = "secret_conflict_state_555"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", conflict_port))
    sock.listen(1)

    try:
        redirect_uri = f"http://127.0.0.1:{conflict_port}/oauth-callback"
        mgmt.start_oauth.return_value = {
            "state": conflict_state,
            "url": f"https://auth.example/auth?redirect_uri={urllib.parse.quote(redirect_uri)}&state={conflict_state}",
            "expires_in": 600,
        }

        with caplog.at_level(logging.DEBUG):
            async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
                resp = await client.post(
                    "/api/ai/routes/oauth/start",
                    json={"provider": "codex"},
                )
                assert resp.status_code == 503
                data = resp.json()
                assert "callback_port_unavailable" in str(data)

        # Assert sensitive state token is absent from logs
        assert conflict_state not in caplog.text
        assert "Port conflict on callback server" in caplog.text
    finally:
        sock.close()


@pytest.mark.asyncio
async def test_oauth_flow_device_rejected_with_400(test_env):
    """Verify legacy flow=device requests are rejected with HTTP 400 Bad Request."""
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "codex", "flow": "device"},
        )
        assert resp.status_code == 400
        assert "Device flow is not supported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_manual_mode_on_missing_malformed_or_non_loopback_redirect(test_env):
    """Verify missing, malformed, or non-loopback redirect_uri selects callback_mode='manual' and callback_url=None."""
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        mgmt.start_oauth.return_value = {
            "state": "manual_st_1",
            "url": "https://auth.example/auth?redirect_uri=https%3A%2F%2Fremote.com%2Fcallback&state=manual_st_1",
            "expires_in": 600,
        }
        r1 = await client.post("/api/ai/routes/oauth/start", json={"provider": "claude"})
        assert r1.status_code == 200
        assert r1.json()["callback_mode"] == "manual"
        assert r1.json()["callback_url"] is None

        mgmt.start_oauth.return_value = {
            "state": "manual_st_2",
            "url": "https://auth.example/auth?state=manual_st_2",
            "expires_in": 600,
        }
        r2 = await client.post("/api/ai/routes/oauth/start", json={"provider": "claude"})
        assert r2.status_code == 200
        assert r2.json()["callback_mode"] == "manual"
        assert r2.json()["callback_url"] is None

        mgmt.start_oauth.return_value = {
            "state": "manual_st_3",
            "url": "https://auth.example/auth?redirect_uri=http%3A%2F%2Flocalhost%3A51121%2F..%2Fbad&state=manual_st_3",
            "expires_in": 600,
        }
        r3 = await client.post("/api/ai/routes/oauth/start", json={"provider": "claude"})
        assert r3.status_code == 200
        assert r3.json()["callback_mode"] == "manual"
        assert r3.json()["callback_url"] is None

        cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
        if cb_server is not None:
            async with cb_server._lock:
                assert "manual_st_1" not in cb_server._registrations
                assert "manual_st_2" not in cb_server._registrations
                assert "manual_st_3" not in cb_server._registrations


@pytest.mark.asyncio
async def test_oauth_callback_json_accepts_and_forwards_redirect_url_and_code(test_env, caplog):
    """Verify POST /api/ai/routes/oauth/callback accepts JSON with state, code, and redirect_url,
    forwards safe parameters to supervisor, and never logs sensitive tokens/URLs."""
    import logging
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    state = "manual_submit_state_456"
    secret_code = "SECRET_CODE_MANUAL_777"
    manual_redirect_url = f"http://localhost:51121/oauth-callback?state={state}&code={secret_code}"

    session = PendingOAuthSession(
        state=state,
        provider="antigravity",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="pending",
    )
    mgr._sessions[state] = session
    complete_oauth_file(test_env, "antigravity", "manual_cb_user@example.com", {"access_token": "SECRET_ACCESS_TOKEN_999"})

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
            resp = await client.post(
                "/api/ai/routes/oauth/callback",
                json={
                    "state": state,
                    "code": secret_code,
                    "redirect_url": manual_redirect_url,
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "completed"

    mgmt.submit_oauth_callback.assert_called_with({
        "state": state,
        "code": secret_code,
        "redirect_url": manual_redirect_url,
    })

    log_text = caplog.text
    assert secret_code not in log_text
    assert "SECRET_ACCESS_TOKEN_999" not in log_text
    assert manual_redirect_url not in log_text


@pytest.mark.asyncio
async def test_oauth_callback_submit_error_forwarded_and_logged_at_most_class_name(test_env, caplog):
    """Verify callback submit errors from supervisor are forwarded rather than swallowed,
    and log at most the exception class name at debug level."""
    import logging
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    state = "submit_err_state_888"
    session = PendingOAuthSession(
        state=state,
        provider="claude",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="pending",
    )
    mgr._sessions[state] = session

    sensitive_err = "CRITICAL_INTERNAL_UPSTREAM_FAILURE_SECRET_DATA_xyz"
    mgmt.submit_oauth_callback.side_effect = RuntimeError(sensitive_err)

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
            resp = await client.post(
                "/api/ai/routes/oauth/callback",
                json={"state": state, "code": "secret_cb_code"},
            )
            assert resp.status_code in (400, 500, 502, 503)

    log_text = caplog.text
    assert "RuntimeError" in log_text
    assert sensitive_err not in log_text
    assert "secret_cb_code" not in log_text


@pytest.mark.asyncio
async def test_oauth_unknown_provider_rejected_with_400(test_env):
    """Verify unknown provider is rejected with 400 Bad Request (preserving allowlist contract)."""
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "completely_unknown_llm"},
        )
        assert resp.status_code == 400
        assert "not one of the approved OAuth providers" in resp.json()["detail"]



@pytest.mark.asyncio
async def test_oauth_start_failure_logs_safe_type_only(test_env, caplog):
    """Verify that exceptions during mgmt.start_oauth log only safe type information without raw secret text."""
    import logging
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]

    sensitive_str = "SENSITIVE_PROXY_START_TOKEN_SECRET_987654"
    mgmt.start_oauth.side_effect = RuntimeError(f"Upstream auth failure: {sensitive_str}")

    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
            resp = await client.post(
                "/api/ai/routes/oauth/start",
                json={"provider": "codex"},
            )
            assert resp.status_code in (500, 502, 503)

    log_text = caplog.text
    assert "RuntimeError" in log_text
    assert sensitive_str not in log_text


@pytest.mark.asyncio
async def test_oauth_poll_pending_then_success_reconciles_cleanly(test_env):
    """Critical controller finding: Verify that polling a session while upstream is pending
    does NOT leave session.status in 'reconciling', so subsequent poll after upstream success
    proceeds to check OAuth status and successfully reconciles the account."""
    import time
    from unittest.mock import AsyncMock
    from app.services.oauth_session_manager import PendingOAuthSession
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    state = "pending_then_success_state_999"
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="pending",
    )
    mgr._sessions[state] = session

    # 1. Upstream status is initially pending/wait
    mgmt.get_oauth_status = AsyncMock(return_value={"status": "wait"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # First poll: upstream returns pending
        poll1 = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll1.status_code == 200
        assert poll1.json()["status"] == "pending"
        assert mgmt.get_oauth_status.call_count == 1

        # 2. Now user approves in browser; upstream reports success and writes auth credentials
        complete_oauth_file(test_env, "codex", "pending_success_user@example.com", {"access_token": "tok_recovered_123"})

        # Second poll: should check get_oauth_status, see success, and complete reconciliation
        poll2 = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll2.status_code == 200
        assert poll2.json()["status"] == "completed"
        assert poll2.json()["masked_identity"] is not None
        assert mgmt.get_oauth_status.call_count == 2



@pytest.mark.asyncio
async def test_oauth_cancellation_wins_over_inflight_success(test_env):
    """Verify that if a session is cancelled while get_oauth_status is in-flight,
    a subsequent 'ok' status does NOT transition the cancelled session to reconciling or completed."""
    import asyncio
    import time
    from unittest.mock import AsyncMock
    from app.services.oauth_session_manager import PendingOAuthSession

    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    state = "race_cancel_state_111"
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="pending",
    )
    mgr._sessions[state] = session

    complete_oauth_file(test_env, "codex", "cancelled_user@example.com", {"access_token": "tok_cancelled_never_used"})

    in_flight_event = asyncio.Event()
    release_event = asyncio.Event()

    async def slow_get_status(_state):
        in_flight_event.set()
        await release_event.wait()
        return {"status": "ok"}

    mgmt.get_oauth_status = AsyncMock(side_effect=slow_get_status)

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        poll_task = asyncio.create_task(client.get(f"/api/ai/routes/oauth/poll?state={state}"))

        await in_flight_event.wait()

        # Cancel the session while get_oauth_status is in-flight
        cancel_resp = await client.post("/api/ai/routes/oauth/cancel", json={"state": state})
        assert cancel_resp.status_code == 200
        assert session.status == "cancelled"

        # Now let slow_get_status complete
        release_event.set()

        poll_resp = await poll_task
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()

        assert poll_data["status"] == "cancelled"
        assert session.status == "cancelled"

        repoll = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert repoll.status_code == 200
        assert repoll.json()["status"] == "cancelled"
        assert session.status == "cancelled"


@pytest.mark.asyncio
async def test_oauth_expiry_wins_over_inflight_success(test_env):
    """Verify that if a session expires while get_oauth_status is in-flight,
    a subsequent 'ok' status does NOT transition the expired session to reconciling or completed."""
    import asyncio
    import time
    from unittest.mock import AsyncMock
    from app.services.oauth_session_manager import PendingOAuthSession

    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    state = "race_expire_state_222"
    session = PendingOAuthSession(
        state=state,
        provider="codex",
        flow="browser",
        replace_account_id=None,
        created_at=time.time(),
        expires_at=time.time() + 900.0,
        status="pending",
    )
    mgr._sessions[state] = session

    complete_oauth_file(test_env, "codex", "expired_user@example.com", {"access_token": "tok_expired_never_used"})

    in_flight_event = asyncio.Event()
    release_event = asyncio.Event()

    async def slow_get_status(_state):
        in_flight_event.set()
        await release_event.wait()
        return {"status": "ok"}

    mgmt.get_oauth_status = AsyncMock(side_effect=slow_get_status)

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        poll_task = asyncio.create_task(client.get(f"/api/ai/routes/oauth/poll?state={state}"))

        await in_flight_event.wait()

        # Simulate expiry while get_oauth_status is running
        session.expires_at = time.time() - 10.0

        release_event.set()

        poll_resp = await poll_task
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()

        assert poll_data["status"] == "expired"
        assert session.status == "expired"

        repoll = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert repoll.status_code == 200
        assert repoll.json()["status"] == "expired"
        assert session.status == "expired"


@pytest.mark.asyncio
async def test_oauth_loopback_submit_callback_failure_marks_session_failed(test_env, caplog):
    """Verify that when loopback on_code callback submission to supervisor fails,
    the session is marked failed with a safe message, unregistered from the callback server,
    logs only the exception class, and the callback server returns static 500 HTML_ERROR.
    Subsequent browser retries return 400 (not false 200) and UI polling sees failed."""
    import logging
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    port = 52440
    state = "loopback_fail_state_333"
    secret_code = "SECRET_AUTH_CODE_TO_NOT_LEAK_789"
    secret_internal_leak = "INTERNAL_LEAKED_SECRET_STACK_TRACE_XYZ"
    redirect_uri = f"http://127.0.0.1:{port}/oauth-codex-callback"

    mgmt.start_oauth.return_value = {
        "state": state,
        "url": f"https://auth.codex.example/authorize?redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
        "expires_in": 600,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        start_resp = await client.post("/api/ai/routes/oauth/start", json={"provider": "codex"})
        assert start_resp.status_code == 200

        # Simulate supervisor submit_oauth_callback failure
        mgmt.submit_oauth_callback.side_effect = RuntimeError(f"Database error: {secret_internal_leak}")

        # Send browser redirect GET to the loopback callback server
        cb_url = f"{redirect_uri}?state={state}&code={secret_code}"
        with caplog.at_level(logging.DEBUG):
            async with httpx.AsyncClient() as raw_client:
                cb_resp = await raw_client.get(cb_url)

        # 1. Callback server returns 500 Internal Server Error
        assert cb_resp.status_code == 500
        assert "Authorization Error" in cb_resp.text

        # 2. Session is marked failed
        session = mgr._sessions[state]
        assert session.status == "failed"
        assert session.error == "OAuth callback submission failed"

        # 3. Callback listener was unregistered
        cb_server = getattr(mgr, "callback_server", getattr(mgr, "_callback_server", None))
        assert cb_server is not None
        for _ in range(40):
            async with cb_server._lock:
                if state not in cb_server._registrations:
                    break
            await asyncio.sleep(0.05)
        async with cb_server._lock:
            assert state not in cb_server._registrations

        # 4. A browser retry cannot falsely succeed (listener stopped or state no longer registered)
        try:
            async with httpx.AsyncClient() as raw_client:
                retry_resp = await raw_client.get(cb_url)
            assert retry_resp.status_code == 400
        except httpx.ConnectError:
            pass  # Listener closed when state was unregistered; connection refused as expected

        # 5. UI polling sees failed with safe message
        poll_resp = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll_resp.status_code == 200
        poll_data = poll_resp.json()
        assert poll_data["status"] == "failed"
        assert poll_data["error"] == "OAuth callback submission failed"
        assert secret_internal_leak not in str(poll_data)

        # 6. Zero secret logging: only exception class name logged
        log_text = caplog.text
        assert "RuntimeError" in log_text
        assert secret_internal_leak not in log_text
        assert secret_code not in log_text


@pytest.mark.asyncio
async def test_oauth_loopback_on_code_when_supervisor_stopped(test_env, caplog):
    """Verify that if supervisor is stopped when loopback callback arrives,
    session is marked failed, callback is unregistered, and static 500 is returned."""
    import logging
    import urllib.parse
    transport = httpx.ASGITransport(app=app)
    mgmt = test_env["mgmt"]
    mgr = test_env["oauth_mgr"]

    port = 52441
    state = "loopback_stopped_sup_state_444"
    redirect_uri = f"http://127.0.0.1:{port}/oauth-codex-callback"

    mgmt.start_oauth.return_value = {
        "state": state,
        "url": f"https://auth.codex.example/authorize?redirect_uri={urllib.parse.quote(redirect_uri)}&state={state}",
        "expires_in": 600,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        start_resp = await client.post("/api/ai/routes/oauth/start", json={"provider": "codex"})
        assert start_resp.status_code == 200

        # Stop supervisor
        test_env["supervisor"]._process = None

        cb_url = f"{redirect_uri}?state={state}&code=test_code_xyz"
        with caplog.at_level(logging.DEBUG):
            async with httpx.AsyncClient() as raw_client:
                cb_resp = await raw_client.get(cb_url)

        assert cb_resp.status_code == 500
        session = mgr._sessions[state]
        assert session.status == "failed"
        assert "Proxy supervisor is not running" in session.error

        poll_resp = await client.get(f"/api/ai/routes/oauth/poll?state={state}")
        assert poll_resp.status_code == 200
        assert poll_resp.json()["status"] == "failed"

        log_text = caplog.text
        assert "RuntimeError" in log_text
        assert "test_code_xyz" not in log_text


# ===========================================================================
# P7 Regression Test: Structural & Invariant Verification for list_routes
# ===========================================================================


@pytest.mark.asyncio
async def test_list_routes_structural_invariants_and_shape(test_env, monkeypatch):
    """P7 Regression Test: verify list_routes produces exact expected schema shape,
    exact keys per route, health fields, and correct model prefixing/ordering."""
    from app.services.direct_proxy_routes import SUPPORTED_ROUTE_IDS, get_direct_route
    monkeypatch.setattr(settings, "ai_provider", "aistudio")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        resp = await client.get("/api/ai/routes")
        assert resp.status_code == 200
        data = resp.json()

        # Top-level keys
        assert set(data.keys()) == {
            "routes",
            "active_route_id",
            "proxy_status",
            "vault_state",
            "recovery_state",
            "settings",
        }

        # Routes list invariants
        routes = data["routes"]
        assert len(routes) == len(OAUTH_PROVIDERS) + len(SUPPORTED_ROUTE_IDS)

        # Ordering invariant: seeded DB routes first (OAuth in seed order), then direct providers
        db_oauth_ids = [f"oauth:{p}" for p in OAUTH_PROVIDERS]
        route_ids = [r["id"] for r in routes]
        assert route_ids[:len(db_oauth_ids)] == db_oauth_ids
        assert route_ids[len(db_oauth_ids):] == list(SUPPORTED_ROUTE_IDS)

        # Required fields per route
        expected_route_keys = {
            "id",
            "kind",
            "provider",
            "display_label",
            "proxy_prefix",
            "enabled",
            "is_active",
            "health",
            "accounts",
            "keys",
            "config",
            "models",
            "recovery_state",
        }
        for r in routes:
            assert set(r.keys()) == expected_route_keys
            assert isinstance(r["health"], dict)
            assert "healthy" in r["health"]
            assert "status" in r["health"]
            assert "proxy_status" in r["health"]
            assert r["health"]["status"] in ("active", "configured", "unconfigured")

            if r["kind"] == "oauth":
                assert "account_count" in r["health"]
                assert r["config"] == {}
                assert r["keys"] == []
            elif r["kind"] == "direct":
                assert r["health"]["transport"] == "proxy"
                assert r["accounts"] == []
                assert r["keys"] == []
                assert "is_configured" in r["config"]
                assert r["config"]["transport"] == "proxy"


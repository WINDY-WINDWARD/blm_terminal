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
    mock_supervisor = MagicMock(spec=ProxySupervisor)
    mock_supervisor.is_running.return_value = True
    mock_supervisor.ensure_started = AsyncMock(return_value=("127.0.0.1", 8317, "test-client-key"))
    mock_supervisor.get_status.return_value = {
        "state": "running",
        "host": "127.0.0.1",
        "port": 8317,
        "pid": 12345,
    }
    mock_mgmt = MagicMock()
    mock_mgmt.start_oauth = AsyncMock(return_value={
        "state": "test_state_123",
        "url": "https://auth.example.com/oauth/authorize",
        "expires_in": 900,
    })
    mock_mgmt.get_oauth_status = AsyncMock(return_value={"status": "pending"})
    mock_mgmt.cancel_oauth_session = AsyncMock(return_value={"status": "cancelled"})
    mock_mgmt.reset_cooldown = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.delete_credential = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.patch_config = AsyncMock(return_value={"status": "ok"})
    mock_mgmt.submit_oauth_callback = AsyncMock(return_value={"status": "ok"})
    mock_supervisor.get_management_client.return_value = mock_mgmt
    mock_supervisor.reload_custom_endpoints = AsyncMock()
    mock_supervisor.request_sync = MagicMock()
    mock_supervisor.stop = AsyncMock()

    oauth_mgr = OAuthSessionManager()

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
async def test_list_routes_includes_oauth_and_direct(test_env):
    """Verify GET /ai/routes lists OAuth routes, direct providers, and active route."""
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

        for p in DIRECT_PROVIDERS:
            assert f"direct:{p}" in route_ids

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
        direct_routes = [r for r in data["routes"] if r["kind"] == "direct"]
        assert len(direct_routes) >= len(DIRECT_PROVIDERS)
        for dr in direct_routes:
            assert dr["recovery_state"] is None
            assert len(dr["models"]) >= 1


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

        # 3. Reject invalid route formats and non-existent providers
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
        test_env["mgmt"].patch_config.assert_called_with({"routing": {"strategy": "round-robin"}})


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
    """Verify endpoint model preview, model refresh, and connectivity test."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=test_env["headers"]) as client:
        # Mock httpx models call
        mock_models_resp = MagicMock()
        mock_models_resp.status_code = 200
        mock_models_resp.json.return_value = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
            ]
        }

        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_models_resp)):
            # 1. Preview
            prev_resp = await client.post(
                "/api/ai/routes/endpoints/models/preview",
                json={"base_url": "https://api.openai.com/v1", "api_key": "sk-preview-key"},
            )
            assert prev_resp.status_code == 200
            assert prev_resp.json()["models"] == ["gpt-4o", "gpt-4o-mini"]

            # Create endpoint to test refresh and connectivity
            create_resp = await client.post(
                "/api/ai/routes/endpoints",
                json={"display_label": "Test Refresh EP", "base_url": "https://api.openai.com/v1"},
            )
            ep_id = create_resp.json()["id"]

            # 2. Refresh
            ref_resp = await client.post(f"/api/ai/routes/endpoints/{ep_id}/models/refresh")
            assert ref_resp.status_code == 200
            assert ref_resp.json()["models"] == ["gpt-4o", "gpt-4o-mini"]

            # 3. Test connectivity
            test_resp = await client.post(f"/api/ai/routes/endpoints/{ep_id}/test")
            assert test_resp.status_code == 200
            assert test_resp.json()["status"] == "ok"
            assert "latency_ms" in test_resp.json()


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

        # 2. Start device flow
        mgmt.start_oauth.return_value = {
            "state": "device_state_def",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 600,
        }
        start_device = await client.post(
            "/api/ai/routes/oauth/start",
            json={"provider": "codex", "flow": "device"},
        )
        assert start_device.status_code == 200
        d_data = start_device.json()
        assert d_data["user_code"] == "WDJB-MJHT"
        assert d_data["verification_uri"] == "https://github.com/login/device"

        # 3. Poll pending session
        mgmt.get_oauth_status.return_value = {"status": "pending"}
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
        mgmt.get_oauth_status.return_value = {
            "status": "completed",
            "identity": "alice@example.com",
            "auth": {"identity": "alice@example.com", "access_token": "new_refreshed_token"},
        }

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

        updated_auth = await vault.get_oauth_auth(vault_ref)
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
        mgmt.get_oauth_status.return_value = {
            "status": "completed",
            "identity": "bob@example.com",
            "auth": {"identity": "bob@example.com", "access_token": "bob_token"},
        }

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

        # 4. Test account
        t_resp = await client.post(f"/api/ai/routes/accounts/{account_id}/test")
        assert t_resp.status_code == 200
        assert t_resp.json()["status"] == "ok"
        assert "latency_ms" in t_resp.json()

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

    mgmt.get_oauth_status.return_value = {
        "status": "completed",
        "identity": "callback_user@example.com",
        "auth": {"identity": "callback_user@example.com", "access_token": "SENSITIVE_OAUTH_ACCESS_TOKEN_ABC"},
    }

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

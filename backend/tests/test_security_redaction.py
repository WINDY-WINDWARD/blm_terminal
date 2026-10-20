import json
import logging
import os
import secrets
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import main
from main import app
from app.database import Base, get_db
from app.models.system_config import SystemConfig
from app.models.user import User
from app.auth import get_current_user, get_admin_user
from app.routers.system_config import SYSTEM_CONFIG_SECRET_KEYS, ALLOWED_STRING_KEYS


SENTINEL_OPENALGO_SECRET = "sentinel_openalgo_shhh_998877"
SENTINEL_OPENAI_SECRET = "sentinel_openai_key_xyz_112233"
SENTINEL_ANTHROPIC_SECRET = "sentinel_anthropic_secret_445566"
SENTINEL_COPILOT_SECRET = "sentinel_copilot_token_778899"
SENTINEL_CODEX_SECRET = "sentinel_codex_access_token_334455"
SENTINEL_CLAUDE_CODE_SECRET = "sentinel_claude_code_token_119922"


def test_system_config_secret_keys_set():
    """Verify that the secret-key set contains direct AI keys, OpenAlgo, Copilot, Claude Code, and Codex tokens."""
    expected_direct_ai_keys = {
        "ai.zen_api_key",
        "ai.go_api_key",
        "ai.aistudio_api_key",
        "ai.groq_api_key",
        "ai.nvidia_api_key",
        "ai.anthropic_api_key",
        "ai.openai_api_key",
        "ai.openrouter_api_key",
        "ai.deepseek_api_key",
        "ai.xai_api_key",
        "ai.together_api_key",
    }
    assert expected_direct_ai_keys.issubset(SYSTEM_CONFIG_SECRET_KEYS)
    assert "openalgo.api_key" in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.copilot_gh_token" in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.claude_code_token" in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.codex_access_token" in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.codex_refresh_token" in SYSTEM_CONFIG_SECRET_KEYS

    # Verify all secret keys belong to ALLOWED_STRING_KEYS
    for k in SYSTEM_CONFIG_SECRET_KEYS:
        assert k in ALLOWED_STRING_KEYS, f"Secret key {k} must be in ALLOWED_STRING_KEYS"

    # Verify non-secret keys are NOT marked as secret
    assert "openalgo.url" not in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.provider" not in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.hunter_model" not in SYSTEM_CONFIG_SECRET_KEYS
    assert "ai.verifier_model" not in SYSTEM_CONFIG_SECRET_KEYS


@pytest.fixture
async def security_test_env(tmp_path: Path):
    """Set up DB with sentinel secrets and override auth dependencies."""
    db_file = tmp_path / "test_sec_redaction.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Seed system_config with sentinel secrets and non-secret config
    async with session_factory() as session:
        items = [
            ("openalgo.url", "http://127.0.0.1:5000"),
            ("openalgo.api_key", SENTINEL_OPENALGO_SECRET),
            ("ai.openai_api_key", SENTINEL_OPENAI_SECRET),
            ("ai.anthropic_api_key", SENTINEL_ANTHROPIC_SECRET),
            ("ai.copilot_gh_token", SENTINEL_COPILOT_SECRET),
            ("ai.codex_access_token", SENTINEL_CODEX_SECRET),
            ("ai.claude_code_token", SENTINEL_CLAUDE_CODE_SECRET),
            ("ai.provider", "openai"),
        ]
        for key, val in items:
            stmt = select(SystemConfig).where(SystemConfig.key == key)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row:
                row.value = val
            else:
                session.add(SystemConfig(key=key, value=val))
        await session.commit()

    test_user = User(id=1, username="test_admin", is_admin=True)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def override_current_user():
        return test_user

    async def override_admin_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_admin_user] = override_admin_user

    test_launch_token = "launch-token-sentinel-test-123"
    test_internal_token = "internal-server-token-sentinel-test-456"

    orig_launch = getattr(main, "LAUNCH_TOKEN", None)
    orig_internal = getattr(main, "INTERNAL_TOKEN", None)

    main.LAUNCH_TOKEN = test_launch_token
    main.INTERNAL_TOKEN = test_internal_token

    yield {
        "launch_token": test_launch_token,
        "internal_token": test_internal_token,
        "headers": {"x-blm-token": test_launch_token},
        "internal_headers": {"x-blm-server-token": test_internal_token},
    }

    main.LAUNCH_TOKEN = orig_launch
    main.INTERNAL_TOKEN = orig_internal
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_admin_user, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_system_config_redaction_and_configured_flags(security_test_env):
    """GET /system-config must omit raw secret values and return configured flags."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=security_test_env["headers"]) as client:
        resp = await client.get("/api/system-config")
        assert resp.status_code == 200
        raw_text = resp.text

        # 1. Assert NO sentinel secret appears anywhere in the response text
        assert SENTINEL_OPENALGO_SECRET not in raw_text
        assert SENTINEL_OPENAI_SECRET not in raw_text
        assert SENTINEL_ANTHROPIC_SECRET not in raw_text
        assert SENTINEL_COPILOT_SECRET not in raw_text
        assert SENTINEL_CODEX_SECRET not in raw_text
        assert SENTINEL_CLAUDE_CODE_SECRET not in raw_text

        data = resp.json()

        # 2. Assert configured flags are True for populated secrets
        assert data.get("openalgo.api_key_configured") is True
        assert data.get("ai.openai_api_key_configured") is True
        assert data.get("ai.anthropic_api_key_configured") is True
        assert data.get("ai.copilot_gh_token_configured") is True
        assert data.get("ai.codex_access_token_configured") is True
        assert data.get("ai.claude_code_token_configured") is True

        # 3. Assert unconfigured keys report False
        assert data.get("ai.deepseek_api_key_configured") is False
        assert data.get("ai.groq_api_key_configured") is False

        # 4. Assert non-secret config is still returned as values
        assert data.get("openalgo.url") == "http://127.0.0.1:5000"
        assert data.get("ai.provider") == "openai"

        # 5. Assert raw secret values are NOT in the dict
        for secret_key in SYSTEM_CONFIG_SECRET_KEYS:
            val = data.get(secret_key)
            assert val is None or val == "", f"Secret key {secret_key} must not return raw value"


@pytest.mark.asyncio
async def test_put_system_config_secret_response_redaction(security_test_env):
    """PUT /system-config/{key} for secrets must omit the submitted value."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=security_test_env["headers"]) as client:
        new_sentinel = "sentinel_new_secret_put_999000"

        # 1. Update secret key
        resp = await client.put(
            "/api/system-config/ai.deepseek_api_key",
            json={"value": new_sentinel},
        )
        assert resp.status_code == 200
        assert new_sentinel not in resp.text, "Submitted secret must not appear in PUT response text"
        data = resp.json()
        assert data.get("key") == "ai.deepseek_api_key"
        assert data.get("configured") is True
        assert "value" not in data, "PUT response for secret must omit 'value'"

        # 2. Clearing a secret key
        clear_resp = await client.put(
            "/api/system-config/ai.deepseek_api_key",
            json={"value": ""},
        )
        assert clear_resp.status_code == 200
        clear_data = clear_resp.json()
        assert clear_data.get("key") == "ai.deepseek_api_key"
        assert clear_data.get("configured") is False
        assert "value" not in clear_data

        # 3. Non-secret key should still echo value
        non_secret_resp = await client.put(
            "/api/system-config/openalgo.url",
            json={"value": "http://127.0.0.1:5001"},
        )
        assert non_secret_resp.status_code == 200
        non_secret_data = non_secret_resp.json()
        assert non_secret_data.get("key") == "openalgo.url"
        assert non_secret_data.get("value") == "http://127.0.0.1:5001"


@pytest.mark.asyncio
async def test_server_only_openalgo_credential_endpoint_auth(security_test_env):
    """Verify that the server-only OpenAlgo credential endpoint requires the internal token."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        endpoint = "/api/system-config/openalgo-credentials"

        # 1. No token -> 401
        r_none = await client.get(endpoint)
        assert r_none.status_code == 401

        # 2. Browser launch token only (x-blm-token) -> 401 (Must NOT authorize internal endpoint)
        r_browser = await client.get(endpoint, headers={"x-blm-token": security_test_env["launch_token"]})
        assert r_browser.status_code == 401

        # 3. Invalid internal token -> 401
        r_invalid = await client.get(
            endpoint,
            headers={"x-blm-server-token": "wrong-internal-token"},
        )
        assert r_invalid.status_code == 401

        # 4. Valid internal token -> 200 with raw credentials
        r_valid = await client.get(
            endpoint,
            headers=security_test_env["internal_headers"],
        )
        assert r_valid.status_code == 200
        creds = r_valid.json()
        assert creds.get("url") == "http://127.0.0.1:5000"
        assert creds.get("api_key") == SENTINEL_OPENALGO_SECRET
        assert creds.get("configured") is True

        # 5. Also works with x-blm-internal-token header when matching INTERNAL_TOKEN
        r_valid_alt = await client.get(
            endpoint,
            headers={"x-blm-internal-token": security_test_env["internal_token"]},
        )
        assert r_valid_alt.status_code == 200
        assert r_valid_alt.json().get("api_key") == SENTINEL_OPENALGO_SECRET


@pytest.mark.asyncio
async def test_server_endpoint_fails_closed_when_internal_token_unset(security_test_env):
    """When INTERNAL_TOKEN is None/unset on the server, the endpoint must fail closed (401)."""
    orig_internal = main.INTERNAL_TOKEN
    main.INTERNAL_TOKEN = None
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/system-config/openalgo-credentials",
                headers={"x-blm-server-token": "any-token"},
            )
            assert resp.status_code == 401
    finally:
        main.INTERNAL_TOKEN = orig_internal


@pytest.mark.asyncio
async def test_sentinel_secrets_absent_from_logs_and_error_payloads(security_test_env, caplog):
    """Ensure that sentinel secrets never leak into log messages or error payloads."""
    transport = httpx.ASGITransport(app=app)
    with caplog.at_level(logging.DEBUG):
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=security_test_env["headers"]) as client:
            # 1. Successful GET
            await client.get("/api/system-config")
            
            # 2. PUT with sentinel
            sentinel = "sentinel_err_secret_12345"
            await client.put(
                "/api/system-config/ai.openai_api_key",
                json={"value": sentinel},
            )

            # 3. Request invalid key to trigger 404 error response
            err_resp = await client.put(
                f"/api/system-config/invalid_key_{sentinel}",
                json={"value": sentinel},
            )
            assert err_resp.status_code == 404

            # Verify no sentinel secret in captured log text
            log_text = caplog.text
            assert SENTINEL_OPENALGO_SECRET not in log_text
            assert SENTINEL_OPENAI_SECRET not in log_text
            assert SENTINEL_ANTHROPIC_SECRET not in log_text

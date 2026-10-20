"""Tests for provider vault, route registry, model helpers, and persistence foundation."""

import asyncio
import hashlib
import json
import logging
import os
import struct
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.provider_vault import (
    KEYRING_ACCOUNT,
    KEYRING_SERVICE,
    VAULT_MAGIC,
    VAULT_VERSION,
    KeyringUnavailableError,
    ProviderVault,
    VaultCorruptError,
    VaultState,
    VaultUnavailableError,
)
from app.services.route_registry import (
    DEFAULT_ROUTE_ID,
    OAUTH_PROVIDERS,
    compute_oauth_proxy_prefix,
    ensure_model_belongs_to_route,
    format_route_model_id,
    is_route_model_id,
    map_legacy_model_to_route,
    normalize_legacy_provider_id,
    parse_route_model_id,
    provider_to_route_id,
    resolve_active_route_id,
    seed_oauth_routes,
    seed_oauth_routes_sync,
    validate_model_for_route,
)


# ---------------------------------------------------------------------------
# Keyring & Vault State Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_keyring_retrieval_and_generation(tmp_path, monkeypatch):
    """Test keyring integration: stores newly generated key if absent, reuses existing key."""
    keyring_store: dict[tuple[str, str], str] = {}

    def mock_get_password(service, account):
        return keyring_store.get((service, account))

    def mock_set_password(service, account, password):
        keyring_store[(service, account)] = password

    import keyring
    monkeypatch.setattr(keyring, "get_password", mock_get_password)
    monkeypatch.setattr(keyring, "set_password", mock_set_password)

    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file)

    # First init: key should be generated and stored in keyring
    state = await vault.initialize()
    assert state == VaultState.AVAILABLE
    assert vault.is_available is True
    assert (KEYRING_SERVICE, KEYRING_ACCOUNT) in keyring_store
    stored_hex = keyring_store[(KEYRING_SERVICE, KEYRING_ACCOUNT)]
    assert len(stored_hex) == 64

    # Second init on new instance: key should be read from keyring
    vault2 = ProviderVault(vault_path=vault_file)
    state2 = await vault2.initialize()
    assert state2 == VaultState.AVAILABLE
    assert vault2._key == bytes.fromhex(stored_hex)


@pytest.mark.asyncio
async def test_keyring_unavailable_state(tmp_path, monkeypatch):
    """Test that keyring failures gracefully transition vault to keyring_unavailable."""
    import keyring
    from keyring.errors import KeyringError

    def failing_get_password(service, account):
        raise KeyringError("Mock keyring daemon failure")

    monkeypatch.setattr(keyring, "get_password", failing_get_password)

    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file)
    state = await vault.initialize()

    assert state == VaultState.KEYRING_UNAVAILABLE
    assert vault.is_available is False

    with pytest.raises(KeyringUnavailableError):
        await vault.get_oauth_auth("oauth:codex")

    with pytest.raises(KeyringUnavailableError):
        await vault.set_oauth_auth("oauth:codex", {"token": "test"})


@pytest.mark.asyncio
async def test_keyring_set_failure_state(tmp_path, monkeypatch):
    """Test that keyring set_password failure transitions to keyring_unavailable."""
    import keyring

    def mock_get_password(service, account):
        return None

    def failing_set_password(service, account, password):
        raise RuntimeError("Write permission denied in keyring")

    monkeypatch.setattr(keyring, "get_password", mock_get_password)
    monkeypatch.setattr(keyring, "set_password", failing_set_password)

    vault = ProviderVault(vault_path=tmp_path / "vault.enc")
    state = await vault.initialize()
    assert state == VaultState.KEYRING_UNAVAILABLE


# ---------------------------------------------------------------------------
# Vault CRUD and Round-Trip Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_roundtrip_all_categories(tmp_path):
    """Test storing and retrieving entries in all vault categories."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file, key=key)
    await vault.initialize()
    assert vault.is_available

    # 1. OAuth auth payloads
    oauth_data = {
        "access_token": "secret-access-token-123",
        "refresh_token": "secret-refresh-token-456",
        "expires_at": 1792000000,
        "email": "user@example.com",
    }
    await vault.set_oauth_auth("oauth:codex", oauth_data)
    assert await vault.get_oauth_auth("oauth:codex") == oauth_data
    assert await vault.get_oauth_auth("oauth:nonexistent") is None

    # 2. Endpoint headers
    headers = {"Authorization": "Bearer sk-custom-key-789", "X-Custom-Org": "org_abc"}
    await vault.set_endpoint_headers("endpoint:123", headers)
    assert await vault.get_endpoint_headers("endpoint:123") == headers
    assert await vault.get_endpoint_headers("endpoint:nonexistent") is None

    # 3. Endpoint keys
    keys = ["sk-key-1", "sk-key-2", "sk-key-3"]
    await vault.set_endpoint_keys("endpoint:123", keys)
    assert await vault.get_endpoint_keys("endpoint:123") == keys

    # 4. Cooldown snapshots
    cooldown = {"status": "cooling_down", "resets_at": 1792001000, "reason": "rate_limit"}
    await vault.set_cooldown_snapshot("oauth:antigravity", cooldown)
    assert await vault.get_cooldown_snapshot("oauth:antigravity") == cooldown

    # 5. Generic vault_ref access
    await vault.set_secret("oauth_auth:oauth:claude", {"token": "claude-token-999"})
    assert (await vault.get_secret("oauth_auth:oauth:claude")) == {"token": "claude-token-999"}
    assert (await vault.get_oauth_auth("oauth:claude")) == {"token": "claude-token-999"}

    await vault.set_secret("custom_entry_key", "custom_secret_value")
    assert await vault.get_secret("custom_entry_key") == "custom_secret_value"

    # Persistence verification: reload from file with same key
    vault2 = ProviderVault(vault_path=vault_file, key=key)
    await vault2.initialize()
    assert await vault2.get_oauth_auth("oauth:codex") == oauth_data
    assert await vault2.get_endpoint_headers("endpoint:123") == headers
    assert await vault2.get_endpoint_keys("endpoint:123") == keys
    assert await vault2.get_cooldown_snapshot("oauth:antigravity") == cooldown
    assert await vault2.get_secret("custom_entry_key") == "custom_secret_value"


@pytest.mark.asyncio
async def test_vault_deletions_and_reset(tmp_path):
    """Test individual entry deletions and full vault reset."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file, key=key)
    await vault.initialize()

    await vault.set_oauth_auth("oauth:codex", {"token": "t1"})
    await vault.set_endpoint_headers("endpoint:e1", {"h": "v"})
    await vault.set_endpoint_keys("endpoint:e1", ["k1"])
    await vault.set_cooldown_snapshot("oauth:codex", {"cd": 1})

    # Test removals
    assert await vault.remove_oauth_auth("oauth:codex") is True
    assert await vault.remove_oauth_auth("oauth:codex") is False
    assert await vault.get_oauth_auth("oauth:codex") is None

    assert await vault.remove_endpoint_headers("endpoint:e1") is True
    assert await vault.get_endpoint_headers("endpoint:e1") is None

    assert await vault.remove_endpoint_keys("endpoint:e1") is True
    assert await vault.get_endpoint_keys("endpoint:e1") is None

    assert await vault.remove_cooldown_snapshot("oauth:codex") is True
    assert await vault.get_cooldown_snapshot("oauth:codex") is None

    # Reset
    await vault.set_secret("custom_k", "val")
    await vault.reset_vault()
    assert await vault.get_secret("custom_k") is None

    # Verify persisted empty state
    vault2 = ProviderVault(vault_path=vault_file, key=key)
    await vault2.initialize()
    assert await vault2.get_secret("custom_k") is None


# ---------------------------------------------------------------------------
# Vault Corruption Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_corrupt_truncated_file(tmp_path):
    """Test that truncated files trigger vault_corrupt state."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"
    vault_file.write_bytes(b"BLMVLT\x00\x01short")

    vault = ProviderVault(vault_path=vault_file, key=key)
    state = await vault.initialize()

    assert state == VaultState.VAULT_CORRUPT
    assert vault.is_available is False
    with pytest.raises(VaultCorruptError):
        await vault.get_oauth_auth("oauth:codex")


@pytest.mark.asyncio
async def test_vault_corrupt_bad_magic_or_version(tmp_path):
    """Test that incorrect header magic or version triggers vault_corrupt."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"

    # Bad magic
    bad_magic = b"WRONGM\x00\x01" + os.urandom(40)
    vault_file.write_bytes(bad_magic)
    vault = ProviderVault(vault_path=vault_file, key=key)
    state = await vault.initialize()
    assert state == VaultState.VAULT_CORRUPT

    # Bad version
    bad_version = VAULT_MAGIC + struct.pack(">H", 99) + os.urandom(40)
    vault_file.write_bytes(bad_version)
    vault2 = ProviderVault(vault_path=vault_file, key=key)
    state2 = await vault2.initialize()
    assert state2 == VaultState.VAULT_CORRUPT


@pytest.mark.asyncio
async def test_vault_corrupt_tampered_ciphertext(tmp_path):
    """Test that flipped bits in ciphertext/tag fail GCM authentication and trigger vault_corrupt."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file, key=key)
    await vault.initialize()
    await vault.set_oauth_auth("oauth:codex", {"token": "secret"})

    # Tamper with the encrypted file (flip one byte near the end)
    raw = bytearray(vault_file.read_bytes())
    raw[-1] ^= 0xFF
    vault_file.write_bytes(bytes(raw))

    vault2 = ProviderVault(vault_path=vault_file, key=key)
    state2 = await vault2.initialize()
    assert state2 == VaultState.VAULT_CORRUPT
    with pytest.raises(VaultCorruptError):
        await vault2.get_oauth_auth("oauth:codex")


@pytest.mark.asyncio
async def test_vault_corrupt_wrong_key(tmp_path):
    """Test that attempting decryption with a different key triggers vault_corrupt."""
    key1 = os.urandom(32)
    key2 = os.urandom(32)
    vault_file = tmp_path / "vault.enc"

    vault1 = ProviderVault(vault_path=vault_file, key=key1)
    await vault1.initialize()
    await vault1.set_oauth_auth("oauth:codex", {"token": "secret"})

    vault2 = ProviderVault(vault_path=vault_file, key=key2)
    state2 = await vault2.initialize()
    assert state2 == VaultState.VAULT_CORRUPT


# ---------------------------------------------------------------------------
# Atomic Replacement and Concurrency Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vault_atomic_replacement_and_concurrency(tmp_path):
    """Test that concurrent writes succeed without file corruption or temporary file leakage."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file, key=key)
    await vault.initialize()

    async def write_task(idx: int):
        await vault.set_oauth_auth(f"oauth:task_{idx}", {"idx": idx, "payload": "x" * 100})

    # Execute 20 concurrent write operations
    await asyncio.gather(*(write_task(i) for i in range(20)))

    # Verify no .tmp files remain in directory
    tmp_files = list(tmp_path.glob("*.tmp.*"))
    assert len(tmp_files) == 0

    # Verify all 20 entries persisted
    vault2 = ProviderVault(vault_path=vault_file, key=key)
    await vault2.initialize()
    for i in range(20):
        entry = await vault2.get_oauth_auth(f"oauth:task_{i}")
        assert entry is not None
        assert entry["idx"] == i


# ---------------------------------------------------------------------------
# Zero Secret Logging Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_secret_logging(tmp_path, caplog):
    """Verify that vault operations never log secret tokens, headers, or keys."""
    key = os.urandom(32)
    vault_file = tmp_path / "vault.enc"
    vault = ProviderVault(vault_path=vault_file, key=key)

    secret_token = "VERY_SENSITIVE_OAUTH_TOKEN_XYZ987"
    secret_header = "VERY_SENSITIVE_API_HEADER_VAL_123"

    with caplog.at_level(logging.DEBUG):
        await vault.initialize()
        await vault.set_oauth_auth("oauth:codex", {"access_token": secret_token})
        await vault.get_oauth_auth("oauth:codex")
        await vault.set_endpoint_headers("endpoint:e1", {"Authorization": secret_header})
        await vault.get_endpoint_headers("endpoint:e1")
        await vault.reset_vault()

    all_logs = " ".join(record.message for record in caplog.records)
    assert secret_token not in all_logs
    assert secret_header not in all_logs


# ---------------------------------------------------------------------------
# Route and Model Registry Tests
# ---------------------------------------------------------------------------

def test_oauth_proxy_prefix_calculation():
    """Verify that compute_oauth_proxy_prefix generates exact expected SHA-256 prefixes."""
    expected_prefixes = {
        "oauth:codex": "blm-43acc341bd709366",
        "oauth:antigravity": "blm-c8b4ae88275f90e3",
        "oauth:claude": "blm-353e78a1ea416fb6",
        "oauth:xai": "blm-7391db532800571a",
        "oauth:kimi": "blm-39624648dfb455c7",
        "oauth:kimi-ai": "blm-36a3f093c699f163",
        "oauth:meta": "blm-03c241dab390035a",
        "oauth:devin": "blm-c6669062f2b4e6f3",
    }
    for route_id, expected in expected_prefixes.items():
        assert compute_oauth_proxy_prefix(route_id) == expected


def test_normalize_legacy_provider_id():
    """Test legacy provider ID normalization."""
    assert normalize_legacy_provider_id("gemini") == "antigravity"
    assert normalize_legacy_provider_id("antigravity") == "antigravity"
    assert normalize_legacy_provider_id("zen") == "zen-paid"
    assert normalize_legacy_provider_id("zen-free") == "zen-paid"
    assert normalize_legacy_provider_id("codex") == "codex"
    assert normalize_legacy_provider_id("openai") == "openai"
    assert normalize_legacy_provider_id(None) == "aistudio"
    assert normalize_legacy_provider_id("") == "aistudio"


def test_provider_to_route_id():
    """Test mapping legacy and modern provider strings to canonical route IDs."""
    # Preserves already-qualified route IDs
    assert provider_to_route_id("oauth:codex") == "oauth:codex"
    assert provider_to_route_id("endpoint:00000000-0000-0000-0000-000000000000") == "endpoint:00000000-0000-0000-0000-000000000000"
    assert provider_to_route_id("direct:openai") == "direct:openai"

    # Maps OAuth providers
    assert provider_to_route_id("codex") == "oauth:codex"
    assert provider_to_route_id("gemini") == "oauth:antigravity"
    assert provider_to_route_id("antigravity") == "oauth:antigravity"
    assert provider_to_route_id("claude") == "oauth:claude"
    assert provider_to_route_id("xai") == "oauth:xai"
    assert provider_to_route_id("kimi") == "oauth:kimi"
    assert provider_to_route_id("kimi-ai") == "oauth:kimi-ai"
    assert provider_to_route_id("meta") == "oauth:meta"
    assert provider_to_route_id("devin") == "oauth:devin"

    # Maps direct providers
    assert provider_to_route_id("openai") == "direct:openai"
    assert provider_to_route_id("aistudio") == "direct:aistudio"
    assert provider_to_route_id("zen") == "direct:zen-paid"
    assert provider_to_route_id("zen-free") == "direct:zen-paid"

    # Default
    assert provider_to_route_id(None) == DEFAULT_ROUTE_ID
    assert provider_to_route_id("") == DEFAULT_ROUTE_ID


def test_format_and_parse_route_model_id():
    """Test formatting and parsing route-qualified model IDs, including slash-containing models."""
    # Basic model
    model_id = format_route_model_id("oauth:codex", "gpt-4o")
    assert model_id == "blm:oauth:codex/gpt-4o"
    assert parse_route_model_id(model_id) == ("oauth:codex", "gpt-4o")

    # Slash-containing upstream model names
    slash_model = format_route_model_id("endpoint:uuid-123", "meta-llama/llama-3-70b-instruct")
    assert slash_model == "blm:endpoint:uuid-123/meta-llama/llama-3-70b-instruct"
    route, upstream = parse_route_model_id(slash_model)
    assert route == "endpoint:uuid-123"
    assert upstream == "meta-llama/llama-3-70b-instruct"

    # Multiple slashes in upstream model
    multi_slash = "blm:direct:openrouter/org/sub/model-name:v1"
    route_ms, upstream_ms = parse_route_model_id(multi_slash)
    assert route_ms == "direct:openrouter"
    assert upstream_ms == "org/sub/model-name:v1"

    # Predicate helper
    assert is_route_model_id("blm:oauth:codex/gpt-4o") is True
    assert is_route_model_id("blm:endpoint:custom/deepseek-ai/DeepSeek-V3") is True
    assert is_route_model_id("gpt-4o") is False
    assert is_route_model_id("blm:invalid") is False
    assert is_route_model_id("") is False
    assert is_route_model_id(None) is False

    # Error cases
    with pytest.raises(ValueError):
        parse_route_model_id("gpt-4o")  # missing blm:
    with pytest.raises(ValueError):
        parse_route_model_id("blm:oauth:codex")  # missing slash
    with pytest.raises(ValueError):
        parse_route_model_id("blm:/gpt-4o")  # empty route
    with pytest.raises(ValueError):
        parse_route_model_id("blm:oauth:codex/")  # empty model
    with pytest.raises(ValueError):
        format_route_model_id("", "gpt-4o")
    with pytest.raises(ValueError):
        format_route_model_id("oauth:codex", "")


def test_map_legacy_model_to_route():
    """Test mapping bare legacy model strings and stale route models to target route."""
    # Bare string
    assert map_legacy_model_to_route("gpt-4o", "oauth:codex") == "blm:oauth:codex/gpt-4o"
    assert map_legacy_model_to_route("gemini-3.8-flash-low", "oauth:antigravity") == "blm:oauth:antigravity/gemini-3.8-flash-low"

    # Already qualified for the same route
    assert map_legacy_model_to_route("blm:oauth:codex/gpt-4o", "oauth:codex") == "blm:oauth:codex/gpt-4o"

    # Stale/cross route remapping
    stale = "blm:oauth:antigravity/gemini-3.8-flash-low"
    assert map_legacy_model_to_route(stale, "oauth:codex") == "blm:oauth:codex/gemini-3.8-flash-low"

    # Stale route with slash-containing model
    stale_slash = "blm:endpoint:old-route/meta-llama/llama-3-70b-instruct"
    assert map_legacy_model_to_route(stale_slash, "endpoint:new-route") == "blm:endpoint:new-route/meta-llama/llama-3-70b-instruct"

    # None or empty maps to route default
    assert map_legacy_model_to_route(None, "oauth:codex") == "blm:oauth:codex/gpt-4o"
    assert map_legacy_model_to_route("", "oauth:antigravity") == "blm:oauth:antigravity/gemini-3.8-flash-low"


def test_validate_and_ensure_model_for_route():
    """Test route model validation and catalog enforcement."""
    active_route = "oauth:codex"
    valid_model = "blm:oauth:codex/gpt-4o"
    other_route_model = "blm:oauth:antigravity/gpt-4o"
    bare_model = "gpt-4o"

    assert validate_model_for_route(valid_model, active_route) is True
    assert validate_model_for_route(other_route_model, active_route) is False
    assert validate_model_for_route(bare_model, active_route) is False
    assert validate_model_for_route(None, active_route) is False

    # Allowed catalog filtering
    catalog = ["gpt-4o", "o1", "o3-mini"]
    assert validate_model_for_route(valid_model, active_route, allowed_models=catalog) is True
    assert validate_model_for_route("blm:oauth:codex/unknown-model", active_route, allowed_models=catalog) is False

    # ensure_model_belongs_to_route
    r, m = ensure_model_belongs_to_route(valid_model, active_route, allowed_models=catalog)
    assert r == "oauth:codex"
    assert m == "gpt-4o"

    with pytest.raises(ValueError):
        ensure_model_belongs_to_route(other_route_model, active_route)
    with pytest.raises(ValueError):
        ensure_model_belongs_to_route("blm:oauth:codex/disallowed", active_route, allowed_models=catalog)


# ---------------------------------------------------------------------------
# Database Seeding and Model Persistence Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_database_route_seeding_and_idempotency(tmp_path):
    """Test that seed_oauth_routes creates the 8 OAuth routes idempotently."""
    db_file = tmp_path / "test_seed.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", echo=False)

    from app.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # First seeding
    async with session_factory() as session:
        routes = await seed_oauth_routes(session)
        assert len(routes) == 8
        providers = {r.provider for r in routes}
        assert providers == set(OAUTH_PROVIDERS)
        for r in routes:
            assert r.kind == "oauth"
            assert r.enabled is True
            assert r.proxy_prefix == compute_oauth_proxy_prefix(r.id)

    # Second seeding (idempotent â€” no new rows, no errors)
    async with session_factory() as session:
        routes2 = await seed_oauth_routes(session)
        assert len(routes2) == 8
        all_routes = (await session.execute(select(AIProviderRoute))).scalars().all()
        assert len(all_routes) == 8

    await engine.dispose()


@pytest.mark.asyncio
async def test_route_and_credential_relationships(tmp_path):
    """Test SQLAlchemy models for AIProviderRoute and AIProviderCredential."""
    db_file = tmp_path / "test_models.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", echo=False)

    from app.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as session:
        route = AIProviderRoute(
            id="oauth:codex",
            kind="oauth",
            provider="codex",
            display_label="Codex",
            proxy_prefix="blm-43acc341bd709366",
            enabled=True,
            config_json="{}",
        )
        session.add(route)
        await session.flush()

        cred = AIProviderCredential(
            id="cred_1",
            route_id="oauth:codex",
            kind="oauth",
            vault_reference="oauth_auth:oauth:codex",
            proxy_credential_name="codex-user1.json",
            masked_identity="user@example.com",
            priority=1,
            weight=10,
            enabled=True,
            status="active",
        )
        session.add(cred)
        await session.commit()

    async with session_factory() as session:
        loaded_route = (
            await session.execute(
                select(AIProviderRoute).where(AIProviderRoute.id == "oauth:codex")
            )
        ).scalar_one()

        assert len(loaded_route.credentials) == 1
        c = loaded_route.credentials[0]
        assert c.masked_identity == "user@example.com"
        assert c.masked_label == "user@example.com"
        assert c.vault_ref == "oauth_auth:oauth:codex"
        assert c.status == "active"
        assert c.weight == 10

    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_active_route_id(tmp_path):
    """Test resolving active route from system_config and defaults."""
    db_file = tmp_path / "test_active_route.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}", echo=False)

    from app.database import Base
    from app.models.system_config import SystemConfig

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # 1. Without system_config setting -> defaults to aistudio
    async with session_factory() as session:
        route = await resolve_active_route_id(session)
        assert route.startswith("direct:")

    # 2. With legacy 'gemini' set in system_config -> resolves to oauth:antigravity
    async with session_factory() as session:
        session.add(SystemConfig(key="ai.provider", value="gemini"))
        await session.commit()
        route = await resolve_active_route_id(session)
        assert route == "oauth:antigravity"

    # 3. With explicit route ID set in system_config -> resolves to that route
    async with session_factory() as session:
        cfg = (
            await session.execute(select(SystemConfig).where(SystemConfig.key == "ai.provider"))
        ).scalar_one()
        cfg.value = "oauth:codex"
        await session.commit()
        route = await resolve_active_route_id(session)
        assert route == "oauth:codex"

    await engine.dispose()

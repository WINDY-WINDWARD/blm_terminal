"""Unit and lifecycle tests for ProxySupervisor and ProxyManagementClient."""

import asyncio
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.provider_vault import ProviderVault, VaultState, VaultUnavailableError
from app.services.proxy_supervisor import (
    ProcessCrashedError,
    ProxyManagementClient,
    ProxySupervisor,
    ProxySupervisorError,
    ReadinessTimeoutError,
    SupervisorState,
    cleanup_stale_runtimes,
    find_free_loopback_port,
    generate_proxy_config,
    materialize_vault_secrets,
    redact_sensitive_data,
    set_dir_permissions_0700,
    set_file_permissions_0600,
    sync_auth_and_cooldowns,
)


@pytest.fixture
def mock_vault(tmp_path):
    """Create a test ProviderVault in available state."""
    vault = ProviderVault(vault_path=tmp_path / "test_vault.enc", key=b"0" * 32)
    # Pre-populate some secrets
    vault._data = {
        "version": 1,
        "oauth_auth": {
            "codex": {"access_token": "token-123", "refresh_token": "refresh-456"},
            "antigravity.json": {"session": "sess-789"},
        },
        "endpoint_headers": {},
        "endpoint_keys": {},
        "cooldown_snapshots": {
            "codex": {"status": "cooling", "until": 1800000000},
            "antigravity.cds": {"status": "active"},
        },
        "entries": {},
    }
    vault._state = VaultState.AVAILABLE
    vault._initialized = True
    return vault


def test_generate_proxy_config_flags():
    """Verify generated YAML config satisfies all required flags and contains no leaked secrets."""
    config_yaml = generate_proxy_config(
        host="127.0.0.1",
        port=8317,
        client_key="test-client-secret-key-123",
        management_key="test-mgmt-secret-key-456",
        auth_dir="/path/to/runtime/auth",
        strategy="fill-first",
    )

    assert "config-version: 8" in config_yaml
    assert 'host: "127.0.0.1"' in config_yaml
    assert "port: 8317" in config_yaml
    assert "allow-remote: false" in config_yaml
    assert "disable-control-panel: true" in config_yaml
    assert 'strategy: "fill-first"' in config_yaml
    assert "session-affinity: true" in config_yaml
    assert 'session-affinity-ttl: "1h"' in config_yaml
    assert "force-model-prefix: true" in config_yaml
    assert "save-cooldown-status: true" in config_yaml
    assert "request-retry: 3" in config_yaml
    assert "max-retry-credentials: 0" in config_yaml
    assert "max-retry-interval: 30" in config_yaml
    assert 'auth-dir: "/path/to/runtime/auth"' in config_yaml or "auth-dir:" in config_yaml

    # No upstream OAuth or user secrets leaked
    assert "token-123" not in config_yaml
    assert "refresh-456" not in config_yaml


def test_redact_sensitive_data():
    """Ensure sensitive credentials, tokens, and keys are masked."""
    payload = {
        "secret-key": "super-secret-mgmt-key",
        "client_key": "local-client-key",
        "api-keys": ["key-1", "key-2"],
        "authorization": "Bearer secret-token",
        "normal_field": "public-value",
        "nested": {
            "token": "sensitive-oauth-token",
            "info": "ok",
        },
    }
    redacted = redact_sensitive_data(payload)
    assert redacted["secret-key"] == "[REDACTED]"
    assert redacted["client_key"] == "[REDACTED]"
    assert redacted["api-keys"] == "[REDACTED]"
    assert redacted["authorization"] == "[REDACTED]"
    assert redacted["normal_field"] == "public-value"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["info"] == "ok"


def test_permissions_helpers(tmp_path):
    """Test 0700 dir and 0600 file permission enforcement."""
    test_dir = tmp_path / "perm_dir"
    test_dir.mkdir()
    set_dir_permissions_0700(test_dir)

    test_file = test_dir / "perm_file.txt"
    test_file.write_text("secure data", encoding="utf-8")
    set_file_permissions_0600(test_file)

    if os.name != "nt":
        dir_mode = stat.S_IMODE(test_dir.stat().st_mode)
        file_mode = stat.S_IMODE(test_file.stat().st_mode)
        assert dir_mode == 0o700
        assert file_mode == 0o600
    else:
        # On Windows, verify file exists and is readable/writable by current process
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "secure data"


def test_find_free_loopback_port():
    """Verify ephemeral port allocation returns a non-zero valid port number."""
    port1 = find_free_loopback_port()
    assert 1024 <= port1 <= 65535


@pytest.mark.asyncio
async def test_materialize_and_sync_vault_secrets(mock_vault, tmp_path):
    """Verify pre-start materialization and post-run synchronization of auth and cooldown files."""
    auth_dir = tmp_path / "runtime_auth"

    # 1. Materialize
    count = await materialize_vault_secrets(mock_vault, auth_dir)
    assert count == 4  # 2 oauth auth + 2 cooldowns

    codex_json = auth_dir / "codex.json"
    antigravity_json = auth_dir / "antigravity.json"
    codex_cds = auth_dir / "codex.cds"
    antigravity_cds = auth_dir / "antigravity.cds"

    assert codex_json.exists()
    assert antigravity_json.exists()
    assert codex_cds.exists()
    assert antigravity_cds.exists()

    codex_data = json.loads(codex_json.read_text(encoding="utf-8"))
    assert codex_data["access_token"] == "token-123"

    # 2. Simulate CLIProxyAPI refreshing tokens and updating cooldown on disk
    codex_data["access_token"] = "refreshed-token-999"
    codex_json.write_text(json.dumps(codex_data), encoding="utf-8")

    new_cds = {"status": "cooling", "until": 2000000000}
    codex_cds.write_text(json.dumps(new_cds), encoding="utf-8")

    # Add a brand new credential generated by CLIProxyAPI OAuth
    new_auth = auth_dir / "claude.json"
    new_auth.write_text(json.dumps({"oauth_key": "claude-token-abc"}), encoding="utf-8")

    # 3. Sync back to vault
    synced_count = await sync_auth_and_cooldowns(mock_vault, auth_dir)
    assert synced_count >= 3

    # Check updated vault content
    updated_codex = await mock_vault.get_oauth_auth("codex.json")
    assert updated_codex["access_token"] == "refreshed-token-999"

    updated_cds = await mock_vault.get_cooldown_snapshot("codex.cds")
    assert updated_cds["until"] == 2000000000

    new_claude = await mock_vault.get_oauth_auth("claude.json")
    assert new_claude["oauth_key"] == "claude-token-abc"


def test_cleanup_stale_runtimes(tmp_path):
    """Ensure stale run-* directories from non-existent PIDs are removed."""
    runtime_root = tmp_path / "cliproxy-runtime"
    runtime_root.mkdir()

    # Dead PID directory (999999999 is overwhelmingly dead)
    dead_dir = runtime_root / "run-999999999-abcd1234"
    dead_dir.mkdir()
    (dead_dir / "config.yaml").write_text("old", encoding="utf-8")

    # Non-numeric / malformed directory
    bad_dir = runtime_root / "run-invalid-pid"
    bad_dir.mkdir()

    # Living process directory (current test PID)
    live_dir = runtime_root / f"run-{os.getpid()}-live1234"
    live_dir.mkdir()

    cleaned = cleanup_stale_runtimes(runtime_root)
    assert cleaned >= 2
    assert not dead_dir.exists()
    assert not bad_dir.exists()
    assert live_dir.exists()  # Own living PID is preserved


@pytest.mark.asyncio
async def test_supervisor_lazy_start_and_vault_requirement(tmp_path):
    """Verify supervisor does not start until ensure_started() and requires AVAILABLE vault."""
    vault = ProviderVault(vault_path=tmp_path / "unavail.enc", key=None)
    vault._state = VaultState.KEYRING_UNAVAILABLE
    vault._initialized = True

    supervisor = ProxySupervisor(vault=vault, runtime_root=tmp_path / "runtime")
    assert supervisor.state == SupervisorState.STOPPED
    assert not supervisor.is_running

    with pytest.raises(VaultUnavailableError, match="vault is not available"):
        await supervisor.ensure_started()

    assert supervisor.state == SupervisorState.STOPPED


@pytest.mark.asyncio
async def test_supervisor_mocked_lifecycle(mock_vault, tmp_path):
    """Verify full supervisor lifecycle: lazy start, readiness polling, status reporting, and graceful cleanup."""
    fake_bin = tmp_path / "fake_cliproxyapi.exe"
    fake_bin.write_text("fake binary content", encoding="utf-8")

    runtime_root = tmp_path / "runtime_root"

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=runtime_root,
        readiness_timeout=3.0,
    )

    # Mock subprocess.Popen and readiness polling
    mock_proc = MagicMock()
    mock_proc.pid = 4242
    mock_proc.poll.return_value = None  # Process is running

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(supervisor, "_poll_readiness", new_callable=AsyncMock) as mock_ready:
            mock_ready.return_value = True

            host, port, client_key = await supervisor.ensure_started()

            assert host == "127.0.0.1"
            assert isinstance(port, int)
            assert port > 0
            assert len(client_key) >= 32
            assert supervisor.state == SupervisorState.RUNNING
            assert supervisor.is_running

            # Status does not leak secret keys
            status = supervisor.get_status()
            assert status["state"] == "running"
            assert status["port"] == port
            assert status["pid"] == 4242
            assert "client_key" not in status
            assert "management_key" not in status

            # Ensure config was created and permissions set
            assert supervisor.runtime_dir is not None
            assert supervisor.runtime_dir.exists()
            config_file = supervisor.runtime_dir / "config.yaml"
            assert config_file.exists()

            # Test management client creation
            mgmt_client = supervisor.get_management_client()
            assert mgmt_client is not None
            assert "secret" not in repr(mgmt_client)

            # Test graceful stop
            await supervisor.stop()

            assert supervisor.state == SupervisorState.STOPPED
            assert not supervisor.is_running
            assert supervisor.port is None
            assert supervisor.client_key is None
            # Runtime dir should be removed
            if supervisor.runtime_dir:
                assert not supervisor.runtime_dir.exists()


@pytest.mark.asyncio
async def test_supervisor_readiness_failure(mock_vault, tmp_path):
    """Verify supervisor transitions to CRASHED when readiness check fails or times out."""
    fake_bin = tmp_path / "fake_cliproxyapi.exe"
    fake_bin.write_text("fake binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        readiness_timeout=0.2,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.poll.return_value = 1  # Exited immediately
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = "bind: address already in use"

    with patch("subprocess.Popen", return_value=mock_proc):
        with pytest.raises(ReadinessTimeoutError, match="CLIProxyAPI failed readiness check"):
            await supervisor.ensure_started()

        assert supervisor.state == SupervisorState.CRASHED
        status = supervisor.get_status()
        assert status["state"] == "crashed"
        assert "address already in use" in status["last_error"]


@pytest.mark.asyncio
async def test_supervisor_bounded_restart_backoff(mock_vault, tmp_path):
    """Verify bounded restart with backoff when running process dies unexpectedly."""
    fake_bin = tmp_path / "fake_bin.exe"
    fake_bin.write_text("binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        max_restarts=2,
    )
    supervisor._state = SupervisorState.RUNNING

    # Mock dead process
    mock_proc = MagicMock()
    mock_proc.poll.return_value = -9
    mock_proc.returncode = -9
    supervisor._process = mock_proc

    # Simulate restarts failing
    with patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock) as mock_start:
        mock_start.side_effect = Exception("Restart boot failed")

        restarted = await supervisor.restart_if_crashed()
        assert not restarted
        assert supervisor._restart_count == 1

        restarted = await supervisor.restart_if_crashed()
        assert not restarted
        assert supervisor._restart_count == 2

        # Exceeded max restarts
        restarted = await supervisor.restart_if_crashed()
        assert not restarted
        assert supervisor.state == SupervisorState.CRASHED
        assert "Max restarts" in supervisor.get_status()["last_error"]


@pytest.mark.asyncio
async def test_proxy_management_client_redaction_and_headers():
    """Verify ProxyManagementClient constructs correct headers, masks keys, and redacts sensitive data."""
    client = ProxyManagementClient(
        base_url="http://127.0.0.1:8317",
        management_key="super-secret-mgmt-token-32-chars",
    )

    # 1. Masked string representation
    rep = repr(client)
    assert "super-secret-mgmt-token" not in rep
    assert "key_len=32" in rep

    # 2. Correct headers
    headers = client._get_headers()
    assert headers["Authorization"] == "Bearer super-secret-mgmt-token-32-chars"
    assert headers["X-Management-Key"] == "super-secret-mgmt-token-32-chars"

    # 3. Mocked health check
    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_http.get = AsyncMock(return_value=mock_resp)

    client._client = mock_http
    assert await client.health() is True
    mock_http.get.assert_called_with("http://127.0.0.1:8317/healthz")

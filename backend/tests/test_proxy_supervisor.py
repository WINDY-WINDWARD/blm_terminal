"""Unit and lifecycle tests for ProxySupervisor and ProxyManagementClient."""

import asyncio
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.provider_vault import ProviderVault, VaultState, VaultUnavailableError
from app.services.proxy_supervisor import (
    ProcessCrashError,
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
    # Pre-populate some secrets (both extensionless and extension-bearing keys)
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
    assert "host: 127.0.0.1" in config_yaml
    assert "port: 8317" in config_yaml
    assert "allow-remote: false" in config_yaml
    assert "disable-control-panel: true" in config_yaml
    assert "strategy: fill-first" in config_yaml
    assert "session-affinity: true" in config_yaml
    assert "session-affinity-ttl: 1h" in config_yaml
    assert "force-model-prefix: true" in config_yaml
    assert "save-cooldown-status: true" in config_yaml
    assert "request-retry: 3" in config_yaml
    assert "max-retry-credentials: 0" in config_yaml
    assert "max-retry-interval: 30" in config_yaml
    assert "auth-dir:" in config_yaml

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
        assert test_file.exists()
        assert test_file.read_text(encoding="utf-8") == "secure data"


def test_find_free_loopback_port():
    """Verify ephemeral port allocation returns a non-zero valid port number."""
    port1 = find_free_loopback_port()
    assert 1024 <= port1 <= 65535


@pytest.mark.asyncio
async def test_materialize_and_sync_vault_secrets_reversible_mapping(mock_vault, tmp_path):
    """Verify materialization and reversible sync mapping for extensionless and extension-bearing keys."""
    auth_dir = tmp_path / "runtime_auth"

    # 1. Materialize: 2 oauth auth + 2 cooldowns
    count = await materialize_vault_secrets(mock_vault, auth_dir)
    assert count == 4

    codex_json = auth_dir / "codex.json"
    antigravity_json = auth_dir / "antigravity.json"
    codex_cds = auth_dir / "codex.cds"
    antigravity_cds = auth_dir / "antigravity.cds"

    assert codex_json.exists()
    assert antigravity_json.exists()
    assert codex_cds.exists()
    assert antigravity_cds.exists()

    # 2. Simulate refresh modifications
    codex_data = json.loads(codex_json.read_text(encoding="utf-8"))
    codex_data["access_token"] = "refreshed-token-999"
    codex_json.write_text(json.dumps(codex_data), encoding="utf-8")

    ag_data = json.loads(antigravity_json.read_text(encoding="utf-8"))
    ag_data["session"] = "refreshed-ag-sess"
    antigravity_json.write_text(json.dumps(ag_data), encoding="utf-8")

    new_cds = {"status": "cooling", "until": 2000000000}
    codex_cds.write_text(json.dumps(new_cds), encoding="utf-8")

    new_ag_cds = {"status": "cooldown_active"}
    antigravity_cds.write_text(json.dumps(new_ag_cds), encoding="utf-8")

    # Add a brand new credential (not previously in vault)
    new_auth = auth_dir / "claude.json"
    new_auth.write_text(json.dumps({"oauth_key": "claude-token-abc"}), encoding="utf-8")

    # 3. Sync back to vault
    synced_count = await sync_auth_and_cooldowns(mock_vault, auth_dir)
    assert synced_count >= 5

    # Extensionless key "codex" was updated under "codex", NOT duplicated as "codex.json"
    all_auth = await mock_vault.get_all_oauth_auth()
    assert "codex" in all_auth
    assert "codex.json" not in all_auth
    assert all_auth["codex"]["access_token"] == "refreshed-token-999"

    # Extension-bearing key "antigravity.json" was preserved under "antigravity.json"
    assert "antigravity.json" in all_auth
    assert all_auth["antigravity.json"]["session"] == "refreshed-ag-sess"

    # Brand new credential stored as exact filename "claude.json"
    assert "claude.json" in all_auth
    assert all_auth["claude.json"]["oauth_key"] == "claude-token-abc"

    # Extensionless cooldown key "codex" was updated under "codex", NOT "codex.cds"
    all_cds = await mock_vault.get_all_cooldown_snapshots()
    assert "codex" in all_cds
    assert "codex.cds" not in all_cds
    assert all_cds["codex"]["until"] == 2000000000

    # Extension-bearing cooldown key "antigravity.cds" preserved
    assert "antigravity.cds" in all_cds
    assert all_cds["antigravity.cds"]["status"] == "cooldown_active"


def test_cleanup_stale_runtimes_with_cliproxy_pid_and_active_preservation(tmp_path):
    """Test orphan cleanup with cliproxy.pid, PID-reuse prevention, and active runtime preservation."""
    runtime_root = tmp_path / "cliproxy-runtime"
    runtime_root.mkdir()

    # 1. Stale dir with dead parent PID and verified orphaned cliproxy child process
    orphan_dir = runtime_root / "run-999999991-dead1234"
    orphan_dir.mkdir()
    (orphan_dir / "config.yaml").write_text("old", encoding="utf-8")
    (orphan_dir / "cliproxy.pid").write_text("8888", encoding="utf-8")

    # 2. Stale dir with PID-reuse hazard: child PID belongs to unrelated non-cliproxy process
    reuse_dir = runtime_root / "run-999999992-dead5678"
    reuse_dir.mkdir()
    (reuse_dir / "cliproxy.pid").write_text("7777", encoding="utf-8")

    # 3. Active runtime dir to preserve
    active_dir = runtime_root / f"run-{os.getpid()}-active001"
    active_dir.mkdir()
    (active_dir / "cliproxy.pid").write_text("6666", encoding="utf-8")

    mock_cliproxy_proc = MagicMock()
    mock_cliproxy_proc.name.return_value = "cliproxyapi.exe"
    mock_cliproxy_proc.cmdline.return_value = ["cliproxyapi.exe", "--config", "config.yaml"]

    mock_unrelated_proc = MagicMock()
    mock_unrelated_proc.name.return_value = "notepad.exe"
    mock_unrelated_proc.cmdline.return_value = ["notepad.exe"]

    def mock_pid_exists(pid):
        return pid in (8888, 7777, 6666)

    def mock_process_factory(pid):
        if pid == 8888:
            return mock_cliproxy_proc
        elif pid == 7777:
            return mock_unrelated_proc
        raise ValueError(f"Unknown mock PID {pid}")

    with patch("psutil.pid_exists", side_effect=mock_pid_exists):
        with patch("psutil.Process", side_effect=mock_process_factory):
            cleaned = cleanup_stale_runtimes(runtime_root, active_runtime_dir=active_dir)

            assert cleaned == 2
            # Orphan directory was cleaned up and orphaned cliproxy process was terminated
            assert not orphan_dir.exists()
            mock_cliproxy_proc.terminate.assert_called_once()

            # Reuse directory was cleaned up, but unrelated process was NOT killed
            assert not reuse_dir.exists()
            mock_unrelated_proc.terminate.assert_not_called()

            # Active runtime directory was preserved
            assert active_dir.exists()


@pytest.mark.asyncio
async def test_supervisor_lazy_start_and_vault_requirement(tmp_path):
    """Verify supervisor does not start until ensure_started() and requires AVAILABLE vault."""
    vault = ProviderVault(vault_path=tmp_path / "unavail.enc", key=None)
    vault._state = VaultState.KEYRING_UNAVAILABLE
    vault._initialized = True

    supervisor = ProxySupervisor(vault=vault, runtime_root=tmp_path / "runtime")
    assert supervisor.state == SupervisorState.STOPPED

    with pytest.raises(VaultUnavailableError, match="vault is not available"):
        await supervisor.ensure_started()

    assert supervisor.state == SupervisorState.STOPPED


@pytest.mark.asyncio
async def test_supervisor_mocked_lifecycle(mock_vault, tmp_path):
    """Test full supervisor lifecycle: ensure_started, pid recording, readiness, management client, and stop."""
    fake_bin = tmp_path / "fake_cliproxyapi.exe"
    fake_bin.write_text("fake binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        readiness_timeout=2.0,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 4242
    mock_proc.poll.return_value = None  # Process is running

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

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

            # Verify cliproxy.pid file was recorded with child PID
            assert supervisor.runtime_dir is not None
            assert supervisor.runtime_dir.exists()
            pid_file = supervisor.runtime_dir / "cliproxy.pid"
            assert pid_file.exists()
            assert pid_file.read_text(encoding="utf-8").strip() == "4242"

            # Ensure config was created and permissions set
            config_file = supervisor.runtime_dir / "config.yaml"
            assert config_file.exists()

            # Test management client creation
            mgmt_client = supervisor.get_management_client()
            assert mgmt_client is not None
            assert "secret" not in repr(mgmt_client)

            # Test graceful stop cleans runtime dir
            runtime_dir = supervisor.runtime_dir
            await supervisor.stop()

            assert supervisor.state == SupervisorState.STOPPED
            assert not supervisor.is_running
            assert supervisor.port is None
            assert supervisor.client_key is None
            assert not runtime_dir.exists()


@pytest.mark.asyncio
async def test_supervisor_readiness_timeout_unresponsive_child(mock_vault, tmp_path):
    """Verify readiness timeout terminates a live unresponsive child without blocking event loop."""
    fake_bin = tmp_path / "fake_cliproxyapi.exe"
    fake_bin.write_text("fake binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        readiness_timeout=0.15,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    # Simulate child is ALIVE during polling, but exits after terminate
    poll_results = [None, None, None, None, -15]
    def mock_poll():
        if poll_results:
            return poll_results.pop(0)
        return -15

    mock_proc.poll = MagicMock(side_effect=mock_poll)
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = "timeout on init"

    with patch("subprocess.Popen", return_value=mock_proc):
        with pytest.raises(ReadinessTimeoutError, match="CLIProxyAPI failed readiness check"):
            # If stderr.read() or cleanup were blocking the event loop, this would hang
            await asyncio.wait_for(supervisor.ensure_started(), timeout=3.0)

        assert supervisor.state == SupervisorState.CRASHED
        mock_proc.terminate.assert_called()


@pytest.mark.asyncio
async def test_supervisor_stop_cleans_runtime_on_crashed_or_failed_readiness(mock_vault, tmp_path):
    """Ensure stop() removes runtime dir and plaintext secrets even in CRASHED/failed-readiness state."""
    fake_bin = tmp_path / "fake_cliproxyapi.exe"
    fake_bin.write_text("fake binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        readiness_timeout=0.1,
    )

    mock_proc = MagicMock()
    mock_proc.pid = 9876
    mock_proc.poll.return_value = 1
    mock_proc.stderr = MagicMock()
    mock_proc.stderr.read.return_value = "fatal crash"

    with patch("subprocess.Popen", return_value=mock_proc):
        with pytest.raises(ReadinessTimeoutError):
            await supervisor.ensure_started()

    assert supervisor.state == SupervisorState.CRASHED
    assert supervisor.runtime_dir is not None
    assert supervisor.runtime_dir.exists()
    assert (supervisor.runtime_dir / "auth").exists()

    # Call stop on crashed supervisor
    runtime_dir = supervisor.runtime_dir
    await supervisor.stop()

    assert supervisor.state == SupervisorState.STOPPED
    assert not runtime_dir.exists()


@pytest.mark.asyncio
async def test_supervisor_ensure_started_restarts_dead_child(mock_vault, tmp_path):
    """Verify dead running child is detected and restarted through ensure_started() with runtime cleanup."""
    fake_bin = tmp_path / "fake_bin.exe"
    fake_bin.write_text("binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        readiness_timeout=1.0,
        max_restarts=2,
    )

    proc1 = MagicMock()
    proc1.pid = 1111
    proc1.poll.return_value = None  # Alive initially

    proc2 = MagicMock()
    proc2.pid = 2222
    proc2.poll.return_value = None  # Replacement is alive

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("subprocess.Popen", side_effect=[proc1, proc2]):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            # 1. Initial successful start
            h1, p1, k1 = await supervisor.ensure_started()
            assert supervisor.is_running
            dir1 = supervisor.runtime_dir
            assert dir1.exists()

            # 2. Child dies unexpectedly while supervisor is RUNNING
            proc1.poll.return_value = 1
            proc1.returncode = 1
            assert not supervisor.is_running

            # 3. Next call to ensure_started() detects dead child, cleans up dir1, and restarts
            h2, p2, k2 = await supervisor.ensure_started()
            assert supervisor.is_running
            assert supervisor.pid == 2222
            dir2 = supervisor.runtime_dir
            assert dir2.exists()
            assert dir1 != dir2
            assert not dir1.exists()


@pytest.mark.asyncio
async def test_supervisor_bounded_restart_max_restarts_exceeded(mock_vault, tmp_path):
    """Verify bounded restart stops after max_restarts and raises ProcessCrashError."""
    fake_bin = tmp_path / "fake_bin.exe"
    fake_bin.write_text("binary", encoding="utf-8")

    supervisor = ProxySupervisor(
        vault=mock_vault,
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        max_restarts=2,
    )

    dead_proc = MagicMock()
    dead_proc.pid = 3333
    dead_proc.poll.return_value = -9
    dead_proc.returncode = -9
    supervisor._process = dead_proc
    supervisor._state = SupervisorState.RUNNING

    with patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock) as mock_start:
        mock_start.side_effect = Exception("Boot error")

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


@pytest.mark.asyncio
async def test_model_cache_invalidated_on_lifecycle_events(tmp_path, mock_vault):
    """Verify _MODEL_CACHE entries are cleared on restart, stop, and _start_unlocked."""
    from app.services.proxy_supervisor import _MODEL_CACHE

    fake_bin = tmp_path / ("cliproxy.exe" if sys.platform == "win32" else "cliproxy")
    fake_bin.touch()

    supervisor = ProxySupervisor(
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        vault=mock_vault,
    )

    sup_id = id(supervisor)
    _MODEL_CACHE[(sup_id, "antigravity")] = (100.0, ("model-a", "model-b"))
    _MODEL_CACHE[(99999999, "other")] = (100.0, ("other-model",))

    # Test stop invalidates
    supervisor._invalidate_model_cache()
    assert (sup_id, "antigravity") not in _MODEL_CACHE
    assert (99999999, "other") in _MODEL_CACHE

    # Populate again
    _MODEL_CACHE[(sup_id, "antigravity")] = (200.0, ("model-a",))

    # Mock _cleanup_process, _cancel_sync, sync_auth_and_cooldowns, _start_unlocked for restart
    with patch.object(supervisor, "_cleanup_process", new_callable=AsyncMock), \
         patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock), \
         patch.object(supervisor, "_cancel_sync", new_callable=AsyncMock):
        await supervisor.restart()

    assert (sup_id, "antigravity") not in _MODEL_CACHE

    # Populate again
    _MODEL_CACHE[(sup_id, "antigravity")] = (300.0, ("model-a",))
    with patch.object(supervisor, "_cleanup_process", new_callable=AsyncMock), \
         patch.object(supervisor, "_cancel_sync", new_callable=AsyncMock):
        await supervisor.stop()

    assert (sup_id, "antigravity") not in _MODEL_CACHE
    _MODEL_CACHE.pop((99999999, "other"), None)


@pytest.mark.asyncio
async def test_recover_suppresses_restart_during_oauth_flow(tmp_path, mock_vault):
    fake_bin = tmp_path / ("cliproxy.exe" if sys.platform == "win32" else "cliproxy")
    fake_bin.touch()

    supervisor = ProxySupervisor(
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        vault=mock_vault,
    )
    supervisor._state = SupervisorState.RUNNING
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    supervisor._process = mock_proc
    supervisor._port = 9999
    supervisor._client_key = "test-client-key"
    expected_endpoint = (supervisor._host, supervisor._port, supervisor._client_key)

    supervisor.hold_oauth_flow(seconds=300.0)

    with patch.object(supervisor, "_cleanup_process", new_callable=AsyncMock) as mock_cleanup, \
         patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock) as mock_start:
        res = await supervisor.recover("first_event_timeout", preserve_oauth_flow=True)

    assert res == expected_endpoint
    mock_cleanup.assert_not_called()
    mock_start.assert_not_called()
    assert supervisor._last_suppressed_reason == "first_event_timeout"
    assert supervisor._last_recovery_reason == ""
    assert supervisor._recovery_count == 0


@pytest.mark.asyncio
async def test_recover_restarts_and_records_reason(tmp_path, mock_vault):
    from app.services.proxy_supervisor import _MODEL_CACHE

    fake_bin = tmp_path / ("cliproxy.exe" if sys.platform == "win32" else "cliproxy")
    fake_bin.touch()

    supervisor = ProxySupervisor(
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        vault=mock_vault,
    )
    supervisor._state = SupervisorState.RUNNING
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    supervisor._process = mock_proc
    supervisor._port = 9999
    supervisor._client_key = "test-client-key"

    supervisor.hold_oauth_flow(seconds=300.0)

    sup_id = id(supervisor)
    _MODEL_CACHE[(sup_id, "antigravity")] = (100.0, ("model-a",))

    with patch.object(supervisor, "_cleanup_process", new_callable=AsyncMock) as mock_cleanup, \
         patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock) as mock_start, \
         patch.object(supervisor, "_cancel_sync", new_callable=AsyncMock):
        res = await supervisor.recover("first_event_timeout", preserve_oauth_flow=False)

    mock_cleanup.assert_called_once()
    mock_start.assert_called_once()
    assert supervisor._recovery_count == 1
    assert supervisor._last_recovery_reason == "first_event_timeout"
    assert (sup_id, "antigravity") not in _MODEL_CACHE


@pytest.mark.asyncio
async def test_restart_delegates_to_recover(tmp_path, mock_vault):
    fake_bin = tmp_path / ("cliproxy.exe" if sys.platform == "win32" else "cliproxy")
    fake_bin.touch()

    supervisor = ProxySupervisor(
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        vault=mock_vault,
    )
    supervisor._port = 8317
    supervisor._client_key = "client-key"

    with patch.object(supervisor, "_cleanup_process", new_callable=AsyncMock), \
         patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock), \
         patch.object(supervisor, "_cancel_sync", new_callable=AsyncMock):
        await supervisor.restart()

    assert supervisor._last_recovery_reason == "explicit_restart"
    assert supervisor._recovery_count == 1


@pytest.mark.asyncio
async def test_ensure_started_restarts_on_unresponsive_management_api(tmp_path, mock_vault):
    fake_bin = tmp_path / ("cliproxy.exe" if sys.platform == "win32" else "cliproxy")
    fake_bin.touch()

    supervisor = ProxySupervisor(
        bin_path=fake_bin,
        runtime_root=tmp_path / "runtime",
        vault=mock_vault,
    )
    supervisor._state = SupervisorState.RUNNING
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    supervisor._process = mock_proc
    supervisor._port = 8317
    supervisor._client_key = "client-key"

    with patch.object(supervisor, "_management_api_responsive", new_callable=AsyncMock, return_value=False), \
         patch.object(supervisor, "_cleanup_process", new_callable=AsyncMock), \
         patch.object(supervisor, "_start_unlocked", new_callable=AsyncMock), \
         patch.object(supervisor, "_cancel_sync", new_callable=AsyncMock):
        await supervisor.ensure_started()

    assert supervisor._last_recovery_reason == "management_unresponsive"
    assert supervisor._recovery_count == 1


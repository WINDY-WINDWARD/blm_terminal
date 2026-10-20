"""CLIProxyAPI packaging, supervisor, and lifecycle service.

Provides:
- Process supervisor for local CLIProxyAPI sidecar (v8 layout)
- Loopback-only ephemeral port binding and random client/management key generation
- 0700 runtime directory and 0600 file permission enforcement
- Pre-start vault secret materialization (OAuth auth JSON and .cds cooldown files)
- Readiness polling (/healthz), bounded restart with exponential backoff, and crash reporting
- Debounced and shutdown vault synchronization for refreshed auth JSON and .cds files
- Redacted internal management client (/v8/management)
- Stale runtime directory and orphaned process cleanup using psutil
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
import psutil

from app.config import settings
from app.services.provider_vault import (
    ProviderVault,
    VaultState,
    VaultUnavailableError,
    get_provider_vault,
)

logger = logging.getLogger("blm.proxy_supervisor")

SENSITIVE_FIELD_NAMES = {
    "secret-key",
    "secret_key",
    "management_key",
    "client_key",
    "api-keys",
    "api_keys",
    "authorization",
    "x-management-key",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "password",
}


class SupervisorState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    CRASHED = "crashed"
    STOPPING = "stopping"


class ProxySupervisorError(Exception):
    """Base error for CLIProxyAPI supervisor operations."""


class ProcessCrashedError(ProxySupervisorError):
    """Raised when the proxy process terminates unexpectedly."""


class ReadinessTimeoutError(ProxySupervisorError):
    """Raised when readiness check times out."""


def redact_sensitive_data(val: Any) -> Any:
    """Recursively redact sensitive keys from nested dicts/lists for safe logging and diagnostics."""
    if isinstance(val, dict):
        out = {}
        for k, v in val.items():
            if str(k).lower() in SENSITIVE_FIELD_NAMES:
                out[k] = "[REDACTED]"
            else:
                out[k] = redact_sensitive_data(v)
        return out
    elif isinstance(val, list):
        return [redact_sensitive_data(x) for x in val]
    return val


def set_dir_permissions_0700(path: Path) -> None:
    """Set 0700 (rwx------) permissions on directory."""
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass


def set_file_permissions_0600(path: Path) -> None:
    """Set 0600 (rw-------) permissions on file."""
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    else:
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


def find_free_loopback_port() -> int:
    """Find and return an available ephemeral loopback TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def resolve_cliproxy_bin() -> Path:
    """Resolve the CLIProxyAPI binary across environment and repository locations."""
    env_bin = os.environ.get("CLIPROXY_BIN")
    if env_bin:
        p = Path(env_bin).resolve()
        if p.exists() and p.is_file():
            return p

    is_win = sys.platform == "win32"
    bin_name = "cliproxyapi.exe" if is_win else "cliproxyapi"

    # 1. Local vendor staging directory
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    candidate = repo_root / "vendor" / "cliproxyapi" / "runtime" / bin_name
    if candidate.exists() and candidate.is_file():
        return candidate

    # 2. Packaged electron resources
    res_path = os.environ.get("RESOURCES_PATH")
    if res_path:
        cand1 = Path(res_path) / "resources" / "cliproxyapi" / bin_name
        if cand1.exists() and cand1.is_file():
            return cand1
        cand2 = Path(res_path) / "cliproxyapi" / bin_name
        if cand2.exists() and cand2.is_file():
            return cand2

    raise FileNotFoundError(
        f"CLIProxyAPI binary '{bin_name}' not found. Run scripts/stage_cliproxyapi to stage it."
    )


def generate_proxy_config(
    host: str,
    port: int,
    client_key: str,
    management_key: str,
    auth_dir: Path | str,
    strategy: str = "fill-first",
    session_affinity_ttl: str = "1h",
    request_retry: int = 3,
    max_retry_credentials: int = 0,
    max_retry_interval: int = 30,
) -> str:
    """Generate CLIProxyAPI v8 YAML configuration.

    Enforces:
    - allow-remote: false
    - disable-control-panel: true
    - force-model-prefix: true
    - save-cooldown-status: true
    - configured strategy (default fill-first)
    - sticky sessions enabled (session-affinity: true)
    - vetted retry defaults
    - zero upstream secrets written into config
    """
    auth_dir_str = str(Path(auth_dir).resolve()).replace("\\", "/")
    return f"""config-version: 8

server:
  host: "{host}"
  port: {port}

management:
  allow-remote: false
  secret-key: "{management_key}"
  disable-control-panel: true

access:
  api-keys:
    - "{client_key}"

routing:
  strategy: "{strategy}"
  session-affinity: true
  session-affinity-ttl: "{session_affinity_ttl}"
  force-model-prefix: true

  retry:
    request-retry: {request_retry}
    max-retry-credentials: {max_retry_credentials}
    max-retry-interval: {max_retry_interval}

  cooldown:
    save-cooldown-status: true

oauth:
  auth-dir: "{auth_dir_str}"
"""


async def materialize_vault_secrets(vault: ProviderVault, auth_dir: Path) -> int:
    """Materialize encrypted OAuth auth JSON and .cds cooldown files from vault to auth_dir."""
    auth_dir.mkdir(parents=True, exist_ok=True)
    set_dir_permissions_0700(auth_dir)
    count = 0

    # 1. OAuth auth files
    all_auth = await vault.get_all_oauth_auth()
    for key, data in all_auth.items():
        fname = key if key.endswith(".json") else f"{key}.json"
        target = auth_dir / fname
        content = json.dumps(data, indent=2) if isinstance(data, dict) else str(data)
        target.write_text(content, encoding="utf-8")
        set_file_permissions_0600(target)
        count += 1

    # 2. Cooldown status snapshots (.cds)
    all_cooldowns = await vault.get_all_cooldown_snapshots()
    for key, data in all_cooldowns.items():
        fname = key if key.endswith(".cds") else f"{key}.cds"
        target = auth_dir / fname
        content = json.dumps(data) if isinstance(data, dict) else str(data)
        target.write_text(content, encoding="utf-8")
        set_file_permissions_0600(target)
        count += 1

    return count


async def sync_auth_and_cooldowns(vault: ProviderVault, auth_dir: Path) -> int:
    """Scan auth_dir and sync refreshed OAuth auth JSON and .cds snapshots back into the vault."""
    if not auth_dir.exists():
        return 0
    count = 0

    # 1. OAuth auth JSON files
    for p in auth_dir.glob("*.json"):
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
            await vault.set_oauth_auth(p.name, data)
            count += 1
        except Exception as exc:
            logger.warning("ProxySupervisor: failed syncing %s to vault: %s", p.name, exc)

    # 2. Cooldown .cds snapshot files
    for p in auth_dir.glob("*.cds"):
        try:
            raw = p.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except Exception:
                data = raw
            await vault.set_cooldown_snapshot(p.name, data)
            count += 1
        except Exception as exc:
            logger.warning("ProxySupervisor: failed syncing %s to vault: %s", p.name, exc)

    return count


def cleanup_stale_runtimes(runtime_root: Path) -> int:
    """Detect and remove stale runtime directories and kill orphaned proxy processes."""
    if not runtime_root.exists():
        return 0
    cleaned = 0

    try:
        entries = list(runtime_root.iterdir())
    except OSError:
        return 0

    for item in entries:
        if not item.is_dir():
            continue
        parts = item.name.split("-")
        is_stale = False
        pid = None
        if len(parts) >= 3 and parts[0] == "run":
            try:
                pid = int(parts[1])
                if not psutil.pid_exists(pid):
                    is_stale = True
                else:
                    try:
                        p = psutil.Process(pid)
                        p_name = p.name().lower()
                        if "cliproxy" not in p_name and pid != os.getpid():
                            is_stale = True
                        elif "cliproxy" in p_name:
                            logger.info("Terminating orphaned proxy process pid=%d", pid)
                            p.terminate()
                            try:
                                p.wait(timeout=1.0)
                            except psutil.TimeoutExpired:
                                p.kill()
                            is_stale = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        is_stale = True
            except ValueError:
                is_stale = True
        else:
            is_stale = True

        if is_stale:
            try:
                shutil.rmtree(item, ignore_errors=True)
                cleaned += 1
                logger.info("Cleaned stale proxy runtime dir: %s", item.name)
            except Exception as exc:
                logger.debug("Failed removing stale dir %s: %s", item.name, exc)

    return cleaned


class ProxyManagementClient:
    """Redacted internal management client for CLIProxyAPI /v8/management."""

    def __init__(
        self,
        base_url: str,
        management_key: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._management_key = management_key
        self._client = client
        self._timeout = timeout

    def __repr__(self) -> str:
        # Never leak management key
        return f"<ProxyManagementClient base_url={self._base_url!r} key_len={len(self._management_key)}>"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._management_key}",
            "X-Management-Key": self._management_key,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self._base_url}{endpoint}"
        headers = self._get_headers()
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )
            resp.raise_for_status()
            if resp.content:
                try:
                    return resp.json()
                except Exception:
                    return resp.text
            return None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise ProxySupervisorError(f"Management API {method} {endpoint} returned HTTP {status}") from None
        except Exception as exc:
            raise ProxySupervisorError(f"Management API request failed: {type(exc).__name__}") from None
        finally:
            if client is not self._client:
                await client.aclose()

    async def health(self) -> bool:
        """Query /healthz readiness endpoint."""
        url = f"{self._base_url}/healthz"
        client = self._client or httpx.AsyncClient(timeout=3.0)
        try:
            resp = await client.get(url)
            return resp.status_code == 200
        except Exception:
            return False
        finally:
            if client is not self._client:
                await client.aclose()

    async def get_config(self) -> dict[str, Any]:
        """Read configuration with sensitive client/management keys redacted."""
        data = await self._request("GET", "/v8/management/config")
        if isinstance(data, dict):
            return redact_sensitive_data(copy.deepcopy(data))
        return {}

    async def patch_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Patch configuration via /v8/management/config."""
        res = await self._request("PATCH", "/v8/management/config", json_body=patch)
        return redact_sensitive_data(res) if isinstance(res, dict) else {}

    async def reset_cooldown(
        self, channel: str | None = None, model: str | None = None
    ) -> dict[str, Any]:
        """Clear credential cooldown via /v8/management/routing/cooldown/reset."""
        body = {}
        if channel:
            body["channel"] = channel
        if model:
            body["model"] = model
        res = await self._request("POST", "/v8/management/routing/cooldown/reset", json_body=body)
        return res if isinstance(res, dict) else {"status": "ok"}

    async def get_credentials(self) -> list[dict[str, Any]]:
        """List credentials via /v8/management/credentials."""
        res = await self._request("GET", "/v8/management/credentials")
        if isinstance(res, list):
            return [redact_sensitive_data(x) for x in res]
        elif isinstance(res, dict) and "credentials" in res:
            return [redact_sensitive_data(x) for x in res["credentials"]]
        return []

    async def get_credential_models(self) -> list[str]:
        """Retrieve aggregated models via /v8/management/credentials/models."""
        res = await self._request("GET", "/v8/management/credentials/models")
        if isinstance(res, list):
            return [str(m) for m in res]
        elif isinstance(res, dict) and "models" in res:
            return [str(m) for m in res["models"]]
        return []

    async def start_oauth(
        self, provider: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Start an OAuth authorization flow via /v8/management/oauth/auth-url."""
        query_params = {"provider": provider}
        if params:
            query_params.update(params)
        res = await self._request("GET", "/v8/management/oauth/auth-url", params=query_params)
        return res if isinstance(res, dict) else {}

    async def submit_oauth_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit an OAuth callback code/URL via /v8/management/oauth/callback."""
        res = await self._request("POST", "/v8/management/oauth/callback", json_body=payload)
        return res if isinstance(res, dict) else {}

    async def get_oauth_status(self, state: str) -> dict[str, Any]:
        """Query OAuth flow status via /v8/management/oauth/status."""
        res = await self._request("GET", "/v8/management/oauth/status", params={"state": state})
        return res if isinstance(res, dict) else {}

    async def cancel_oauth_session(self, state: str) -> dict[str, Any]:
        """Cancel an OAuth session via /v8/management/oauth/session."""
        res = await self._request("DELETE", "/v8/management/oauth/session", params={"state": state})
        return res if isinstance(res, dict) else {}

    async def delete_credential(self, name: str) -> dict[str, Any]:
        """Delete a credential by name via /v8/management/credentials."""
        res = await self._request("DELETE", f"/v8/management/credentials/{name}")
        return res if isinstance(res, dict) else {}


class ProxySupervisor:
    """FastAPI lifecycle supervisor for the local CLIProxyAPI sidecar process."""

    def __init__(
        self,
        vault: ProviderVault | None = None,
        bin_path: Path | str | None = None,
        runtime_root: Path | str | None = None,
        strategy: str = "fill-first",
        max_restarts: int = 3,
        readiness_timeout: float = 8.0,
    ) -> None:
        self._vault = vault or get_provider_vault()
        self._bin_path = Path(bin_path).resolve() if bin_path else None
        self._runtime_root = Path(runtime_root).resolve() if runtime_root else None
        self._strategy = strategy
        self._max_restarts = max_restarts
        self._readiness_timeout = readiness_timeout

        self._state: SupervisorState = SupervisorState.STOPPED
        self._lock = asyncio.Lock()
        self._host: str = "127.0.0.1"
        self._port: int | None = None
        self._client_key: str | None = None
        self._management_key: str | None = None
        self._process: subprocess.Popen | None = None
        self._runtime_dir: Path | None = None
        self._auth_dir: Path | None = None
        self._restart_count: int = 0
        self._last_error: str | None = None
        self._management_client: ProxyManagementClient | None = None
        self._sync_task: asyncio.Task | None = None

    @property
    def state(self) -> SupervisorState:
        return self._state

    @property
    def is_running(self) -> bool:
        if self._state != SupervisorState.RUNNING:
            return False
        if self._process is None or self._process.poll() is not None:
            return False
        return True

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int | None:
        return self._port

    @property
    def client_key(self) -> str | None:
        return self._client_key

    @property
    def pid(self) -> int | None:
        if self._process and self._process.poll() is None:
            return self._process.pid
        return None

    @property
    def runtime_dir(self) -> Path | None:
        return self._runtime_dir

    @property
    def auth_dir(self) -> Path | None:
        return self._auth_dir

    def get_bin_path(self) -> Path:
        if self._bin_path:
            return self._bin_path
        return resolve_cliproxy_bin()

    def get_runtime_root(self) -> Path:
        if self._runtime_root:
            return self._runtime_root
        env_root = os.environ.get("CLIPROXY_RUNTIME_ROOT")
        if env_root:
            return Path(env_root).resolve()
        return Path(settings.db_path).resolve().parent / "cliproxy-runtime"

    def get_management_client(self) -> ProxyManagementClient:
        if not self._management_client:
            raise ProxySupervisorError("CLIProxyAPI is not running; management client unavailable")
        return self._management_client

    def get_status(self) -> dict[str, Any]:
        """Return non-secret status summary."""
        return {
            "state": self._state.value,
            "host": self._host,
            "port": self._port,
            "pid": self.pid,
            "restart_count": self._restart_count,
            "last_error": self._last_error,
            "is_running": self.is_running,
        }

    def cleanup_stale_runtimes(self) -> int:
        """Clean up stale runtime directories and orphaned processes at startup."""
        return cleanup_stale_runtimes(self.get_runtime_root())

    async def ensure_started(self) -> tuple[str, int, str]:
        """Lazily ensure the proxy is running and ready. Returns (host, port, client_key)."""
        async with self._lock:
            if self.is_running and self._port and self._client_key:
                return (self._host, self._port, self._client_key)

            # Lazy start after vault availability check
            if hasattr(self._vault, "get_state"):
                res = self._vault.get_state()
                vault_state = await res if asyncio.iscoroutine(res) else res
            else:
                vault_state = getattr(self._vault, "state", VaultState.KEYRING_UNAVAILABLE)
            if vault_state != VaultState.AVAILABLE:
                raise VaultUnavailableError(
                    f"Cannot start CLIProxyAPI: vault is not available (state: {vault_state.value})"
                )

            await self._start_unlocked()
            assert self._port is not None and self._client_key is not None
            return (self._host, self._port, self._client_key)

    async def start(self) -> None:
        """Start the supervisor process."""
        await self.ensure_started()

    async def _start_unlocked(self) -> None:
        self._state = SupervisorState.STARTING
        self._last_error = None

        runtime_root = self.get_runtime_root()
        runtime_root.mkdir(parents=True, exist_ok=True)
        set_dir_permissions_0700(runtime_root)
        cleanup_stale_runtimes(runtime_root)

        bin_path = self.get_bin_path()
        if not bin_path.exists() or not bin_path.is_file():
            self._state = SupervisorState.CRASHED
            self._last_error = f"Binary missing at {bin_path}"
            raise FileNotFoundError(self._last_error)

        self._port = find_free_loopback_port()
        self._client_key = secrets.token_urlsafe(32)
        self._management_key = secrets.token_urlsafe(32)

        dir_name = f"run-{os.getpid()}-{secrets.token_hex(4)}"
        self._runtime_dir = runtime_root / dir_name
        self._runtime_dir.mkdir(parents=True, exist_ok=True)
        set_dir_permissions_0700(self._runtime_dir)

        self._auth_dir = self._runtime_dir / "auth"
        self._auth_dir.mkdir(parents=True, exist_ok=True)
        set_dir_permissions_0700(self._auth_dir)

        # Materialize secrets
        await materialize_vault_secrets(self._vault, self._auth_dir)

        # Generate config
        cfg_str = generate_proxy_config(
            host=self._host,
            port=self._port,
            client_key=self._client_key,
            management_key=self._management_key,
            auth_dir=self._auth_dir,
            strategy=self._strategy,
        )
        cfg_path = self._runtime_dir / "config.yaml"
        cfg_path.write_text(cfg_str, encoding="utf-8")
        set_file_permissions_0600(cfg_path)

        cmd = [str(bin_path), "--config", str(cfg_path)]
        logger.info("ProxySupervisor: starting CLIProxyAPI on %s:%d", self._host, self._port)

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = (
                subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
            )

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self._runtime_dir),
            creationflags=creation_flags,
        )

        self._management_client = ProxyManagementClient(
            base_url=f"http://{self._host}:{self._port}",
            management_key=self._management_key,
        )

        ready = await self._poll_readiness(self._readiness_timeout)
        if not ready:
            err_msg = self._collect_process_error()
            await self._cleanup_process()
            self._state = SupervisorState.CRASHED
            self._last_error = err_msg
            raise ReadinessTimeoutError(f"CLIProxyAPI failed readiness check: {err_msg}")

        self._state = SupervisorState.RUNNING
        logger.info("ProxySupervisor: CLIProxyAPI is RUNNING (child pid=%d)", self._process.pid)

    async def _poll_readiness(self, timeout: float) -> bool:
        start_time = time.monotonic()
        url = f"http://{self._host}:{self._port}/healthz"
        async with httpx.AsyncClient(timeout=1.0) as client:
            while time.monotonic() - start_time < timeout:
                if self._process is not None and self._process.poll() is not None:
                    return False
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(0.05)
        return False

    def _collect_process_error(self) -> str:
        if not self._process:
            return "No process"
        exit_code = self._process.poll()
        stderr_text = ""
        if self._process.stderr:
            try:
                stderr_text = self._process.stderr.read() or ""
            except Exception:
                pass
        return f"exited with code {exit_code}: {stderr_text.strip()}"

    async def _cleanup_process(self) -> None:
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
                # Wait up to 3s for termination
                for _ in range(30):
                    if self._process.poll() is not None:
                        break
                    await asyncio.sleep(0.1)
                if self._process.poll() is None:
                    self._process.kill()
                    self._process.wait(timeout=1.0)
            except Exception as exc:
                logger.debug("ProxySupervisor: error cleaning process: %s", exc)

    async def restart_if_crashed(self) -> bool:
        """Check if process crashed and perform bounded restart if needed."""
        async with self._lock:
            if self._state not in (SupervisorState.RUNNING, SupervisorState.STARTING):
                return False
            if self._process is not None and self._process.poll() is not None:
                logger.warning(
                    "ProxySupervisor: process died unexpectedly (code=%s)",
                    self._process.returncode,
                )
                if self._restart_count < self._max_restarts:
                    self._restart_count += 1
                    backoff = 0.25 * (2 ** (self._restart_count - 1))
                    logger.info(
                        "ProxySupervisor: restarting (%d/%d) after %.2fs",
                        self._restart_count,
                        self._max_restarts,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    try:
                        await self._start_unlocked()
                        return True
                    except Exception as exc:
                        logger.error("ProxySupervisor: restart %d failed: %s", self._restart_count, exc)
                        self._last_error = f"Restart attempt {self._restart_count} failed: {exc}"
                        if self._restart_count >= self._max_restarts:
                            self._state = SupervisorState.CRASHED
                            self._last_error = f"Max restarts ({self._max_restarts}) exceeded; process crashed"
                        return False

                self._state = SupervisorState.CRASHED
                self._last_error = f"Max restarts ({self._max_restarts}) exceeded; process crashed"
                return False
            return True

    def request_sync(self, delay_seconds: float = 0.5) -> None:
        """Schedule a debounced background sync of auth and cooldown files to the vault."""
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()

        async def _delayed_sync() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                if self._auth_dir and self._auth_dir.exists():
                    await sync_auth_and_cooldowns(self._vault, self._auth_dir)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("ProxySupervisor: background sync error: %s", exc)

        self._sync_task = asyncio.create_task(_delayed_sync())

    async def sync_now(self) -> int:
        """Immediately sync auth JSON and cooldowns back to the vault."""
        if self._auth_dir and self._auth_dir.exists():
            return await sync_auth_and_cooldowns(self._vault, self._auth_dir)
        return 0

    async def stop(self) -> None:
        """Gracefully stop the proxy, sync auth and cooldowns to vault, and clean runtime dir."""
        async with self._lock:
            if self._state == SupervisorState.STOPPED:
                return
            self._state = SupervisorState.STOPPING
            logger.info("ProxySupervisor: stopping...")

            if self._sync_task and not self._sync_task.done():
                self._sync_task.cancel()

            # 1. Terminate process
            await self._cleanup_process()

            # 2. Final sync to vault
            if self._auth_dir and self._auth_dir.exists():
                try:
                    await sync_auth_and_cooldowns(self._vault, self._auth_dir)
                except Exception as exc:
                    logger.warning("ProxySupervisor: failed final vault sync on stop: %s", exc)

            # 3. Delete runtime directory
            if self._runtime_dir and self._runtime_dir.exists():
                try:
                    shutil.rmtree(self._runtime_dir, ignore_errors=True)
                except Exception as exc:
                    logger.debug("ProxySupervisor: failed removing runtime dir: %s", exc)

            self._state = SupervisorState.STOPPED
            self._process = None
            self._port = None
            self._client_key = None
            self._management_key = None
            self._runtime_dir = None
            self._auth_dir = None
            self._management_client = None
            logger.info("ProxySupervisor: stopped successfully")


_default_supervisor: ProxySupervisor | None = None


def get_proxy_supervisor() -> ProxySupervisor:
    """Return the global ProxySupervisor singleton instance."""
    global _default_supervisor
    if _default_supervisor is None:
        _default_supervisor = ProxySupervisor()
    return _default_supervisor


def set_proxy_supervisor(supervisor: ProxySupervisor | None) -> None:
    """Set or reset the global ProxySupervisor singleton instance (useful in tests)."""
    global _default_supervisor
    _default_supervisor = supervisor

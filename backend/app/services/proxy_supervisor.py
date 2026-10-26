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
import yaml
from app.services.private_files import restrict_access
from app.services.redaction import SENSITIVE_FIELD_NAMES, redact_mapping
from app.services.route_registry import compute_oauth_proxy_prefix, OAUTH_PROVIDERS

from app.config import settings
from app.services.provider_vault import (
    ProviderVault,
    VaultState,
    VaultUnavailableError,
    get_provider_vault,
)

logger = logging.getLogger("blm.proxy_supervisor")

# The sidecar's /v1/models aggregates upstream catalogs and can be slow; keep
# explicit refreshes responsive without re-querying on every UI poll.
_MODEL_CACHE: dict[tuple[int, str], tuple[float, tuple[str, ...]]] = {}
_MODEL_CACHE_TTL = 300.0


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


ProcessCrashError = ProcessCrashedError


class ReadinessTimeoutError(ProxySupervisorError):
    """Raised when readiness check times out."""


def redact_sensitive_data(val: Any) -> Any:
    """Recursively redact sensitive keys from nested dicts/lists for safe logging and diagnostics.

    Kept as a thin alias so existing imports keep working; the rules live in
    ``app.services.redaction``.
    """
    return redact_mapping(val)


def set_dir_permissions_0700(path: Path) -> None:
    """Set 0700 (rwx------) permissions on directory."""
    restrict_access(path, directory=True)


def set_file_permissions_0600(path: Path) -> None:
    restrict_access(path)


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
    custom_endpoints: list[dict[str, Any]] | None = None,
    direct_providers: list[dict[str, Any]] | None = None,
    session_affinity: bool = True,
) -> str:
    config = {
        "config-version": 8,
        "server": {"host": host, "port": port},
        "management": {"allow-remote": False, "secret-key": management_key, "disable-control-panel": True},
        "access": {"api-keys": [client_key]},
        "routing": {
            "strategy": strategy,
            "session-affinity": session_affinity,
            "session-affinity-ttl": session_affinity_ttl,
            "force-model-prefix": True,
            "retry": {"request-retry": request_retry, "max-retry-credentials": max_retry_credentials, "max-retry-interval": max_retry_interval},
            "cooldown": {"save-cooldown-status": True},
        },
        "oauth": {"auth-dir": str(Path(auth_dir).resolve()).replace("\\", "/")},
    }
    if custom_endpoints:
        from app.services.endpoint_validator import validate_custom_endpoint_url
        entries = []
        for endpoint in custom_endpoints:
            base_url, _ = validate_custom_endpoint_url(endpoint.get("base-url") or endpoint.get("base_url", ""), endpoint.get("headers"))
            entries.append({
                "name": endpoint.get("name", "custom"),
                "prefix": endpoint.get("prefix", endpoint.get("name", "custom")),
                "base-url": base_url,
                "headers": endpoint.get("headers") or {},
                "models": [model if isinstance(model, dict) else {"name": str(model)} for model in endpoint.get("models", [])],
                "api-key-entries": endpoint.get("api-key-entries") or endpoint.get("api-keys") or endpoint.get("api_keys") or [],
            })
        config["openai-compatibility"] = entries

    if direct_providers:
        openai_entries = config.setdefault("openai-compatibility", [])
        for provider in direct_providers:
            section = provider.get("section")
            entry = {key: value for key, value in provider.items() if key != "section"}
            if section == "openai-compatibility":
                openai_entries.append(entry)
            elif section in ("gemini-api-key", "claude-api-key"):
                config.setdefault(section, []).append(entry)
        if not openai_entries:
            config.pop("openai-compatibility", None)

    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


async def materialize_vault_secrets(vault: ProviderVault, auth_dir: Path, credentials: list[Any] | None = None) -> int:
    """Materialize encrypted OAuth auth JSON and .cds cooldown files from vault to auth_dir."""
    auth_dir.mkdir(parents=True, exist_ok=True)
    set_dir_permissions_0700(auth_dir)
    count = 0

    # 1. OAuth auth files
    all_auth = await vault.get_all_oauth_auth()
    for key, data in all_auth.items():
        credential = None
        if credentials is not None:
            credential = next((entry for entry in credentials if entry.vault_reference.removeprefix("oauth_auth:") == key), None)
            if credential is None:
                continue
        payload = json.loads(data) if isinstance(data, str) else dict(data)
        provider = credential.route_id.split(":", 1)[1] if credential else payload.get("type") or key.removesuffix(".json")
        if provider in OAUTH_PROVIDERS:
            payload["type"] = provider
            payload["prefix"] = compute_oauth_proxy_prefix(f"oauth:{provider}")
        if credential is not None:
            payload.update(priority=credential.priority, weight=credential.weight, disabled=not credential.enabled)
        fname = credential.proxy_credential_name if credential else key
        fname = fname if fname.endswith(".json") else f"{fname}.json"
        if Path(fname).name != fname or "/" in fname or "\\" in fname:
            raise ProxySupervisorError("Invalid credential filename")
        target = auth_dir / fname
        target.touch(mode=0o600)
        set_file_permissions_0600(target)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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


async def sync_auth_and_cooldowns(vault: ProviderVault, auth_dir: Path, credential_keys: dict[str, str] | None = None) -> int:
    """Scan auth_dir and sync refreshed OAuth auth JSON and .cds snapshots back into the vault.

    Applies a reversible key mapping: if the extensionless key exists in the vault,
    refreshed data is written back under that key; otherwise the exact filename key is preserved.
    """
    if not auth_dir.exists():
        return 0
    count = 0

    # 1. OAuth auth JSON files
    existing_auth = await vault.get_all_oauth_auth()
    for p in auth_dir.glob("*.json"):
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
            stem = p.stem
            if credential_keys is not None and p.name not in credential_keys:
                continue
            target_key = credential_keys[p.name] if credential_keys is not None else (stem if stem in existing_auth else p.name)
            await vault.set_oauth_auth(target_key, data)
            count += 1
        except Exception as exc:
            logger.warning("ProxySupervisor: credential sync failed (%s)", type(exc).__name__)

    # 2. Cooldown .cds snapshot files
    existing_cooldowns = await vault.get_all_cooldown_snapshots()
    for p in auth_dir.glob("*.cds"):
        try:
            raw = p.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except Exception:
                data = raw
            stem = p.stem
            target_key = stem if stem in existing_cooldowns else p.name
            await vault.set_cooldown_snapshot(target_key, data)
            count += 1
        except Exception as exc:
            logger.warning("ProxySupervisor: failed syncing %s to vault: %s", p.name, exc)

    return count


def cleanup_stale_runtimes(
    runtime_root: Path,
    active_runtime_dir: Path | None = None,
) -> int:
    """Detect and remove stale runtime directories and kill orphaned proxy processes.

    Reads the child PID recorded in cliproxy.pid, verifies the process is actually
    cliproxy to guard against PID reuse hazards, terminates/kills the orphan, and removes
    the stale directory while preserving any specified active runtime.
    """
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

        # Preserve active runtime directory if specified
        if active_runtime_dir is not None:
            try:
                if item.resolve() == active_runtime_dir.resolve():
                    continue
            except Exception:
                pass

        parts = item.name.split("-")
        is_stale = False
        if len(parts) >= 3 and parts[0] == "run":
            try:
                parent_pid = int(parts[1])
                if not psutil.pid_exists(parent_pid):
                    is_stale = True
                else:
                    try:
                        p = psutil.Process(parent_pid)
                        p_name = p.name().lower()
                        # If parent PID exists but is not python/blm process, it was reused
                        if "python" not in p_name and "blm" not in p_name and parent_pid != os.getpid():
                            is_stale = True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        is_stale = True
            except ValueError:
                is_stale = True
        else:
            is_stale = True

        if is_stale:
            # Check for child PID in cliproxy.pid file
            pid_file = item / "cliproxy.pid"
            if pid_file.exists():
                try:
                    child_pid = int(pid_file.read_text(encoding="utf-8").strip())
                    if psutil.pid_exists(child_pid):
                        try:
                            cp = psutil.Process(child_pid)
                            cp_name = cp.name().lower()
                            cmdline = " ".join(cp.cmdline()).lower() if hasattr(cp, "cmdline") else ""
                            # Safe check: terminate only if verified as cliproxy
                            if "cliproxy" in cp_name or "cliproxy" in cmdline:
                                logger.info("Terminating orphaned proxy process pid=%d", child_pid)
                                cp.terminate()
                                try:
                                    cp.wait(timeout=1.0)
                                except psutil.TimeoutExpired:
                                    cp.kill()
                            else:
                                logger.warning(
                                    "PID %d in %s is not cliproxy (name=%s); skipping kill to prevent PID reuse hazard",
                                    child_pid,
                                    item.name,
                                    cp_name,
                                )
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except (ValueError, OSError) as exc:
                    logger.debug("Failed reading cliproxy.pid from %s: %s", item.name, exc)

            try:
                shutil.rmtree(item, ignore_errors=True)
                cleaned += 1
                logger.info("Cleaned stale proxy runtime dir: %s", item.name)
            except Exception as exc:
                logger.debug("Failed removing stale dir %s: %s", item.name, exc)

    return cleaned



async def materialize_custom_endpoints(
    vault: ProviderVault,
    session: Any = None,
) -> list[dict[str, Any]]:
    """Load enabled custom endpoints from DB and vault secrets for CLIProxyAPI openai-compatibility."""
    endpoints: list[dict[str, Any]] = []
    try:
        from app.models.ai_provider import AIProviderRoute, AIProviderCredential
        from sqlalchemy import select

        async def _query(s: Any) -> list[dict[str, Any]]:
            res = await s.execute(
                select(AIProviderRoute).where(
                    AIProviderRoute.kind == "endpoint",
                    AIProviderRoute.enabled == True,
                )
            )
            routes = res.scalars().all()
            out: list[dict[str, Any]] = []
            for r in routes:
                cfg = {}
                if r.config_json:
                    try:
                        cfg = json.loads(r.config_json)
                    except Exception:
                        pass
                base_url = cfg.get("base_url") or ""
                if not base_url:
                    continue
                models = cfg.get("models") or ["default"]
                prefix = r.proxy_prefix or r.id.replace(":", "-")
                headers = await vault.get_endpoint_headers(r.id) or {}

                c_res = await s.execute(
                    select(AIProviderCredential).where(
                        AIProviderCredential.route_id == r.id,
                        AIProviderCredential.enabled == True,
                    )
                )
                creds = c_res.scalars().all()
                api_keys: list[dict[str, Any]] = []
                for cred in creds:
                    k = await vault.get_secret(cred.vault_reference)
                    if k:
                        api_keys.append({
                            "api-key": str(k).strip(),
                            "priority": cred.priority,
                            "weight": cred.weight,
                        })

                out.append({
                    "name": prefix,
                    "prefix": prefix,
                    "base-url": base_url,
                    "headers": headers,
                    "models": [{"name": m} for m in models],
                    "api-keys": api_keys,
                    "api-key-entries": api_keys,
                })
            return out

        if session is not None:
            endpoints = await _query(session)
        else:
            from app.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                endpoints = await _query(s)
    except Exception as exc:
        logger.debug("materialize_custom_endpoints: could not load endpoints: %s", exc)

    return endpoints


async def load_routing_settings(session: Any) -> dict[str, Any]:
    from sqlalchemy import select
    from app.models.system_config import SystemConfig

    defaults = {"strategy": "fill-first", "session_affinity": True, "session_affinity_ttl": "1h", "request_retry": 3, "max_retry_credentials": 0, "max_retry_interval": 30}
    mapping = {"ai.routing_strategy": "strategy", **{f"ai.{key}": key for key in defaults if key != "strategy"}}
    rows = (await session.execute(select(SystemConfig).where(SystemConfig.key.in_(mapping)))).scalars().all()
    for row in rows:
        key = mapping[row.key]
        if key == "session_affinity":
            defaults[key] = row.value.lower() in ("true", "1", "yes")
        elif key in ("request_retry", "max_retry_credentials", "max_retry_interval"):
            defaults[key] = int(row.value)
        else:
            defaults[key] = row.value
    return defaults


def routing_config(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy": settings["strategy"], "session-affinity": settings["session_affinity"],
        "session-affinity-ttl": settings["session_affinity_ttl"],
        "retry": {key.replace("_", "-"): settings[key] for key in ("request_retry", "max_retry_credentials", "max_retry_interval")},
    }


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
        timeout: float | None = None,
    ) -> Any:
        url = f"{self._base_url}{endpoint}"
        headers = self._get_headers()
        client = self._client or httpx.AsyncClient(
            timeout=timeout if timeout is not None else self._timeout,
            trust_env=False,
        )
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
        client = self._client or httpx.AsyncClient(timeout=3.0, trust_env=False)
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
        if not isinstance(res, dict) or not isinstance(res.get("files"), list):
            raise ProxySupervisorError("Invalid credential listing response")
        return [redact_sensitive_data(entry) for entry in res["files"]]

    async def get_credential_models(self, name: str) -> list[str]:
        res = await self._request("GET", "/v8/management/credentials/models", params={"name": name})
        if not isinstance(res, dict) or not isinstance(res.get("models"), list):
            raise ProxySupervisorError("Invalid credential model response")
        return [model["id"] for model in res["models"] if isinstance(model, dict) and isinstance(model.get("id"), str)]

    async def update_credential(self, name: str, *, enabled: bool, priority: int, weight: int, prefix: str) -> None:
        await self._request("PATCH", "/v8/management/credentials/fields", json_body={"name": name, "priority": priority, "weight": weight, "prefix": prefix})
        await self._request("PATCH", "/v8/management/credentials/status", json_body={"name": name, "disabled": not enabled})

    async def refresh_credential(self, name: str) -> dict[str, Any]:
        return await self._request("POST", "/v8/management/credentials/refresh", json_body={"name": name})

    async def start_oauth(
        self, provider: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Start an OAuth authorization flow via /v8/management/oauth/auth-url."""
        query_params = {"provider": provider}
        if params:
            query_params.update(params)
        # OAuth URL generation can take longer than the default management
        # timeout on a cold sidecar (the provider metadata fetch happens
        # inline), so give this call its own budget.
        res = await self._request(
            "GET",
            "/v8/management/oauth/auth-url",
            params=query_params,
            timeout=60.0,
        )
        return res if isinstance(res, dict) else {}

    async def submit_oauth_callback(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit an OAuth callback code/URL via /v8/management/oauth/callback."""
        res = await self._request("POST", "/v8/management/oauth/callback", json_body=payload)
        return res if isinstance(res, dict) else {}

    async def get_oauth_status(self, state: str) -> dict[str, Any]:
        """Query OAuth flow status via /v8/management/oauth/status."""
        try:
            res = await asyncio.wait_for(
                self._request(
                    "GET",
                    "/v8/management/oauth/status",
                    params={"state": state},
                    timeout=3.0,
                ),
                timeout=3.5,
            )
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            raise ProxySupervisorError("OAuth status query timed out") from exc
        return res if isinstance(res, dict) else {}

    async def cancel_oauth_session(self, state: str) -> dict[str, Any]:
        """Cancel an OAuth session via /v8/management/oauth/session."""
        res = await self._request("DELETE", "/v8/management/oauth/session", params={"state": state})
        return res if isinstance(res, dict) else {}

    async def delete_credential(self, name: str) -> dict[str, Any]:
        """Delete a credential by name via /v8/management/credentials."""
        res = await self._request("DELETE", "/v8/management/credentials", params={"name": name})
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
        # The sidecar logs every request it serves. Its output must never go to
        # an unread pipe: once the OS buffer fills, the child blocks inside its
        # logger while holding internal locks, and every management endpoint
        # (/config, /auth-files, /oauth/*) hangs forever while /healthz still
        # answers. Redirect to a file instead and read it only for diagnostics.
        self._log_handle: Any | None = None
        self._log_path: Path | None = None
        self._runtime_dir: Path | None = None
        self._auth_dir: Path | None = None
        self._restart_count: int = 0
        self._last_error: str | None = None
        self._management_client: ProxyManagementClient | None = None
        self._sync_task: asyncio.Task | None = None
        self._credential_keys: dict[str, str] | None = None
        self._accepting_requests = True
        self._last_management_probe_at: float = 0.0
        # While an OAuth consent flow is pending, restarting the sidecar would
        # discard the in-memory flow state and break the callback. Suppress the
        # wedge probe until the flow finishes or this deadline expires.
        self._oauth_flow_deadline: float = 0.0
        self._last_recovery_reason: str = ""
        self._last_suppressed_reason: str = ""
        self._recovery_count: int = 0

    def hold_oauth_flow(self, seconds: float = 600.0) -> None:
        self._oauth_flow_deadline = time.monotonic() + seconds

    def release_oauth_flow(self) -> None:
        self._oauth_flow_deadline = 0.0

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

    async def _management_api_responsive(self) -> bool:
        """Probe the sidecar's management plane, which wedges independently of /healthz.

        A hung management API means OAuth start and credential operations will time
        out, and inference typically stalls on the same process. Probe at most once
        every 15s so normal requests do not pay for it.
        """
        now = time.monotonic()
        if now - self._last_management_probe_at < 15.0:
            return True
        self._last_management_probe_at = now
        try:
            client = self.get_management_client()
            await asyncio.wait_for(client.get_credentials(), timeout=3.0)
            return True
        except Exception as exc:
            logger.warning(
                "ProxySupervisor: management API probe failed (%s)",
                type(exc).__name__,
            )
            return False

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

    @property
    def runtime_dir(self) -> Path | None:
        """Return the active or current runtime directory."""
        return self._runtime_dir

    def cleanup_stale_runtimes(self) -> int:
        """Clean up stale runtime directories and orphaned processes at startup."""
        return cleanup_stale_runtimes(self.get_runtime_root(), active_runtime_dir=self._runtime_dir)

    async def ensure_started(self) -> tuple[str, int, str]:
        """Lazily ensure the proxy is running and ready. Returns (host, port, client_key)."""
        async with self._lock:
            if not self._accepting_requests:
                raise ProxySupervisorError("Proxy supervisor is shutting down")
            await self._vault.get_state()
            if self.is_running and self._port and self._client_key:
                # Do not restart on auth-file mtime changes: the sidecar
                # rewrites its own auth files on token refresh, and replacing
                # the process mid-run discards the warm credential state. A
                # genuinely wedged child is recovered by the management probe
                # below and by the first-event watchdog in the inference path.
                if time.monotonic() < self._oauth_flow_deadline:
                    return (self._host, self._port, self._client_key)
                if await self._management_api_responsive():
                    return (self._host, self._port, self._client_key)
                return await self._recover_unlocked("management_unresponsive")

            # Dead process detection if previously started but now dead/crashed
            if self._process is not None and self._process.poll() is not None:
                return await self._recover_unlocked("dead_child")

            # The sidecar also serves API-key direct routes, so a locked vault must
            # not prevent startup. Vault-backed materialization is skipped instead.
            if hasattr(self._vault, "get_state"):
                res = self._vault.get_state()
                vault_state = await res if asyncio.iscoroutine(res) else res
            else:
                vault_state = getattr(self._vault, "state", VaultState.KEYRING_UNAVAILABLE)
            if vault_state != VaultState.AVAILABLE:
                logger.warning(
                    "ProxySupervisor: starting without vault materialization (state=%s)",
                    vault_state.value,
                )

            # Clean previous runtime dir if any exists before starting
            if self._runtime_dir and self._runtime_dir.exists():
                shutil.rmtree(self._runtime_dir, ignore_errors=True)
                self._runtime_dir = None
                self._auth_dir = None

            await self._start_unlocked()
            assert self._port is not None and self._client_key is not None
            return (self._host, self._port, self._client_key)

    async def _vault_is_available(self) -> bool:
        try:
            if hasattr(self._vault, "get_state"):
                res = self._vault.get_state()
                state = await res if asyncio.iscoroutine(res) else res
            else:
                state = getattr(self._vault, "state", VaultState.KEYRING_UNAVAILABLE)
            return state == VaultState.AVAILABLE
        except Exception as exc:
            logger.warning("ProxySupervisor: vault state check failed (%s)", type(exc).__name__)
            return False

    async def list_proxy_models(self, prefix: str) -> list[str]:
        """Return the proxy's catalog for one model prefix, stripped of the prefix."""
        cache_key = (id(self), prefix)
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None and (time.monotonic() - cached[0]) < _MODEL_CACHE_TTL:
            return list(cached[1])

        try:
            host, port, client_key = await self.ensure_started()
            async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
                resp = await client.get(
                    f"http://{host}:{port}/v1/models",
                    headers={"Authorization": f"Bearer {client_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("ProxySupervisor: model listing failed (%s)", type(exc).__name__)
            return []

        marker = f"{prefix}/"
        models: set[str] = set()
        for item in data.get("data", []) if isinstance(data, dict) else []:
            model_id = item.get("id") if isinstance(item, dict) else None
            if isinstance(model_id, str) and model_id.startswith(marker):
                models.add(model_id[len(marker):])
        resolved = sorted(models)
        _MODEL_CACHE[cache_key] = (time.monotonic(), tuple(resolved))
        return resolved

    def _invalidate_model_cache(self) -> None:
        """Invalidate cached proxy model lists for this supervisor instance."""
        sup_id = id(self)
        to_del = [k for k in _MODEL_CACHE if k[0] == sup_id]
        for k in to_del:
            _MODEL_CACHE.pop(k, None)

    async def _handle_restart_unlocked(self) -> None:
        if self._restart_count >= self._max_restarts:
            await self._cleanup_process()
            if self._runtime_dir and self._runtime_dir.exists():
                shutil.rmtree(self._runtime_dir, ignore_errors=True)
                self._runtime_dir = None
                self._auth_dir = None
            self._state = SupervisorState.CRASHED
            self._last_error = f"Max restarts ({self._max_restarts}) exceeded; process crashed"
            raise ProcessCrashError(self._last_error)

        self._restart_count += 1
        backoff = 0.25 * (2 ** (self._restart_count - 1))
        logger.info(
            "ProxySupervisor: restarting (%d/%d) after %.2fs",
            self._restart_count,
            self._max_restarts,
            backoff,
        )

        # 1. Clean up dead process
        await self._cleanup_process()

        # 2. Sync any remaining auth/cooldowns from old runtime before cleaning
        if self._auth_dir and self._auth_dir.exists():
            try:
                await sync_auth_and_cooldowns(self._vault, self._auth_dir, self._credential_keys)
            except Exception as exc:
                logger.warning("ProxySupervisor: error syncing before restart: %s", exc)

        # 3. Clean up old runtime directory before creating a replacement
        if self._runtime_dir and self._runtime_dir.exists():
            shutil.rmtree(self._runtime_dir, ignore_errors=True)
            self._runtime_dir = None
            self._auth_dir = None

        await asyncio.sleep(backoff)
        await self._start_unlocked()

    async def start(self) -> None:
        """Start the supervisor process."""
        await self.ensure_started()

    async def _start_unlocked(self) -> None:
        self._invalidate_model_cache()
        # Clean up any leftover runtime directory before creating a fresh one
        if self._runtime_dir and self._runtime_dir.exists():
            shutil.rmtree(self._runtime_dir, ignore_errors=True)
            self._runtime_dir = None
            self._auth_dir = None

        self._state = SupervisorState.STARTING
        self._last_error = None

        runtime_root = self.get_runtime_root()
        runtime_root.mkdir(parents=True, exist_ok=True)
        set_dir_permissions_0700(runtime_root)
        cleanup_stale_runtimes(runtime_root, active_runtime_dir=self._runtime_dir)

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
        from app.database import AsyncSessionLocal
        from app.models.ai_provider import AIProviderCredential, AIProviderRoute
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            # Only credentials whose parent route is enabled may reach the sidecar;
            # a disabled OAuth provider must be inert, not merely hidden in the UI.
            credential_stmt = (
                select(AIProviderCredential)
                .join(AIProviderRoute, AIProviderCredential.route_id == AIProviderRoute.id)
                .where(
                    AIProviderCredential.kind == "oauth",
                    AIProviderRoute.enabled == True,  # noqa: E712
                )
            )
            credentials = list((await session.execute(credential_stmt)).scalars().all())
            routing_settings = await load_routing_settings(session)

        from app.services.direct_proxy_routes import build_direct_proxy_entries

        vault_available = await self._vault_is_available()
        if vault_available:
            self._credential_keys = {
                entry.proxy_credential_name if entry.proxy_credential_name.endswith(".json") else f"{entry.proxy_credential_name}.json": entry.vault_reference.removeprefix("oauth_auth:")
                for entry in credentials
            }
            try:
                await materialize_vault_secrets(self._vault, self._auth_dir, credentials)
            except Exception as exc:
                logger.warning(
                    "ProxySupervisor: OAuth materialization skipped (%s)", type(exc).__name__
                )
            try:
                custom_endpoints = await materialize_custom_endpoints(self._vault)
            except Exception as exc:
                logger.warning(
                    "ProxySupervisor: custom endpoint materialization skipped (%s)", type(exc).__name__
                )
                custom_endpoints = []
        else:
            self._credential_keys = {}
            custom_endpoints = []

        direct_providers = await build_direct_proxy_entries()

        # Generate config
        cfg_str = generate_proxy_config(
            host=self._host,
            port=self._port,
            client_key=self._client_key,
            management_key=self._management_key,
            auth_dir=self._auth_dir,
            custom_endpoints=custom_endpoints,
            direct_providers=direct_providers,
            **routing_settings,
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

        self._log_path = self._runtime_dir / "cliproxy.log"
        try:
            self._close_log_handle()
            # Keep the sidecar log bounded across restarts; it only needs to
            # hold enough recent output to explain a crash.
            try:
                if self._log_path.exists() and self._log_path.stat().st_size > 8 * 1024 * 1024:
                    self._log_path.unlink()
            except OSError:
                pass
            self._log_handle = self._log_path.open("a", encoding="utf-8", errors="replace")
            restrict_access(self._log_path)
        except Exception as exc:
            logger.warning(
                "ProxySupervisor: cannot open sidecar log file (%s); discarding output",
                type(exc).__name__,
            )
            self._log_handle = None
            self._log_path = None

        stdout_target = self._log_handle if self._log_handle is not None else subprocess.DEVNULL
        stderr_target = (
            subprocess.STDOUT if self._log_handle is not None else subprocess.DEVNULL
        )

        self._process = subprocess.Popen(
            cmd,
            stdout=stdout_target,
            stderr=stderr_target,
            text=True,
            cwd=str(self._runtime_dir),
            creationflags=creation_flags,
        )

        # Write child PID into permission-restricted cliproxy.pid file
        pid_file = self._runtime_dir / "cliproxy.pid"
        pid_file.write_text(str(self._process.pid), encoding="utf-8")
        set_file_permissions_0600(pid_file)

        self._management_client = ProxyManagementClient(
            base_url=f"http://{self._host}:{self._port}",
            management_key=self._management_key,
        )

        ready = await self._poll_readiness(self._readiness_timeout)
        if not ready:
            # Terminate unresponsive child first so stderr pipe reaches EOF and cannot hang
            await self._cleanup_process()
            err_msg = await self._collect_process_error()
            self._state = SupervisorState.CRASHED
            self._last_error = err_msg
            raise ReadinessTimeoutError(f"CLIProxyAPI failed readiness check: {err_msg}")

        self._state = SupervisorState.RUNNING
        self._restart_count = 0
        logger.info("ProxySupervisor: CLIProxyAPI is RUNNING (child pid=%d)", self._process.pid)

    async def _poll_readiness(self, timeout: float) -> bool:
        start_time = time.monotonic()
        url = f"http://{self._host}:{self._port}/healthz"
        async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
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

    def _close_log_handle(self) -> None:
        """Close the sidecar log file, tolerating repeated or partial cleanup."""
        handle = self._log_handle
        self._log_handle = None
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass

    async def _collect_process_error(self) -> str:
        if not self._process:
            return "No process"
        exit_code = self._process.poll()
        log_tail = ""
        log_path = self._log_path
        if log_path is not None:
            try:
                def _read_tail() -> str:
                    try:
                        with log_path.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(0, 2)
                            size = fh.tell()
                            fh.seek(max(0, size - 2048))
                            return fh.read()
                    except Exception:
                        return ""
                log_tail = await asyncio.wait_for(asyncio.to_thread(_read_tail), timeout=1.0)
            except Exception:
                pass
        return f"exited with code {exit_code}: {log_tail.strip()}"

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
        # The log file is opened for the child's stdout/stderr; close it before
        # the runtime directory is removed so Windows can delete the file.
        self._close_log_handle()

    async def restart_if_crashed(self) -> bool:
        """Check if process crashed and perform bounded restart if needed."""
        async with self._lock:
            if self._state not in (SupervisorState.RUNNING, SupervisorState.STARTING, SupervisorState.CRASHED):
                return False
            if self._process is not None and self._process.poll() is not None:
                try:
                    await self._handle_restart_unlocked()
                    return True
                except Exception:
                    return False
            return True

    async def _cancel_sync(self) -> None:
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)
        self._sync_task = None

    def request_sync(self, delay_seconds: float = 0.5) -> None:
        if not self._accepting_requests or (self._sync_task and not self._sync_task.done()):
            return

        async def delayed_sync() -> None:
            try:
                await asyncio.sleep(delay_seconds)
                await self.sync_now()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("ProxySupervisor: background sync failed (%s)", type(exc).__name__)

        self._sync_task = asyncio.create_task(delayed_sync())

    async def sync_now(self) -> int:
        async with self._lock:
            if self._auth_dir and self._auth_dir.exists():
                return await sync_auth_and_cooldowns(self._vault, self._auth_dir, self._credential_keys)
            return 0

    async def recover(self, reason: str, *, preserve_oauth_flow: bool = False) -> tuple[str, int, str]:
        """Recover supervisor with reason tracking and optional OAuth flow preservation."""
        async with self._lock:
            return await self._recover_unlocked(reason, preserve_oauth_flow=preserve_oauth_flow)

    async def _recover_unlocked(self, reason: str, *, preserve_oauth_flow: bool = False) -> tuple[str, int, str]:
        if preserve_oauth_flow and self.is_running and time.monotonic() < self._oauth_flow_deadline:
            logger.warning("ProxySupervisor: restart suppressed (reason=%s); OAuth flow in progress", reason)
            self._last_suppressed_reason = reason
            return self._host, self._port, self._client_key

        self._last_recovery_reason = reason
        self._recovery_count += 1
        logger.warning("ProxySupervisor: restarting sidecar (reason=%s count=%s)", reason, self._recovery_count)

        self._invalidate_model_cache()
        await self._cancel_sync()
        await self._cleanup_process()
        if self._auth_dir and self._auth_dir.exists():
            await sync_auth_and_cooldowns(self._vault, self._auth_dir, self._credential_keys)
        self._state = SupervisorState.STOPPED
        self._process = None
        await self._start_unlocked()
        return self._host, self._port, self._client_key

    async def restart(self) -> tuple[str, int, str]:
        """Restart supervisor and return (host, port, client_key)."""
        return await self.recover("explicit_restart")

    async def reload_custom_endpoints(self) -> None:
        """If supervisor is currently running, restart to re-materialize custom endpoints."""
        _MODEL_CACHE.clear()
        if self.is_running:
            await self.restart()

    async def stop(self, *, sync: bool = True, permanent: bool = False) -> None:
        """Gracefully stop the proxy, sync auth and cooldowns to vault, and clean runtime dir."""
        self._invalidate_model_cache()
        if permanent:
            self._accepting_requests = False
        await self._cancel_sync()
        async with self._lock:
            if self._state == SupervisorState.STOPPED and (not self._runtime_dir or not self._runtime_dir.exists()):
                return
            self._state = SupervisorState.STOPPING
            logger.info("ProxySupervisor: stopping...")

            # 1. Terminate process
            await self._cleanup_process()

            # 2. Final sync to vault
            if sync and self._auth_dir and self._auth_dir.exists():
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
            self._log_path = None
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

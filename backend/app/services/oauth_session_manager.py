"""In-memory OAuth session manager with lifecycle, expiry, and identity reconciliation.

Enforces:
- Browser OAuth only with loopback listener integration
- Pending-session timeout/expiry and cancellation
- Strict reauth identity reconciliation:
  replace existing account only on identity match, otherwise add a new account with a notice
- Zero secret / token / query string logging
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
import time
from typing import Any
import urllib.parse
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.endpoint_validator import mask_identity
from app.services.oauth_callback_server import (
    OAuthCallbackError,
    OAuthCallbackServer,
    parse_loopback_redirect,
)
from app.services.provider_vault import ProviderVault, get_provider_vault
from app.services.proxy_supervisor import get_proxy_supervisor
from app.services.redaction import redact_text
from app.services.route_registry import OAUTH_PROVIDERS, compute_oauth_proxy_prefix
from app.services.proxy_supervisor import set_file_permissions_0600

logger = logging.getLogger("blm.oauth_session_manager")

DEFAULT_SESSION_TTL = 900.0  # 15 minutes


class OAuthPortConflictError(RuntimeError):
    """Raised when an explicit callback port cannot be bound due to conflict."""
    code = "callback_port_unavailable"


def redact_oauth_error(err: str | None) -> str:
    """Sanitize error messages to ensure no tokens, query strings, or client secrets leak."""
    return redact_text(err, limit=300, default="OAuth authorization failed", strip_query=True)


@dataclass
class PendingOAuthSession:
    state: str
    provider: str
    flow: str = "browser"
    replace_account_id: str | None = None
    created_at: float = 0.0
    expires_at: float = 0.0
    auth_url: str | None = None
    callback_mode: str = "manual"  # "loopback" | "manual"
    callback_url: str | None = None
    device_code: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    interval: int = 5
    status: str = "pending"  # "pending" | "reconciling" | "completed" | "expired" | "cancelled" | "failed"
    result: dict[str, Any] | None = None
    error: str | None = None
    reconcile_event: asyncio.Event = field(default_factory=asyncio.Event)
    auth_files: dict[str, str] = field(default_factory=dict)


class OAuthSessionManager:
    """Manages active OAuth authentication flows, loopback listeners, and identity reconciliation."""

    def __init__(
        self,
        ttl: float = DEFAULT_SESSION_TTL,
        callback_server: OAuthCallbackServer | None = None,
        session_factory: Any | None = None,
    ) -> None:
        self._ttl = ttl
        self._sessions: dict[str, PendingOAuthSession] = {}
        self._lock = asyncio.Lock()
        self._reconcile_lock = asyncio.Lock()
        self._session_factory = session_factory
        self._callback_server: OAuthCallbackServer = (
            callback_server if callback_server is not None else OAuthCallbackServer()
        )

    @property
    def callback_server(self) -> OAuthCallbackServer:
        return self._callback_server

    async def _complete_loopback_session(self, state: str) -> None:
        terminal_statuses = {"completed", "failed", "cancelled", "expired"}
        # Hold until the exchange reaches a terminal status or the 15s grace period expires.
        deadline = time.monotonic() + 15.0
        try:
            while True:
                try:
                    res = await self.poll_session(state=state)
                    status = (res.get("status") if isinstance(res, dict) else "") or ""
                    if status.lower() in terminal_statuses:
                        break
                except Exception as exc:
                    logger.debug("Loopback poll_session error: %s", type(exc).__name__)
                    # If poll_session raised an exception, stop looping
                    break

                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.5)
        finally:
            get_proxy_supervisor().release_oauth_flow()
            await self._unregister_callback(state)

    async def _submit_callback(self, supervisor, state: str, code: str) -> None:
        """Submit the consent code exactly once.

        The pending flow lives in the sidecar's memory and is keyed by the
        state that was embedded in the authorization URL. Restarting the
        sidecar here would discard that flow, so every retry after a restart
        is guaranteed to fail with "unknown or expired state". If the
        management plane is wedged, surface the sanitized error and let the
        user start a fresh sign-in.
        """
        await supervisor.get_management_client().submit_oauth_callback(
            {"state": state, "code": code}
        )

    def _make_on_code_handler(self, state: str):
        async def _on_code(st: str, code: str) -> None:
            supervisor = get_proxy_supervisor()
            if not supervisor.is_running:
                err_msg = "Proxy supervisor is not running"
                async with self._lock:
                    sess = self._sessions.get(st)
                    if sess is not None:
                        sess.status = "failed"
                        sess.error = err_msg
                        sess.result = {
                            "status": "failed",
                            "error": err_msg,
                            "provider": sess.provider,
                        }
                get_proxy_supervisor().release_oauth_flow()
                asyncio.create_task(self._unregister_callback(st))
                logger.debug("Loopback callback submit failed: RuntimeError")
                raise RuntimeError(err_msg)

            try:
                await self._submit_callback(supervisor, st, code)
            except Exception as exc:
                logger.debug("Loopback callback submit failed: %s", type(exc).__name__)
                err_msg = "OAuth callback submission failed"
                async with self._lock:
                    sess = self._sessions.get(st)
                    if sess is not None:
                        sess.status = "failed"
                        sess.error = err_msg
                        sess.result = {
                            "status": "failed",
                            "error": err_msg,
                            "provider": sess.provider,
                        }
                get_proxy_supervisor().release_oauth_flow()
                asyncio.create_task(self._unregister_callback(st))
                raise

            # Complete reconciliation and unregister in background so the HTTP response is written first
            asyncio.create_task(self._complete_loopback_session(st))

        return _on_code

    def _make_on_error_handler(self, state: str):
        async def _on_error(error_code: str) -> None:
            redacted = redact_oauth_error(error_code)
            async with self._lock:
                sess = self._sessions.get(state)
                if sess is not None:
                    sess.status = "failed"
                    sess.error = redacted
            await self._unregister_callback(state)
            get_proxy_supervisor().release_oauth_flow()

        return _on_error

    async def _unregister_callback(self, state: str) -> None:
        if self._callback_server is not None:
            try:
                await self._callback_server.unregister(state)
            except Exception as exc:
                logger.debug("Unregister callback error: %s", type(exc).__name__)

    async def _begin_proxy_flow(self, supervisor, prov: str) -> dict[str, Any]:
        """Initiate OAuth flow on proxy sidecar with single-retry on restart."""
        mgmt = supervisor.get_management_client()
        try:
            return await mgmt.start_oauth(prov, params={})
        except Exception as exc:
            logger.warning(
                "Failed to start OAuth session via proxy for %s: %s; restarting sidecar and retrying",
                prov,
                type(exc).__name__,
            )
            try:
                await supervisor.recover("oauth_start_retry")
                mgmt = supervisor.get_management_client()
                return await mgmt.start_oauth(prov, params={})
            except Exception as retry_exc:
                logger.warning(
                    "OAuth start still failing after sidecar restart for %s: %s",
                    prov,
                    type(retry_exc).__name__,
                )
                raise RuntimeError(
                    f"Proxy management API failed to initiate OAuth for '{prov}'"
                ) from retry_exc

    def _parse_flow(
        self, proxy_resp: dict[str, Any], prov: str
    ) -> tuple[str, str, int, float, str | None]:
        """Extract auth_url, state, interval, expires_in, and redirect_uri from proxy response."""
        auth_url = proxy_resp.get("auth_url") or proxy_resp.get("url") or proxy_resp.get("authorization_url")
        interval = int(proxy_resp.get("interval") or 5)
        if not auth_url:
            raise RuntimeError(
                f"Proxy returned no authorization URL for '{prov}'; the sidecar may be unresponsive."
            )

        state = proxy_resp.get("state")
        if not state:
            try:
                _auth_qs = urllib.parse.parse_qs(urllib.parse.urlsplit(auth_url).query)
                state = (_auth_qs.get("state") or [None])[0]
            except Exception:
                state = None
        if not state:
            state = secrets.token_urlsafe(24)

        expires_in = float(proxy_resp.get("expires_in") or self._ttl)

        redirect_uri: str | None = None
        try:
            parsed_auth = urllib.parse.urlsplit(auth_url)
            qs = urllib.parse.parse_qs(parsed_auth.query, keep_blank_values=True)
            if "redirect_uri" in qs and qs["redirect_uri"]:
                redirect_uri = qs["redirect_uri"][0]
        except Exception:
            redirect_uri = None
        if not redirect_uri and proxy_resp.get("redirect_uri"):
            redirect_uri = proxy_resp.get("redirect_uri")

        return auth_url, state, interval, expires_in, redirect_uri

    async def _attach_callback(
        self, supervisor, state: str, redirect_uri: str | None
    ) -> tuple[str, str | None]:
        """Register loopback listener under proxy flow hold, handling port conflict."""
        callback_mode = "manual"
        callback_url: str | None = None
        if not redirect_uri:
            return callback_mode, callback_url

        try:
            parse_loopback_redirect(redirect_uri)
            try:
                await self._callback_server.register(
                    state=state,
                    redirect_uri=redirect_uri,
                    on_code=self._make_on_code_handler(state),
                    on_error=self._make_on_error_handler(state),
                )
                callback_mode = "loopback"
                callback_url = redirect_uri
            except OAuthCallbackError as oc_err:
                if "already in use or cannot be bound" in str(oc_err):
                    logger.debug("Port conflict on callback server: %s", type(oc_err).__name__)
                    try:
                        await supervisor.get_management_client().cancel_oauth_session(state)
                    except Exception as cancel_exc:
                        logger.debug("Best-effort cancel on port conflict failed: %s", type(cancel_exc).__name__)
                    raise OAuthPortConflictError("callback_port_unavailable") from oc_err
                logger.debug("Callback register failed: %s", type(oc_err).__name__)
                callback_mode = "manual"
                callback_url = None
        except OAuthCallbackError:
            callback_mode = "manual"
            callback_url = None

        return callback_mode, callback_url

    async def _register_session(self, session_obj: PendingOAuthSession) -> None:
        """Store pending session under the session manager lock."""
        async with self._lock:
            self._sessions[session_obj.state] = session_obj

    async def _validate_replace_account(
        self, replace_account_id: str, prov: str, db_session: AsyncSession | None
    ) -> None:
        """Verify replace_account_id exists, has kind oauth, and belongs to requested provider."""
        expected_route = f"oauth:{prov}"
        if db_session is not None:
            res = await db_session.execute(
                select(AIProviderCredential).where(AIProviderCredential.id == replace_account_id)
            )
            existing = res.scalar_one_or_none()
        else:
            from app.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                res = await s.execute(
                    select(AIProviderCredential).where(AIProviderCredential.id == replace_account_id)
                )
                existing = res.scalar_one_or_none()

        if existing is None:
            raise ValueError(f"Account to replace '{replace_account_id}' was not found.")
        if existing.kind != "oauth":
            raise ValueError(
                f"Account '{replace_account_id}' is of kind '{existing.kind}', only OAuth accounts can be reauthenticated."
            )
        if existing.route_id != expected_route:
            raise ValueError(
                f"Account '{replace_account_id}' belongs to route '{existing.route_id}', "
                f"not the requested route '{expected_route}'."
            )

    async def _handle_upstream_failure(
        self,
        session: PendingOAuthSession,
        status_data: dict[str, Any],
        p_status: str,
        db_session: AsyncSession | None,
    ) -> dict[str, Any]:
        """Handle failure/denied/error reported by proxy upstream status."""
        raw_err = (
            status_data.get("error_description")
            or status_data.get("error")
            or status_data.get("message")
            or f"OAuth authorization {p_status}"
        )
        redacted_err = redact_oauth_error(str(raw_err))
        fail_result = {
            "status": "failed",
            "error": redacted_err,
            "provider": session.provider,
        }
        async with self._lock:
            session.status = "failed"
            session.error = redacted_err
            session.result = fail_result

        await self._unregister_callback(session.state)

        if session.replace_account_id:
            async def _save_error(s: AsyncSession) -> None:
                res = await s.execute(
                    select(AIProviderCredential).where(AIProviderCredential.id == session.replace_account_id)
                )
                existing_c = res.scalar_one_or_none()
                if existing_c is not None:
                    existing_c.status = "error"
                    existing_c.last_redacted_error = redacted_err
                    await s.commit()

            try:
                if db_session is not None:
                    await _save_error(db_session)
                else:
                    from app.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as s:
                        await _save_error(s)
            except Exception as exc:
                logger.debug("Failed saving credential error: %s", type(exc).__name__)

        return fail_result

    async def start_session(
        self,
        provider: str,
        replace_account_id: str | None = None,
        db_session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Start a new OAuth flow (browser only) and register loopback callback if applicable."""
        prov = provider.strip().lower()
        if prov.startswith("oauth:"):
            prov = prov.split(":", 1)[1]

        if prov not in OAUTH_PROVIDERS:
            raise ValueError(f"Provider '{prov}' is not one of the approved OAuth providers: {OAUTH_PROVIDERS}")

        vault = get_provider_vault()
        await vault.get_state()
        if not vault.is_available:
            raise RuntimeError(
                f"Provider vault is currently unavailable (state: {vault.state.value}). Cannot start OAuth."
            )

        if replace_account_id:
            await self._validate_replace_account(replace_account_id, prov, db_session)

        supervisor = get_proxy_supervisor()
        await supervisor.ensure_started()
        auth_files = self._snapshot_auth_files(supervisor.auth_dir)
        proxy_resp = await self._begin_proxy_flow(supervisor, prov)
        auth_url, state, interval, expires_in, redirect_uri = self._parse_flow(proxy_resp, prov)

        now = time.time()
        supervisor.hold_oauth_flow()
        try:
            callback_mode, callback_url = await self._attach_callback(supervisor, state, redirect_uri)
            session_obj = PendingOAuthSession(
                state=state,
                provider=prov,
                flow="browser",
                replace_account_id=replace_account_id,
                created_at=now,
                expires_at=now + expires_in,
                auth_url=auth_url,
                callback_mode=callback_mode,
                callback_url=callback_url,
                interval=interval,
                status="pending",
                auth_files=auth_files,
            )
            await self._register_session(session_obj)
        except Exception:
            supervisor.release_oauth_flow()
            raise

        return {
            "state": state,
            "provider": prov,
            "flow": "browser",
            "callback_mode": callback_mode,
            "callback_url": callback_url,
            "auth_url": auth_url,
            "expires_in": int(expires_in),
            "interval": interval,
            "status": "pending",
        }

    async def _require(self, state: str) -> PendingOAuthSession:
        """Fetch session by state or raise KeyError."""
        async with self._lock:
            session = self._sessions.get(state)
        if session is None:
            raise KeyError(f"OAuth session with state '{state}' not found or already closed.")
        return session

    async def _terminal_snapshot(self, session: PendingOAuthSession) -> dict[str, Any] | None:
        """Evaluate terminal states (expired, cancelled, failed, completed).

        Owns the full pending/failed/completed/cancelled/expired check,
        unregisters callback, and triggers proxy cancel on expiry.
        Returns a response dict if terminal, or None if still active.
        """
        now = time.time()
        state = session.state

        if session.status == "expired" or now > session.expires_at:
            async with self._lock:
                session.status = "expired"
            await self._unregister_callback(state)
            supervisor = get_proxy_supervisor()
            if supervisor.is_running:
                try:
                    await supervisor.get_management_client().cancel_oauth_session(state)
                except Exception:
                    pass
            return {
                "status": "expired",
                "message": "OAuth authorization session expired. Please start a new session.",
            }

        if session.status == "cancelled":
            await self._unregister_callback(state)
            return {"status": "cancelled", "message": "OAuth session was cancelled."}

        if session.status == "failed":
            await self._unregister_callback(state)
            return session.result or {
                "status": "failed",
                "error": session.error or "OAuth authorization failed",
                "provider": session.provider,
            }

        if session.status == "completed" and session.result is not None:
            await self._unregister_callback(state)
            return session.result

        return None

    async def _wait_for_reconcile(self, session: PendingOAuthSession) -> dict[str, Any]:
        """Wait for concurrent reconciliation event with a 15 s timeout."""
        try:
            await asyncio.wait_for(session.reconcile_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            return {"status": "pending", "message": "Reconciliation in progress..."}
        return session.result or {
            "status": session.status,
            "error": session.error,
            "provider": session.provider,
        }

    async def _claim_reconcile(self, session: PendingOAuthSession) -> tuple[bool, dict[str, Any] | None]:
        """Claim exclusive reconciler under lock with terminal snapshot check.

        Returns (is_claimed, terminal_or_wait_result).
        If is_claimed is True, the caller is the exclusive reconciler.
        If is_claimed is False, terminal_or_wait_result contains the response.
        """
        async with self._lock:
            if session.status == "cancelled":
                await self._unregister_callback(session.state)
                return False, {"status": "cancelled", "message": "OAuth session was cancelled."}
            if session.status == "expired" or time.time() > session.expires_at:
                session.status = "expired"
                await self._unregister_callback(session.state)
                return False, {
                    "status": "expired",
                    "message": "OAuth authorization session expired. Please start a new session.",
                }
            if session.status == "failed":
                await self._unregister_callback(session.state)
                return False, (session.result or {
                    "status": "failed",
                    "error": session.error or "OAuth authorization failed",
                    "provider": session.provider,
                })
            if session.status == "completed" and session.result is not None:
                await self._unregister_callback(session.state)
                return False, session.result

            if session.status == "reconciling":
                return False, None  # Caller should wait_for_reconcile

            session.status = "reconciling"
            session.reconcile_event.clear()
            return True, None

    async def _reconcile(
        self,
        session: PendingOAuthSession,
        status_data: dict[str, Any],
        db_session: AsyncSession | None,
    ) -> dict[str, Any]:
        """Execute reconciliation and persist final state under reconcile lock."""
        state = session.state
        try:
            if db_session is not None:
                res_dict = await self._do_reconcile(session, status_data, db_session)
            elif self._session_factory is not None:
                async with self._session_factory() as s:
                    res_dict = await self._do_reconcile(session, status_data, s)
            else:
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as s:
                    res_dict = await self._do_reconcile(session, status_data, s)

            async with self._lock:
                session.status = "completed"
                session.result = res_dict
            session.reconcile_event.set()
            await self._unregister_callback(state)
            return res_dict
        except Exception as exc:
            err_str = redact_oauth_error(str(exc))
            fail_dict = {
                "status": "failed",
                "error": f"Reconciliation failed: {err_str}",
                "provider": session.provider,
            }
            async with self._lock:
                session.status = "failed"
                session.error = err_str
                session.result = fail_dict
            session.reconcile_event.set()
            await self._unregister_callback(state)
            raise
        finally:
            session.reconcile_event.set()

    async def poll_session(
        self,
        state: str,
        db_session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Poll the status of an ongoing OAuth flow and reconcile on completion."""
        session = await self._require(state)

        terminal_res = await self._terminal_snapshot(session)
        if terminal_res is not None:
            return terminal_res

        wait_reconcile = False
        async with self._lock:
            if session.status == "reconciling":
                wait_reconcile = True

        if wait_reconcile:
            return await self._wait_for_reconcile(session)

        supervisor = get_proxy_supervisor()
        if not supervisor.is_running:
            return {"status": "pending", "message": "Proxy is starting..."}

        try:
            status_data = await supervisor.get_management_client().get_oauth_status(state)
        except Exception as exc:
            logger.debug("OAuth status request failed (%s)", type(exc).__name__)
            return {"status": "pending"}

        p_status = str(status_data.get("status", "pending")).lower()

        if p_status in ("failed", "error", "denied", "cancelled") or status_data.get("error"):
            return await self._handle_upstream_failure(session, status_data, p_status, db_session)

        if p_status != "ok":
            return {
                "status": "pending",
                "interval": session.interval,
                "callback_mode": session.callback_mode,
                "callback_url": session.callback_url,
                "provider": session.provider,
            }

        claimed, early_res = await self._claim_reconcile(session)
        if not claimed:
            if early_res is not None:
                return early_res
            return await self._wait_for_reconcile(session)

        return await self._reconcile(session, status_data, db_session)

    @staticmethod
    def _snapshot_auth_files(auth_dir: Path | None) -> dict[str, str]:
        if auth_dir is None or not auth_dir.exists():
            return {}
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in auth_dir.glob("*.json") if not path.is_symlink()}

    def _find_new_auth_candidate(
        self, session: PendingOAuthSession, auth_dir: Path
    ) -> tuple[Path, dict[str, Any], str]:
        """Find the single new OAuth credential file produced by the flow and extract identity."""
        candidates = []
        for filename, digest in self._snapshot_auth_files(auth_dir).items():
            if session.auth_files.get(filename) == digest:
                continue
            path = auth_dir / filename
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("type") == session.provider:
                candidates.append((path, payload))
        if len(candidates) != 1:
            raise RuntimeError("OAuth completed without one identifiable credential file; retry authorization")
        path, payload = candidates[0]
        identity = payload.get("email") or payload.get("account_id") or payload.get("identity") or payload.get("user")
        if not identity:
            raise RuntimeError("OAuth credential file has no account identity")
        return path, payload, str(identity)

    async def _do_reconcile(
        self, session: PendingOAuthSession, status_data: dict[str, Any], s: AsyncSession,
    ) -> dict[str, Any]:
        async with self._reconcile_lock:
            if session.status == "cancelled":
                return {"status": "cancelled"}
            supervisor = get_proxy_supervisor()
            auth_dir = supervisor.auth_dir
            if auth_dir is None:
                raise RuntimeError("OAuth credential directory is unavailable")
            path, payload, identity = self._find_new_auth_candidate(session, auth_dir)
            route_id = f"oauth:{session.provider}"
            vault = get_provider_vault()
            existing = list((await s.execute(select(AIProviderCredential).where(AIProviderCredential.route_id == route_id, AIProviderCredential.kind == "oauth"))).scalars().all())
            matched = None
            for credential in existing:
                stored = await vault.get_oauth_auth(credential.vault_reference.removeprefix("oauth_auth:"))
                if isinstance(stored, dict):
                    stored_identity = stored.get("email") or stored.get("account_id") or stored.get("identity") or stored.get("user")
                    if stored_identity and str(stored_identity).strip().lower() == identity.strip().lower():
                        matched = credential
                        break
            notice = None
            if session.replace_account_id and (matched is None or matched.id != session.replace_account_id):
                notice = "Reauthentication identity mismatch. Added the authenticated identity as a separate account."
            credential = matched
            if credential is None:
                credential = AIProviderCredential(
                    id=str(uuid.uuid4()), route_id=route_id, kind="oauth",
                    vault_reference=f"oauth_auth:{path.name}", proxy_credential_name=path.name,
                    masked_identity=mask_identity(str(identity)), priority=1, weight=1,
                    enabled=True, status="active",
                )
                s.add(credential)
            old_name = credential.proxy_credential_name
            old_reference = credential.vault_reference
            payload.update(type=session.provider, prefix=compute_oauth_proxy_prefix(route_id),
                           priority=credential.priority, weight=credential.weight, disabled=not credential.enabled)
            credential.proxy_credential_name = path.name
            credential.vault_reference = f"oauth_auth:{path.name}"
            credential.status = "active" if credential.enabled else "disabled"
            credential.cooldown = None
            credential.last_redacted_error = None
            set_file_permissions_0600(path)
            path.write_text(json.dumps(payload), encoding="utf-8")
            await vault.set_oauth_auth(path.name, payload)
            await supervisor.get_management_client().update_credential(
                path.name, enabled=credential.enabled, priority=credential.priority,
                weight=credential.weight, prefix=payload["prefix"],
            )
            await s.commit()
            if old_name != path.name:
                old_filename = old_name if old_name.endswith(".json") else f"{old_name}.json"
                if (auth_dir / old_filename).exists():
                    await supervisor.get_management_client().delete_credential(old_filename)
                if supervisor._credential_keys is not None:
                    supervisor._credential_keys.pop(old_filename, None)
            if old_reference != credential.vault_reference:
                await vault.remove_oauth_auth(old_reference.removeprefix("oauth_auth:"))
            if supervisor._credential_keys is not None:
                supervisor._credential_keys[path.name] = path.name
            current_files = self._snapshot_auth_files(auth_dir)
            async with self._lock:
                for pending in self._sessions.values():
                    pending.auth_files[path.name] = current_files[path.name]
            supervisor.request_sync()
            return {
                "status": "completed",
                "account_id": credential.id,
                "route_id": route_id,
                "masked_identity": credential.masked_identity,
                "notice": notice,
            }

    async def cancel_all_sessions(self) -> None:
        for state, session in list(self._sessions.items()):
            if session.status in ("pending", "reconciling"):
                await self.cancel_session(state)
            else:
                await self._unregister_callback(state)
        async with self._reconcile_lock:
            self._sessions.clear()

    async def cancel_session(self, state: str) -> dict[str, str]:
        """Cancel an ongoing OAuth session."""
        async with self._lock:
            session = self._sessions.get(state)
            if session:
                session.status = "cancelled"

        await self._unregister_callback(state)

        supervisor = get_proxy_supervisor()
        if supervisor.is_running:
            try:
                await supervisor.get_management_client().cancel_oauth_session(state)
            except Exception as exc:
                logger.debug("Cancel oauth error on supervisor: %s", type(exc).__name__)

        return {"status": "cancelled", "state": state}

    async def shutdown(self) -> None:
        """Shutdown all sessions and the callback server."""
        await self.cancel_all_sessions()
        if self._callback_server is not None:
            try:
                await self._callback_server.shutdown()
            except Exception as exc:
                logger.debug("OAuth callback server shutdown error: %s", type(exc).__name__)

    async def handle_callback(
        self,
        state: str,
        code: str | None = None,
        redirect_url: str | None = None,
        raw_params: dict[str, Any] | None = None,
        db_session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Submit callback payload to proxy supervisor without logging query strings or tokens."""
        supervisor = get_proxy_supervisor()
        if supervisor.is_running:
            payload: dict[str, Any] = {"state": state}
            if code:
                payload["code"] = code
            if redirect_url:
                payload["redirect_url"] = redirect_url
                if not code:
                    try:
                        parsed = urllib.parse.urlsplit(redirect_url)
                        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                        if "code" in qs and qs["code"]:
                            payload["code"] = qs["code"][0]
                    except Exception:
                        pass
            if raw_params:
                for k, v in raw_params.items():
                    if k not in payload:
                        payload[k] = v
            try:
                await supervisor.get_management_client().submit_oauth_callback(payload)
            except Exception as exc:
                logger.debug("Submit OAuth callback failed: %s", type(exc).__name__)
                raise
        return await self.poll_session(state=state, db_session=db_session)


# Global session manager instance
_oauth_session_manager: OAuthSessionManager | None = None


def get_oauth_session_manager() -> OAuthSessionManager:
    global _oauth_session_manager
    if _oauth_session_manager is None:
        _oauth_session_manager = OAuthSessionManager()
    return _oauth_session_manager

"""In-memory OAuth session manager with lifecycle, expiry, and identity reconciliation.

Enforces:
- Browser and device code flows
- Pending-session timeout/expiry and cancellation
- Strict reauth identity reconciliation:
  replace existing account only on identity match, otherwise add a new account with a notice
- Zero secret / token / query string logging
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import logging
import re
import secrets
import time
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.endpoint_validator import mask_identity
from app.services.provider_vault import ProviderVault, get_provider_vault
from app.services.proxy_supervisor import get_proxy_supervisor
from app.services.route_registry import OAUTH_PROVIDERS, compute_oauth_proxy_prefix
from app.services.proxy_supervisor import set_file_permissions_0600

logger = logging.getLogger("blm.oauth_session_manager")

DEFAULT_SESSION_TTL = 900.0  # 15 minutes


def redact_oauth_error(err: str | None) -> str:
    """Sanitize error messages to ensure no tokens, query strings, or client secrets leak."""
    if not err:
        return "OAuth authorization failed"
    s = str(err)
    # Strip URL query parameters
    s = re.sub(r"([?&])[^ \t\r\n]+", "", s)
    # Mask authorization tokens, bearer auth, API keys, client secrets
    s = re.sub(r"(?i)bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", s)
    s = re.sub(r"(?i)sk-[A-Za-z0-9_\-]+", "sk-[REDACTED]", s)
    s = re.sub(r"(?i)client_secret=[^ \t\r\n&]+", "client_secret=[REDACTED]", s)
    if len(s) > 300:
        s = s[:300] + "..."
    return s.strip()


@dataclass
class PendingOAuthSession:
    state: str
    provider: str
    flow: str  # "browser" | "device"
    replace_account_id: str | None
    created_at: float
    expires_at: float
    auth_url: str | None = None
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
    """Manages active OAuth authentication flows and identity reconciliation."""

    def __init__(self, ttl: float = DEFAULT_SESSION_TTL) -> None:
        self._ttl = ttl
        self._sessions: dict[str, PendingOAuthSession] = {}
        self._lock = asyncio.Lock()
        self._reconcile_lock = asyncio.Lock()

    async def start_session(
        self,
        provider: str,
        flow: str = "browser",
        replace_account_id: str | None = None,
        db_session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Start a new OAuth flow (device or browser)."""
        prov = provider.strip().lower()
        if prov.startswith("oauth:"):
            prov = prov.split(":", 1)[1]

        if prov not in OAUTH_PROVIDERS:
            raise ValueError(f"Provider '{prov}' is not one of the approved OAuth providers: {OAUTH_PROVIDERS}")

        # Check vault availability
        vault = get_provider_vault()
        await vault.get_state()
        if not vault.is_available:
            raise RuntimeError(
                f"Provider vault is currently unavailable (state: {vault.state.value}). Cannot start OAuth."
            )

        # Verify replace_account_id exists, has kind oauth, and belongs to the requested provider
        if replace_account_id:
            expected_route = f"oauth:{prov}"
            existing: AIProviderCredential | None = None
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

        # Ensure supervisor is started
        supervisor = get_proxy_supervisor()
        await supervisor.ensure_started()
        mgmt = supervisor.get_management_client()

        params: dict[str, Any] = {}
        if flow == "device":
            params["flow"] = "device"

        auth_files = self._snapshot_auth_files(supervisor.auth_dir)

        # Start via proxy management API
        try:
            proxy_resp = await mgmt.start_oauth(prov, params=params)
        except Exception as exc:
            logger.warning("Failed to start OAuth session via proxy for %s: %s", prov, exc)
            raise RuntimeError(f"Proxy management API failed to initiate OAuth for '{prov}'") from exc

        state = proxy_resp.get("state") or secrets.token_urlsafe(24)
        expires_in = float(proxy_resp.get("expires_in") or self._ttl)
        now = time.time()

        auth_url = proxy_resp.get("auth_url") or proxy_resp.get("url") or proxy_resp.get("authorization_url")
        user_code = proxy_resp.get("user_code")
        verification_uri = proxy_resp.get("verification_uri") or proxy_resp.get("verification_url")
        device_code = proxy_resp.get("device_code")
        interval = int(proxy_resp.get("interval") or 5)

        session_obj = PendingOAuthSession(
            state=state,
            provider=prov,
            flow=flow,
            replace_account_id=replace_account_id,
            created_at=now,
            expires_at=now + expires_in,
            auth_url=auth_url,
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            interval=interval,
            status="pending",
            auth_files=auth_files,
        )

        async with self._lock:
            self._sessions[state] = session_obj

        # Safe summary for caller (no secret)
        return {
            "state": state,
            "provider": prov,
            "flow": flow,
            "auth_url": auth_url,
            "user_code": user_code,
            "verification_uri": verification_uri,
            "expires_in": int(expires_in),
            "interval": interval,
            "status": "pending",
        }

    async def poll_session(
        self,
        state: str,
        db_session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Poll the status of an ongoing OAuth flow and reconcile on completion."""
        async with self._lock:
            session = self._sessions.get(state)

        if session is None:
            raise KeyError(f"OAuth session with state '{state}' not found or already closed.")

        now = time.time()
        # 1. Check expiration
        if now > session.expires_at:
            async with self._lock:
                session.status = "expired"
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

        # 2. Check cancellation
        if session.status == "cancelled":
            return {"status": "cancelled", "message": "OAuth session was cancelled."}

        # 3. Check already failed
        if session.status == "failed":
            return session.result or {
                "status": "failed",
                "error": session.error or "OAuth authorization failed",
                "provider": session.provider,
            }

        # 4. Check already completed
        if session.status == "completed" and session.result is not None:
            return session.result

        # 5. Check if currently reconciling
        need_wait = False
        async with self._lock:
            if session.status == "reconciling":
                need_wait = True

        if need_wait:
            try:
                await asyncio.wait_for(session.reconcile_event.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                return {"status": "pending", "message": "Reconciliation in progress..."}
            return session.result or {
                "status": session.status,
                "error": session.error,
                "provider": session.provider,
            }

        # 6. Poll supervisor management client
        supervisor = get_proxy_supervisor()
        if not supervisor.is_running:
            return {"status": "pending", "message": "Proxy is starting..."}

        try:
            status_data = await supervisor.get_management_client().get_oauth_status(state)
        except Exception as exc:
            logger.debug("OAuth status request failed (%s)", type(exc).__name__)
            return {"status": "pending"}

        p_status = str(status_data.get("status", "pending")).lower()

        # Check for immediate failure / error / denied states from upstream
        if p_status in ("failed", "error", "denied", "cancelled") or status_data.get("error"):
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

            # Persist error on account if replacing
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
                    logger.debug("Failed saving credential error: %s", exc)

            return fail_result

        if p_status != "ok":
            return {
                "status": "pending",
                "interval": session.interval,
                "user_code": session.user_code,
                "verification_uri": session.verification_uri,
            }

        # Transition to reconciling under lock so only ONE coroutine runs reconciliation
        async with self._lock:
            if session.status in ("completed", "failed"):
                return session.result or {"status": session.status}
            if session.status == "reconciling":
                need_wait_reconcile = True
            else:
                session.status = "reconciling"
                need_wait_reconcile = False

        if need_wait_reconcile:
            try:
                await asyncio.wait_for(session.reconcile_event.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                return {"status": "pending", "message": "Reconciliation in progress..."}
            return session.result or {
                "status": session.status,
                "error": session.error,
                "provider": session.provider,
            }

        # Exclusive reconciler
        try:
            if db_session is not None:
                res_dict = await self._do_reconcile(session, status_data, db_session)
            else:
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as s:
                    res_dict = await self._do_reconcile(session, status_data, s)

            async with self._lock:
                session.status = "completed"
                session.result = res_dict
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
            raise
        finally:
            session.reconcile_event.set()

    @staticmethod
    def _snapshot_auth_files(auth_dir: Path | None) -> dict[str, str]:
        if auth_dir is None or not auth_dir.exists():
            return {}
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in auth_dir.glob("*.json") if not path.is_symlink()}

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
            route_id = f"oauth:{session.provider}"
            vault = get_provider_vault()
            existing = list((await s.execute(select(AIProviderCredential).where(AIProviderCredential.route_id == route_id, AIProviderCredential.kind == "oauth"))).scalars().all())
            matched = None
            for credential in existing:
                stored = await vault.get_oauth_auth(credential.vault_reference.removeprefix("oauth_auth:"))
                if isinstance(stored, dict):
                    stored_identity = stored.get("email") or stored.get("account_id") or stored.get("identity") or stored.get("user")
                    if stored_identity and str(stored_identity).strip().lower() == str(identity).strip().lower():
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
            return {"status": "completed", "account_id": credential.id, "route_id": route_id,
                    "masked_identity": credential.masked_identity, "notice": notice}

    async def cancel_all_sessions(self) -> None:
        for state, session in list(self._sessions.items()):
            if session.status in ("pending", "reconciling"):
                await self.cancel_session(state)
        async with self._reconcile_lock:
            self._sessions.clear()

    async def cancel_session(self, state: str) -> dict[str, str]:
        """Cancel an ongoing OAuth session."""
        async with self._lock:
            session = self._sessions.get(state)
            if session:
                session.status = "cancelled"

        supervisor = get_proxy_supervisor()
        if supervisor.is_running:
            try:
                await supervisor.get_management_client().cancel_oauth_session(state)
            except Exception as exc:
                logger.debug("Cancel oauth error on supervisor: %s", exc)

        return {"status": "cancelled", "state": state}

    async def handle_callback(
        self,
        state: str,
        code: str | None = None,
        raw_params: dict[str, Any] | None = None,
        db_session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Submit callback payload to proxy supervisor without logging query strings or tokens."""
        supervisor = get_proxy_supervisor()
        if supervisor.is_running:
            payload: dict[str, Any] = {"state": state}
            if code:
                payload["code"] = code
            if raw_params:
                for k, v in raw_params.items():
                    if k not in payload:
                        payload[k] = v
            try:
                await supervisor.get_management_client().submit_oauth_callback(payload)
            except Exception:
                pass
        return await self.poll_session(state=state, db_session=db_session)


# Global session manager instance
_oauth_session_manager: OAuthSessionManager | None = None


def get_oauth_session_manager() -> OAuthSessionManager:
    global _oauth_session_manager
    if _oauth_session_manager is None:
        _oauth_session_manager = OAuthSessionManager()
    return _oauth_session_manager

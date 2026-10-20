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
import logging
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
from app.services.route_registry import OAUTH_PROVIDERS

logger = logging.getLogger("blm.oauth_session_manager")

DEFAULT_SESSION_TTL = 900.0  # 15 minutes


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
    status: str = "pending"  # "pending" | "completed" | "expired" | "cancelled" | "failed"
    result: dict[str, Any] | None = None
    error: str | None = None


class OAuthSessionManager:
    """Manages active OAuth authentication flows and identity reconciliation."""

    def __init__(self, ttl: float = DEFAULT_SESSION_TTL) -> None:
        self._ttl = ttl
        self._sessions: dict[str, PendingOAuthSession] = {}
        self._lock = asyncio.Lock()

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
        if not vault.is_available:
            raise RuntimeError(
                f"Provider vault is currently unavailable (state: {vault.state.value}). Cannot start OAuth."
            )

        # Verify replace_account_id exists if specified
        if replace_account_id:
            if db_session is not None:
                res = await db_session.execute(
                    select(AIProviderCredential).where(AIProviderCredential.id == replace_account_id)
                )
                existing = res.scalar_one_or_none()
                if existing is None:
                    raise ValueError(f"Account to replace '{replace_account_id}' was not found.")
            else:
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as s:
                    res = await s.execute(
                        select(AIProviderCredential).where(AIProviderCredential.id == replace_account_id)
                    )
                    existing = res.scalar_one_or_none()
                    if existing is None:
                        raise ValueError(f"Account to replace '{replace_account_id}' was not found.")

        # Ensure supervisor is started
        supervisor = get_proxy_supervisor()
        await supervisor.ensure_started()
        mgmt = supervisor.get_management_client()

        params: dict[str, Any] = {}
        if flow == "device":
            params["flow"] = "device"

        # Start via proxy management API
        try:
            proxy_resp = await mgmt.start_oauth(prov, params=params)
        except Exception as exc:
            logger.warning("Failed to start OAuth session via proxy for %s: %s", prov, exc)
            raise RuntimeError(f"Proxy management API failed to initiate OAuth for '{prov}'") from exc

        state = proxy_resp.get("state") or secrets.token_urlsafe(24)
        expires_in = float(proxy_resp.get("expires_in") or self._ttl)
        now = time.time()

        auth_url = proxy_resp.get("auth_url") or proxy_resp.get("url")
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
            session.status = "expired"
            supervisor = get_proxy_supervisor()
            if supervisor.is_running():
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

        # 3. Check already completed
        if session.status == "completed" and session.result is not None:
            return session.result

        # 4. Poll supervisor management client
        supervisor = get_proxy_supervisor()
        if not supervisor.is_running():
            return {"status": "pending", "message": "Proxy is starting..."}

        try:
            status_data = await supervisor.get_management_client().get_oauth_status(state)
        except Exception as exc:
            logger.debug("Proxy management get_oauth_status returned error for state %s: %s", state, exc)
            return {"status": "pending"}

        p_status = str(status_data.get("status", "pending")).lower()
        if p_status not in ("completed", "success", "done"):
            return {
                "status": "pending",
                "interval": session.interval,
                "user_code": session.user_code,
                "verification_uri": session.verification_uri,
            }

        # Session has completed upstream! Perform identity reconciliation.
        async def _reconcile(s: AsyncSession) -> dict[str, Any]:
            route_id = f"oauth:{session.provider}"
            # Extract raw identity safely without logging tokens
            raw_identity = (
                status_data.get("identity")
                or status_data.get("email")
                or status_data.get("user")
                or status_data.get("credential_name")
                or f"{session.provider}-account"
            )
            masked = mask_identity(str(raw_identity))
            vault = get_provider_vault()
            notice: str | None = None
            cred: AIProviderCredential

            # Store auth payload in vault
            auth_payload = status_data.get("auth") or status_data.get("token") or status_data

            if session.replace_account_id:
                # Query existing account
                res = await s.execute(
                    select(AIProviderCredential).where(AIProviderCredential.id == session.replace_account_id)
                )
                existing = res.scalar_one_or_none()
                if existing is not None:
                    # Identity match check: try vault unmasked identity first, fallback to exact masked match
                    existing_ident = existing.masked_identity.lower().strip()
                    new_ident = str(raw_identity).lower().strip()
                    new_masked = masked.lower().strip()
                    existing_raw = None
                    try:
                        stored_auth = await vault.get_oauth_auth(existing.vault_reference)
                        if isinstance(stored_auth, dict):
                            existing_raw = stored_auth.get("identity") or stored_auth.get("email") or stored_auth.get("user")
                        elif isinstance(stored_auth, str):
                            parsed = json.loads(stored_auth)
                            if isinstance(parsed, dict):
                                existing_raw = parsed.get("identity") or parsed.get("email") or parsed.get("user")
                    except Exception:
                        pass

                    if existing_raw:
                        is_match = (str(existing_raw).strip().lower() == new_ident)
                    else:
                        is_match = (existing_ident == new_ident or existing_ident == new_masked)

                    if is_match:
                        # Replace matched account
                        cred = existing
                        cred.status = "active"
                        cred.cooldown = None
                        cred.last_redacted_error = None
                        cred.updated_at = datetime.now(timezone.utc)
                        await vault.set_oauth_auth(cred.vault_reference, auth_payload)
                        notice = None
                    else:
                        # IDENTITY MISMATCH: Do NOT overwrite! Create new account and set notice
                        cred_id = str(uuid.uuid4())
                        vault_ref = f"oauth_{session.provider}_{cred_id}"
                        proxy_name = f"{session.provider}_{cred_id[:8]}"
                        cred = AIProviderCredential(
                            id=cred_id,
                            route_id=route_id,
                            kind="oauth",
                            vault_reference=vault_ref,
                            proxy_credential_name=proxy_name,
                            masked_identity=masked,
                            priority=existing.priority,
                            weight=existing.weight,
                            enabled=True,
                            status="active",
                        )
                        s.add(cred)
                        await vault.set_oauth_auth(vault_ref, auth_payload)
                        notice = (
                            f"Reauthentication identity mismatch: logged in as '{masked}' "
                            f"instead of '{existing.masked_identity}'. Added as a new account."
                        )
                else:
                    # Existing not found; create new
                    cred_id = str(uuid.uuid4())
                    vault_ref = f"oauth_{session.provider}_{cred_id}"
                    proxy_name = f"{session.provider}_{cred_id[:8]}"
                    cred = AIProviderCredential(
                        id=cred_id,
                        route_id=route_id,
                        kind="oauth",
                        vault_reference=vault_ref,
                        proxy_credential_name=proxy_name,
                        masked_identity=masked,
                        priority=1,
                        weight=1,
                        enabled=True,
                        status="active",
                    )
                    s.add(cred)
                    await vault.set_oauth_auth(vault_ref, auth_payload)
            else:
                # Normal addition (no replacement requested)
                # Check if existing account with same identity exists
                res = await s.execute(
                    select(AIProviderCredential).where(
                        AIProviderCredential.route_id == route_id,
                        AIProviderCredential.masked_identity == masked,
                    )
                )
                existing_match = res.scalar_one_or_none()
                if existing_match is not None:
                    cred = existing_match
                    cred.status = "active"
                    cred.cooldown = None
                    cred.last_redacted_error = None
                    cred.updated_at = datetime.now(timezone.utc)
                    await vault.set_oauth_auth(cred.vault_reference, auth_payload)
                else:
                    cred_id = str(uuid.uuid4())
                    vault_ref = f"oauth_{session.provider}_{cred_id}"
                    proxy_name = f"{session.provider}_{cred_id[:8]}"
                    cred = AIProviderCredential(
                        id=cred_id,
                        route_id=route_id,
                        kind="oauth",
                        vault_reference=vault_ref,
                        proxy_credential_name=proxy_name,
                        masked_identity=masked,
                        priority=1,
                        weight=1,
                        enabled=True,
                        status="active",
                    )
                    s.add(cred)
                    await vault.set_oauth_auth(vault_ref, auth_payload)

            await s.commit()
            supervisor.request_sync()

            out = {
                "status": "completed",
                "account_id": cred.id,
                "route_id": route_id,
                "masked_identity": cred.masked_identity,
                "notice": notice,
            }
            return out

        if db_session is not None:
            res_dict = await _reconcile(db_session)
        else:
            from app.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                res_dict = await _reconcile(s)

        session.status = "completed"
        session.result = res_dict
        return res_dict

    async def cancel_session(self, state: str) -> dict[str, str]:
        """Cancel an ongoing OAuth session."""
        async with self._lock:
            session = self._sessions.get(state)
            if session:
                session.status = "cancelled"

        supervisor = get_proxy_supervisor()
        if supervisor.is_running():
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
        if supervisor.is_running():
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

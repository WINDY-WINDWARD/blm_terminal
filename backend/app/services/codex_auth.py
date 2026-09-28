"""OpenAI Codex (ChatGPT subscription) OAuth — device-code login + token refresh.

Port of the Hermes Agent ``auth_codex.py`` device flow, adapted to this codebase:
- Tokens persist in the ``system_config`` DB table (``ai.codex_access_token`` /
  ``ai.codex_refresh_token``) instead of ``~/.hermes/auth.json``.
- Async-first (``httpx.AsyncClient``); no cross-process locking (single desktop backend).
- Refresh tokens are SINGLE-USE with server-side rotation: every refresh returns a
  new refresh token that must be persisted immediately.

Flow:
1. ``start_device_login()`` — POST deviceauth/usercode → {device_auth_id, user_code, …}
2. User opens https://auth.openai.com/codex/device and enters the code.
3. ``poll_device_login()`` — poll deviceauth/token until 200 → {authorization_code, code_verifier}
4. ``exchange_authorization_code()`` — swap for {access_token, refresh_token}, persist both.
5. ``get_codex_access_token()`` — return a valid access token, refreshing when the
   JWT ``exp`` claim is within the skew window.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import select

logger = logging.getLogger(__name__)

# --- Hermes-derived constants -------------------------------------------------
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_ISSUER = "https://auth.openai.com"
CODEX_DEVICE_URL = "https://auth.openai.com/codex/device"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
# Third-party harness identity (OpenAI requires harnesses to identify
# themselves — mirrors Hermes' HermesAgent/{version} + originator header).
CODEX_USER_AGENT = "BLM-Terminal/1.0"
CODEX_ORIGINATOR = "blm-terminal"

# Refresh up to 2 minutes before the JWT exp.
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120

# DB slots for the token pair.
DB_ACCESS_TOKEN_KEY = "ai.codex_access_token"
DB_REFRESH_TOKEN_KEY = "ai.codex_refresh_token"

# Curated Codex model list — the Codex backend exposes no /models catalog,
# so this is maintained by hand from OpenAI's Codex models doc
# (developers.openai.com/codex/models). Tier hints in labels tell users
# what their ChatGPT plan unlocks; retired IDs (gpt-5.1-codex-* shut down
# Jul 2026, gpt-5.2 / gpt-5.4 / gpt-5.4-mini retired Aug 2026,
# gpt-5.3-codex / gpt-5.3-codex-spark deprecated per models doc Sep 2026)
# are dropped because the backend 400s them with "model is not supported".
# gpt-5.5 retires Oct 14 2026 — kept until then.
CODEX_MODELS: list[dict[str, str]] = [
    {"id": "gpt-6-astra", "label": "[Codex] gpt-6-astra (newest)"},
    {"id": "gpt-6-sol", "label": "[Codex] gpt-6-sol (complex coding, Plus and up)"},
    {"id": "gpt-6-luna", "label": "[Codex] gpt-6-luna (fast, all plans)"},
    {"id": "gpt-5.6-sol", "label": "[Codex] gpt-5.6-sol (flagship, Plus and up)"},
    {"id": "gpt-5.6-terra", "label": "[Codex] gpt-5.6-terra (balanced, all plans)"},
    {"id": "gpt-5.6-luna", "label": "[Codex] gpt-5.6-luna (fast, Plus and up)"},
    {"id": "gpt-5.5", "label": "[Codex] gpt-5.5 (retires Oct 14 2026)"},
]


class CodexAuthError(RuntimeError):
    """Structured Codex auth failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "codex_auth_error",
        relogin_required: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.relogin_required = relogin_required
        self.retry_after = retry_after


# --- DB helpers ----------------------------------------------------------------

async def _db_get(key: str) -> str | None:
    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == key)
            )
            val = res.scalar_one_or_none()
            return val.strip() if val and val.strip() else None
    except Exception as e:
        logger.warning("Codex auth: failed to read %s: %s", key, e)
        return None


async def _db_set(key: str, value: str) -> None:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.database import AsyncSessionLocal
    from app.models.system_config import SystemConfig

    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(SystemConfig).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": value}
        )
        await session.execute(stmt)
        await session.commit()


async def _db_clear(key: str) -> None:
    from sqlalchemy import delete

    from app.database import AsyncSessionLocal
    from app.models.system_config import SystemConfig

    async with AsyncSessionLocal() as session:
        await session.execute(delete(SystemConfig).where(SystemConfig.key == key))
        await session.commit()


# --- JWT helpers ---------------------------------------------------------------

def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT payload claims without verification (exp/account lookup only)."""
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def access_token_expiring_soon(access_token: str, skew_seconds: int = ACCESS_TOKEN_REFRESH_SKEW_SECONDS) -> bool:
    exp = decode_jwt_claims(access_token).get("exp")
    if not isinstance(exp, (int, float)):
        return True  # can't tell — treat as needing refresh
    return float(exp) <= (time.time() + max(0, int(skew_seconds)))


def chatgpt_account_id(access_token: str) -> str | None:
    """Extract ChatGPT-Account-Id from the JWT (required header for some account shapes)."""
    auth_claims = decode_jwt_claims(access_token).get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        acct = auth_claims.get("chatgpt_account_id")
        if isinstance(acct, str) and acct.strip():
            return acct.strip()
    return None


# --- Device-code login flow ----------------------------------------------------

async def start_device_login() -> dict[str, Any]:
    """Step 1: request a user code. Returns device_auth_id/user_code/verification URL."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{CODEX_ISSUER}/api/accounts/deviceauth/usercode",
            json={"client_id": CODEX_OAUTH_CLIENT_ID},
            headers={"Content-Type": "application/json"},
        )
    if resp.status_code == 429:
        raise CodexAuthError(
            "OpenAI is rate-limiting Codex login requests (HTTP 429). Wait a minute and retry.",
            code="codex_rate_limited",
            retry_after=60.0,
        )
    if resp.status_code != 200:
        raise CodexAuthError(
            f"Device code request returned status {resp.status_code}.",
            code="device_code_request_error",
        )
    data = resp.json()
    if not data.get("user_code") or not data.get("device_auth_id"):
        raise CodexAuthError(
            "Device code response missing required fields.", code="device_code_incomplete"
        )
    return {
        "device_auth_id": data["device_auth_id"],
        "user_code": data["user_code"],
        "verification_url": CODEX_DEVICE_URL,
        "interval": max(3, int(data.get("interval", 5))),
    }


async def poll_device_login(device_auth_id: str, user_code: str) -> dict[str, Any]:
    """Step 2: single poll attempt. Returns {status: pending|complete, ...}.

    403/404 = user hasn't finished yet. On 200, exchanges the authorization code
    for tokens, persists them, and returns {status: complete}.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{CODEX_ISSUER}/api/accounts/deviceauth/token",
            json={"device_auth_id": device_auth_id, "user_code": user_code},
            headers={"Content-Type": "application/json"},
        )
    if resp.status_code in (403, 404):
        return {"status": "pending"}
    if resp.status_code != 200:
        raise CodexAuthError(
            f"Device auth polling returned status {resp.status_code}.",
            code="device_code_poll_error",
        )
    code_resp = resp.json()
    tokens = await exchange_authorization_code(
        code_resp.get("authorization_code", ""),
        code_resp.get("code_verifier", ""),
    )
    await save_codex_tokens(tokens["access_token"], tokens["refresh_token"])
    return {"status": "complete"}


async def exchange_authorization_code(authorization_code: str, code_verifier: str) -> dict[str, str]:
    """Step 3: swap the authorization code for an access/refresh token pair."""
    if not authorization_code or not code_verifier:
        raise CodexAuthError(
            "Device auth response missing authorization_code or code_verifier.",
            code="device_code_incomplete_exchange",
        )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            CODEX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": f"{CODEX_ISSUER}/deviceauth/callback",
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code == 429:
        raise CodexAuthError(
            "OpenAI is rate-limiting Codex login (HTTP 429).",
            code="codex_rate_limited",
            retry_after=60.0,
        )
    if resp.status_code != 200:
        raise CodexAuthError(
            f"Token exchange returned status {resp.status_code}.",
            code="token_exchange_error",
        )
    tokens = resp.json()
    if not tokens.get("access_token"):
        raise CodexAuthError(
            "Token exchange did not return an access_token.",
            code="token_exchange_no_access_token",
        )
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
    }


# --- Token storage + refresh ---------------------------------------------------

async def save_codex_tokens(access_token: str, refresh_token: str) -> None:
    """Persist a fresh token pair (rotation: always store the newest refresh token)."""
    await _db_set(DB_ACCESS_TOKEN_KEY, access_token)
    if refresh_token:
        await _db_set(DB_REFRESH_TOKEN_KEY, refresh_token)


async def clear_codex_tokens() -> None:
    await _db_clear(DB_ACCESS_TOKEN_KEY)
    await _db_clear(DB_REFRESH_TOKEN_KEY)


async def refresh_codex_tokens() -> dict[str, str]:
    """Use the stored single-use refresh token to mint a new pair (and persist it)."""
    refresh_token = await _db_get(DB_REFRESH_TOKEN_KEY)
    if not refresh_token:
        raise CodexAuthError(
            "No Codex refresh token stored. Sign in again.",
            code="codex_auth_missing",
            relogin_required=True,
        )
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            CODEX_OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": CODEX_USER_AGENT,
            },
        )
    if resp.status_code == 429:
        raise CodexAuthError(
            "Codex quota exhausted (429). Credentials are still valid; retry later.",
            code="codex_rate_limited",
        )
    if resp.status_code != 200:
        # 401/403 or invalid_grant = refresh token consumed/expired → relogin.
        relogin = resp.status_code in (400, 401, 403)
        raise CodexAuthError(
            f"Codex token refresh failed (HTTP {resp.status_code})."
            + (" Sign in again." if relogin else ""),
            code="codex_refresh_failed",
            relogin_required=relogin,
        )
    payload = resp.json()
    access_token = payload.get("access_token", "")
    if not access_token:
        raise CodexAuthError(
            "Codex token refresh response was missing access_token.",
            code="codex_refresh_missing_access_token",
        )
    new_refresh = payload.get("refresh_token") or refresh_token
    await save_codex_tokens(access_token, new_refresh)
    return {"access_token": access_token, "refresh_token": new_refresh}


async def get_codex_access_token(*, force_refresh: bool = False) -> str | None:
    """Return a valid Codex access token, refreshing proactively when near expiry."""
    access_token = await _db_get(DB_ACCESS_TOKEN_KEY)
    if not access_token:
        return None
    if force_refresh or access_token_expiring_soon(access_token):
        try:
            refreshed = await refresh_codex_tokens()
            return refreshed["access_token"]
        except CodexAuthError as e:
            if e.code == "codex_rate_limited":
                # Quota stop — the existing token may still work for a bit; hand it
                # back and let the wire surface the 429 distinctly.
                logger.warning("Codex refresh hit quota limit; using stored token")
                return access_token
            logger.warning("Codex refresh failed: %s", e)
            return None
    return access_token


async def get_codex_status() -> dict[str, Any]:
    """Login status for the Settings UI / /ai/status."""
    access_token = await _db_get(DB_ACCESS_TOKEN_KEY)
    if not access_token:
        return {"logged_in": False, "expires_at": None}
    claims = decode_jwt_claims(access_token)
    exp = claims.get("exp")
    return {
        "logged_in": True,
        "expires_at": int(exp) if isinstance(exp, (int, float)) else None,
        "expiring_soon": access_token_expiring_soon(access_token),
    }

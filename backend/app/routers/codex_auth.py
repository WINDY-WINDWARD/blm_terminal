"""REST surface for the OpenAI Codex (ChatGPT subscription) device-code login.

Flow (driven by the Settings widget):
1. ``POST /auth/codex/login/start`` → {device_auth_id, user_code, verification_url}
2. User opens verification_url in a browser and enters user_code.
3. Frontend polls ``GET /auth/codex/login/poll?device_auth_id=…&user_code=…``
   until {status: complete} (tokens are persisted server-side on completion).
4. ``GET /auth/codex/status`` → {logged_in, expires_at, expiring_soon}
5. ``POST /auth/codex/logout`` → clears stored tokens.
"""

import logging

from fastapi import APIRouter, Depends

from app.auth import get_admin_user
from app.services.codex_auth import (
    CODEX_DEVICE_URL,
    CodexAuthError,
    clear_codex_tokens,
    get_codex_status,
    poll_device_login,
    start_device_login,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth/codex",
    tags=["auth", "codex"],
    dependencies=[Depends(get_admin_user)],
)


@router.post("/login/start")
async def codex_login_start() -> dict:
    """Begin the ChatGPT device-code login. Returns the code the user must enter."""
    try:
        result = await start_device_login()
    except CodexAuthError as e:
        return {"error": str(e), "code": e.code}
    return result


@router.get("/login/poll")
async def codex_login_poll(device_auth_id: str, user_code: str) -> dict:
    """Poll once for device-code completion. Persists tokens on success."""
    try:
        return await poll_device_login(device_auth_id, user_code)
    except CodexAuthError as e:
        return {"status": "error", "error": str(e), "code": e.code}


@router.get("/status")
async def codex_status() -> dict:
    """Login status for the Settings UI / /ai/status."""
    status = await get_codex_status()
    return {"verification_url": CODEX_DEVICE_URL, **status}


@router.post("/logout")
async def codex_logout() -> dict:
    """Clear stored Codex tokens."""
    await clear_codex_tokens()
    return {"logged_out": True}

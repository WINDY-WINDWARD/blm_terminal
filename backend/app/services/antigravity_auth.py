import json
import logging
from pathlib import Path
import httpx
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = Path(__file__).parent.parent.parent / ".ag_credentials.json"

AG_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
AG_CLIENT_SECRET = "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"

_cached_access_token = None
_token_expires_at = None

async def get_antigravity_token() -> str | None:
    """Get a valid access token for Antigravity, refreshing if necessary."""
    global _cached_access_token, _token_expires_at
    
    now = datetime.now(timezone.utc)
    
    # Return cached if valid for at least 5 more minutes
    if _cached_access_token and _token_expires_at and _token_expires_at > (now + timedelta(minutes=5)):
        return _cached_access_token
        
    if not CREDENTIALS_FILE.exists():
        logger.error("Antigravity credentials missing. Run 'python backend/scripts/ag_login.py'.")
        return None
        
    try:
        creds = json.loads(CREDENTIALS_FILE.read_text())
        refresh_token = creds.get("refresh_token")
        if not refresh_token:
            return None
            
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": AG_CLIENT_ID,
                    "client_secret": AG_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            )
            
        if resp.status_code == 200:
            data = resp.json()
            _cached_access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            _token_expires_at = now + timedelta(seconds=expires_in)
            return _cached_access_token
        else:
            logger.error(f"Failed to refresh Antigravity token: {resp.text}")
            return None
    except Exception as e:
        logger.exception("Error refreshing Antigravity token.")
        return None

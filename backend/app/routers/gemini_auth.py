import os
import json
import base64
import hashlib
import logging
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/gemini", tags=["auth", "gemini"])

AG_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
AG_CLIENT_SECRET = "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"
AG_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

# OS-Safe Credentials File Path
if os.environ.get("DB_PATH"):
    CREDENTIALS_FILE = Path(os.environ["DB_PATH"]).parent / ".ag_credentials.json"
else:
    CREDENTIALS_FILE = Path(__file__).resolve().parents[3] / ".ag_credentials.json"

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urlparse(self.path).query
        params = parse_qs(query)
        if "code" in params:
            self.server.oauth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authentication Successful!</h2><p>You can close this window now.</p><script>setTimeout(() => window.close(), 2000);</script></body></html>")
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Authentication Failed!</h2><p>No code returned.</p></body></html>")
            self.server.oauth_code = None

def run_local_server(port=51121, timeout=120):
    server = HTTPServer(("localhost", port), OAuthCallbackHandler)
    server.oauth_code = None
    server.timeout = timeout
    
    # Handle exactly one request
    server.handle_request()
    return server.oauth_code

async def _wait_for_callback(code_verifier: str):
    loop = asyncio.get_running_loop()
    try:
        code = await loop.run_in_executor(None, run_local_server, 51121, 120)
        if not code:
            logger.error("OAuth failed or timed out waiting for callback.")
            return
            
        # Exchange token
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": AG_CLIENT_ID,
            "client_secret": AG_CLIENT_SECRET,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": "http://localhost:51121/oauth-callback",
            "grant_type": "authorization_code",
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                logger.error("Token exchange failed: %s", resp.text)
                return
                
            token_data = resp.json()
        
        # Save credentials
        CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CREDENTIALS_FILE, "w") as f:
            json.dump(token_data, f)
            
        logger.info("Gemini (Antigravity) credentials saved to %s", CREDENTIALS_FILE)
    except Exception as e:
        logger.error("Error during background OAuth flow: %s", e)

@router.get("/login")
async def gemini_login():
    """Initiate the Google OAuth flow for Gemini (Antigravity)."""
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode('utf-8').replace('=', '')
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode('utf-8')).digest()).decode('utf-8').replace('=', '')
    
    redirect_uri = "http://localhost:51121/oauth-callback"
    
    params = {
        "client_id": AG_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(AG_SCOPES),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }
    
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    # Start background task to listen on 51121
    asyncio.create_task(_wait_for_callback(code_verifier))
    
    return {"auth_url": auth_url}

@router.get("/status")
async def gemini_status():
    """Check if Gemini credentials exist and are valid."""
    if not CREDENTIALS_FILE.exists():
        return {"configured": False}
        
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            data = json.load(f)
            
        return {
            "configured": True,
            "has_refresh_token": "refresh_token" in data
        }
    except Exception as e:
        logger.error("Failed to read credentials: %s", e)
        return {"configured": False, "error": str(e)}

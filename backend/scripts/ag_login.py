import os
import json
import webbrowser
import httpx
import sys
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

import base64
import hashlib

# Load .env to check if Antigravity is even selected
load_dotenv(".env")
load_dotenv(".env.local", override=True)

AG_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
AG_CLIENT_SECRET = "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"
AG_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]

CREDENTIALS_FILE = Path(__file__).parent.parent / ".ag_credentials.json"

def test_token(access_token: str) -> bool:
    """Test if the access token is valid by hitting a lightweight Google endpoint."""
    resp = httpx.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"access_token": access_token}
    )
    return resp.status_code == 200

def refresh_access_token(refresh_token: str) -> str | None:
    """Attempt to get a new access token using the refresh token."""
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": AG_CLIENT_ID,
            "client_secret": AG_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    )
    if resp.status_code == 200:
        return resp.json().get("access_token")
    return None

class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        
        parsed_url = urlparse(self.path)
        if parsed_url.path != "/oauth-callback":
            self.wfile.write(b"Not found")
            return
            
        params = parse_qs(parsed_url.query)
        
        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.wfile.write(b"<html><body><h1>Authentication successful!</h1><p>You can close this tab and return to your terminal.</p><script>window.close()</script></body></html>")
        else:
            self.wfile.write(b"<html><body><h1>Authentication failed!</h1><p>No code found. Please check your terminal.</p></body></html>")
            
    def log_message(self, format, *args):
        pass # suppress console logging

def generate_pkce_pair():
    """Generate a high-entropy PKCE verifier and its SHA-256 challenge."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').rstrip('=')
    challenge_bytes = hashlib.sha256(verifier.encode('utf-8')).digest()
    challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
    return verifier, challenge

def login():
    """Perform Local Server OAuth Login with PKCE."""
    # Google strictly expects this redirect URI for this Client ID
    redirect_uri = "http://localhost:51121/oauth-callback"
    
    # Start a local server strictly on port 51121
    try:
        server = HTTPServer(('127.0.0.1', 51121), OAuthHandler)
    except OSError as e:
        print(f"Failed to bind to port 51121. Is another instance running? Error: {e}")
        sys.exit(1)
        
    code_verifier, code_challenge = generate_pkce_pair()
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={AG_CLIENT_ID}&"
        f"redirect_uri={redirect_uri}&"
        f"response_type=code&"
        f"scope={' '.join(AG_SCOPES)}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"code_challenge={code_challenge}&"
        f"code_challenge_method=S256"
    )
    
    print("\n" + "="*60)
    print("Antigravity Auth Required!")
    print("="*60)
    print("1. A browser window will open. Login with your Google account.")
    print("2. The browser will auto-redirect and authenticate.")
    print("If it doesn't open automatically, click this link:\n")
    print(auth_url)
    print("\nWaiting for authentication..." + "="*60 + "\n")
    
    webbrowser.open(auth_url)
    
    server.auth_code = None
    while not server.auth_code:
        server.handle_request()
        
    code = server.auth_code
    server.server_close()
    
    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": AG_CLIENT_ID,
            "client_secret": AG_CLIENT_SECRET,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
    )
    
    if resp.status_code != 200:
        print(f"Failed to exchange code: {resp.text}")
        sys.exit(1)
        
    data = resp.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print("No refresh token received. You may need to revoke access in Google Account and try again.")
        sys.exit(1)
        
    CREDENTIALS_FILE.write_text(json.dumps({"refresh_token": refresh_token}))
    print("\n[SUCCESS] Antigravity Auth Successful! Credentials saved.\n")

def main():
    if os.environ.get("AI_PROVIDER") != "antigravity":
        # If not using antigravity, skip seamlessly
        return

    if CREDENTIALS_FILE.exists():
        try:
            creds = json.loads(CREDENTIALS_FILE.read_text())
            refresh_token = creds.get("refresh_token")
            if refresh_token:
                # Test if refresh token works
                access_token = refresh_access_token(refresh_token)
                if access_token and test_token(access_token):
                    # Valid token, proceed silently
                    return
        except Exception as e:
            pass
            
    # Need to login
    login()

if __name__ == "__main__":
    main()

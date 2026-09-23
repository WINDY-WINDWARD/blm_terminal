"""iinvest.cogencis.com data source client.

Auto-acquires a guest JWT (no user action required) by reusing the AES-256
key the iinvest frontend ships in its own JS bundle. All 18 read-only data
endpoints + the news endpoint are exposed as typed methods; an aggregator
hits all of them in parallel via ``asyncio.gather``.

Auth: iinvest's ``/api/login`` returns an OpenSSL ``Salted__<salt><ct>`` blob
encrypted with a hardcoded passphrase. Decrypting yields a 24-hour HS256 JWT
for a shared ``view``-role guest user. The key is in the public bundle, so
this is functionally equivalent to a "free tier" auth — no credentials, no
captcha, no Settings field.

Refresh: a 20-hour background cycle replaces the JWT 4 hours before expiry.
On 401 from any data call, the client re-logs in once and retries; if the
retry still 401s, the call surfaces as a 503.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.services.persistent_cache import get_cached_json, set_cached_json

logger = logging.getLogger(__name__)


# Defer the NSE client import to avoid a circular import at module load
# (nse_client_async imports a bunch of FastAPI deps that may not be set
# up during a simple unit test). The reference is set at the bottom of
# this module once both modules are loaded.
nse_client: Any = None  # type: ignore[assignment]


# ── Constants (verified live) ────────────────────────────────────────────────

IINVEST_BASE_URL = "https://data.cogencis.com"
IINVEST_SITE_URL = "https://iinvest.cogencis.com"
IINVEST_LOGIN_URL = f"{IINVEST_SITE_URL}/api/login"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Origin": IINVEST_SITE_URL,
    "Referer": f"{IINVEST_SITE_URL}/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

# 24h JWT lifetime; refresh 4h early to leave slack.
_JWT_REFRESH_AHEAD_SECONDS = 4 * 3600

# Harvested tokens expiring sooner than this are rejected (the 24h harvest
# cache otherwise serves day-old tokens that 401 on every call).
_JWT_ACCEPT_MARGIN_SECONDS = 15 * 60

# Guest-login AES passphrase. PUBLIC — ships in iinvest's own JS bundle
# (/_next/static/chunks/pages/_app-*.js); functionally a free-tier key, not a
# secret. Env override exists for emergency rotation without a rebuild.
# NOTE: CryptoJS `AES.decrypt(blob, key)` treats the base64 *string itself*
# as the passphrase bytes (openssl `enc -k` semantics), so we feed the
# literal 44-char string, NOT its base64-decoded bytes.
_COGENCIS_AES_KEY_DEFAULT = "SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us="
_AES_KEY_PASSPHRASE = os.environ.get("COGENCIS_AES_KEY", _COGENCIS_AES_KEY_DEFAULT)

# Module-level singleton (mirrors screener_client / news_fetcher pattern).
_iinvest_client: "IinvestClient | None" = None


def _current_aes_key() -> str:
    return _AES_KEY_PASSPHRASE


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey (MD5, 1 iteration) — matches `openssl enc -k`."""
    out = b""
    prev = b""
    while len(out) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        out += prev
    return out[:key_len], out[key_len:key_len + iv_len]


def _decrypt_salted_blob(blob_b64: str, passphrase: str) -> dict[str, Any]:
    """Decrypt an OpenSSL `Salted__` AES-256-CBC blob to a JSON dict.

    Raises ValueError with a classified message: shape problems (not
    base64 / not a Salted__ blob / empty ciphertext) mean the endpoint
    misbehaved and must NOT trigger key recovery; padding/JSON problems
    mean the key is wrong and MAY trigger recovery. Callers rely on this
    distinction.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    try:
        raw = base64.b64decode(blob_b64)
    except Exception as exc:
        raise ValueError(f"login blob is not base64: {exc}") from exc
    if len(raw) < 17 or raw[:8] != b"Salted__":
        raise ValueError("not an OpenSSL Salted__ blob")
    salt, ct = raw[8:16], raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ct) + decryptor.finalize()
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16 or padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("bad PKCS7 padding (wrong key?)")
    try:
        return json.loads(padded[:-pad_len].decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"decrypted payload is not JSON: {exc}") from exc


# ── Auth & Harvester ─────────────────────────────────────────────────────────

from app.services.browser_harvester import harvest_local_storage


# ── Client ────────────────────────────────────────────────────────────────────


class IinvestClient:
    """Async client for iinvest.cogencis.com data APIs."""

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._jwt: str | None = None
        self._jwt_expires_at: datetime | None = None
        self._last_error: str | None = None
        # asyncio.Lock objects bind to the event loop that first uses them, but
        # the client is shared across loops (main lifespan loop + per-thread
        # worker loops via _run_async). The lock is therefore created lazily
        # per running loop — see _get_lock (same pattern as NewsFetcher).
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        # Override-able for tests
        self._refresh_ahead_seconds = _JWT_REFRESH_AHEAD_SECONDS

    def _get_lock(self) -> asyncio.Lock:
        """Return a lock bound to the current event loop (loop-mismatch safe)."""
        current_loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not current_loop:
            self._lock = asyncio.Lock()
            self._lock_loop = current_loop
        return self._lock

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Acquire the JWT and prepare the httpx client. Idempotent."""
        await self._init_locked()

    async def _init_locked(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(
                headers=dict(DEFAULT_HEADERS),
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=False,
            )
        await self._ensure_jwt()
        if not self._jwt:
            self._last_error = "JWT unavailable (consent missing or harvest failed); skipping probe"
            logger.warning(self._last_error)
            return
        # Validate the token with a cheap probe
        try:
            await self._http.get(
                f"{IINVEST_BASE_URL}/api/v1/financials/peers/filters",
                headers={"Authorization": f"Bearer {self._jwt}"},
            )
        except Exception as exc:
            self._last_error = f"JWT probe failed: {exc}"
            logger.warning(self._last_error)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── Auth ───────────────────────────────────────────────────────────────

    async def _ensure_jwt(self) -> None:
        """Acquire or refresh the JWT. Thread-safe & coalesced."""
        now = datetime.now(timezone.utc)
        if (
            self._jwt
            and self._jwt_expires_at
            and self._jwt_expires_at - now > timedelta(seconds=self._refresh_ahead_seconds)
        ):
            return

        async with self._get_lock():
            # Double check after acquiring lock
            if (
                self._jwt
                and self._jwt_expires_at
                and self._jwt_expires_at - now > timedelta(seconds=self._refresh_ahead_seconds)
            ):
                return
            await self._fetch_jwt()

    @staticmethod
    def _extract_token(raw_token: str | None) -> str | None:
        """Unwrap the `next-auth.token` localStorage JSON-string form."""
        if not raw_token:
            return None
        token = raw_token
        if raw_token.strip().startswith("{"):
            try:
                parsed = json.loads(raw_token)
                token = parsed.get("token", raw_token)
            except Exception:
                token = raw_token
        return token or None

    def _token_live(self, token: str, now: datetime) -> datetime | None:
        """Return exp when the token is acceptable, else None.

        Harvested tokens are validated, not trusted: the 24h harvest cache
        otherwise serves day-old tokens that 401 on every data call.
        """
        try:
            import jwt as pyjwt
            decoded = pyjwt.decode(token, options={"verify_signature": False})
            exp = decoded.get("exp")
        except Exception:
            return None
        if not exp:
            return None
        exp_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        if exp_at - now < timedelta(seconds=_JWT_ACCEPT_MARGIN_SECONDS):
            return None
        return exp_at

    async def _guest_login(self) -> None:
        """Acquire a guest JWT via iinvest `/api/login` (no browser needed).

        POSTs with no body, decrypts the `Salted__` blob with the public
        bundle passphrase. Falls back to automatic key recovery (§2.5) once
        when decryption fails (bundle rotated).
        """
        if self._http is None:
            raise RuntimeError("IinvestClient not initialized")

        async def _attempt() -> dict[str, Any]:
            resp = await self._http.post(IINVEST_LOGIN_URL)
            resp.raise_for_status()
            blob = (resp.json() or {}).get("data", "")
            if not blob:
                raise ValueError("empty login blob")
            return _decrypt_salted_blob(blob, _current_aes_key())

        try:
            payload = await _attempt()
        except ValueError as exc:
            msg = str(exc)
            # Shape problems (no blob / not a blob) mean the endpoint
            # misbehaved — key recovery cannot help, fail fast without an
            # extra login POST.
            if "blob" in msg and ("empty" in msg or "not an OpenSSL" in msg or "not base64" in msg):
                raise RuntimeError(f"iinvest guest login failed: {msg}") from exc
            logger.warning("IinvestClient: guest login failed (%s) — trying key recovery", exc)
            if not await self._recover_aes_key():
                raise RuntimeError(f"iinvest guest login failed: {exc}") from exc
            try:
                payload = await _attempt()
            except Exception as exc2:
                raise RuntimeError(f"iinvest guest login failed after key recovery: {exc2}") from exc2
        except Exception as exc:
            # Transport errors (DNS, timeout, HTTP 5xx): the key cannot fix
            # these — surface immediately without recovery traffic.
            raise RuntimeError(f"iinvest guest login request failed: {exc}") from exc

        try:
            token = payload["response"]["token"]
            exp_raw = payload["response"].get("expiration")
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"iinvest login payload malformed: {exc}") from exc
        now = datetime.now(timezone.utc)
        exp_at = self._token_live(token, now)
        if exp_at is None and exp_raw:
            try:
                iso = str(exp_raw).strip()
                if iso.endswith("Z"):
                    iso = iso[:-1] + "+00:00"
                exp_at = datetime.fromisoformat(iso)
                if exp_at.tzinfo is None:
                    exp_at = exp_at.replace(tzinfo=timezone.utc)
            except Exception:
                exp_at = None
        if exp_at is None or exp_at - now < timedelta(seconds=_JWT_ACCEPT_MARGIN_SECONDS):
            raise RuntimeError("iinvest login returned an expired/expiring token")
        self._jwt = token
        self._jwt_expires_at = exp_at
        self._last_error = None
        logger.info("IinvestClient: guest JWT acquired via /api/login (expires %s)",
                    self._jwt_expires_at.isoformat())

    async def _recover_aes_key(self) -> bool:
        """Auto key recovery (§2.5): re-extract the passphrase from the live bundle."""
        global _AES_KEY_PASSPHRASE
        import re

        try:
            if self._http is None:
                return False
            home = await self._http.get(IINVEST_SITE_URL + "/")
            home.raise_for_status()
            m = re.search(r"/_next/static/chunks/pages/_app-[\w.-]+\.js", home.text)
            if not m:
                return False
            js = await self._http.get(IINVEST_SITE_URL + m.group(0))
            js.raise_for_status()
            km = re.search(r'AES\.decrypt\([^,]+,\s*["\']([A-Za-z0-9+/=]{44})["\']\)', js.text)
            if not km or km.group(1) == _current_aes_key():
                return False
            _AES_KEY_PASSPHRASE = km.group(1)
            logger.warning("IinvestClient: AES key recovered from live bundle")
            return True
        except Exception as exc:
            logger.warning("IinvestClient: key recovery failed: %s", exc)
            return False

    async def _fetch_jwt(self, *, force_fresh: bool = False) -> None:
        """Fetch token via browser harvest, falling back to guest login.

        Order: harvest (needs consent + browser) first to preserve current
        behavior on healthy machines; `/api/login` guest flow when harvest
        yields nothing usable. `force_fresh` bypasses the 24h harvest cache —
        used after a 401 where the cached token is known stale.
        """
        now = datetime.now(timezone.utc)
        raw_token = await harvest_local_storage(
            IINVEST_SITE_URL, "next-auth.token", force=force_fresh)
        token = self._extract_token(raw_token)
        if token is not None:
            exp_at = self._token_live(token, now)
            if exp_at is not None:
                self._jwt = token
                self._jwt_expires_at = exp_at
                self._last_error = None
                logger.info("IinvestClient: JWT acquired via harvester (expires %s)",
                            self._jwt_expires_at.isoformat())
                return
            logger.info("IinvestClient: harvested token expired/expiring — trying guest login")
        else:
            self._last_error = "Browser harvester unable to acquire next-auth.token (consent missing or harvester unavailable)"
        await self._guest_login()

    @property
    def is_authenticated(self) -> bool:
        # Liveness, not mere presence: a stored-but-expired JWT must read
        # as unauthenticated so callers re-acquire instead of 401-looping.
        return (
            self._jwt is not None
            and self._jwt_expires_at is not None
            and self._jwt_expires_at > datetime.now(timezone.utc)
        )

    @property
    def jwt(self) -> str | None:
        return self._jwt

    def health(self) -> dict[str, Any]:
        # Healthy only with a live (non-expired) token — presence alone
        # previously reported healthy while every call 401'd on stale JWTs.
        live = (
            self._jwt is not None
            and self._jwt_expires_at is not None
            and self._jwt_expires_at > datetime.now(timezone.utc)
        )
        return {
            "configured": True,
            "healthy": live,
            "expires_at": self._jwt_expires_at.isoformat() if self._jwt_expires_at else None,
            "last_error": self._last_error,
        }

    # ── HTTP helper with 401-retry ─────────────────────────────────────────

    async def _call(
        self,
        endpoint_name: str,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        _retried: bool = False,
    ) -> dict[str, Any]:
        """Generic data-API call with 401 → re-login + retry and persistent caching."""
        # Cache key construction for GET requests (exclude probe endpoint to preserve fresh auth checks)
        cache_key: str | None = None
        if method == "GET" and endpoint_name != "iinvest.financial_peer_filters":
            params_str = ""
            if params:
                params_str = ":" + urllib.parse.urlencode(sorted(params.items()))
            cache_key = f"{endpoint_name}:{url}{params_str}"
            try:
                cached = await get_cached_json(cache_key)
                if cached is not None:
                    logger.debug("iinvest persistent cache hit: %s", cache_key)
                    return cached
            except Exception as e:
                logger.warning("iinvest cache lookup failed for %s: %s", cache_key, e)

        async def _do() -> dict[str, Any]:
            if self._http is None:
                raise RuntimeError("IinvestClient not initialized")
            await self._ensure_jwt()
            headers = {"Authorization": f"Bearer {self._jwt}"}
            if method == "GET":
                resp = await self._http.get(url, params=params, headers=headers)
            else:
                resp = await self._http.post(url, params=params, json=json_body, headers=headers)
            if resp.status_code == 401:
                # Force re-login on next call
                self._jwt = None
                self._jwt_expires_at = None
                raise _Unauthorized(f"401 on {url}")
            if resp.status_code >= 400:
                raise RuntimeError(f"iinvest {endpoint_name} HTTP {resp.status_code}: {resp.text[:200]}")
            return resp.json()

        try:
            # iinvest data endpoints should NOT compete for the NSE India rate-limit semaphore!
            # They use their own lightweight request coalescing.
            from app.services.coalesce import coalesce as _coalesce

            res = await _coalesce(
                f"{endpoint_name}:{url}:{params}:{_retried}",
                _do
            )
            if cache_key and isinstance(res, dict):
                try:
                    await set_cached_json(cache_key, res, ttl_hours=24)
                except Exception as e:
                    logger.warning("iinvest set_cached_json failed for %s: %s", cache_key, e)
            return res
        except _Unauthorized:
            if _retried:
                self._last_error = f"401 on {endpoint_name} even after re-login"
                raise RuntimeError(self._last_error) from None
            # Serialize re-logins: the get_all fan-out (19 parallel
            # endpoints) expiring at once must not fire 19 harvests + logins.
            # (Lock is free here — _ensure_jwt's lock was released before HTTP.)
            async with self._get_lock():
                await self._fetch_jwt(force_fresh=True)
            return await self._call(endpoint_name, method, url, params, json_body, _retried=True)

    # ── Path builder (public so the router and tests can use it) ───────────

    @staticmethod
    def build_path(isin: str, symbol: str, company_name: str) -> str:
        """Build the iinvest data-API path slug.

        Path is lowercased because the iinvest data APIs are case-sensitive.
        Both symbol and company name are URL-encoded (M&M → M%26M, spaces → %20).
        """
        encoded_sym = urllib.parse.quote(symbol, safe="")
        encoded_name = urllib.parse.quote(company_name, safe="")
        return f"{isin.lower()}/symbol/ns/{encoded_sym.lower()}/{encoded_name.lower()}"

    # ── Path resolution (3-tier) ───────────────────────────────────────────

    async def resolve_path(
        self, symbol: str, db: Any | None = None,
    ) -> tuple[str | None, str | None]:
        """Return (isin, path) for a symbol.

        Resolution order:
          1. In-process TTL cache (24h)
          2. stock_universe DB cache (24h)
          3. NSE GetQuoteApi (functionName=getMetaData) — returns ISIN +
             companyName directly. This is the source of truth for NSE
             symbols. The iinvest /api/v1/marketdata/symbollookup endpoint
             is unreliable (returns 0 results for short symbols like TCS,
             and wrong ISINs for symbols with substring collisions like
             RELIANCE → "Reliance Broadcast").
        """
        from app.services.cache import iinvest_path_cache
        from app.models.stockuniverse import StockUniverse
        from sqlalchemy import select

        symbol_upper = symbol.upper()

        # Tier 1: in-process cache
        cached = iinvest_path_cache.get(symbol_upper)
        if cached:
            return cached.get("isin"), cached.get("path")

        # Tier 2: DB cache
        if db is not None:
            stmt = select(
                StockUniverse.isin,
                StockUniverse.iinvest_path,
                StockUniverse.iinvest_path_resolved_at,
            ).where(StockUniverse.symbol == symbol_upper)
            row = (await db.execute(stmt)).first()
            if row and row[0] and row[1] and row[2]:
                age = datetime.now(timezone.utc).replace(tzinfo=None) - row[2]
                if age < timedelta(days=1):
                    iinvest_path_cache[symbol_upper] = {"isin": row[0], "path": row[1]}
                    return row[0], row[1]

        # Tier 3: NSE GetQuoteApi — the source of truth for ISIN + companyName.
        # Verified live (2026-06-18): returns the ISIN directly in the
        # `isin` field, plus `companyName` and `symbol`. The response is
        # a single-element list (or empty if the symbol is invalid).
        # Coalesced: 6x parallel Deals-tab requests for the same symbol
        # collapse into a single NSE call to avoid rate-limiting.
        try:
            from app.services.coalesce import coalesce as _coalesce
            from app.services.iinvest_client import nse_client  # set up below

            async def _fetch_isin() -> tuple[str, str] | None:
                return await nse_client.get_isin_for_symbol(symbol_upper)

            isin_company = await _coalesce(f"iinvest:path:{symbol_upper}", _fetch_isin)
        except Exception as exc:
            self._last_error = f"NSE getMetaData failed for {symbol_upper}: {exc}"
            return None, None

        if not isin_company:
            self._last_error = f"NSE returned no ISIN for {symbol_upper}"
            return None, None
        isin, company_name = isin_company

        # Build the iinvest path from the verified NSE data
        path = self.build_path(isin, symbol_upper, company_name)

        iinvest_path_cache[symbol_upper] = {"isin": isin, "path": path}
        if db is not None:
            # Queue the stock_universe ISIN/path update via write_queue to avoid
            # contending with jobs/api_cache single-row updates at startup.
            # Keep the AsyncSession commit for test FakeSession compat but make it
            # non-blocking: try queue first, fall back to direct.
            try:
                from app.services.write_queue import enqueue_write, PRIO_BULK_DATA
                import sqlite3
                from app.config import settings
                from app.database import _apply_sqlite_pragmas

                def _do_update(conn=None):
                    if conn is not None:
                        conn.execute(
                            "UPDATE stock_universe SET isin=?, iinvest_path=?, iinvest_path_resolved_at=?, updated_at=CURRENT_TIMESTAMP WHERE symbol=?",
                            (isin, path, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=' '), symbol_upper),
                        )
                    else:
                        con = sqlite3.connect(settings.db_path, timeout=15, check_same_thread=False, isolation_level=None)
                        try:
                            cur = con.cursor()
                            _apply_sqlite_pragmas(cur)
                            cur.close()
                            con.execute(
                                "UPDATE stock_universe SET isin=?, iinvest_path=?, iinvest_path_resolved_at=?, updated_at=CURRENT_TIMESTAMP WHERE symbol=?",
                                (isin, path, datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=' '), symbol_upper),
                            )
                            con.commit()
                        finally:
                            con.close()

                # Enqueue as bulk data (coalesced by queue, but distinct symbols each have unique job_key)
                # Use direct enqueue_write so it participates in single-writer serialization.
                try:
                    enqueue_write(PRIO_BULK_DATA, _do_update)
                except Exception:
                    # Fallback to original async path if queue unavailable (tests)
                    await db.execute(
                        StockUniverse.__table__.update()
                        .where(StockUniverse.symbol == symbol_upper)
                        .values(
                            isin=isin,
                            iinvest_path=path,
                            iinvest_path_resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                    )
                    try:
                        await db.commit()
                    except AttributeError:
                        pass
            except Exception:
                # Ultimate fallback: original async commit
                await db.execute(
                    StockUniverse.__table__.update()
                    .where(StockUniverse.symbol == symbol_upper)
                    .values(
                        isin=isin,
                        iinvest_path=path,
                        iinvest_path_resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                )
                try:
                    await db.commit()
                except AttributeError:
                    pass
        return isin, path

    # ── Data fetchers ──────────────────────────────────────────────────────

    async def get_announcements(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.announcements", "GET",
            f"{IINVEST_BASE_URL}/api/v1/announcements",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_auditors(self, path: str) -> dict[str, Any]:
        return await self._call(
            "iinvest.auditors", "GET",
            f"{IINVEST_BASE_URL}/api/v1/auditors",
            params={"path": path, "detailed": "true"},
        )

    async def get_block_deals(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        """Fetch iinvest block deals (type=1)."""
        return await self._call(
            "iinvest.block_deals", "GET",
            f"{IINVEST_BASE_URL}/api/v1/blockdeals",
            params={"type": 1, "path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_bulk_deals(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        """Fetch iinvest bulk deals (type=2). Under the hood, iinvest uses the blockdeals endpoint with type=2."""
        return await self._call(
            "iinvest.bulk_deals", "GET",
            f"{IINVEST_BASE_URL}/api/v1/blockdeals",
            params={"type": 2, "path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_board_meetings(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.board_meetings", "GET",
            f"{IINVEST_BASE_URL}/api/v1/boardmeetings",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_capital_history(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.capital_history", "GET",
            f"{IINVEST_BASE_URL}/api/v1/capitalhistory",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_corporate_actions(self, path: str, action_type: str = "Dividend", page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.corporate_actions", "GET",
            f"{IINVEST_BASE_URL}/api/v1/corporateaction",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true", "actionType": action_type},
        )

    async def get_financial_peer_filters(self) -> dict[str, Any]:
        return await self._call(
            "iinvest.financial_peer_filters", "GET",
            f"{IINVEST_BASE_URL}/api/v1/financials/peers/filters",
        )

    async def get_financial_peers(
        self, isin: str, filter_basis: int = 9, compare: int = 2,
        year: int | None = None, statement_type: str = "c",
        page: int = 1, size: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "isin": isin, "filterBasis": filter_basis, "compare": compare,
            "statementType": statement_type, "pageNo": page, "pageSize": size,
        }
        if year is not None:
            params["year"] = year
        return await self._call(
            "iinvest.financial_peers", "GET",
            f"{IINVEST_BASE_URL}/api/v1/financials/peers",
            params=params,
        )

    async def get_index_of_charges(self, isin: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.index_of_charges", "GET",
            f"{IINVEST_BASE_URL}/api/v1/indexofcharges",
            params={"isin": isin, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_insider_trading(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.insider_trading", "GET",
            f"{IINVEST_BASE_URL}/api/v1/insidertrading",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_key_shareholders(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.key_shareholders", "GET",
            f"{IINVEST_BASE_URL}/api/v1/keyshareholders",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_legal_cases(self, isin: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.legal_cases", "GET",
            f"{IINVEST_BASE_URL}/api/v1/legalcases",
            params={"isin": isin, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_marketdata_timeseries(self, path: str, timescale: int = 1, from_: str = "1DAY") -> dict[str, Any]:
        return await self._call(
            "iinvest.marketdata_timeseries", "GET",
            f"{IINVEST_BASE_URL}/api/v1/marketdata/timeseries",
            params={"path": path, "timescale": timescale, "from": from_},
        )

    async def get_pledged_shares(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.pledged_shares", "GET",
            f"{IINVEST_BASE_URL}/api/v1/pledgedshares",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_sast(self, path: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.sast", "GET",
            f"{IINVEST_BASE_URL}/api/v1/sast",
            params={"path": path, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_tribunals(self, isin: str, page: int = 1, size: int = 20) -> dict[str, Any]:
        return await self._call(
            "iinvest.tribunals", "GET",
            f"{IINVEST_BASE_URL}/api/v1/tribunals",
            params={"isin": isin, "pageNo": page, "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_news(self, isins: list[str], page: int = 1, size: int = 20) -> dict[str, Any]:
        """Fetch full news stories (with `story` body) for the given ISIN(s).

        Uses the full /api/v1/news/stories endpoint (not the /web/ public
        variant). NLP sentiment/threat are NOT in the payload — they must
        be computed locally via nlp_service.
        """
        return await self._call(
            "iinvest.news", "GET",
            f"{IINVEST_BASE_URL}/api/v1/news/stories",
            params={
                "sWebNews": "true", "forWebSite": "true",
                "pageNo": page, "pageSize": size, "isins": ",".join(isins),
            },
        )

    # ── Aggregator ─────────────────────────────────────────────────────────

    async def get_all(self, path: str, isin: str, news_limit: int = 20) -> dict[str, Any]:
        """Fetch all 18 endpoints in parallel. Error-tolerant per-section."""
        coros = {
            "announcements": self.get_announcements(path),
            "auditors": self.get_auditors(path),
            "block_deals": self.get_block_deals(path),
            "bulk_deals": self.get_bulk_deals(path),
            "board_meetings": self.get_board_meetings(path),
            "capital_history": self.get_capital_history(path),
            "corporate_actions_dividend": self.get_corporate_actions(path, "Dividend"),
            "corporate_actions_split": self.get_corporate_actions(path, "Split"),
            "corporate_actions_bonus": self.get_corporate_actions(path, "Bonus"),
            "corporate_actions_others": self.get_corporate_actions(path, "Others"),
            "financial_peer_filters": self.get_financial_peer_filters(),
            "index_of_charges": self.get_index_of_charges(isin),
            "insider_trading": self.get_insider_trading(path),
            "key_shareholders": self.get_key_shareholders(path),
            "legal_cases": self.get_legal_cases(isin),
            "pledged_shares": self.get_pledged_shares(path),
            "sast": self.get_sast(path),
            "tribunals": self.get_tribunals(isin),
            "news": self.get_news([isin], size=news_limit),
        }
        results = await asyncio.gather(*coros.values(), return_exceptions=True)
        out: dict[str, Any] = {}
        for key, res in zip(coros.keys(), results):
            if isinstance(res, BaseException):
                out[key] = {"error": str(res)}
            else:
                out[key] = res
        return out


class _Unauthorized(Exception):
    """Internal: 401 from iinvest, trigger re-login."""


# ── Wire the NSE client reference at module load ─────────────────────────────
# Defer the import to avoid circular-dep issues. If the NSE client can't be
# imported (e.g. during a unit test that only loads this module), the
# `nse_client` global stays None and resolve_path will surface an
# ImportError. The IinvestClient methods that don't need NSE (all 18 data
# fetchers + news) continue to work.
try:
    from app.services import nse_client_async  # noqa: F401
    nse_client = nse_client_async.NSEClientAsync()
except Exception:  # pragma: no cover - defensive
    logger.debug("iinvest_client: nse_client_async not importable yet (NSE path resolution disabled)")


# ── Singleton accessor ───────────────────────────────────────────────────────


def get_iinvest_client() -> IinvestClient:
    global _iinvest_client
    if _iinvest_client is None:
        _iinvest_client = IinvestClient()
    return _iinvest_client

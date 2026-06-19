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

# The AES-256 passphrase hardcoded in iinvest's _app-*.js bundle.
# May be overridden via env var for emergency rotation.
DEFAULT_AES_KEY = "SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us="
AES_KEY = os.environ.get("COGENCIS_AES_KEY", DEFAULT_AES_KEY)

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

# Module-level singleton (mirrors screener_client / news_fetcher pattern).
_iinvest_client: "IinvestClient | None" = None


# ── Crypto helpers ────────────────────────────────────────────────────────────


def _evp_bytes_to_key(passphrase: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey with MD5, 1 round — the kdf CryptoJS.AES uses by default."""
    d = b""
    d_i = b""
    while len(d) < key_len + iv_len:
        d_i = hashlib.md5(d_i + passphrase + salt).digest()
        d += d_i
    return d[:key_len], d[key_len:key_len + iv_len]


def decrypt_login_blob(b64_blob: str, passphrase: str = AES_KEY) -> dict[str, Any]:
    """Decrypt a ``Salted__<salt><ct>`` blob produced by CryptoJS.AES.encrypt.

    Returns the parsed JSON payload. Raises ValueError on bad key or
    malformed blob.
    """
    raw = base64.b64decode(b64_blob)
    if not raw.startswith(b"Salted__"):
        raise ValueError("Not a CryptoJS OpenSSL-format blob (missing 'Salted__' magic)")
    salt = raw[8:16]
    ct = raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode(), salt)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    pt_padded = decryptor.update(ct) + decryptor.finalize()
    pad = pt_padded[-1]
    if not 1 <= pad <= 16:
        raise ValueError("Bad PKCS#7 padding — wrong key or corrupted blob")
    plaintext = pt_padded[:-pad]
    return json.loads(plaintext.decode("utf-8"))


# ── Client ────────────────────────────────────────────────────────────────────


class IinvestClient:
    """Async client for iinvest.cogencis.com data APIs."""

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._jwt: str | None = None
        self._jwt_expires_at: datetime | None = None
        self._last_error: str | None = None
        self._lock = asyncio.Lock()
        # Override-able for tests
        self._refresh_ahead_seconds = _JWT_REFRESH_AHEAD_SECONDS

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def init(self) -> None:
        """Acquire the JWT and prepare the httpx client. Idempotent."""
        async with self._lock:
            await self._init_locked()

    async def _init_locked(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(
                headers=dict(DEFAULT_HEADERS),
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=False,
            )
        await self._ensure_jwt()
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
        """Acquire or refresh the JWT. Safe to call repeatedly."""
        now = datetime.now(timezone.utc)
        if (
            self._jwt
            and self._jwt_expires_at
            and self._jwt_expires_at - now > timedelta(seconds=self._refresh_ahead_seconds)
        ):
            return
        await self._fetch_jwt()

    async def _fetch_jwt(self) -> None:
        """POST /api/login, decrypt, store the JWT + expiry."""
        if self._http is None:
            raise RuntimeError("IinvestClient not initialized — call init() first")
        resp = await self._http.post(IINVEST_LOGIN_URL)
        if resp.status_code != 200:
            self._last_error = f"/api/login HTTP {resp.status_code}"
            raise RuntimeError(self._last_error)
        body = resp.json()
        blob = body.get("data")
        if not isinstance(blob, str):
            self._last_error = "/api/login: missing 'data' field"
            raise RuntimeError(self._last_error)
        try:
            payload = decrypt_login_blob(blob)
        except Exception as exc:
            self._last_error = f"JWT decrypt failed: {exc}"
            raise RuntimeError(self._last_error) from exc
        token = payload.get("response", {}).get("token")
        if not token:
            self._last_error = "Login payload missing response.token"
            raise RuntimeError(self._last_error)
        self._jwt = token
        # Parse expiry from the JWT itself (iinvest's `expiration` field is
        # +05:30 and is the same as `exp`; we read `exp` to be timezone-safe)
        try:
            import jwt as pyjwt
            decoded = pyjwt.decode(token, options={"verify_signature": False})
            exp = decoded.get("exp")
        except Exception:
            exp = None
        if exp:
            self._jwt_expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        else:
            # Fallback: assume 24h
            self._jwt_expires_at = now + timedelta(hours=24)
        self._last_error = None
        logger.info("IinvestClient: JWT acquired (expires %s)", self._jwt_expires_at.isoformat())

    @property
    def is_authenticated(self) -> bool:
        return self._jwt is not None and self._jwt_expires_at is not None

    @property
    def jwt(self) -> str | None:
        return self._jwt

    def health(self) -> dict[str, Any]:
        return {
            "configured": True,
            "healthy": self.is_authenticated,
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
        """Generic data-API call with 401 → re-login + retry."""
        from app.services.nse_rate_limiter import throttled_nse_call

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
            return await throttled_nse_call(
                endpoint_name, _do, is_async_fn=True,
            )
        except _Unauthorized:
            if _retried:
                self._last_error = f"401 on {endpoint_name} even after re-login"
                raise RuntimeError(self._last_error) from None
            await self._fetch_jwt()
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
        try:
            from app.services.iinvest_client import nse_client  # set up below
            isin_company = await nse_client.get_isin_for_symbol(symbol_upper)
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
            await db.execute(
                StockUniverse.__table__.update()
                .where(StockUniverse.symbol == symbol_upper)
                    .values(
                        isin=isin,
                        iinvest_path=path,
                        iinvest_path_resolved_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                )
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

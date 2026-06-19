# iinvest.cogencis.com Integration

## Overview

This document describes how to add the **iinvest.cogencis.com** data source to the FastAPI
analytics backend. iinvest is a NSE-subsidiary research portal whose data layer is unusually
rich for a free service: announcements, board meetings, corporate actions, insider trading,
pledged shares, legal cases, key shareholders, peer comparison, and OHLC timeseries.

The integration is **zero-friction for the user** — the iinvest frontend's own JavaScript
bundle ships a hardcoded AES-256 key in plaintext. We use the same key to obtain a
view-role guest JWT automatically. No user action, no Settings field, no captcha, no
credentials.

The existing `/api/py/[...path]` catch-all proxy in Next.js
(`src/app/api/py/[...path]/route.ts`) already forwards all requests to the FastAPI backend,
so **no Next.js changes are required for the proxy** — only the FDM widget gains new
collapsible sections.

---

## Plan Review: Missing Items Fixed

The original plan assumed the user would paste a JWT into Settings. Live testing (see
`HAR_ANALYSIS.md`) revealed that the iinvest `/api/login` endpoint is callable with no body
and returns an AES-encrypted blob that decrypts to a valid 24h JWT using a key that ships in
the public JS bundle. This eliminates the entire "Settings field" UX and the related DB
table. Specific plan adjustments:

1. **No `IinvestAuth` DB table needed** — the JWT is acquired automatically on init, lives
   in process memory, and is refreshed every 20h. The v1/v2 plan's `iinvest_auth` table is
   removed.

2. **No `SettingsWidget` change needed** — the FDM widget just calls `/api/iinvest/*`
   endpoints. If the client is unhealthy, the widget shows a per-section "iinvest
   unavailable" message with a retry button.

3. **No `routers/iinvest_auth.py` needed** — no auth endpoints to expose.

4. **ISIN resolution uses NSE's GetQuoteApi** — the auto-acquired NSE session
   gives us `www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getMetaData`
   which returns `{isin, companyName}` directly. This replaced the
   iinvest `/api/v1/marketdata/symbollookup` endpoint (which gave wrong
   ISINs for short symbols like RELIANCE → "Reliance Broadcast").
   HTML scrape (tier 4) is a fallback when the API returns empty.

5. **Health check is exposed as both a route and an MCP tool** — `GET /api/iinvest/health`
   for the widget badge, `iinvest_health` MCP tool for LLM agents.

6. **Auto key recovery is built into the client** — if Cogencis rotates the AES key, the
   client refetches the JS bundle, extracts the new key, and retries silently.

---

## Auth: How It Works

The iinvest frontend's login flow is unusual: it POSTs to `/api/login` with no body and
receives a base64 `Salted__` blob encrypted with AES-256-CBC. The decryption key is
embedded in the SPA's own JavaScript bundle. Decrypting the blob yields a valid 24-hour
JWT for the built-in `view`-role guest account (`user_id: 765`).

The full automated flow:

1. `IinvestClient.init()` calls `POST https://iinvest.cogencis.com/api/login` (no body,
   no headers beyond the standard browser-like set).
2. The response is a JSON object: `{"data": "U2FsdGVkX1/..."}`.
3. The client decrypts the `data` field using AES-256-CBC with the passphrase
   `SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us=`.
4. The decrypted JSON contains `{response: {token, expiration, apps, roles, username}}`.
5. The token is stored in process memory. A background task refreshes it every 20 hours
   (4 hours before expiry).
6. All subsequent calls to `data.cogencis.com/api/v1/*` include
   `Authorization: Bearer <jwt>`.

**No credentials are stored anywhere. No user action is required.**

### Key rotation recovery

If the key ever changes (Cogencis rolls a new build):

1. Init's decrypt fails or returns non-JSON.
2. The client fetches `https://iinvest.cogencis.com/` to find the current
   `_app-*.js` bundle filename.
3. It downloads the bundle and regex-extracts the new AES key.
4. It updates the in-memory key and retries `/api/login`.
5. If recovery itself fails, the client is marked unhealthy and returns 503.

### Legal / ethical note

The AES key is **public** — it ships to every browser that loads the iinvest site. The
JWT is role `view` (read-only, no write access). This is functionally equivalent to a
browser extension that auto-refreshes the session. **No copyrighted data is downloaded in
the auth step.** Disclose the auth mechanism in code comments.

---

## Files to Create / Modify

### 1. Alembic migration — add 3 columns to `stock_universe`

`backend/alembic/versions/<hash>_add_iinvest_columns_to_stock_universe.py`:

```python
"""add iinvest columns to stock_universe

Adds isin, iinvest_path, iinvest_path_resolved_at columns for the persistent
iinvest path cache. No backfill is required — populated lazily on first request.

Revision ID: <hash>
Revises: 2174ad44a498
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<hash>"
down_revision: Union[str, Sequence[str], None] = "2174ad44a498"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stock_universe", schema=None) as batch_op:
        batch_op.add_column(sa.Column("isin", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("iinvest_path", sa.String(length=256), nullable=True))
        batch_op.add_column(
            sa.Column(
                "iinvest_path_resolved_at",
                sa.DateTime(timezone=False),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("stock_universe", schema=None) as batch_op:
        batch_op.drop_column("iinvest_path_resolved_at")
        batch_op.drop_column("iinvest_path")
        batch_op.drop_column("isin")
```

### 2. Update ORM and Pydantic schema

`backend/app/models/stockuniverse.py` — add 3 mapped columns (next to `morningstar_id` at
line 37):

```python
isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
iinvest_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
iinvest_path_resolved_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=False), nullable=True
)
```

`backend/app/schemas/stockuniverse.py` — add 3 fields (next to `morningstarId` at line 25):

```python
isin: str | None = None
iinvestPath: str | None = None
iinvestPathResolvedAt: datetime | None = None
```

### 3. Add 2 caches

`backend/app/services/cache.py` — add 2 TTLCache entries (after line 15):

```python
iinvest_cache = _TTLCache(maxsize=200, ttl=900.0)        # 15 min
iinvest_path_cache = _TTLCache(maxsize=2000, ttl=86400.0)  # 24 h
```

### 4. New file — `backend/app/services/iinvest_client.py`

Full implementation. ~600 lines. Key methods:

```python
DEFAULT_AES_KEY = "SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us="

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Origin": "https://iinvest.cogencis.com",
    "Referer": "https://iinvest.cogencis.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


class IinvestClient:
    def __init__(self) -> None:
        self._aes_key: str = os.getenv("COGENCIS_AES_KEY", DEFAULT_AES_KEY)
        self._jwt: str | None = None
        self._jwt_expires_at: datetime | None = None
        self._healthy: bool = False
        self._last_error: str | None = None
        self._last_validated_at: datetime | None = None
        self._http: httpx.AsyncClient | None = None
        self._refresh_task: asyncio.Task | None = None
        self._shutdown: bool = False

    async def init(self) -> None:
        """Auto-acquire guest JWT and start background refresh task."""
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
            headers=DEFAULT_HEADERS,
        )
        try:
            await self._refresh_jwt()
            self._healthy = True
            self._last_validated_at = datetime.utcnow()
            self._last_error = None
        except Exception as exc:
            logger.error("iinvest init failed: %s", exc)
            self._healthy = False
            self._last_error = str(exc)
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def close(self) -> None:
        self._shutdown = True
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._http:
            await self._http.aclose()

    @property
    def is_healthy(self) -> bool:
        return self._healthy and self._jwt is not None

    def health_dict(self) -> dict[str, Any]:
        return {
            "configured": self._http is not None,
            "healthy": self.is_healthy,
            "last_validated": self._last_validated_at.isoformat() if self._last_validated_at else None,
            "expires_at": self._jwt_expires_at.isoformat() if self._jwt_expires_at else None,
            "last_error": self._last_error,
        }

    async def _refresh_jwt(self) -> None:
        """POST /api/login → decrypt → store JWT."""
        if not self._http:
            raise RuntimeError("IinvestClient not initialised")
        resp = await self._http.post("https://iinvest.cogencis.com/api/login")
        resp.raise_for_status()
        body = resp.json()
        blob = body.get("data")
        if not blob:
            raise RuntimeError("iinvest /api/login returned no data field")
        plaintext = self._decrypt_blob(blob, self._aes_key)
        parsed = json.loads(plaintext)
        if not parsed.get("status") or not parsed.get("response", {}).get("token"):
            raise RuntimeError(f"iinvest login failed: {parsed}")
        self._jwt = parsed["response"]["token"]
        # expiration is "2026-06-19T01:29:31.000+05:30" → convert to UTC
        exp_str = parsed["response"]["expiration"]
        # parse with timezone
        from datetime import datetime as _dt
        self._jwt_expires_at = _dt.fromisoformat(exp_str).astimezone(_dt.timezone.utc).replace(tzinfo=None)
        logger.info(
            "iinvest: JWT acquired (expires %s, role=%s)",
            self._jwt_expires_at,
            parsed["response"].get("roles"),
        )

    def _decrypt_blob(self, b64_blob: str, passphrase: str) -> str:
        """Decrypt OpenSSL Salted__ AES-256-CBC blob (CryptoJS-compatible)."""
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        raw = base64.b64decode(b64_blob)
        assert raw[:8] == b"Salted__", f"unexpected magic: {raw[:8]!r}"
        salt = raw[8:16]
        ciphertext = raw[16:]
        # OpenSSL EVP_BytesToKey: MD5(passphrase || salt) repeated
        d = b""
        d_i = b""
        while len(d) < 48:  # 32 key + 16 IV
            d_i = hashlib.md5(d_i + passphrase.encode("utf-8") + salt).digest()
            d += d_i
        key, iv = d[:32], d[32:48]
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = plaintext[-1]
        return plaintext[:-pad_len].decode("utf-8")

    async def _refresh_loop(self) -> None:
        while not self._shutdown:
            if not self._jwt_expires_at:
                await asyncio.sleep(60)
                continue
            # Refresh 4h before expiry
            time_until_refresh = (
                self._jwt_expires_at - timedelta(hours=4) - datetime.utcnow()
            ).total_seconds()
            await asyncio.sleep(max(time_until_refresh, 60))
            if self._shutdown:
                return
            try:
                await self._refresh_jwt()
                self._healthy = True
                self._last_error = None
            except Exception as exc:
                logger.error("iinvest JWT refresh failed: %s", exc)
                self._last_error = str(exc)
                # Try key recovery
                try:
                    await self._recover_key()
                    await self._refresh_jwt()
                    self._healthy = True
                except Exception as recovery_exc:
                    logger.error("iinvest key recovery failed: %s", recovery_exc)
                    self._healthy = False

    async def _recover_key(self) -> None:
        """Refetch the JS bundle and extract the new AES key."""
        if not self._http:
            return
        home = await self._http.get("https://iinvest.cogencis.com/")
        match = re.search(r'_app-([a-f0-9]+\.js)', home.text)
        if not match:
            raise RuntimeError("could not find _app bundle filename in homepage")
        bundle_url = (
            f"https://iinvest.cogencis.com/_next/static/chunks/pages/"
            f"_app-{match.group(1)}"
        )
        bundle = await self._http.get(bundle_url)
        key_match = re.search(
            r'AES\.decrypt\([^,]+,\s*"([A-Za-z0-9+/=]{44})"', bundle.text
        )
        if not key_match:
            raise RuntimeError("could not extract AES key from bundle")
        new_key = key_match.group(1)
        if new_key != self._aes_key:
            logger.warning("iinvest: detected new AES key, updating")
            self._aes_key = new_key

    async def _call(
        self,
        endpoint_name: str,
        method: str,
        url: str,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Throttled data API call. Auto-refreshes JWT on 401."""
        if not self.is_healthy or not self._http or not self._jwt:
            raise RuntimeError("iinvest client not healthy")

        async def _do_call() -> dict[str, Any]:
            headers = {**DEFAULT_HEADERS, "Authorization": f"Bearer {self._jwt}"}
            resp = await self._http.request(
                method, url, params=params, headers=headers
            )
            if resp.status_code == 401:
                # Try refresh + retry once
                await self._refresh_jwt()
                headers["Authorization"] = f"Bearer {self._jwt}"
                resp = await self._http.request(
                    method, url, params=params, headers=headers
                )
            resp.raise_for_status()
            return resp.json()

        return await throttled_nse_call(endpoint_name, _do_call, is_async_fn=True)

    # ------------------------------------------------------------------
    # Path resolution (3-tier)
    # ------------------------------------------------------------------

    async def resolve_path(
        self, symbol: str, db: AsyncSession | None = None
    ) -> tuple[str, str]:
        """Resolve iinvest path slug for a symbol. 3-tier: cache → DB → NSE.

        Tier 3 uses NSE's GetQuoteApi (functionName=getMetaData) which returns
        the ISIN + companyName directly. The previous implementation used
        iinvest's /api/v1/marketdata/symbollookup, but it returned wrong
        ISINs for short symbols (TCS, INFY → 0 results; RELIANCE → wrong
        "Reliance Broadcast" via fuzzy substring match).
        """
        symbol = symbol.upper().strip()

        # Tier 1: in-process cache
        cached = iinvest_path_cache.get(symbol)
        if cached:
            return cached["isin"], cached["path"]

        # Tier 2: DB
        if db:
            row = await db.get(StockUniverseModel, symbol)
            if (
                row
                and row.isin
                and row.iinvest_path
                and row.iinvest_path_resolved_at
                and (datetime.utcnow() - row.iinvest_path_resolved_at) < timedelta(hours=24)
            ):
                iinvest_path_cache[symbol] = {"isin": row.isin, "path": row.iinvest_path}
                return row.isin, row.iinvest_path

        # Tier 3: NSE GetQuoteApi — the source of truth for ISIN + companyName.
        from app.services.nse_client_async import nse_client_async
        isin_company = await nse_client_async.get_isin_for_symbol(symbol)
        if not isin_company:
            return None, None
        isin, company_name = isin_company
        path = self.build_path(isin, symbol, company_name)

        # Persist to DB
        if db:
            row = await db.get(StockUniverseModel, symbol)
            if row:
                row.isin = isin
                row.iinvest_path = path
                row.iinvest_path_resolved_at = datetime.utcnow()
                await db.commit()

        iinvest_path_cache[symbol] = {"isin": isin, "path": path}
        return isin, path

    async def _resolve_via_symbollookup(self, symbol: str) -> str | None:
        # DEPRECATED — kept only for reference. The NSE GetQuoteApi is now
        # the source of truth. See IinvestClient.resolve_path.
        try:
            data = await self._call(
                "iinvest.symbollookup",
                "GET",
                "https://data.cogencis.com/api/v1/marketdata/symbollookup",
                params={
                    "searchTerm": symbol,
                    "searchOn": "symbol",
                    "indexName": "idxLookup",
                    "pageNo": "1",
                    "pageSize": "10",
                },
            )
            results = data.get("response", {}).get("data", [])
            for r in results:
                isin = r.get("value", "")
                full_path = r.get("path", "")
                if isin and full_path:
                    return full_path
        except Exception as exc:
            logger.warning("iinvest symbollookup failed for %s: %s", symbol, exc)
        return None

    async def _resolve_via_html(self, symbol: str, company_name: str) -> str | None:
        """No-auth fallback: fetch the iinvest page, extract ISIN from URL."""
        if not self._http:
            return None
        try:
            encoded_name = urllib.parse.quote(company_name, safe="")
            url = (
                f"https://iinvest.cogencis.com/ZZZ/symbol/ns/{symbol}/{encoded_name}"
                f"?tab=overview"
            )
            resp = await self._http.get(url, follow_redirects=True)
            if resp.status_code == 200:
                final_url = str(resp.url)
                isin = final_url.split("/")[3]  # /<ISIN>/symbol/...
                if re.match(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$", isin):
                    return f"{isin.lower()}/symbol/ns/{symbol.lower()}/{encoded_name.lower()}"
        except Exception as exc:
            logger.warning("iinvest HTML fallback failed for %s: %s", symbol, exc)
        return None

    # ------------------------------------------------------------------
    # 18 data endpoint fetchers (one per HAR-confirmed URL)
    # ------------------------------------------------------------------

    async def get_announcements(self, path: str, page: int = 1, size: int = 20) -> dict:
        return await self._call(
            "iinvest.announcements",
            "GET",
            "https://data.cogencis.com/api/v1/announcements",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_auditors(self, path: str) -> dict:
        return await self._call(
            "iinvest.auditors",
            "GET",
            "https://data.cogencis.com/api/v1/auditors",
            params={"path": path, "detailed": "true"},
        )

    async def get_block_deals(
        self, path: str, deal_type: int = 2, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.block_deals",
            "GET",
            "https://data.cogencis.com/api/v1/blockdeals",
            params={"type": deal_type, "path": path, "pageNo": page,
                    "pageSize": size, "detailed": "true", "jsonArray": "true"},
        )

    async def get_board_meetings(
        self, path: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.board_meetings",
            "GET",
            "https://data.cogencis.com/api/v1/boardmeetings",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_capital_history(
        self, path: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.capital_history",
            "GET",
            "https://data.cogencis.com/api/v1/capitalhistory",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_corporate_actions(
        self, path: str, action_type: str = "Dividend", page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.corporate_actions",
            "GET",
            "https://data.cogencis.com/api/v1/corporateaction",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true",
                    "actionType": action_type},
        )

    async def get_financial_peers(
        self,
        isin: str,
        filter_basis: int = 10,
        compare: int = 4,
        year: int | None = None,
        statement: str = "c",
        page: int = 1,
        size: int = 20,
    ) -> dict:
        params: dict[str, Any] = {
            "isin": isin,
            "filterBasis": filter_basis,
            "compare": compare,
            "statementType": statement,
            "pageNo": page,
            "pageSize": size,
        }
        if year is not None:
            params["year"] = year
        return await self._call(
            "iinvest.financial_peers",
            "GET",
            "https://data.cogencis.com/api/v1/financials/peers",
            params=params,
        )

    async def get_financial_peer_filters(self) -> dict:
        return await self._call(
            "iinvest.financial_peer_filters",
            "GET",
            "https://data.cogencis.com/api/v1/financials/peers/filters",
        )

    async def get_index_of_charges(
        self, isin: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.index_of_charges",
            "GET",
            "https://data.cogencis.com/api/v1/indexofcharges",
            params={"isin": isin, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_insider_trading(
        self, path: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.insider_trading",
            "GET",
            "https://data.cogencis.com/api/v1/insidertrading",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true",
                    "actionType": "undefined"},
        )

    async def get_key_shareholders(
        self, path: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.key_shareholders",
            "GET",
            "https://data.cogencis.com/api/v1/keyshareholders",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_legal_cases(
        self, isin: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.legal_cases",
            "GET",
            "https://data.cogencis.com/api/v1/legalcases",
            params={"isin": isin, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_marketdata_timeseries(
        self, path: str, timescale: int = 1, from_: str = "1DAY"
    ) -> dict:
        return await self._call(
            "iinvest.marketdata_timeseries",
            "GET",
            "https://data.cogencis.com/api/v1/marketdata/timeseries",
            params={"path": path, "timescale": timescale, "from": from_},
        )

    async def get_pledged_shares(
        self, path: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.pledged_shares",
            "GET",
            "https://data.cogencis.com/api/v1/pledgedshares",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true",
                    "actionType": "undefined"},
        )

    async def get_sast(self, path: str, page: int = 1, size: int = 20) -> dict:
        return await self._call(
            "iinvest.sast",
            "GET",
            "https://data.cogencis.com/api/v1/sast",
            params={"path": path, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true",
                    "actionType": "undefined"},
        )

    async def get_tribunals(
        self, isin: str, page: int = 1, size: int = 20
    ) -> dict:
        return await self._call(
            "iinvest.tribunals",
            "GET",
            "https://data.cogencis.com/api/v1/tribunals",
            params={"isin": isin, "pageNo": page, "pageSize": size,
                    "detailed": "true", "jsonArray": "true"},
        )

    async def get_news(
        self, isins: list[str], page: int = 1, size: int = 20
    ) -> dict:
        """Fetch full news stories (with `story` body) for the given ISIN(s).

        Uses /api/v1/news/stories (the full/internal version with HTML `story` field)
        rather than /api/v1/web/news/stories (web/public, headlines only).
        """
        return await self._call(
            "iinvest.news",
            "GET",
            "https://data.cogencis.com/api/v1/news/stories",
            params={"sWebNews": "true", "forWebSite": "true",
                    "pageNo": page, "pageSize": size, "isins": ",".join(isins)},
        )

    # ------------------------------------------------------------------
    # Aggregator
    # ------------------------------------------------------------------

    async def get_all(
        self, symbol: str, path: str, isin: str, news_limit: int = 20
    ) -> dict[str, Any]:
        """Fetch all 18 endpoints in parallel. Error-tolerant per-section."""
        coros = {
            "announcements": self.get_announcements(path),
            "auditors": self.get_auditors(path),
            "block_deals_today": self.get_block_deals(path, deal_type=2),
            "block_deals_historical": self.get_block_deals(path, deal_type=1),
            "board_meetings": self.get_board_meetings(path),
            "capital_history": self.get_capital_history(path),
            "corporate_actions_dividend": self.get_corporate_actions(path, "Dividend"),
            "corporate_actions_split": self.get_corporate_actions(path, "Split"),
            "corporate_actions_bonus": self.get_corporate_actions(path, "Bonus"),
            "financial_peers": self.get_financial_peers(isin),
            "index_of_charges": self.get_index_of_charges(isin),
            "insider_trading": self.get_insider_trading(path),
            "key_shareholders": self.get_key_shareholders(path),
            "legal_cases": self.get_legal_cases(isin),
            "marketdata_timeseries_1d": self.get_marketdata_timeseries(path, from_="1DAY"),
            "pledged_shares": self.get_pledged_shares(path),
            "sast": self.get_sast(path),
            "tribunals": self.get_tribunals(isin),
            "news": self.get_news([isin], size=news_limit),
        }
        results = await asyncio.gather(
            *[c for c in coros.values()], return_exceptions=True
        )
        return {
            k: ({"error": str(r)} if isinstance(r, BaseException) else r)
            for k, r in zip(coros.keys(), results)
        }


iinvest_client = IinvestClient()
```

### 5. New file — `backend/app/services/iinvest_html_parser.py`

Parses the 9-section `__NEXT_DATA__` block from the overview HTML page. ~150 lines.

```python
"""Parse __NEXT_DATA__ from iinvest overview HTML.

The overview tab embeds all 9 sections (OV, BS, PL, CF, FO, IR, RC, SHP, BD)
in a 49KB JSON block inside a <script id="__NEXT_DATA__"> tag.

Server-side fetches get data: [] (browser fills it via XHR), but we still
parse the structure for the URL path (ISIN) and any inline data.
"""
from __future__ import annotations

import json
import re
from typing import Any

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)


def extract_next_data(html: str) -> dict[str, Any] | None:
    """Extract the __NEXT_DATA__ JSON object from a Next.js page."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def extract_overview_sections(html: str) -> dict[str, Any]:
    """Extract the 9-tab payload from overview HTML.

    Returns:
        {
            "OV": {...},  # Overview
            "BS": {...},  # Balance Sheet
            "PL": {...},  # Profit & Loss
            "CF": {...},  # Cash Flow
            "FO": {...},  # FII/DII/Foreign holdings
            "IR": {...},  # Income ratios
            "RC": {...},  # Ratios consolidated
            "SHP": {...}, # Shareholding pattern
            "BD": {...},  # Block deals
            "isin": "INE467B01029",  # from URL path
        }
    """
    data = extract_next_data(html)
    if not data:
        return {"isin": None, "sections": {}}
    page_props = data.get("props", {}).get("pageProps", {})
    response = page_props.get("data", {}).get("response", {})
    isin = page_props.get("data", {}).get("isin")  # may be empty server-side
    return {
        "isin": isin,
        "sections": {
            "OV": response.get("OV", {}),
            "BS": response.get("BS", {}),
            "PL": response.get("PL", {}),
            "CF": response.get("CF", {}),
            "FO": response.get("FO", {}),
            "IR": response.get("IR", {}),
            "RC": response.get("RC", {}),
            "SHP": response.get("SHP", {}),
            "BD": response.get("BD", {}),
        },
    }
```

### 6. New file — `backend/app/routers/iinvest.py`

~400 lines. 18 data endpoints + overview + health + all + path. Mirrors
`routers/screener.py` structure.

```python
"""iinvest.cogencis.com proxy endpoints.

All data endpoints require a valid auto-acquired JWT (handled in lifespan).
Path resolution is a separate endpoint that the widget calls once per symbol.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stockuniverse import StockUniverse as StockUniverseModel
from app.services.cache import iinvest_cache
from app.services.iinvest_client import iinvest_client
from app.services.iinvest_html_parser import extract_overview_sections

logger = logging.getLogger(__name__)
router = APIRouter(tags=["iinvest"])

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,30}$")


def _cache_get_or_set(key: str, ttl: int, coro_factory):
    """Helper: get from cache or call coro and cache the result."""
    cached = iinvest_cache.get(key)
    if cached is not None:
        return cached
    result = await coro_factory()  # NOTE: this is async
    iinvest_cache[key] = result
    return result


@router.get("/iinvest/health")
async def iinvest_health() -> dict[str, Any]:
    return iinvest_client.health_dict()


@router.get("/iinvest/path/{symbol}")
async def iinvest_path(
    symbol: str, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol format")
    try:
        path = await iinvest_client.resolve_path(symbol, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"symbol": symbol, "path": path}


@router.get("/iinvest/overview/{symbol}")
async def iinvest_overview(symbol: str) -> dict[str, Any]:
    symbol = symbol.upper().strip()
    cache_key = f"iinvest:overview:{symbol}"
    cached = iinvest_cache.get(cache_key)
    if cached is not None:
        return cached
    # No JWT needed — HTML is public
    if not iinvest_client._http:
        raise HTTPException(status_code=503, detail="iinvest client not initialised")
    # Use NSE companyName from DB
    # (omitted for brevity — see full router file)
    ...
    iinvest_cache[cache_key] = result
    return result


# ... 17 more data endpoints, each following the same pattern ...
# (announcements, auditors, block-deals, board-meetings, capital-history,
#  corporate-actions, financial-peers, financial-peer-filters, index-of-charges,
#  insider-trading, key-shareholders, legal-cases, marketdata-timeseries,
#  pledged-shares, sast, tribunals, news, all)
```

The full router file is ~400 lines. Each endpoint:
1. Validates the symbol
2. Checks `iinvest_client.is_healthy` → 503 if not
3. Resolves path (or uses the `path` query param if provided)
4. Checks `iinvest_cache` → returns on hit
5. Calls the corresponding client method (throttled)
6. Caches and returns
7. Maps exceptions to 503/404/502

### 7. Modify `backend/app/routers/__init__.py`

Add:

```python
from app.routers.iinvest import router as iinvest_router

__all__ = [
    ...
    "iinvest_router",
    ...
]
```

### 8. Modify `backend/main.py`

Three changes:

```python
# At the top
from app.services.iinvest_client import iinvest_client

# In lifespan(), after screener_client.init() and before orchestrator.start()
await iinvest_client.init()
```

And register the router:

```python
app.include_router(iinvest_router)
```

### 9. Modify `backend/app/orchestrator.py`

Add `iinvest_client.close()` to the `stop()` method (after line 161):

```python
from app.services.iinvest_client import iinvest_client
...
await iinvest_client.close()
```

### 10. New file — `src/lib/iinvest.ts`

~200 lines. Typed response interfaces + small fetch helper. Mirrors `src/lib/screenerTql.ts`
pattern (no `any`, strict types).

```typescript
// Common envelope
export interface IinvestResponse<T = unknown> {
  status: boolean;
  message: string;
  response: {
    pagingInfo?: { pageNo: number; pageSize: number; total: number };
    columns?: Array<{
      field: string;
      displayName: string;
      dataType: string;
      format?: string;
      action?: string;
    }>;
    data?: T[];
  };
}

export interface IinvestShareholder {
  category: string;
  quarter: string;
  percentage: number;
}

export interface IinvestCorporateAction {
  exDate: string;
  purpose: string;
  recordDate?: string;
  actionType: "Dividend" | "Split" | "Bonus" | "Others";
}

export interface IinvestNewsItem {
  id: string;
  headline: string;
  synopsis: string;
  story: string;            // HTML body from /news/stories (full version)
  sourceLink: string;
  sourceName: string;
  sourceDateTime: string;   // ISO 8601
  thumbNailImage?: string;
  isins: string[];
  categories: string[];
  // NOTE: iinvest does NOT include sentiment or threat_level. NLP is run
  // server-side via nlp_service.analyze_article_dict(headline, synopsis)
  // and added to NewsArticleOut after fetch.
}

// ... more interfaces for announcements, board meetings, etc.

export async function fetchIinvestHealth(): Promise<IinvestHealth> { ... }
export async function fetchIinvestPath(symbol: string): Promise<string> { ... }
export async function fetchIinvestAnnouncements(symbol: string, page = 1): Promise<IinvestResponse> { ... }
// ... 18 fetch helpers
```

### 11. Modify `src/components/widgets/FundamentalsWidget.tsx`

Add 13 collapsible sections. Each follows the same pattern:

```tsx
const [isShareholdersOpen, setIsShareholdersOpen] = useState(false);
const { data: shareholders, isLoading: shareholdersLoading } = useQuery({
  queryKey: ['iinvest', 'key-shareholders', symbol],
  queryFn: () => fetchIinvestKeyShareholders(symbol),
  enabled: isShareholdersOpen && !!symbol,
  staleTime: 24 * 60 * 60 * 1000,
});

<details
  open={isShareholdersOpen}
  onToggle={(e) => setIsShareholdersOpen((e.target as HTMLDetailsElement).open)}
>
  <summary>Shareholding Pattern (iinvest)</summary>
  {shareholdersLoading && <Skeleton />}
  {shareholders?.error && <ErrorMsg error={shareholders.error} onRetry={refetch} />}
  {shareholders?.data && <ShareholdersChart data={shareholders.data} />}
</details>
```

**Section order** (in render):

1. Shareholding Pattern (default open)
2. Corporate Actions (tabs: Dividend/Split/Bonus/Others)
3. Board Meetings
4. Announcements
5. Insider Trading
6. Pledged Shares
7. Auditors
8. Legal & Tribunal Cases
9. Block Deals & SAST
10. Capital History
11. Peer Comparison
12. News
13. Marketdata Timeseries

**Header badge**:

```tsx
const { data: iinvestHealth } = useQuery({
  queryKey: ['iinvest', 'health'],
  queryFn: fetchIinvestHealth,
  refetchInterval: 60_000,
});

{iinvestHealth?.healthy ? (
  <span className="text-green-500 text-xs">iinvest backup</span>
) : (
  <span className="text-red-500 text-xs">iinvest unavailable</span>
)}
```

### 12. Modify `backend/app/mcp_server.py`

Add 20 new `@mcp.tool()` functions. Each follows the screener pattern:

```python
@mcp.tool()
async def iinvest_announcements(
    symbol: str | None = None,
    symbols: list[str] | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """Fetch corporate announcements for an NSE company from iinvest.

    Args:
        symbol: Single symbol.
        symbols: Multiple symbols (bulk).
        page: Page number (default 1).
        size: Records per page (default 20, max 200).

    Returns announcements with PDF links. In bulk mode returns dict keyed by symbol.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    if not iinvest_client.is_healthy:
        raise RuntimeError("iinvest client not healthy — check /api/iinvest/health")

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper().strip()
        if not _SYMBOL_RE.fullmatch(sym):
            raise ValueError(f"Invalid symbol format: {sym}")
        cache_key = f"mcp_iinvest_announcements:{sym}:{page}:{size}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        path = await iinvest_client.resolve_path(sym)
        data = await iinvest_client.get_announcements(path, page=page, size=size)
        _cache_set(cache_key, data)
        return data

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }
```

(The 20 tools are nearly identical — copy-paste with endpoint name changes.)

### 13. Modify `blm-mcp-bundle/manifest.json`

Add 20 entries to the `tools` array:

```json
{ "name": "iinvest_announcements",        "description": "Fetch corporate announcements for an NSE company from iinvest.cogencis.com." },
{ "name": "iinvest_auditors",             "description": "Fetch statutory auditors and appointment dates for an NSE company from iinvest." },
{ "name": "iinvest_block_deals",          "description": "Fetch bulk + block deals for an NSE company from iinvest. deal_type=1 returns bulk deals; deal_type=2 returns block deals. Some overlap between the two responses is expected." },
{ "name": "iinvest_board_meetings",       "description": "Fetch board meeting records with purpose, date, and PDF link for an NSE company from iinvest." },
{ "name": "iinvest_capital_history",      "description": "Fetch capital issuance history for an NSE company from iinvest." },
{ "name": "iinvest_corporate_actions",    "description": "Fetch corporate actions (dividend/split/bonus) for an NSE company from iinvest." },
{ "name": "iinvest_financial_peers",      "description": "Fetch peer comparison with bank/insurance/non-financial ratios and shareholding pattern for an NSE company from iinvest." },
{ "name": "iinvest_financial_peer_filters", "description": "Fetch the filter enum (filterBasis, compare, year) for the iinvest peer comparison endpoint." },
{ "name": "iinvest_index_of_charges",     "description": "Fetch index of charges (MCA filings) for an NSE company from iinvest." },
{ "name": "iinvest_insider_trading",      "description": "Fetch insider trading records for an NSE company from iinvest." },
{ "name": "iinvest_key_shareholders",     "description": "Fetch promoter/FII/DII/public shareholding pattern (quarterly, ~5 years) for an NSE company from iinvest." },
{ "name": "iinvest_legal_cases",          "description": "Fetch legal cases (civil/criminal) for an NSE company from iinvest." },
{ "name": "iinvest_marketdata_timeseries", "description": "Fetch OHLC timeseries (1D/1W/1M/3M/6M/1Y) with 52-week high/low and volume for an NSE company from iinvest." },
{ "name": "iinvest_pledged_shares",       "description": "Fetch pledged shares (by promoter entity) for an NSE company from iinvest." },
{ "name": "iinvest_sast",                 "description": "Fetch SAST (substantial acquisition of shares and takeovers) disclosures for an NSE company from iinvest." },
{ "name": "iinvest_tribunals",            "description": "Fetch NCLT/SEBI tribunal cases for an NSE company from iinvest." },
{ "name": "iinvest_news",                 "description": "Fetch recent news articles (24h rolling index, full story body) for an NSE company from iinvest. NLP sentiment and threat classification are computed locally via nlp_service — iinvest does not pre-tag them." },
{ "name": "iinvest_overview",             "description": "Fetch the 9-section overview (company profile + financials + shareholding) for an NSE company from iinvest." },
{ "name": "iinvest_all",                  "description": "Aggregator — fetch all 18 iinvest data sections in parallel for an NSE company." },
{ "name": "iinvest_health",               "description": "Check iinvest client health (JWT acquired, last validated, last error)." }
```

### 14. Modify `AGENTS.md`

Add iinvest to the directory structure listing (lines 47-67) and the backend services list.

### 15. Modify `backend/pyproject.toml`

Add `cryptography` if not already present (required for AES decryption):

```toml
dependencies = [
    # ... existing ...
    "cryptography>=41.0.0",
]
```

---

## Tests

### `backend/tests/test_iinvest_routes.py`

```python
import pytest

BASE_URL = "http://localhost:4455"  # or BLM_BASE_URL

def get(path: str, **params):
    import requests
    return requests.get(f"{BASE_URL}{path}", params=params, timeout=60)


@pytest.mark.slow
class TestIinvestHealth:
    def test_health_returns_200(self):
        resp = get("/api/iinvest/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "configured" in data
        assert "healthy" in data
        assert "last_validated" in data


@pytest.mark.slow
class TestIinvestPath:
    def test_path_returns_200_for_known_symbol(self):
        resp = get("/api/iinvest/path/RELIANCE")
        if resp.status_code == 503:
            pytest.skip("iinvest not configured")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "RELIANCE"
        assert "ine" in data["path"].lower()  # ISIN starts with INE

    def test_path_404_for_unknown_symbol(self):
        resp = get("/api/iinvest/path/ZZZZZZZZ")
        # Either 404 (symbol not found) or 422 (invalid)
        assert resp.status_code in (404, 422, 503)


@pytest.mark.slow
class TestIinvestAnnouncements:
    def test_announcements_returns_200(self):
        resp = get("/api/iinvest/announcements/RELIANCE")
        if resp.status_code == 503:
            pytest.skip("iinvest not configured")
        assert resp.status_code == 200


@pytest.mark.slow
class TestIinvestKeyShareholders:
    def test_key_shareholders_returns_200(self):
        resp = get("/api/iinvest/key-shareholders/RELIANCE")
        if resp.status_code == 503:
            pytest.skip("iinvest not configured")
        assert resp.status_code == 200


# ... more endpoint tests ...
```

### `backend/tests/test_iinvest_client.py`

Unit tests with mocked httpx (no network):

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.iinvest_client import IinvestClient


class TestIinvestClientAuth:
    @pytest.mark.asyncio
    async def test_init_acquires_jwt(self):
        client = IinvestClient()
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": "Salted__blob_here"}
        mock_resp.raise_for_status = MagicMock()
        mock_http.post.return_value = mock_resp

        with patch.object(client, '_http', mock_http), \
             patch.object(client, '_decrypt_blob', return_value='{"status":true,"response":{"token":"test.jwt.token","expiration":"2026-06-19T01:29:31.000+05:30","roles":"view"}}'):
            await client.init()
            assert client.is_healthy
            assert client._jwt == "test.jwt.token"
            await client.close()

    @pytest.mark.asyncio
    async def test_init_fails_marks_unhealthy(self):
        client = IinvestClient()
        mock_http = AsyncMock()
        mock_http.post.side_effect = Exception("network error")

        with patch.object(client, '_http', mock_http):
            await client.init()
            assert not client.is_healthy
            assert client._last_error is not None
            await client.close()

    def test_decrypt_blob_known_answer(self):
        """Verify the AES decryption matches openssl CLI output."""
        # The known blob from the live test
        # openssl enc -d -aes-256-cbc -md md5 -k "SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us="
        # (re-encrypted by hand for a known plaintext)
        ...


class TestIinvestClientResolvePath:
    @pytest.mark.asyncio
    async def test_resolve_path_cache_hit(self):
        client = IinvestClient()
        from app.services.cache import iinvest_path_cache
        iinvest_path_cache["RELIANCE"] = "test/path"
        result = await client.resolve_path("RELIANCE")
        assert result == "test/path"
        iinvest_path_cache.clear()


class TestIinvestClientRateLimit:
    @pytest.mark.asyncio
    async def test_init_bypasses_throttle(self):
        """init() must not use throttled_nse_call."""
        client = IinvestClient()
        with patch("app.services.iinvest_client.throttled_nse_call") as mock_throttle:
            mock_http = AsyncMock()
            mock_http.post.return_value.json.return_value = {"data": "blob"}
            with patch.object(client, '_http', mock_http), \
                 patch.object(client, '_decrypt_blob', return_value='{"status":true,"response":{"token":"x","expiration":"2026-06-19T01:29:31.000+05:30"}}'):
                await client.init()
                mock_throttle.assert_not_called()
                await client.close()
```

---

## Verification Steps

After implementation:

1. **Run migration**: `cd backend && alembic upgrade head` — adds 3 columns to stock_universe
2. **Restart backend**: `uvicorn main:app --reload` — should log `iinvest: JWT acquired (expires 2026-06-19T..., role=view)`
3. **Health check**: `curl http://localhost:4455/api/iinvest/health` → `{"configured": true, "healthy": true, ...}`
4. **Path resolution**: `curl http://localhost:4455/api/iinvest/path/RELIANCE` → `{"symbol": "RELIANCE", "path": "ine002a01018/symbol/ns/reliance/reliance-industries-limited"}`
5. **Data endpoint**: `curl http://localhost:4455/api/iinvest/announcements/RELIANCE` → JSON with announcement records
6. **FDM widget**: Open FDM widget in browser for RELIANCE, expand "Shareholding Pattern" — should load iinvest data
7. **MCP tool**: In Claude Desktop, call `iinvest_announcements` with `symbol: "RELIANCE"` — should return JSON
8. **MCP bundle build**: `cd blm-mcp-bundle && npm run build` — produces new .mcpb with 52 tools

---

## Operational Caveats

1. **No credentials to leak** — the JWT is in process memory only. No DB row, no file, no env var.
2. **Backend restart loses the JWT** — the next request will block for ~600ms while init re-acquires (one POST + AES decrypt).
3. **If Cogencis changes the auth flow** — the init or refresh will fail, the client marks itself unhealthy, and all endpoints return 503 with a clear message. The auto-recovery mechanism (§2.5) handles key rotation; if the entire endpoint changes, the client needs a code update.
4. **Single shared guest user** — currently a non-issue: `data.cogencis.com` enforces `RateLimit-Policy: 50000;w=60` (≈833 req/s). No courtesy delay is applied; monitor for 429s.
5. **No captcha** observed on `/api/login`. The endpoint appears to be a "free-for-all" unauth token dispenser.
6. **HTTP/1.1 required** — HTTP/2 triggers Akamai WAF timeouts from data-center IPs.

---

## What This Doc Does NOT Cover

- **FDM widget UX details** — see `docs/reference/widgets/fundamentals.md` (if it exists) or the
  React component itself
- **MCP bundle build steps** — see `blm-mcp-bundle/README.md` (if it exists) or `npm run build`
  in that directory
- **iinvest data semantics** — the FDM widget docs cover what each section means to a user

---

## References

- `docs/reference/backend/iinvest.md` — full architecture (more detail than this guide)
- `HAR_ANALYSIS.md` — endpoint catalog derived from a full HINDALCO HAR capture
- `iinvest.cogencis.com_Archive [26-06-18 00-39-50].har` — the source HAR (8.1 MB)
- `docs/reference/backend/screener.md` — pattern this integration was modeled after

---

## 16. iinvest as the Primary Source for Company News

iinvest's `/api/v1/news/stories` endpoint (the **full version with `story` body**) is the
**primary** source for per-company news in both the **NewsWidget** and the
**`get_company_news` MCP tool**. MoneyControl is retained as a fallback (and for breadth
in global news).

### 16.1 Why iinvest beats MoneyControl for company news

| Property | iinvest (`/news/stories`) | MoneyControl |
|---|---|---|
| Latency | <500 ms | 2-5 s (HTML scrape) |
| Index size per symbol | 100-1000+ articles (24h rolling) | ~20-50 articles |
| Sentiment / threat tags | **Post-fetched via `nlp_service`** (not pre-tagged at source) | Post-processed via `nlp_service` |
| Story body | Yes (HTML `story` field) | Yes (full article scrape) |
| Indexing key | ISIN (deterministic) | Symbol (fuzzy match) |
| NLP coverage | English (re-classified) | Any (re-classified) |
| Auth | Auto (guest JWT) | None (public HTML) |
| Free / paid | Free | Free |

iinvest is the only source that:
- Returns news keyed by ISIN (deterministic, no fuzzy matching)
- Has a 24-hour rolling index
- Sub-second response time
- Includes a full `story` body (HTML) for primary content

**Important:** the iinvest `/news/stories` payload does **not** include `sentiment` or
`threat_level` fields. NLP classification is run locally via
`app/services/nlp_service.analyze_article_dict(headline, synopsis)` on each article
**after** the fetch — same pattern as the MoneyControl and RSS flows. The `iinvest:`
source prefix lets `news/all` queries distinguish iinvest articles from RSS ones.

### 16.2 Files to modify (news section)

| File | Change |
|---|---|
| `backend/alembic/versions/<hash>_add_iinvest_columns_to_news_articles.py` | NEW — adds 2 columns |
| `backend/app/models/news.py` | +`iinvest_story_id` (unique-indexed), +`iinvest_published_at` |
| `backend/app/schemas/news.py` | +`iinvestStoryId`, +`iinvestPublishedAt` (optional, for clients that care) |
| `backend/app/services/iinvest_client.py` | (already has `get_news()`) — no change needed |
| `backend/app/services/news_fetcher.py` | NEW function `fetch_iinvest_company_news(symbol, db, days, limit)` — normalizes iinvest articles and upserts to `news_articles` |
| `backend/app/routers/news.py` | Update `GET /news/company/{symbol}` + `POST /news/company` to try iinvest first, fall back to MoneyControl |
| `backend/app/mcp_server.py` | Add `source: str = "auto"` arg to `get_company_news` |
| `src/components/widgets/NewsWidget.tsx` | Add `Source:` selector to the "company" tab + small "iinvest" / "MoneyControl" badge |
| `blm-mcp-bundle/manifest.json` | (no change — `get_company_news` signature stays compatible) |

### 16.3 New Alembic migration

`backend/alembic/versions/<hash>_add_iinvest_columns_to_news_articles.py`:

```python
"""add iinvest columns to news_articles

Adds iinvest_story_id (unique-indexed for dedup) and iinvest_published_at
to the news_articles table. No backfill required.

Revision ID: <hash>
Revises: <iinvest_stock_universe_hash>
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<hash>"
down_revision: Union[str, Sequence[str], None] = "<iinvest_stock_universe_hash>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("news_articles", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("iinvest_story_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "iinvest_published_at",
                sa.DateTime(timezone=False),
                nullable=True,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_news_articles_iinvest_story_id"),
            ["iinvest_story_id"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("news_articles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_news_articles_iinvest_story_id"))
        batch_op.drop_column("iinvest_published_at")
        batch_op.drop_column("iinvest_story_id")
```

### 16.4 New ORM fields

In `backend/app/models/news.py` (after the existing NLP fields, before `__table_args__`):

```python
# ── iinvest fields ───────────────────────────────────────────────────────
iinvest_story_id: Mapped[str | None] = mapped_column(
    String(64),
    nullable=True,
    unique=True,
    index=True,
)
iinvest_published_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=False), nullable=True
)
```

Note: the existing PK on `url` is preserved. The new `iinvest_story_id` is unique-indexed
for fast dedup on upsert.

### 16.5 New fetcher function

In `backend/app/services/news_fetcher.py` (or a new `iinvest_news_fetcher.py` if you
prefer separation):

```python
async def fetch_iinvest_company_news(
    symbol: str,
    db: AsyncSession,
    days: int = 30,
    limit: int = 50,
) -> int:
    """Fetch and store iinvest news articles for a company.

    Returns the number of new/updated articles.
    """
    from app.services.iinvest_client import iinvest_client
    from app.models.stockuniverse import StockUniverse as StockUniverseModel

    symbol_upper = symbol.upper()
    row = await db.get(StockUniverseModel, symbol_upper)
    if not row or not row.isin:
        logger.info("fetch_iinvest_company_news: %s has no ISIN cached", symbol_upper)
        return 0
    isin = row.isin

    try:
        # iinvest /news/stories (full) takes ISIN(s) directly
        data = await iinvest_client.get_news([isin], size=limit)
    except RuntimeError as exc:
        logger.warning("fetch_iinvest_company_news: iinvest unavailable: %s", exc)
        return 0

    stories = (
        data.get("response", {})
            .get("data", [])
    )
    if not stories:
        return 0

    from app.services.nlp_service import analyze_article_dict

    now = datetime.now()
    new_count = 0
    for story in stories:
        url = story.get("sourceLink") or f"iinvest://{story.get('id', '')}"
        if not url:
            continue
        headline = story.get("headline") or ""
        synopsis = story.get("synopsis") or ""
        body = story.get("story") or synopsis
        source_dt = story.get("sourceDateTime")
        publish_date = _parse_iso(source_dt)
        source_name = story.get("sourceName", "cogencis")

        # NLP is run AFTER fetch — iinvest does not pre-tag.
        nlp = analyze_article_dict(
            headline=headline,
            summary=synopsis,
            source_name=source_name,
        )

        parsed = {
            "url": url,
            "source": f"iinvest:{source_name}",
            "title": headline,
            "text": body,
            "top_image": story.get("thumbNailImage"),
            "publish_date": publish_date,
            "fetched_at": now,
            "company_symbol": symbol_upper,
            "sentiment": nlp["sentiment"],
            "sentiment_score": nlp["sentiment_score"],
            "confidence": nlp["confidence"],
            "language": nlp["language"],
            "entities": nlp["entities"],
            "threat_level": nlp["threat_level"],
            "threat_category": nlp["threat_category"],
            "source_credibility": nlp["source_credibility"],
            "iinvest_story_id": str(story.get("id", "")),
            "iinvest_published_at": publish_date,
        }
        # Upsert by iinvest_story_id
        stmt = sqlite_insert(NewsArticle).values(**parsed)
        stmt = stmt.on_conflict_do_update(
            index_elements=["iinvest_story_id"],
            set_={k: v for k, v in parsed.items() if k not in ("url",)},
        )
        await db.execute(stmt)
        new_count += 1

    await db.commit()
    logger.info(
        "fetch_iinvest_company_news: %d articles upserted for %s", new_count, symbol_upper
    )
    return new_count


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None
```

### 16.6 Updated news router

In `backend/app/routers/news.py`, update the existing `GET /news/company/{symbol}` and
`POST /news/company` to accept a `source` query param and try iinvest first:

```python
@router.get(
    "/company/{symbol}",
    summary="Get paginated stored news articles for a company symbol",
    response_model=NewsPaginatedOut,
)
async def get_company_news(
    symbol: str,
    start_date: datetime = Query(default=None),
    end_date: datetime = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str = Query(
        default="auto",
        description="auto | iinvest | moneycontrol | merged",
    ),
    refresh: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> NewsPaginatedOut:
    symbol_upper = symbol.upper()

    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    source_used = "moneycontrol"  # default if iinvest is skipped

    if source in ("auto", "iinvest", "merged"):
        if refresh or await _company_news_empty(db, symbol_upper, start_date, end_date):
            count = await fetch_iinvest_company_news(
                symbol=symbol_upper, db=db, days=(end_date - start_date).days, limit=limit
            )
            logger.info(
                "get_company_news: iinvest fetched %d for %s", count, symbol_upper
            )
        source_used = "iinvest"

    if source == "moneycontrol":
        # Old behavior — explicit MoneyControl path
        if refresh:
            await news_fetcher.fetch_company_news(symbol=symbol_upper, db=db)
        source_used = "moneycontrol"

    if source == "merged":
        # Both — first iinvest, then top up from MoneyControl
        if refresh:
            await news_fetcher.fetch_company_news(symbol=symbol_upper, db=db)
        source_used = "merged"

    # Return paginated DB rows
    conditions = [NewsArticle.company_symbol == symbol_upper]
    if start_date:
        conditions.append(NewsArticle.publish_date >= start_date)
    if end_date:
        conditions.append(NewsArticle.publish_date <= end_date)

    if source == "iinvest":
        conditions.append(NewsArticle.source.like("iinvest:%"))
    elif source == "moneycontrol":
        conditions.append(NewsArticle.source.like("moneycontrol:%"))
    # "auto" and "merged" return everything (with iinvest first by fetched_at)

    count_stmt = select(func.count()).select_from(NewsArticle).where(and_(*conditions))
    precomputed_total = (await db.scalar(count_stmt) or 0)

    if precomputed_total == 0 and source == "auto":
        # iinvest returned nothing AND no MoneyControl articles cached — fall back
        logger.info("get_company_news: iinvest empty for %s, falling back to MC", symbol_upper)
        count = await news_fetcher.fetch_company_news(symbol=symbol_upper, db=db)
        source_used = "moneycontrol"
        # Re-query without source filter
        conditions = [c for c in conditions if "source.like" not in str(c)]
        count_stmt = select(func.count()).select_from(NewsArticle).where(and_(*conditions))
        precomputed_total = (await db.scalar(count_stmt) or 0)

    if precomputed_total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No articles found for symbol '{symbol_upper}'.",
        )

    stmt = (
        select(NewsArticle)
        .where(and_(*conditions))
        .order_by(
            # iinvest articles first, then by publish_date desc
            NewsArticle.source.like("iinvest:%").desc(),
            NewsArticle.publish_date.desc().nullslast(),
        )
        .limit(limit)
        .offset(offset)
    )
    total, articles, has_more = await paginate(
        db, count_stmt, stmt, offset=offset, limit=limit,
        precomputed_total=precomputed_total,
    )

    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
        source_used=source_used,   # NEW field in NewsPaginatedOut
    )
```

Add `source_used: str | None = None` to `NewsPaginatedOut` in
`backend/app/schemas/news.py`.

### 16.7 Updated `get_company_news` MCP tool

```python
@mcp.tool()
async def get_company_news(
    symbol: str | None = None,
    symbols: list[str] | None = None,
    days: int = 30,
    limit: int = 50,
    refresh: bool = False,
    source: str = "auto",          # NEW
    sentiment: str | None = None,
    threat_level: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch news for one or multiple NSE companies.

    Source priority (default "auto"):
      - "iinvest": iinvest.cogencis.com (fast, 24h rolling index, NLP run post-fetch)
      - "moneycontrol": MoneyControl stock quote page (slower, NLP post-processed)
      - "merged": both, deduped by URL
      - "auto": iinvest first, fall back to MoneyControl on 503/empty. When
                 `days > 7` and iinvest returns < 5 articles, auto-downgrade
                 to MoneyControl (iinvest's index is 24h rolling only).

    All other args unchanged from prior versions.
    """
    # ... existing validation ...

    async def _fetch(sym: str) -> dict[str, Any]:
        # Try iinvest first
        if source in ("auto", "iinvest", "merged"):
            count = await news_fetcher.fetch_iinvest_company_news(
                symbol=sym, db=None, days=days, limit=limit,
            )
            if count > 0:
                source_used = "iinvest"
            elif source == "iinvest":
                return {"articles": [], "source_used": "iinvest", "total": 0}
            else:
                source_used = "moneycontrol"  # will fall back
        else:
            source_used = "moneycontrol"

        # Existing MoneyControl path
        if source_used == "moneycontrol" or source == "merged":
            # ... existing fetch_company_news code ...

        return {
            "articles": articles,
            "total": len(articles),
            "source_used": source_used,
        }

    # ... rest unchanged ...
```

### 16.8 NewsWidget UI changes

In `src/components/widgets/NewsWidget.tsx`, add a small selector at the top of the
"company" tab (next to the page size selector):

```tsx
const [newsSource, setNewsSource] = useState<'auto' | 'iinvest' | 'moneycontrol' | 'merged'>('auto');

const { data: companyData, ... } = useQuery<NewsPaginatedResponse>({
  queryKey: ['news/company', symbol, { limit: PAGE_LIMIT, offset: companyOffset, source: newsSource }],
  queryFn: async () => {
    const res = await fetch(
      `/api/py/news/company/${encodeURIComponent(symbol)}?limit=${PAGE_LIMIT}&offset=${companyOffset}&source=${newsSource}`
    );
    if (!res.ok) throw new Error('Failed to fetch company news');
    return res.json() as Promise<NewsPaginatedResponse>;
  },
  staleTime: 5 * 60_000,
});

// Source badge (next to article count)
{companyData?.source_used && (
  <span className="text-xs text-terminal-dim">
    Source: {companyData.source_used}
    {companyData.source_used === 'iinvest' && iinvestHealth?.healthy ? ' ✓' : ''}
  </span>
)}
```

The "Refresh" button passes `?source=iinvest&refresh=true` so the user explicitly refetches
iinvest.

### 16.9 Why this is non-breaking

| Change | Breaking? | Why |
|---|---|---|
| New `source` query param (default `auto`) | No | Default behavior is better than old; existing clients get faster news |
| New `iinvest_story_id` / `iinvest_published_at` columns | No | Both nullable, no DB backfill needed |
| New `source_used` field in `NewsPaginatedOut` | No | Optional, additive |
| New `source` arg on `get_company_news` MCP tool | No | Default `auto` preserves old behavior with better quality |
| `NewsArticle.source` may now have `iinvest:` prefix | Slight | `news/all` filter still works; existing "source: moneycontrol" filter is now "source: moneycontrol:%" |
| Order: iinvest articles sort first | Visible to UI | "B" in NewsArticleOut stays the same; the new ordering is intentional |

### 16.10 Verification steps

1. `alembic upgrade head` — adds 2 columns to news_articles
2. Restart backend — `iinvest: JWT acquired` in logs
3. `curl http://localhost:4455/api/news/company/RELIANCE?source=iinvest&limit=5` → 5 articles, all `source: iinvest:cogencis`
4. `curl http://localhost:4455/api/news/company/RELIANCE?source=auto` → 5 articles, `source_used: iinvest`
5. `curl http://localhost:4455/api/news/company/RELIANCE?source=moneycontrol` → ~20-30 articles, `source_used: moneycontrol` (old behavior)
6. Open NewsWidget in browser, switch to "company" tab — should show "Source: iinvest" badge and iinvest articles
7. Click "Refresh" — should call `?source=iinvest&refresh=true` and re-fetch
8. MCP: in Claude Desktop, call `get_company_news(symbol="RELIANCE", source="iinvest")` → returns iinvest articles
9. Force iinvest unhealthy: temporarily break the JWT — `get_company_news` should fall back to MoneyControl and tag `source_used: moneycontrol`

### 16.11 When iinvest should be the **only** source

If the user wants the cleanest, fastest, most-tagged news for a single company, iinvest alone
is best. Use `?source=iinvest` to skip MoneyControl entirely. The MCP tool's `source="iinvest"`
does the same. The 24h rolling index is enough for most research use cases.

For long-term historical analysis (>30 days back), use `source="merged"` which combines
iinvest (recent) with MoneyControl (older archive).
- `docs/guides/screener-integration.md` — original screener integration guide

# iinvest.cogencis.com Data Source

This document explains how the **iinvest** subsystem works end-to-end — from the FastAPI client
auto-acquiring a guest JWT on startup, through the rate-limited HTTP layer, the ISIN/path
resolver, the 18 data endpoints, into the FDM widget, the AI chat agent, and the MCP bundle.

iinvest.cogencis.com is a NSE-subsidiary research portal. Its data layer is unusually rich for a
free service: it provides 18 read-only data APIs covering announcements, board meetings, corporate
actions, insider trading, pledged shares, legal cases, tribunals, index of charges, SAST
disclosures, block deals, key shareholders (promoter/FII/DII quarterly over ~5y), peer
comparison with bank/insurance ratios, and OHLC timeseries. We use it as a **backup / enrichment
source** for the Fundamentals (FDM) widget.

---

## 1. Architecture at a Glance

The iinvest client is a single async httpx pool that holds an automatically-acquired guest JWT
in memory. All 18 data endpoints share the same JWT and the same throttle pool. Path
construction (the `{ISIN}/symbol/ns/{SYMBOL}/{NAME}` slug) is resolved once per symbol and
cached in the DB.

```mermaid
flowchart LR
    subgraph Client["Client"]
        F[FundamentalsWidget.tsx]
        A[AiWidget / Claude Desktop]
    end

    subgraph Edge["Next.js edge"]
        P["/api/py/[...path]/route.ts<br/>catch-all proxy"]
    end

    subgraph Backend["FastAPI :4455"]
        R["routers/iinvest.py<br/>18 endpoints + all + health + path"]
        C["services/iinvest_client.py<br/>httpx + JWT + 18 fetchers"]
        H["services/iinvest_html_parser.py<br/>__NEXT_DATA__ → 9 sections"]
        M["mcp_server.py<br/>20 iinvest_* tools"]
    end

    subgraph Cache["Cache"]
        IC[(iinvest_cache<br/>15 min)]
        PC[(iinvest_path_cache<br/>24 h)]
    end

    subgraph Data["iinvest.cogencis.com + data.cogencis.com"]
        LOG["/api/login<br/>auto-acquire JWT"]
        API["/api/v1/*<br/>18 data endpoints"]
        HTML["/ISIN/symbol/ns/SYM/NAME<br/>__NEXT_DATA__"]
    end

    subgraph DB["SQLite"]
        SU[("stock_universe<br/>+isin +iinvest_path")]
    end

    F -->|fetch /iinvest/*| P
    A -->|MCP tools/call| M
    P -->|HTTP| R
    M -->|asyncio.gather| C
    R --> C
    C --> H
    C --> IC
    C --> PC
    C -->|Bearer JWT| API
    C -->|HTML scrape| HTML
    C -->|guest login| LOG
    C -->|read+write| SU
```

**Key design choice — guest JWT, no user action.** The iinvest frontend's own JavaScript bundle
ships an AES-256 passphrase in plaintext. We use the same passphrase to decrypt the
`/api/login` response and obtain a valid 24-hour JWT for the built-in `view`-role guest account
(`user_id: 765`). This requires no user credentials, no Settings field, and no captcha. The flow
is functionally identical to a browser's automatic session refresh — just automated.

---

## 2. Auth Flow: Automatic Guest JWT

### 2.1 The /api/login endpoint

iinvest's SPA calls its own `/api/login` endpoint on every page load to refresh the session
token. The endpoint takes **no body** and returns a base64-encoded `Salted__` blob (OpenSSL
AES-256-CBC, 8-byte salt + ciphertext):

```http
POST https://iinvest.cogencis.com/api/login HTTP/1.1
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0
Accept: application/json, text/plain, */*
Origin: https://iinvest.cogencis.com
Referer: https://iinvest.cogencis.com/

HTTP/1.1 200 OK
Content-Type: application/json

{"data":"U2FsdGVkX1/..."}
```

### 2.2 The hardcoded AES key

The decryption key is embedded in the iinvest frontend's JS bundle
(`/_next/static/chunks/pages/_app-*.js`):

```
SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us=
```

This is a 32-byte base64 string. CryptoJS's `AES.decrypt(blob, key)` uses OpenSSL's
`EVP_BytesToKey` (MD5, single iteration, no salt count) which is the same algorithm as
`openssl enc -d -aes-256-cbc -md md5 -k "<key>"`.

**Stable for 8+ days in production** (build ID `sGPBZnnV_ZN2DEbQjH8Rq` unchanged since
2026-06-09). If a new build rolls, see §2.5 (auto key recovery).

### 2.3 Decrypted payload → JWT

```json
{
  "status": true,
  "message": "Successful",
  "response": {
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODE4MTI3NzEsImRhdGEiOnsidXNlcl9pZCI6NzY1LCJhcHBzIjoiY21zLHJhcGksY21zLHJhcGksY21zLHJhcGkiLCJyb2xlcyI6InZpZXcifSwiaWF0IjoxNzgxNzI2MzcxfQ.EwGU3Aoa1YlKz363W3NKoLjWTHTl8phWGU1oYYfT7Q8",
    "expiration": "2026-06-19T01:29:31.000+05:30",
    "apps": "cms,rapi,cms,rapi,cms,rapi",
    "roles": "view",
    "username": "digitalsalt"
  }
}
```

JWT payload decoded:
```json
{
  "exp": 1781812771,
  "data": {
    "user_id": 765,
    "apps": "cms,rapi,cms,rapi,cms,rapi",
    "roles": "view"
  },
  "iat": 1781726371
}
```

**24-hour lifetime.** Role is `view` (read-only). Apps `cms,rapi` cover the entire research data
set on `data.cogencis.com`.

### 2.4 The auto-refresh loop

`IinvestClient._refresh_loop()` (started in `init()`) sleeps until 4h before JWT expiry, then
calls `/api/login` again to get a fresh token. Lifetime is 24h; refresh cadence is 20h after
issue. If `/api/login` ever stops returning a JWT (endpoint removed, key rotated without us
noticing), the client marks itself unhealthy and all endpoints return 503 with a clear message.

### 2.5 Auto key recovery

If decryption fails (returns non-JSON, or `/api/login` returns an unexpected response):

1. Fetch `https://iinvest.cogencis.com/`
2. Parse the HTML to find the current `_app-*.js` bundle filename
3. Download the bundle
4. Regex-extract the first `AES.decrypt(…, "<base64-44-chars>")` call
5. Update the in-memory key
6. Retry `/api/login`

This recovery is automatic and silent (logged at WARNING level). If recovery itself fails, the
client is marked unhealthy.

### 2.6 What we deliberately do NOT do

- We do **not** call `/api/login` with username/password — there's no credential endpoint
- We do **not** call `/api/refereshtoken` — the dedicated refresh flow requires a refresh token
  that only the browser can issue, and our 20h re-login is simpler
- We do **not** persist the JWT to disk or DB — it lives in process memory only
- We do **not** log the full JWT — only first 8 chars + expiration in debug logs

### 2.7 Rate limits observed (live)

| Endpoint | Limit | Source |
|---|---|---|
| `iinvest.cogencis.com/api/login` | None observed (10 sequential POSTs all 200) | Live curl |
| `data.cogencis.com/api/v1/*` | 50,000 req / 60s (`RateLimit-Policy` header) | Live curl |

Both are extremely generous for our use case.

### 2.8 Legal / ethical note

The AES key is **public** — it ships to every browser that loads the iinvest site. The
resulting JWT has role `view` (read-only, no write access). Using it is functionally
equivalent to a browser extension that auto-refreshes the session, or a curl-based read-only
client for a public-facing API. **No copyrighted data is downloaded in the auth step** — only
a credential. Disclose the auth mechanism in code comments.

---

## 3. Endpoints

All 18 data endpoints live under `/api/iinvest/`. Path construction is unified through
`/api/iinvest/path/{symbol}` which resolves and caches the iinvest URL slug.

| Endpoint | Maps to | Cache TTL | Notes |
|---|---|---|---|
| `GET /iinvest/health` | `IinvestClient.health()` | (no cache) | Returns `{configured, healthy, last_validated, last_error, expires_at}` |
| `GET /iinvest/path/{symbol}` | `IinvestClient.resolve_path(symbol)` | 24 h (DB) + 24 h (in-process) | Resolves ISIN + path slug |
| `GET /iinvest/overview/{symbol}` | HTML fetch + parse `__NEXT_DATA__` | 24 h | 9 sections (OV, BS, PL, CF, FO, IR, RC, SHP, BD) |
| `GET /iinvest/announcements/{symbol}` | `/api/v1/announcements` | 15 min | Up to 377 records + PDF links |
| `GET /iinvest/auditors/{symbol}` | `/api/v1/auditors` | 24 h | Auditor personnel + appointment date |
| `GET /iinvest/block-deals/{symbol}` | `/api/v1/blockdeals?type={1\|2}` | 5 min | **Verified 2026-06-18 via IRIS + TANLA live data**: `type=1` returns **Bulk deals** (cross-block 0.5%+ of paid-up capital); `type=2` returns **Block deals** (negotiated 09:15–09:40 IST window, 5%+). Some rows appear in BOTH responses for the same symbol (overlap ~10–40%) — this is iinvest's own behavior, not a bug. |
| `GET /iinvest/board-meetings/{symbol}` | `/api/v1/boardmeetings` | 24 h | Purpose + dates + PDF |
| `GET /iinvest/capital-history/{symbol}` | `/api/v1/capitalhistory` | 24 h | Capital issuance history |
| `GET /iinvest/corporate-actions/{symbol}` | `/api/v1/corporateaction?actionType=…` | 24 h | Dividend / Split / Bonus / Others |
| `GET /iinvest/financial-peers/{symbol}` | `/api/v1/financials/peers` | 24 h | Bank/Insurance/Non-Fin ratios + shareholding |
| `GET /iinvest/financial-peer-filters` | `/api/v1/financials/peers/filters` | 24 h | Static enum of filterBasis/compare/year |
| `GET /iinvest/index-of-charges/{symbol}` | `/api/v1/indexofcharges` | 24 h | Index of charges (MCA filings) |
| `GET /iinvest/insider-trading/{symbol}` | `/api/v1/insidertrading` | 15 min | Insider trades |
| `GET /iinvest/key-shareholders/{symbol}` | `/api/v1/keyshareholders` | 24 h | Promoter/FII/DII quarterly ~5y |
| `GET /iinvest/legal-cases/{symbol}` | `/api/v1/legalcases` | 24 h | Civil/criminal legal cases |
| `GET /iinvest/marketdata-timeseries/{symbol}` | `/api/v1/marketdata/timeseries` | 5 min | OHLC + 52W + volume (response shape `{snapshot, data}` — **no `columns`**) |
| `GET /iinvest/pledged-shares/{symbol}` | `/api/v1/pledgedshares` | 24 h | Promoter pledged shares |
| `GET /iinvest/sast/{symbol}` | `/api/v1/sast` | 24 h | SAST disclosures |
| `GET /iinvest/tribunals/{symbol}` | `/api/v1/tribunals` | 24 h | NCLT / SEBI tribunals |
| `GET /iinvest/news/{symbol}` | `/api/v1/news/stories` (full version with `story` body) | 15 min | Company news — NLP sentiment/threat are **not pre-tagged**, run `nlp_service` on fetch |
| `GET /iinvest/all/{symbol}` | `asyncio.gather(18 endpoints)` | (per-section cache) | Aggregator |

### 3.1 Path resolution (3-tier)

Every data endpoint needs an iinvest path slug. We resolve it once per symbol:

```mermaid
flowchart TB
    REQ[Symbol requested] --> T1{Tier 1: iinvest_path_cache<br/>in-process, 24h TTL}
    T1 -- hit --> RETURN[Return cached path]
    T1 -- miss --> T2{Tier 2: stock_universe.iinvest_path<br/>DB, 24h resolved_at}
    T2 -- hit --> RETURN
    T2 -- miss --> T3{Tier 3: NSE GetQuoteApi<br/>functionName=getMetaData<br/>symbol=SYM&series=EQ&marketType=N}
    T3 -- found --> PARSE[Parse ISIN + companyName from response]
    T3 -- 404/empty --> ERR[Return 404 IINVEST_PATH_NOT_FOUND]
    PARSE --> BUILD[build_path(isin, symbol, companyName)]
    BUILD --> PERSIST[Persist to stock_universe.isin + iinvest_path + resolved_at]
    PERSIST --> RETURN
```

**Tier 3 (NSE GetQuoteApi)** is the source of truth — NSE's response includes the
`isin` field directly, plus `companyName` for path construction. The previous
implementation used iinvest's `/api/v1/marketdata/symbollookup` endpoint, but it
returned wrong ISINs for short symbols (TCS, INFY → 0 results; RELIANCE →
Reliance Broadcast Network via fuzzy substring match). NSE's endpoint is exact.

### 3.2 ISIN → path construction

Once we have the ISIN, the path slug is:

```python
import urllib.parse

def build_path(isin: str, symbol: str, company_name: str) -> str:
    # ISIN is uppercase alpha+digits. NSE symbol may contain & (e.g. M&M).
    encoded_name = urllib.parse.quote(company_name, safe="")
    return f"{isin.lower()}/symbol/ns/{urllib.parse.quote(symbol, safe='')}/{encoded_name}".lower()
```

Edge cases verified:
- `M&M` → `M%26M` (URL-encoded ampersand)
- `L&T` → `LT` (NSE strips the `&` from the symbol; company name retains it)
- Spaces → `%20`
- The data APIs use the **lowercased** path; HTML pages use mixed case

### 3.3 URL-encode quirk for blockdeals `type` param

`/api/v1/blockdeals?type=1` (historical) and `type=2` (other — semantics not verified in
the smoke test; the iinvest JS bundle's `?type=2` query may correspond to a different
filter than "today"). Accept whatever the API returns. The path is lowercased in the query
string. Do not normalize — replicate literally.

### 3.4 Data API response shape (verified live)

Most of the 18 data endpoints return the standard envelope `{status, message, response}`
with `response.columns` (field-code → display-name mapping) and `response.data` (rows).
**However the shape of `data` rows varies by endpoint** — there are three distinct formats:

| Format | Endpoints | Notes |
|---|---|---|
| **Dict rows with `f_*` field codes** | `announcements`, `insidertrading`, `legalcases`, `corporateaction`, `boardmeetings`, `sast`, `pledgedshares`, `indexofcharges`, `tribunals`, `auditors`, `capitalhistory` | Each row is a dict keyed by `f_79`, `f_80`, … plus denormalized fields (`isin`, `exchangesymbol`, `xEx_Date`, `xPurpose`). The `columns` array maps each `f_*` code to `displayName` + `dataType`. The `f_25008` field carries the path slug (e.g. `ine467b01029/tatacons/ns/tcs/tata-consultancy-services_`). |
| **Array rows with header row** | `keyshareholders` | `data[0]` is a header row like `["ID","ParentID","IsExpanded","Description","Mar-26","Dec-25",…]`; subsequent rows are parallel arrays of values. **No `columns` field** — the header row is the schema. |
| **Snapshot + data** | `marketdata/timeseries` | Response is `{snapshot, data}` — **no `columns`, no `pagingInfo`**. Each row uses **named fields** `{open, high, low, close, volume, date, time}` (not `f_*` codes). `snapshot` carries the 52W high/low + current LTP. |
| **Object (single record)** | `financials/peers/filters` | `response` is a static enum: `{filters, compare, annual}`. No `data` array. |
| **News (full vs web)** | `news/stories` (full) vs `web/news/stories` (public) | Both return `{pagingInfo, columns, data}` with named fields per row. The full version includes a `story` field (HTML body); the web version is headlines + links only. **Neither version includes sentiment or threat fields** — NLP must be run locally via `app/services/nlp_service.py`. |

The router returns the raw `response` object to the client. The TypeScript layer in
`src/lib/iinvest.ts` defines typed wrappers for the common ones (shareholders, corporate
actions, news) and falls back to `unknown[]` for the rest.

---

## 4. Request Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant F as FDM Widget
    participant NX as Next.js proxy
    participant FA as FastAPI router
    participant CL as IinvestClient
    participant DC as data.cogencis.com
    participant DB as stock_universe (DB)

    User->>F: opens RELIANCE
    F->>NX: GET /api/iinvest/path/RELIANCE
    NX->>FA: forward
    FA->>CL: resolve_path("RELIANCE")
    CL->>DB: select isin, iinvest_path, iinvest_path_resolved_at
    alt cache miss
        CL->>NSE: GET GetQuoteApi?functionName=getMetaData&series=EQ&symbol=RELIANCE
        NSE-->>CL: { isin: "INE002A01018", companyName: "Reliance Industries Limited" }
        CL->>DB: UPDATE stock_universe SET isin=…, iinvest_path=…, iinvest_path_resolved_at=now()
    end
    CL-->>FA: "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited"
    FA-->>F: path

    User->>F: expands "Key Shareholders" section
    F->>NX: GET /api/iinvest/key-shareholders/RELIANCE
    NX->>FA: forward
    FA->>CL: get_key_shareholders(path)
    CL->>CL: iinvest_cache.get(key) — miss
    CL->>DC: GET /api/v1/keyshareholders?path=ine002a01018/symbol/ns/reliance/...
    DC-->>CL: { response: { columns, data } }
    CL->>CL: iinvest_cache.set(key, value, 900s)
    CL-->>FA: response
    FA-->>F: response
    F->>User: render shareholding table
```

---

## 5. Rate Limiting

We use the existing `nse_rate_limiter.throttled_nse_call()` with **per-endpoint pools** so
iinvest's rate limit and circuit breaker are independent of NSE/screener/morningstar. The
global semaphore (default 2) is shared; the per-endpoint lock and circuit breaker are
keyed by the endpoint_name string. **No courtesy delay is applied** — live verification
showed `data.cogencis.com` enforces a `RateLimit-Policy: 50000;w=60` header (50,000
requests per 60 s) and the `/api/login` endpoint returns 200 for ten sequential POSTs at
1 s intervals with no throttling.

iinvest endpoint names use the prefix `iinvest.*`:

| endpoint_name | Used by |
|---|---|
| `iinvest.login` | init / refresh loop (bypasses throttle — one-time) |
| `iinvest.key_recovery` | auto key recovery (bypasses throttle — rare) |
| `iinvest.announcements` | announcements endpoint |
| `iinvest.auditors` | auditors endpoint |
| `iinvest.block_deals` | block deals endpoint |
| `iinvest.board_meetings` | board meetings endpoint |
| `iinvest.capital_history` | capital history endpoint |
| `iinvest.corporate_actions` | corporate actions endpoint |
| `iinvest.financial_peers` | peer comparison endpoint |
| `iinvest.financial_peer_filters` | peer filter enum endpoint |
| `iinvest.index_of_charges` | index of charges endpoint |
| `iinvest.insider_trading` | insider trading endpoint |
| `iinvest.key_shareholders` | key shareholders endpoint |
| `iinvest.legal_cases` | legal cases endpoint |
| `iinvest.marketdata_timeseries` | OHLC timeseries endpoint |
| `iinvest.pledged_shares` | pledged shares endpoint |
| `iinvest.sast` | SAST endpoint |
| `iinvest.tribunals` | tribunals endpoint |
| `iinvest.news` | news endpoint |
| `iinvest.symbollookup` | (deprecated) was path resolution tier 3 — now uses NSE GetQuoteApi |
| `iinvest.overview_html` | overview HTML scrape |
| `iinvest.login_html` | homepage HTML for key recovery |

If one endpoint trips the circuit, the others remain healthy (per-endpoint circuit state).

### 5.1 Headers (verified working)

All httpx calls use the following default headers:

```python
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
```

**Note:** HTTP/1.1 is required. HTTP/2 triggers Akamai WAF timeouts from data-center IPs.

---

## 6. Caching

### 6.1 In-process caches (cachetools.TTLCache)

| Cache | Max size | TTL | Used by |
|---|---|---|---|
| `iinvest_cache` | 200 | 900 s (15 min) | All 18 data endpoints |
| `iinvest_path_cache` | 2000 | 86,400 s (24 h) | Path resolution |

Path cache is separate (24h vs 15min) because paths are very stable; data refreshes faster.

### 6.2 DB cache (stock_universe)

Three new columns on the `stock_universe` table provide the persistent path cache:

| Column | Type | Purpose |
|---|---|---|
| `isin` | `String(12)`, nullable | Cached ISIN (e.g. `INE467B01029`) |
| `iinvest_path` | `String(256)`, nullable | Full path slug |
| `iinvest_path_resolved_at` | `DateTime`, nullable | 24h TTL marker |

Re-resolution happens lazily on cache miss + stale. The Alembic migration is
`add_iinvest_columns_to_stock_universe.py`.

### 6.3 MCP cache

The MCP server's `_CACHE` dict (10 min TTL) is used for `iinvest_*` tools with key prefix
`mcp_iinvest_*`. Same as the screener convention.

### 6.4 No invalidation calls anywhere

All caches are TTL-based. The only manual invalidation is on `/iinvest/path/{symbol}` after
re-resolution (updates DB row, leaves in-process cache to expire naturally within 24h).

---

## 7. Error Model

| Condition | HTTP | Code | Surfaced to FDM |
|---|---|---|---|
| Init never completed or `/api/login` returns 401 | 503 | `IINVEST_UNAVAILABLE` | "iinvest data temporarily unavailable" + retry button |
| JWT expired + refresh failed | 503 | `IINVEST_TOKEN_EXPIRED` | "iinvest session expired, retrying…" |
| Symbol not in NSE universe | 404 | `SYMBOL_NOT_FOUND` | Silently hide section |
| Path not resolvable (all 4 tiers fail) | 404 | `IINVEST_PATH_NOT_FOUND` | Silently hide section |
| Akamai 403 (after header retry) | 503 | `IINVEST_BLOCKED` | "iinvest blocked, will retry in 60s" |
| Upstream 5xx | 502 | `IINVEST_UPSTREAM` | Generic "fetch failed" |
| Bad params (page<1, size>200) | 422 | `INVALID_PARAM` | (rare; widget validates) |
| Circuit breaker open | 503 | `IINVEST_CIRCUIT_OPEN` | "iinvest circuit open, retrying…" |

The FDM widget **never** shows a global error screen for iinvest. Each collapsible section
has its own error state with a per-section "Retry" button.

---

## 8. The FDM Widget Integration

The FDM widget (`src/components/widgets/FundamentalsWidget.tsx`) gains **13 collapsible
sections** using native HTML `<details>`/`<summary>`. Each section has its own
`useQuery({ enabled: isOpen })` so data is fetched lazily on first expand.

### 8.1 Section list (rendered in this order)

1. **Shareholding Pattern** (default open) — bar chart + quarterly table
2. Corporate Actions — tabbed: Dividend / Split / Bonus / Others
3. Board Meetings — list with purpose + date + PDF link
4. Announcements — paginated, 20/page
5. Insider Trading — table
6. Pledged Shares — % pledged by promoter entity
7. Auditors — list of statutory auditors + appointment date
8. Legal & Tribunal Cases — two tabs
9. Block Deals & SAST — two tabs (today / historical)
10. Capital History — table of issuances
11. Peer Comparison — dropdowns for `compare` and `year`
12. News — list of 20 most recent
13. Marketdata Timeseries — 1D/1W/1M/3M/6M/1Y selectors

### 8.2 Header badge

A small badge next to "Consolidated":

| State | Badge text | Color |
|---|---|---|
| Healthy + recent data | "iinvest backup" | green |
| Stale (no data in 24h) | "iinvest stale" | amber |
| Unhealthy (init/refresh failed) | "iinvest unavailable" | red, clickable → docs |
| Section 503 (per-section) | "—" (in section header) | red |

### 8.3 Per-section loading states

- Closed section: just the title, no spinner
- Open section, fetching: skeleton rows
- Open section, success: data table
- Open section, 503: error message + "Retry" button
- Open section, 404: "Not available for this symbol" (silent)

---

## 8A. iinvest as the Primary Source for Company News

Beyond the FDM widget, **iinvest is the primary source for company-specific news** in both
the **NewsWidget** and the **`get_company_news` MCP tool**. MoneyControl remains as a
fallback (and for breadth in global news) but the iinvest source is faster and more
deterministic.

### 8A.1 Why iinvest for company news

| Source | Latency | Coverage | NLP | Auth | Notes |
|---|---|---|---|---|---|
| **iinvest `/news/stories`** (full) | <500 ms | Per-ISIN, full index (TCS: 664+ articles) | **Post-fetched via `nlp_service`** (iinvest does **not** pre-tag sentiment/threat) | Auto-JWT (free) | Primary |
| iinvest `/web/news/stories` (web) | <500 ms | Per-ISIN, headlines + links only (no `story` body) | Post-fetched via `nlp_service` | Auto-JWT (free) | Optional secondary |
| MoneyControl stock quote page | 2-5 s | Per-symbol, ~20-50 articles | Post-fetched (nlp_service) | None (HTML scrape) | Fallback |
| RSS feeds (Bloomberg, Reuters, etc.) | 5-15 min | Global, no per-symbol | Post-fetched | None | Global news only |

iinvest is the only source that:
- Returns news keyed by ISIN (deterministic, no fuzzy matching)
- Has a 24-hour rolling index
- Has sub-second response time
- Includes a full `story` body (HTML) for primary content

**Important:** the iinvest `/news/stories` payload does **not** include `sentiment` or
`threat_level` fields. NLP classification must be run locally via `app/services/nlp_service.py`
on the `headline` + `synopsis` (or `story` body) — same as the MoneyControl and RSS flows.

### 8A.2 News data flow

```mermaid
flowchart LR
    subgraph Client["Client"]
        NW[NewsWidget.tsx<br/>company tab]
        A[Claude / AiWidget]
    end

    subgraph Edge["Next.js edge"]
        P["/api/py/[...path]"]
    end

    subgraph Backend["FastAPI :4455"]
        NR["routers/news.py<br/>GET /news/company/{symbol}"]
        IC["IinvestClient.get_news()"]
        NLP["nlp_service.analyze_article_dict()<br/>(per article, post-fetch)"]
        NF["news_fetcher.fetch_company_news()<br/>MoneyControl fallback"]
        DB[("news_articles<br/>+iinvest_story_id")]
    end

    NW -->|GET| P
    A -->|get_company_news| P
    P -->|forward| NR
    NR -->|1. primary| IC
    IC -->|200 + stories| NLP
    NLP -->|sentiment + threat| DB
    IC -->|503 / 404 / empty| NF
    NF -->|200| DB
    DB -->|JSON| NR
    NR -->|JSON| P
    P -->|JSON| NW
```

### 8A.3 Endpoint contract

`GET /api/news/company/{symbol}?days=30&limit=50&refresh=false` returns the same
`NewsPaginatedOut` shape as before (the MoneyControl response). The iinvest articles are
normalized to the existing `NewsArticle` schema so the frontend and the `get_company_news`
MCP tool are unchanged.

New query params:

| Param | Default | Purpose |
|---|---|---|
| `source` | `auto` | One of `auto`, `iinvest`, `moneycontrol`, `merged`. `auto` = iinvest first, fall back on 503/404/empty. |
| `refresh` | `false` | Force re-fetch from upstream (skip DB cache) |

### 8A.4 Article normalization (iinvest → NewsArticle)

iinvest `/news/stories` (full) returns each story as a flat dict with at least:
```json
{
  "id": "cog-12345",
  "headline": "TCS Q1 net profit up 12% YoY",
  "synopsis": "Tata Consultancy Services reported...",
  "story": "<p>Full HTML body...</p>",
  "sourceLink": "https://...",
  "sourceName": "Cogencis",
  "sourceDateTime": "2026-06-17T09:30:00",
  "isins": ["INE467B01029"],
  "categories": ["results", "earnings"],
  "thumbNailImage": "https://...",
  "status": "published"
}
```

Mapped to `NewsArticle` (NLP run **after** fetch, not read from payload):
```python
{
  "url": story.get("sourceLink") or f"iinvest://{story.get('id', '')}",
  "source": f"iinvest:{story.get('sourceName', 'cogencis')}",
  "title": story.get("headline"),
  "text": story.get("story") or story.get("synopsis"),
  "top_image": story.get("thumbNailImage"),
  "publish_date": _parse_iso(story.get("sourceDateTime")),
  "fetched_at": now,
  "company_symbol": symbol,
  # NLP fields populated by nlp_service.analyze_article_dict() below:
  "sentiment": nlp_result["sentiment"],
  "sentiment_score": nlp_result["sentiment_score"],
  "threat_level": nlp_result["threat_level"],
  "threat_category": nlp_result["threat_category"],
  "language": nlp_result["language"],
  "entities": nlp_result["entities"],
  "source_credibility": nlp_result["source_credibility"],
  "iinvest_story_id": str(story.get("id", "")),
  "iinvest_published_at": _parse_iso(story.get("sourceDateTime")),
}
```

Source prefix `iinvest:` lets the global news filter distinguish iinvest articles from
RSS-sourced ones in the `news/all` endpoint.

### 8A.5 DB schema additions

Two new columns on `news_articles`:

| Column | Type | Purpose |
|---|---|---|
| `iinvest_story_id` | `String(64)`, nullable, unique-indexed | iinvest's internal story ID (for upsert + dedup) |
| `iinvest_published_at` | `DateTime`, nullable | Original publish time (vs `fetched_at` which is when we stored it) |

Alembic migration `add_iinvest_columns_to_news_articles.py` adds these. No backfill needed.

### 8A.6 NewsWidget UI changes

The "company" tab gains a tiny `Source:` selector with three options:

| Option | Behavior |
|---|---|
| **iinvest (primary)** | Default. Shows iinvest articles. Falls back to MoneyControl silently if iinvest 503s and shows a small "MoneyControl fallback" badge. |
| **MoneyControl** | Force the old behavior. Skips iinvest entirely. |
| **All (merged)** | Fetches both, merges by URL, sorted by publish_date. Useful when neither source is comprehensive. |

The "Refresh" button now hits `POST /api/news/company?source=iinvest&refresh=true` instead
of the MoneyControl-only path. The "Source: iinvest" / "Source: MoneyControl" badge appears
next to the article count.

### 8A.7 MCP `get_company_news` tool

`get_company_news` gains a `source` parameter (default `auto`). When `auto`:
1. Try iinvest → if 200 and non-empty, fetch and run `nlp_service` on each article
2. On 503/404/empty, fall back to MoneyControl (existing flow)
3. Tag response with `"source_used": "iinvest" | "moneycontrol"`

MCP clients get faster, more deterministic company news by default with no API change. The
`sentiment`, `threat_level`, `language`, `days`, `limit`, `refresh` params all work the same
way for both sources — **NLP is post-fetched for both**, not pre-tagged on either.

### 8A.8 Performance

| Path | Latency | DB writes | Notes |
|---|---|---|---|
| iinvest primary (cache miss) | ~500 ms | ~20 upserts per page | One iinvest HTTP call + one DB batch upsert |
| iinvest primary (cache hit) | <5 ms | 0 | 15-min in-process cache |
| MoneyControl fallback | ~3-5 s | ~10-30 upserts | Two HTTP calls + NLP pipeline |
| Both merged | ~6 s | ~40-60 upserts | Use only when explicitly requested |

### 8A.9 Why not replace MoneyControl entirely?

| Reason | Detail |
|---|---|
| **Breadth** | RSS + MoneyControl catch news iinvest doesn't index (blog posts, social media, niche finance sites) |
| **Cross-source NLP consistency** | Filtering "BULLISH news" across all sources requires MoneyControl + RSS to be normalized too |
| **No ISIN for some symbols** | iinvest index is built around NSE/BSE listed companies. Pink sheets, SME, delisted — MoneyControl still works. |
| **Historical depth** | MoneyControl has older archives. iinvest's index rolls after a few months. |

So: **iinvest = primary per-company news**, **MoneyControl + RSS = global news + breadth
+ fallback**.

### 8A.10 New endpoints summary

| Endpoint | Method | Purpose |
|---|---|---|
| `GET /news/company/{symbol}` | GET | Updated to try iinvest first (existing endpoint, no breaking change) |
| `POST /news/company` | POST | Same — now writes both iinvest and MoneyControl articles |
| `GET /news/company/{symbol}?source=iinvest` | GET | Force iinvest only |
| `GET /news/company/{symbol}?source=moneycontrol` | GET | Force MoneyControl only (old behavior) |
| `GET /news/company/{symbol}?source=merged` | GET | Fetch both, merge by URL |

The MCP `get_company_news` tool gets a new `source: str = "auto"` arg (default behavior).
No breaking change for existing LLM clients.

---

## 9. MCP Tools

20 new `@mcp.tool()` functions registered in `backend/app/mcp_server.py`, each with:

- `_SYMBOL_RE.fullmatch(sym)` validation
- 10-min in-process cache (via `mcp_server._CACHE`)
- Single+bulk mode (`symbol XOR symbols`, `asyncio.gather(return_exceptions=True)`)
- Per-symbol error tolerance (bulk returns `{sym: {"error": str}}` on failure)

Naming convention: `iinvest_<endpoint>` (e.g. `iinvest_announcements`, `iinvest_key_shareholders`).

| Tool | Args | Notes |
|---|---|---|
| `iinvest_health` | none | Returns `{configured, healthy, last_validated, expires_at, last_error}` |
| `iinvest_overview` | symbol/symbols | 9 sections from `__NEXT_DATA__` |
| `iinvest_announcements` | symbol/symbols, page, size | |
| `iinvest_auditors` | symbol/symbols | |
| `iinvest_block_deals` | symbol/symbols, deal_type, page, size | |
| `iinvest_board_meetings` | symbol/symbols, page, size | |
| `iinvest_capital_history` | symbol/symbols, page, size | |
| `iinvest_corporate_actions` | symbol/symbols, action_type, page, size | |
| `iinvest_financial_peers` | symbol/symbols, filter_basis, compare, year, statement, page, size | |
| `iinvest_financial_peer_filters` | none | |
| `iinvest_index_of_charges` | symbol/symbols, page, size | |
| `iinvest_insider_trading` | symbol/symbols, page, size | |
| `iinvest_key_shareholders` | symbol/symbols, page, size | |
| `iinvest_legal_cases` | symbol/symbols, page, size | |
| `iinvest_marketdata_timeseries` | symbol/symbols, timescale, from_ | |
| `iinvest_pledged_shares` | symbol/symbols, page, size | |
| `iinvest_sast` | symbol/symbols, page, size | |
| `iinvest_tribunals` | symbol/symbols, page, size | |
| `iinvest_news` | symbol/symbols, days, limit | |
| `iinvest_all` | symbol/symbols, news_limit | Aggregator |

Manifest entries are added to `blm-mcp-bundle/manifest.json` and the bundle rebuilt
(`cd blm-mcp-bundle && npm run build`).

---

## 10. Code Map

| File | Purpose | Lines (est) |
|---|---|---|
| `backend/app/services/iinvest_client.py` | Async client, JWT lifecycle, ISIN resolver, 18 fetchers | ~600 |
| `backend/app/services/iinvest_html_parser.py` | Parse `__NEXT_DATA__` from overview HTML | ~150 |
| `backend/app/routers/iinvest.py` | 18 data + overview + health + all + path | ~400 |
| `backend/app/services/cache.py` | +`iinvest_cache` (200, 900s), +`iinvest_path_cache` (2000, 86400s) | +4 |
| `backend/app/services/nse_rate_limiter.py` | (unchanged; iinvest uses `throttled_nse_call` with new pool prefix) | 0 |
| `backend/app/models/stockuniverse.py` | +3 columns | +12 |
| `backend/app/schemas/stockuniverse.py` | +3 fields | +6 |
| `backend/alembic/versions/<hash>_add_iinvest_columns_to_stock_universe.py` | Migration | ~50 |
| `backend/main.py` | Register router, init in lifespan, close in orchestrator | +20 |
| `backend/app/orchestrator.py` | `await iinvest_client.close()` in `stop()` | +3 |
| `backend/app/mcp_server.py` | +20 tools | +400 |
| `blm-mcp-bundle/manifest.json` | +20 entries | +20 |
| `src/lib/iinvest.ts` | Typed interfaces + fetch helpers | ~200 |
| `src/components/widgets/FundamentalsWidget.tsx` | +13 collapsible sections | +600 |
| `backend/tests/test_iinvest_routes.py` | Integration tests (`@pytest.mark.slow`) | ~300 |
| `backend/tests/test_iinvest_client.py` | Unit tests (mocked httpx) | ~250 |
| `docs/reference/backend/iinvest.md` | This document | (you are here) |
| `docs/guides/iinvest-integration.md` | Step-by-step integration guide | ~500 |

**No new env vars required.** The AES key is hardcoded as a module constant with an optional
`COGENCIS_AES_KEY` env var override for emergency rotation.

---

## 11. Performance Characteristics (live-measured)

| Metric | Value | Notes |
|---|---|---|
| JWT acquisition | ~600 ms (1 POST + decrypt) | Once per 20h, in background |
| NSE GetQuoteApi (tier 3) | ~150-300 ms | Once per 24h per symbol |
| HTML scrape (tier 4) | ~200-500 ms | 47 KB HTML, parsed with stdlib json |
| Typical data endpoint | 60-1000 ms | 4-50 KB JSON, no extra processing |
| News (`/news/stories`, pageSize=50) | ~700 ms, ~40 KB | Full version with `story` body |
| Aggregator (`/iinvest/all`) | ~1-2 s | 18 endpoints in parallel via `asyncio.gather` |
| Cache hit | <1 ms | TTL-based, no I/O |
| HTML parse | ~5 ms | 47 KB `__NEXT_DATA__` → 9 section dicts |

### 11.1 Memory footprint

- JWT: 1 KB string
- AES key: 100 bytes
- iinvest_cache: 200 entries × ~20 KB = ~4 MB worst case
- iinvest_path_cache: 2000 entries × ~150 bytes = ~300 KB
- In-process refresh task: minimal (sleeps 99.99% of the time)

### 11.2 Rate limiter overhead

iinvest calls share the global NSE semaphore (default 2 concurrent). The per-endpoint
state (lock, circuit breaker) is keyed by the iinvest endpoint name, so iinvest calls don't
serialize with NSE polling at the state level. **No courtesy delay is needed**: live
verification showed `data.cogencis.com` enforces a `RateLimit-Policy: 50000;w=60` header
(50,000 requests per 60 s ≈ 833 req/s), and ten sequential `/api/login` POSTs at 1 s
intervals all returned 200 with no throttling. The `iinvest.*` endpoint_name pool uses
the **default 0.0s courtesy delay** — if we later see Akamai edge throttling from a
data-center IP, the pool can be tuned per-endpoint via the rate limiter's existing
`NSE_COURTESY_DELAY_SECONDS` override (or per-endpoint key) without code changes.

---

## 12. Known Limitations

1. **Cogencis may rotate the AES key** — handled by §2.5 auto-recovery, but if the JS bundle
   structure changes (new function name, different signature), the regex may miss. Logged at
   WARNING; recovers on next refresh cycle.
2. **Single guest user (user_id 765)** — shared across all anonymous visitors. iinvest may
   rate-limit by user_id if load increases. Mitigation: monitor for 429 responses; throttle
   is currently a non-issue (50K req/60s on `data.cogencis.com`).
3. **iinvest `users` and `watchlist` endpoints return 501** for the guest user (role: `view`
   doesn't have access). We don't use these endpoints.
4. **Akamai Bot Manager** can challenge data-center IPs. Mitigation: use HTTP/1.1 + the
   verified headers (§5.1). HTTP/2 triggers timeouts from WSL/datacenter IPs.
5. **News endpoint returns up to 67,825 records globally** — we cap at 50 per symbol per page
   and use 15-min cache. The MCP `iinvest_news` tool has a `limit` arg for explicit caps.
6. **iinvest news has a 24h rolling index** — deep history (e.g. `days=30`) is not available
   from iinvest. The `auto` source mode in `get_company_news` falls back to MoneyControl
   automatically when `days > 7` (iinvest will only return 1-2 days of recent news).
7. **HTML `__NEXT_DATA__.data` is empty server-side** — the overview endpoint always returns
   `{data: []}` for the 9 sections when fetched without a browser session. The data APIs are
   the source of truth for those sections.
8. **iinvest does not pre-tag sentiment/threat** — the `/news/stories` payload has no
   `sentiment` or `threat_level` fields. NLP must be run locally via `nlp_service` on the
   `headline` + `story` (or `synopsis`). Same pattern as MoneyControl and RSS flows.

---

## 13. References

- `HAR_ANALYSIS.md` (821 lines) — endpoint catalog derived from a full HINDALCO HAR capture
- `iinvest.cogencis.com_Archive [26-06-18 00-39-50].har` (8.1 MB) — the source HAR
- `docs/guides/iinvest-integration.md` — step-by-step implementation guide
- `docs/reference/backend/screener.md` — template this doc was modeled after
- `docs/reference/backend/orchestrator.md` — background worker architecture
- `docs/guides/screener-integration.md` — original screener integration pattern

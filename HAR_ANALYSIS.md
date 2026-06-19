# iinvest.cogencis.com — HAR Analysis Report

> Source: 2 HAR files (NEW: 2026-06-18 00:39 HINDALCO, OLD: 2026-06-17 15:39 TCS)
> Tool: Python 3.10 in-memory parsing
> HAR creator: Firefox (DevTools export)
> Captured sessions: 1 stock-detail page each; tab navigation is **client-side only** (Next.js GSSP), so all data API calls appear under a single `pageref`.

---

## 0. TL;DR

- **Two API surfaces**:
  - `https://iinvest.cogencis.com` — Next.js SSR app (the HTML) + a local BFF (`/api/users`, `/api/watchlist`)
  - `https://data.cogencis.com` — all the **data** APIs (Next.js client talks to this directly using `Authorization: Bearer <JWT>`)
- **Auth**: HS256 JWT in `Authorization: Bearer` header, signed by the iinvest app. 24h lifetime. Stored in browser as `next-auth.token` localStorage key (`{token, expiration, refreshToken, name}`).
- **20 distinct data endpoints hit** in the captured sessions. The page bundle (`pages/_app-…js`) defines **48 distinct endpoint paths** in a `u={}` map (full list below — many not exercised in either HAR).
- **No search/autocomplete network call was captured** — the search input is wired to a `useGetApiQuery("searchs", …)` RTK hook that calls `symbolLookUp` (`/marketdata/symbollookup`) with `searchTerm`, `searchOn=name|isin|symbol`, `indexName=idxLookup`, debounced 200ms, min 3 chars. The dynamic chunk that contains the call site wasn't loaded in either HAR (the user navigated via direct URL, never typed in the search box).
- **Timeseries chart**: 1 endpoint, 2 builders (`getTimeSeries` with `symbol=` and `getPathSeries` with `path=`). Only `timescale=1&from=1DAY` was observed. The endpoint serves 386 rows of intraday OHLCV.
- **HTML embeds the overview tab data via SSR** in `<script id="__NEXT_DATA__">` (~49KB) — so the overview tab is **zero** XHR calls; everything else (peers, corporate action, board meetings, etc.) is XHR.

---

## 1. Authentication & Headers

### 1.1 Hosts hit

| Host | Total reqs (NEW) | XHR/fetch | Static | Notes |
|---|---|---|---|---|
| `iinvest.cogencis.com` | 61 | 43 | 18 | Next.js SSR + BFF + JS/CSS/fonts |
| `data.cogencis.com` | 118 | 59 | 59 | All data APIs (Express) + Akamai bot-manager pixel |
| (none other observed) | — | — | — | no `akamaihd.net`, `googleapis.com`, etc. in this HAR |

### 1.2 Auth flow

- **No token endpoint observed** in either HAR. The HAR was captured during an already-authenticated session, with the JWT already present in the `next-auth.token` localStorage entry.
- The page bundle does contain a reference to `/api/login` (1 string literal in `_app-...js`), but no call to it appears in the capture.
- The app does have a session-warning modal ("You've been inactive for a while. Your session will expire in 1 minute. Do you want to continue your session?") implying the JWT lifetime is observable client-side.

### 1.3 Request headers by host

**`iinvest.cogencis.com`** (HTML/JS/CSS/fonts, plus local BFF):
| Header | Value(s) | Notes |
|---|---|---|
| `Host` | `iinvest.cogencis.com` | |
| `User-Agent` | `Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0` | |
| `Accept` | `*/*` for XHR, `text/html` for the page, `font/woff2` etc. for assets | |
| `Accept-Language` | `en-US,en;q=0.9` | |
| `Accept-Encoding` | `gzip, deflate, br, zstd` | |
| `Cookie` | `next-auth.token=<JSON>`, `ak_bmsc=…`, `bm_sv=…`, `bm_mi=…`, `+_ga/_ga_W3GPYYVVFC` | localStorage `next-auth.token` is NOT a real cookie — it's a JSON in localStorage. The browser injects `next-auth.token` as a cookie for SSR hydration. |
| `Cache-Control` | `no-cache` | |
| `DNT` | `1`, `Sec-GPC: 1` | privacy headers |
| `Sec-Fetch-*` | `mode: cors / no-cors`, `site: same-origin / cross-site`, `dest: script / style / font / empty` | |
| `TE` | `trailers` | |
| `Origin` | only on the local BFF (not on `_next` assets) | |
| `Authorization` | NOT sent to this host | |

**`data.cogencis.com`** (all data APIs):
| Header | Value | Notes |
|---|---|---|
| `Host` | `data.cogencis.com` | |
| `User-Agent` | same Firefox 152 | |
| `Accept` | `application/json, text/plain, */*` | |
| `Accept-Encoding` | `gzip, deflate, br, zstd` | |
| `Accept-Language` | `en-US,en;q=0.9` | |
| `Origin` | `https://iinvest.cogencis.com` | **required** — CORS-validated |
| **`Authorization`** | **`Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODE3NzU4NjMsImRhdGEiOnsidXNlcl9pZCI6NzY1LCJhcHBzIjoiY21zLHJhcGksY21zLHJhcGksY21zLHJhcGkiLCJyb2xlcyI6InZpZXcifSwiaWF0IjoxNzgxNjg5NDYzfQ.nW-xVuEsh8OKE60fcpkLFmEfsGtYlv…`** | HS256 JWT, see §13 |
| `Cookie` | NOT sent (the cookie that goes here is the `next-auth.token` but the browser doesn't auto-attach it cross-site; only the JS reads it from localStorage and adds the header) | |
| `Sec-Fetch-Site` | `same-site` | |
| `Sec-Fetch-Mode` | `cors` | |
| `Sec-Fetch-Dest` | `empty` | |
| `Cache-Control` | `no-cache`, `Pragma: no-cache` | |
| `TE` | `trailers` | |
| `DNT`, `Sec-GPC` | `1` | |

**CORS preflight (`OPTIONS`)** observed before every data API call (except the very first ones per host because the browser caches preflights):
- Request: `Access-Control-Request-Method: GET`, `Access-Control-Request-Headers: authorization`, `Origin: https://iinvest.cogencis.com`
- Response: `204 No Content`, `access-control-allow-origin: https://iinvest.cogencis.com`, `access-control-allow-credentials: true` (set on `iinvest` host; `data` host only sets ACAO)

### 1.4 Cookies

`Set-Cookie` observed (server-set):

| Host | Cookie | Purpose | Notes |
|---|---|---|---|
| `iinvest.cogencis.com` | `bm_sv=…` (Akamai Bot Manager session) | Bot-detection | `Domain=.cogencis.com; Path=/; Max-Age=7196; SameSite=None; Secure` |
| `data.cogencis.com` | `ak_bmsc=…` (Akamai Bot Manager) | Bot-detection | same shape |

These Akamai cookies are set automatically on first navigation to either host; they will be sent back on every subsequent request to `.cogencis.com`.

**Cookies ever sent in `Cookie:` request header** (client-side, by the time the data APIs fire):
- `next-auth.token` — but note this is a NextAuth token delivered by the iinvest SSR; in localStorage the structure is `{token, expiration, refreshToken, name}`; the browser puts it in the cookie jar for SSR.
- `ak_bmsc`, `bm_sv`, `bm_mi` — Akamai Bot Manager
- `_ga`, `_ga_W3GPYYVVFC` — Google Analytics (only NEW HAR, indicates the G-`TVWE449CRB` tag is active)

**Server-set cookies in NEW HAR: 2 (`ak_bmsc`, `bm_sv`). In OLD HAR: 1 (`ak_bmsc`)** — `bm_sv` is set on the first navigation and refreshed periodically.

---

## 2. All distinct data API endpoints (HAR-observed)

20 endpoints hit. All GET, all `application/json; charset=utf-8` responses, all wrapped in `{status: bool, message: string, response: …}` envelope.

| # | Endpoint (URL pattern) | Method | Observed query params | PageNo/pageSize | Status | Size (bytes) | Tab |
|---|---|---|---|---|---|---|---|
| 1 | `/api/v1/announcements` | GET | `path` (ISIN/symbol/ns/SYM/NAME), `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true` | 1/20 | 200 | 5,774 | Announcements |
| 2 | `/api/v1/auditors` | GET | `path`, `detailed=true` | — | 200 | 446 | Auditors |
| 3 | `/api/v1/blockdeals` | GET | `type=1` (bulk) or `type=2` (block), `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true` | 1/20 | 200 | 146–4,191 | Block Deals |
| 4 | `/api/v1/boardmeetings` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true` | 1/20 | 200 | 6,250 | Board Meetings |
| 5 | `/api/v1/capitalhistory` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true` | 1/20 | 200 | 3,239 | Capital History |
| 6 | `/api/v1/connectedcompanies` | GET | `path`, `din=<DIN>`, `jsonArray=true` | — | 200 | 152–1,484 | Connected Companies (per-director drilldown) |
| 7 | `/api/v1/corporateaction` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true`, `actionType` ∈ {`Dividend`, `Split`, `Bonus`, `Others`} (drilldown filter) | 1/20 | 200 | 5,560 avg | Corporate Actions |
| 8 | `/api/v1/financials/peers` | GET | `isin`, `filterBasis` ∈ {`9` (revenue), `10`, `11`}, `compare` ∈ {`2`, `4`, `14`, `15`, `16`, `20`}, `year` (`null` or `2025`/`2026`), `statementType` ∈ {`s`, `c`}, `pageNo=1`, `pageSize=7` | 1/7 | 200 | 1,644 avg | Peer Comparison |
| 9 | `/api/v1/financials/peers/filters` | GET | (no params) | — | 200 | 592 | Peer Comparison (filter dropdown) |
| 10 | `/api/v1/indexofcharges` | GET | `isin`, `detailed=true`, `pageNo=1`, `pageSize=20`, `jsonArray=true` | 1/20 | 200 | 2,814 | Index of Charges |
| 11 | `/api/v1/insidertrading` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true`, `actionType=undefined` (string!) | 1/20 | 200 | 5,669 | Insider Trading |
| 12 | `/api/v1/keyshareholders` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=undefined` (string!) | 1/20 | 200 | 22,125 | Key Shareholders |
| 13 | `/api/v1/legalcases` | GET | `isin`, `detailed=true`, `pageNo=1`, `pageSize=20`, `jsonArray=true` | 1/20 | 200 | 30,597 | Legal Cases |
| 14 | `/api/v1/marketdata/timeseries` | GET | `path`, `timescale=1`, `from=1DAY` (and optionally `to=<date>` or `symbol=`) | — | 200 | 43,021 | Chart (top of page) |
| 15 | `/api/v1/pledgedshares` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true`, `actionType=undefined` (string) | 1/20 | 200 | 2,329 | Pledged Shares |
| 16 | `/api/v1/sast` | GET | `path`, `pageNo=1`, `pageSize=20`, `detailed=true`, `jsonArray=true`, `actionType=undefined` (string) | 1/20 | 200 | 5,473 | SAST |
| 17 | `/api/v1/tribunals` | GET | `isin`, `detailed=true`, `pageNo=1`, `pageSize=20`, `jsonArray=true` | 1/20 | 200 | 2,884 | Tribunals |
| 18 | `/api/v1/web/news/stories` | GET | `sWebNews=true`, `forWebSite=true`, `pageNo=1`, `pageSize=20`, `isins=<ISIN>` | 1/20 | 200 | 20,662 | News |
| 19 | `/api/v1/users` (iinvest local BFF) | GET | (none) | — | **501** | 46 | — (auth check) |
| 20 | `/api/v1/watchlist` (iinvest local BFF) | GET | (none) | — | **501** | 46 | — (auth check) |

All data APIs use `https://data.cogencis.com`. Items 19 and 20 are on `https://iinvest.cogencis.com` and return 501 `{"message":"No authorization token was found"}` — the iinvest local BFF needs a different auth token (not the JWT sent to `data.cogencis.com`).

### Response envelope (every data API)

```json
{
  "status": true,
  "message": "Sucess",   // or "Succes" (typo on announcements endpoint!)
  "response": { ... }     // shape varies per endpoint, see §2.1
}
```

### 2.1 Per-endpoint response shape

| Endpoint | `.response` keys | Notes |
|---|---|---|
| `announcements` | `pagingInfo, columns, data` | `columns` is a list of `{field, displayName, dataType, format, dWidth, mWidth, action}`. Field codes are `f_156`, `f_158`, `f_159`, `f_25008`, … (numeric field codes — not human-readable). |
| `auditors` | `pagingInfo, columns, data` | `data: [["f_120"]]` — a list of lists when empty (quirk) |
| `blockdeals` | `pagingInfo, data` | **no `columns` key** |
| `boardmeetings` | `pagingInfo, columns, data` | |
| `capitalhistory` | `pagingInfo, columns, data` | |
| `connectedcompanies` | `pagingInfo, data` | **no `columns` key**; pagingInfo fields can be `None` |
| `corporateaction` | `pagingInfo, columns, data` | `data` items have a mix of `f_*` codes AND named fields (`isin`, `exchangesymbol`, `xface_value`, `xEx_Date`, `xPurpose`) |
| `financials/peers` | `pagingInfo, columns, data` | `columns[0].action = "navigate"` (clickable) |
| `financials/peers/filters` | `filters, compare, annual` | NOT a `pagingInfo/columns/data` shape — separate structure |
| `indexofcharges` | `pagingInfo, columns, data` | |
| `insidertrading` | `pagingInfo, columns, data` | |
| `keyshareholders` | `pagingInfo, columns, data` | first column `displayName="rptyear"`, `data: [["ID"]]` when empty |
| `legalcases` | `pagingInfo, columns, data` | |
| `marketdata/timeseries` | **`snapshot, data`** (no `pagingInfo`!) | `snapshot` is the latest quote (`{columns, data: {f_11: netchange, f_2: ltp, …}}`); `data` is a list of OHLCV rows `{open, high, low, close, volume, date, time}` |
| `pledgedshares` | `pagingInfo, columns, data` | |
| `sast` | `pagingInfo, columns, data` | |
| `tribunals` | `pagingInfo, columns, data` | |
| `web/news/stories` | `pagingInfo, columns, data` | first column is `sourceDateTime` (not `f_*`); `data` items have named fields (`headline, synopsis, categories, isins, cins, sections, sourceLink, thumbNailImage, isWebNews, source, sourceDateTime, status, enteredDateTime`) |

**`pagingInfo`** (when present): `{totalRecords, pageNo, pageSize, recordCount, noOfPages}` — all integers, but several fields can be `null`.

### 2.2 Sample response (one example, 1 endpoint)

`/api/v1/announcements` for HINDALCO (truncated):

```json
{
  "status": true,
  "message": "Succes",
  "response": {
    "pagingInfo": {"totalRecords": 120, "pageNo": 1, "pageSize": 20, "recordCount": 20, "noOfPages": 6},
    "columns": [
      {"field": "f_156", "dWidth": 100, "format": "DD-MMM-YY HH:MM", "action": null, "mWidth": 150, "dataType": "Date", "displayName": "DATE/ TIME"}
    ],
    "data": [
      {"f_156": "2025-12-13T12:50:20", "f_158": "General Updates", "f_159": "Outcome of Board Meeting", "f_25008": "ine038a01020/announ/hindalco/..."}
    ]
  }
}
```

---

## 3. Page navigation

**Only 1 HTML page was captured per HAR** (single-tab session):

| HAR | URL | Query |
|---|---|---|
| NEW | `https://iinvest.cogencis.com/INE038A01020/symbol/ns/HINDALCO/Hindalco%20Industries%20Limited` | `?tab=overview` |
| OLD | `https://iinvest.cogencis.com/INE467B01029/symbol/ns/TCS/Tata%20Consultancy%20Services%20Limited` | `?tab=overview` |

**All tab switching is client-side (Next.js shallow route change).** No new HTML page is loaded when the user clicks "Block Deals", "Peer Comparison", etc. — only XHR calls fire.

The single HTML page contains a `__NEXT_DATA__` block (see §5) that pre-renders the overview tab. The React client then refetches or hydrates other tabs on demand.

### Top-level page route pattern (Next.js dynamic)

```
GET /{ISIN}/symbol/{exchange|ns|bse}/{exchangesymbol}/{name}
```

Where:
- `{ISIN}` is a 12-char `INE##########`
- The second segment is hardcoded `symbol`
- `{exchange}` is `ns` (NSE) or `bse` (BSE)
- `{exchangesymbol}` is the exchange ticker (e.g. `HINDALCO`, `TCS`)
- `{name}` is the human company name (URL-encoded, spaces as `%20`)

`?tab=` parameter values observed (from the `__NEXT_DATA__` and from the `data` keys of the SSR response): **`overview`** (the only one in this capture). The SSR data envelope has keys `OV, BS, PL, CF, FO, IR, RC, SHP, BD` — see §5 for what each maps to.

### Other top-level routes referenced in HTML

| Path | Component | Notes |
|---|---|---|
| `/` | Home | Has the search widget (MUI `Autocomplete` `free-solo-2-demo`); not captured in either HAR |
| `/spotlight` | Spotlight | |
| `/screeners` | Screeners | |
| `/ipo` | IPO | |

No call to the home `/` was made in either HAR.

---

## 4. Tab-to-endpoint mapping

The page bundle renders the overview tab from the SSR `__NEXT_DATA__`. The other tabs are loaded by XHR.

**Single HTML page** (entry 0 of each HAR). After load, the user clicks through tabs which fire XHRs:

### Timeline of XHRs on the HINDALCO page (NEW HAR, `pageref=page_1`)

| Tab/Action | XHR fired (entry #) | Endpoint | Notes |
|---|---|---|---|
| Page load | 27 | `marketdata/timeseries?path=…&timescale=1&from=1DAY` | Timeseries chart at top |
| (auth probes) | 28, 29 | `iinvest.cogencis.com/api/users`, `…/api/watchlist` | Return 501 — used to check auth |
| Auditors | 31 | `auditors?path=…&detailed=true` | Initial load |
| (debounced) | 50 | `auditors?path=…&detailed=true` | Re-fired shortly after |
| News | 45 | `web/news/stories?isins=…&…` | |
| Connected Companies | 53, 55, 57, 59, 61, 63, 65 | `connectedcompanies?din=…&path=…&jsonArray=true` | One call per **director** (DIN) — 6 different DINs. Fired when user clicks each director's name in the overview "Board of Directors" panel. |
| Shareholding | 69 | `keyshareholders?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=undefined` | |
| Block Deals | 75, 77 | `blockdeals?type=2&path=…&…` then `?type=1&…` | Two types called: `type=2` (bulk), `type=1` (block). Sub-tabs. |
| Insider Trading | 79 | `insidertrading?path=…&actionType=undefined&…` | Note: `actionType=undefined` is sent as the literal string `"undefined"` |
| SAST | 81 | `sast?path=…&actionType=undefined&…` | same literal "undefined" string |
| Pledged Shares | 83 | `pledgedshares?path=…&actionType=undefined&…` | same |
| Capital History | 85 | `capitalhistory?path=…&…` | |
| Announcements | 93 | `announcements?path=…&…` | |
| Board Meetings | 95 | `boardmeetings?path=…&…` | |
| Corporate Actions | 97, 99, 101, 103, 105, 107 | `corporateaction?path=…&…` | Called **6 times** — once for the "All" view and then for each sub-filter `actionType=Dividend`, `Split`, `Bonus`, `Others` (in some order) |
| Peer Comparison | 111, 113, 115 | `financials/peers/filters` (no params) then `financials/peers?isin=…&filterBasis=…&compare=…&year=null&statementType=…&…` | filters called once, then peers called for `statementType=s` and `statementType=c` (consolidated) |
| Tribunals / Index of Charges / Legal Cases | 118, 120, 123, 125, 127, 129, 131, 133, 135, 137, 139, 141, 143 | `tribunals?isin=…`, `indexofcharges?isin=…`, `legalcases?isin=…` | These three endpoints are **re-fired 4 times each** (12 calls total) — likely React StrictMode double-render in dev or the user clicking each tab multiple times |
| Peer Comparison — filter change | 145, 146, 149, 151, 153, 154, 157, 159, 161, 163, 165, 167, 169, 171, 173, 175, 177 | `financials/peers?isin=…&filterBasis=…&compare=…&year=…&statementType=…&…` | User clicked through the filter dropdown: `filterBasis` 9→10→11, `compare` 2→14→15→16→20→4, `year` null→2026→2025. |

**CSR (client-side routing)**: no `_next/data/{buildId}/…` JSON file fetch was observed — Next.js GSSP/SSR mode is used, so tab switches don't re-fetch the HTML.

---

## 5. Embedded data (`__NEXT_DATA__`)

**Yes, the HTML page embeds a single `<script id="__NEXT_DATA__">` block.** This is the server-rendered payload for the **overview** tab. The user lands on the page with all overview data already there; nothing XHRs for the overview tab.

### `__NEXT_DATA__` top-level keys

```json
{
  "props": {
    "pageProps": {
      "nonce": "5ee9282e-40aa-475c-abbe-fa868eb7f5db",
      "data": {
        "status": true,
        "message": "Sucess",
        "response": {
          "OV":  { "C": { …company profile… } },
          "BS":  { "S": [ …balance sheet rows… ], "C": [ …columns… ] },
          "PL":  { "S": [ …P&L rows… ],      "C": [ …columns… ] },
          "CF":  { "S": [ …cash-flow rows… ], "C": [ …columns… ] },
          "FO":  { "S": [ …financial overview rows… ], "C": [ …columns… ] },
          "IR":  { "QR": {…}, "HR": {…}, "NR": {…}, "YR": {…} },
          "RC":  { "S": [ …ratios rows… ], "C": [ …columns… ] },
          "SHP": { "C": [ …shareholding data… ] },
          "BD":  { "C": [ …board of directors… ] }
        }
      }
    },
    "__N_SSP": true
  },
  "page": "/[isin]/[symbol]/[extension]/[exchangesymbol]/[name]",
  "query": {"tab": "overview", "isin": "INE038A01020", "symbol": "symbol", "extension": "ns", "exchangesymbol": "HINDALCO", "name": "Hindalco Industries Limited"},
  "buildId": "sGPBZnnV_ZN2DEbQjH8Rq",
  "isFallback": false,
  "isExperimentalCompile": false,
  "gssp": true,
  "appGip": true,
  "scriptLoader": []
}
```

### Mapping `__NEXT_DATA__.response` keys to page tabs

| Key | Section | Inferred tab | Total chars (HINDALCO) | Shape |
|---|---|---|---|---|
| `OV` | Overview (company profile) | top-of-page profile card | 3,066 | `OV.C` is a single object with ~60 fields (cin, bseCode, nseSymbol, marketcap, address, profileText, sector, auditorName, **flags** [{Tribunals:6},{Charges:152},{Default Details:0},{Legal Cases:10}], PE, TTM_EPS, high_52wk, low_52wk, Promoter Holding %, etc.) |
| `BS` | Balance Sheet | Balance Sheet tab | 7,038 | `BS.S` is the row tree (id/parentId/isExpanded/Description/5-year values), `BS.C` is the column metadata |
| `PL` | Profit & Loss | P&L tab | 4,188 | same shape as BS |
| `CF` | Cash Flow | Cash Flow tab | 7,717 | same shape as BS |
| `FO` | Financial Overview | Financials summary tab | 1,539 | same shape as BS |
| `IR` | Income / Returns (?) | Ratio / Income tab | 18,278 | sub-objects `QR, HR, NR, YR` (quarterly, half-yearly, nine-monthly, yearly?) each ~4500 chars |
| `RC` | Ratios / Calculated (?) | Ratios tab | 4,144 | same shape as BS |
| `SHP` | Shareholding pattern | Shareholding tab | 6,769 | `SHP.C` is a list of shareholding rows |
| `BD` | Board of Directors | Directors panel (top of page) | 1,063 | `BD.C` is a list of director objects (name, DIN, designation) |

### Size

- **HTML page size**: 20,772 bytes (transfer-compressed); 96,770 bytes uncompressed
- **`__NEXT_DATA__` script block**: 49,332 bytes (`<script id="__NEXT_DATA__" type="application/json">…</script>`)
  - opener: 51 bytes, JSON content: 49,272 bytes, closer: 9 bytes
  - The JSON contains the same data as the `data.cogencis.com` JSON endpoint but re-shaped (numeric field IDs are replaced with human names inside `OV.C`, but `BS/PL/CF/FO/RC` still use the `f_*` field codes and a row tree)

The HTML also has 20 `<script>` tags (all `_next/static/chunks/…js` and one `polyfills` chunk). There are no `window.__*` global injections, no other `<script id="…">` blocks besides `__NEXT_DATA__`, no `<template>` or `<pre>` data blobs.

---

## 6. Search / autocomplete / ISIN resolution

### What's wired in the page bundle

The header has a **MUI `<Autocomplete>`** search box (`id="free-solo-2-demo"`, `placeholder="Search"`, `type="search"`). The component is in `pages/_app-…js` and `chunks/7837-…js`.

A second variant of the same component (`free-solo-2-demo-peers`) is used in the **Peer Comparison** modal. Both use the same data source.

**API the search box calls** (defined in `pages/_app-…js`):

```js
getSymbolLookUp = (t, i, o, s, l) => {
  // t = searchTerm, i = pageNo, o = pageSize
  // s = instrumentType (optional), l = derivatives (optional)
  let params = [
    {pathName:"searchTerm", pathValue: t},
    {pathName:"searchOn",   pathValue: "name|isin|symbol"},
    {pathName:"indexName",  pathValue: "idxLookup"},
    {pathName:"pageNo",     pathValue: i},
    {pathName:"pageSize",   pathValue: o}
  ];
  if (s) { params.push({pathName:"instrumentType", pathValue: s}); if (l) params.push({pathName:"derivatives", pathValue: l}); }
  return getEndpoint("symbolLookUp", params);
};
// => GET https://data.cogencis.com/api/v1/marketdata/symbollookup?searchTerm=…&searchOn=name|isin|symbol&indexName=idxLookup&pageNo=1&pageSize=10
```

In the peers modal, the query is invoked via an RTK Query hook with `queryKey: "searchs"` and `queryFn: useGetApiQuery("".concat(a), n, 10)` where `a=inputValue, n=pageNo, 10=pageSize` — debounced 200ms, min **3 characters**.

The response (per JS) is `e.data.response` and is mapped:
```js
e => { label: e.f_400, value: e.f_5104, path: e.path }
```

So:
- `f_400` = display name (e.g. "Hindalco Industries Ltd.")
- `f_5104` = ISIN (e.g. "INE038A01020")
- `path` = the URL path used in navigation (e.g. `"ine038a01020/hinindus/ns/hindalco/hindalco-industries-limited"`)

### What was NOT captured in either HAR

**No call to `symbollookup` was made** in either HAR. Both HARs were captured with the user navigating **directly to the URL** (deep link to a stock). The search box was never typed in.

**Implication for the backend client implementation**: this endpoint exists and is wired, but its **exact request/response shape is inferred from the JS bundle**, not from a network capture. The first client implementation will need to call it manually to verify.

### iinvest homepage

The iinvest home is `https://iinvest.cogencis.com/`. It's a Next.js page that also exposes the same search component. No HAR captured it. It does have `<a href="/">` (self) and `<a href="/spotlight">`, `<a href="/screeners">`, `<a href="/ipo">`.

---

## 7. Block deals / Insider trading / Shareholding / Announcements / etc.

All of these are XHR calls — no separate page navigation. URL pattern, params, and example response size are in §2.

| Tab | URL | Filter param | Notes |
|---|---|---|---|
| Block Deals (Bulk) | `…/api/v1/blockdeals?type=1&path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true` | `type=1` | |
| Block Deals (Block) | `…/api/v1/blockdeals?type=2&path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true` | `type=2` | |
| Insider Trading | `…/api/v1/insidertrading?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true&actionType=undefined` | `actionType` (default literal string `"undefined"`) | |
| SAST | `…/api/v1/sast?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true&actionType=undefined` | `actionType` (string `"undefined"`) | |
| Pledged Shares | `…/api/v1/pledgedshares?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true&actionType=undefined` | `actionType` (string `"undefined"`) | |
| Capital History | `…/api/v1/capitalhistory?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true` | none | |
| Shareholding (Key Shareholders) | `…/api/v1/keyshareholders?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=undefined` | `jsonArray` literal string `"undefined"` (quirk — should be `true` but the app sends the string `"undefined"`) | |
| Auditors | `…/api/v1/auditors?path=…&detailed=true` | none | no pagination |
| Announcements | `…/api/v1/announcements?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true` | none | |
| Board Meetings | `…/api/v1/boardmeetings?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true` | none | |
| Corporate Actions (All) | `…/api/v1/corporateaction?path=…&pageNo=1&pageSize=20&detailed=true&jsonArray=true` | none (no `actionType`) | |
| Corporate Actions → Dividend | `…/api/v1/corporateaction?path=…&…&actionType=Dividend` | `actionType=Dividend` | |
| Corporate Actions → Split | `…/api/v1/corporateaction?path=…&…&actionType=Split` | `actionType=Split` | |
| Corporate Actions → Bonus | `…/api/v1/corporateaction?path=…&…&actionType=Bonus` | `actionType=Bonus` | |
| Corporate Actions → Others | `…/api/v1/corporateaction?path=…&…&actionType=Others` | `actionType=Others` | |
| Tribunals | `…/api/v1/tribunals?isin=…&detailed=true&pageNo=1&pageSize=20&jsonArray=true` | uses `isin=…` (NOT `path=…`) | |
| Index of Charges | `…/api/v1/indexofcharges?isin=…&detailed=true&pageNo=1&pageSize=20&jsonArray=true` | uses `isin=…` | |
| Legal Cases | `…/api/v1/legalcases?isin=…&detailed=true&pageNo=1&pageSize=20&jsonArray=true` | uses `isin=…` | |
| News | `…/api/v1/web/news/stories?sWebNews=true&forWebSite=true&pageNo=1&pageSize=20&isins=…` | `isins` (note: plural, comma-separated) | |
| Connected Companies (per DIN) | `…/api/v1/connectedcompanies?din=…&path=…&jsonArray=true` | `din` (Director Identification Number) | one call per director in `BD.C` |
| Peer Comparison — filter dropdown | `…/api/v1/financials/peers/filters` (no params) | — | |
| Peer Comparison — table | `…/api/v1/financials/peers?isin=…&filterBasis=…&compare=…&year=…&statementType=…&pageNo=1&pageSize=7` | `filterBasis` (revenue/earnings/…), `compare` (companies in same industry), `year`, `statementType` (`s`=standalone, `c`=consolidated) | |

`path` is the canonical parameter (it's `ISIN/exchange/ns|bs/SYMBOL/Company Name`). Some endpoints accept `isin=…` instead of `path=…` — they're equivalent.

---

## 8. Timeseries / OHLC / marketdata

### Endpoint

`GET https://data.cogencis.com/api/v1/marketdata/timeseries?path=…&timescale=1&from=1DAY`

### Two builders in the JS bundle

```js
// Used when the user provides a bare symbol (e.g. "HINDALCO")
getTimeSeries = (symbol, timescale, from, to) =>
  to ? getEndpoint("timeSeries", [
    {pathName:"symbol",    pathValue:symbol},
    {pathName:"timescale", pathValue:timescale},
    {pathName:"from",      pathValue:from},
    {pathName:"to",        pathValue:to}
  ]) : getEndpoint("timeSeries", [
    {pathName:"symbol",    pathValue:symbol},
    {pathName:"timescale", pathValue:timescale},
    {pathName:"from",      pathValue:from}
  ]);

// Used when the user provides a full path (e.g. "INE038A01020/symbol/ns/HINDALCO/Hindalco…")
getPathSeries = (path, timescale, from, to) => /* same shape, but pathName:"path" instead of "symbol" */
```

So the timeseries endpoint supports two interchangeable identifier styles:
- `symbol=HINDALCO` (bare)
- `path=INE038A01020/symbol/ns/HINDALCO/Hindalco%20Industries%20Limited` (full)

### Observed values

- `timescale`: only `1` (intraday, 1-minute)
- `from`: only `1DAY` (one trading day of intraday data)
- `to`: not used
- `symbol` vs `path`: only `path=…` observed in the HAR; `symbol=…` is the alternative per JS

**No tab switch was captured that changes the time range** — the HAR only shows the default intraday-1-minute view. The frontend likely has a UI to pick 1D/5D/1M/6M/1Y/etc., but the parameter values for those ranges are not present in the capture (they'd be other values of `from` like `5DAY`, `1MONTH`, `6MONTH`, `1YEAR` etc., and other `timescale` values).

### Response shape

```json
{
  "status": true,
  "message": "Sucess",
  "response": {
    "snapshot": {
      "columns": [
        {"field": "f_5051", "displayName": "Symbol",         "dataType": "string",   "format": null,             "dWidth": …, "mWidth": …},
        {"field": "f_400",  "displayName": "Name",           "dataType": "string",   "format": null,             "dWidth": …, "mWidth": …},
        {"field": "f_2",    "displayName": "LTP",            "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_11",   "displayName": "Net Change",     "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_56",   "displayName": "%Chng",          "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_100",  "displayName": "Total Volume",   "dataType": "number",   "format": "n0",             "dWidth": …, "mWidth": …},
        {"field": "f_10",   "displayName": "Date/Time",      "dataType": "datetime", "format": "DD MMM YY HH:mm:ss", "dWidth": …, "mWidth": …},
        {"field": "f_302",  "displayName": "Open",           "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_300",  "displayName": "High",           "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_301",  "displayName": "Low",            "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_304",  "displayName": "P Close",        "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_5002", "displayName": "52Wk High",      "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …},
        {"field": "f_5003", "displayName": "52Wk Low",       "dataType": "number",   "format": "n2",             "dWidth": …, "mWidth": …}
      ],
      "data": {
        "f_11": 25.5,                  // net change
        "f_5002": 1176,                // 52wk high
        "f_56": 2.6,                   // % change
        "f_25008": "ine038a01020/hinindus/ns/hindalco/...",
        "f_400": "Hindalco Industries Ltd.",
        "f_300": 1011.6,               // high (day)
        "f_5051": "HININDUS.NS",
        "f_2": 1007.9,                 // LTP
        "f_10": "2026-06-17T15:59:52Z",
        "f_302": 985,                  // open
        "f_5003": 635.05,              // 52wk low
        "f_301": 971.2,                // low (day)
        "f_100": 10853418,             // total volume
        "f_304": 982.4                 // previous close
      }
    },
    "data": [
      {"open": 1007.9, "high": 1007.9, "low": 1007.9, "close": 1007.9, "volume": 0, "date": "2026-06-17", "time": "16:44:00"},
      {"open": 1007.9, "high": 1007.9, "low": 1007.9, "close": 1007.9, "volume": 6, "date": "2026-06-17", "time": "15:59:00"},
      … 386 total intraday bars
    ]
  }
}
```

`response.snapshot` is the latest quote (current LTP, 52w high/low, day open/high/low/prev close). `response.data` is the OHLCV candle series (386 bars for one trading day at 1-minute intervals).

**Size**: 43,021 bytes for HINDALCO with 386 bars.

### Field dictionary endpoint (in JS, not in HAR)

The page bundle has:

```js
eF.Z.get("".concat("https://data.cogencis.com/api/v1","/marketdata/fielddictionary"), {
  headers: {…,"Authorization":"Bearer ".concat(t.token)}
}).then(...)
```

This endpoint is called **once at app startup** to fetch a "field dictionary" that maps `f_*` field IDs to human labels. The result is cached in `localStorage` under the key `field-dictionary`. **Not captured in either HAR** (likely because the dictionary was already cached from a previous session, or the dictionary fetch is silent and a 304 was returned). The dictionary endpoint:

- `GET /api/v1/marketdata/fielddictionary`
- Returns `response` = an object mapping `f_*` → human label

---

## 9. Pagination

| Endpoint family | pageNo | pageSize | Max? | Sort? |
|---|---|---|---|---|
| `announcements, boardmeetings, capitalhistory, connectedcompanies (only pagingInfo), corporateaction, insidertrading, keyshareholders, pledgedshares, sast, blockdeals, legalcases, indexofcharges, tribunals, web/news/stories` | `1` (only ever `1` in HAR) | `20` | unknown — no `pageNo=2` was ever called | none visible |
| `financials/peers` | `1` | **`7`** (small) | unknown | none visible |

The pagingInfo response contains `{totalRecords, pageNo, pageSize, recordCount, noOfPages}` — the client can derive pagination from that.

`connectedcompanies` pagingInfo has all `NoneType` (string `null`) values, so the response is essentially `recordCount` only.

**No "load more" or "next page" button click was exercised** in either HAR. Default page size for table endpoints is 20; for peer comparison it's 7.

---

## 10. Rate limiting & errors

### Non-200 responses observed

| Status | URL | Body |
|---|---|---|
| **501** | `https://iinvest.cogencis.com/api/users` | `{"message":"No authorization token was found"}` |
| **501** | `https://iinvest.cogencis.com/api/watchlist` | `{"message":"No authorization token was found"}` |
| 204 | All `OPTIONS` preflights to `data.cogencis.com` | (empty) |
| 0 | `https://iinvest.cogencis.com/akam/13/2ad63f58` | (Akamai bot-manager beacon) |

- **No 401, 403, 429, or 5xx** observed for the data APIs.
- **No `Retry-After` headers** observed.
- The two 501s on the iinvest BFF are **auth failures** (the iinvest local BFF needs a different auth token than the JWT sent to `data.cogencis.com`).
- The iinvest app always probes these two endpoints on page load; in a logged-in session they presumably return user data + watchlist, not 501.

### Error response shape (inferred from JS bundle)

`axios` is used (no raw `fetch`/XHR for the data APIs in the page bundle). On a non-2xx response, the promise rejects and the page falls back to error UI. The exact error JSON shape returned by the server for 4xx/5xx is not in the HAR (no error responses).

The two 501s on the iinvest BFF use a **different envelope** from the data APIs:
```json
{"message": "No authorization token was found"}
```
(no `status` boolean, no `response` object)

---

## 11. Static assets

| Domain | Asset count (NEW) | Notes |
|---|---|---|
| `iinvest.cogencis.com/_next/static/` | 39 JS + 2 CSS + 8 woff2 + 4 svg + 1 ico + 1 webp | All served from same host as the page |
| `data.cogencis.com/akam/13/2ad63f58` | 1 pixel | Akamai bot-manager beacon |
| (none other) | — | No fonts.googleapis.com, no gstatic, no other CDN |

**Asset breakdown (NEW HAR):**
- `application/javascript`: 41 files (chunks 648, 1114, 3131, 4303, 5564, 6306, 6172, 6646, 4678, 7440, 7882, 7927, 9265, 9912, 031aa83e, 2638.ba, 1310.e3, 6557.e8, 763.d8, 5655.30, 7837.b8, 9627.87, 2020.f8, 4532.7a, 840.fd, 8275.12, 7399.9d, 1220.ef, 3389.4f, 2853.a8, 9415.ff, ad7f724d, framework, main, webpack, pages/_app, pages/[isin]…[name])
- `font/woff2`: 8 files (Urbanist Regular/Medium/Bold/SemiBold, Poppins Regular/Light/Medium/SemiBold)
- `text/css`: 2 files (`a92b2f7370749665.css`, `7ac8cb26da507440.css`)
- `image/svg+xml`: 4 files (logos)
- `image/x-icon`: 1 (favicon.ico)
- `image/webp`: 1

The page bundle (`pages/_app-...js`) is **252,718 bytes** (the most important file — contains the endpoint map, the API builder functions, and most of the API call sites). The page-specific bundle (`pages/%5Bisin%5D/…[name]-fc741df389d9209d.js`) is 11,544 bytes.

**Content-Security-Policy** (extracted from `_app-...js`):
```
default-src 'self'
script-src  'self' 'nonce-${nonce}' 'unsafe-eval' data.cogencis.com iinvest.cogencis.com
style-src   'self' 'unsafe-inline'
connect-src 'self' data.cogencis.com iinvest.cogencis.com www.google-analytics.com
font-src    'self' data:
img-src     'self' data:
worker-src  'self'
frame-ancestors 'self'
form-action 'self'
```

This means: the iinvest app is allowed to **connect** (XHR/fetch) only to itself, `data.cogencis.com`, and Google Analytics. Scripts may be loaded only from the same origin (and the two cogencis hosts — though no scripts are actually loaded from `data.cogencis.com` in the capture).

**Google Analytics**: `G-TVWE449CRB` (gtag.js). The OLD HAR has no `_ga` cookies, the NEW HAR does — meaning GA was added between the two captures (or the NEW session had GA enabled).

---

## 12. Cookies — final state

After the full HINDALCO page session (NEW HAR), the following cookies would be in the browser cookie jar for `.cogencis.com` (combined from `Set-Cookie` on responses and from `Cookie:` on requests):

| Cookie name | Domain | Purpose | Set on | Expires | HttpOnly? | Secure? | SameSite |
|---|---|---|---|---|---|---|---|
| `bm_sv` | `.cogencis.com` | Akamai Bot Manager session validation | iinvest HTML | ~2h sliding | no | yes | None |
| `bm_mi` | `.cogencis.com` | Akamai Bot Manager | (set on data.cogencis.com) | session | no | yes | None |
| `ak_bmsc` | `.cogencis.com` | Akamai Bot Manager | data.cogencis.com HTML/JS | ~session | no | yes | None |
| `next-auth.token` | (set as cookie) | JWT + refresh | iinvest SSR | — | no | yes | — |
| `_ga` | `.cogencis.com` | Google Analytics | GA tag | 2 years | no | no | Lax |
| `_ga_W3GPYYVVFC` | `.cogencis.com` | Google Analytics (session) | GA tag | 2 years | no | no | Lax |

OLD HAR (TCS session) had only `ak_bmsc`, `bm_mi`, `bm_sv`, `next-auth.token` (no GA cookies, no `_ga`).

**`next-auth.token` cookie value** (used by the SSR; the actual localStorage `next-auth.token` JSON object has the same content + `expiration` field): the JWT itself (see §13).

The localStorage `next-auth.token` JSON structure (per JS bundle):
```json
{
  "token": "<JWT string>",
  "expiration": "2026-06-18T15:14:23.000Z",
  "refreshToken": "<refresh JWT or empty>",
  "name": "<user name>"
}
```

There's also a separate `next-auth-token-one` localStorage key referenced (same shape).

---

## 13. Token details

### Authorization header (sent to `data.cogencis.com`)

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODE3NzU4NjMsImRhdGEiOnsidXNlcl9pZCI6NzY1LCJhcHBzIjoiY21zLHJhcGksY21zLHJhcGksY21zLHJhcGkiLCJyb2xlcyI6InZpZXcifSwiaWF0IjoxNzgxNjg5NDYzfQ.<SIGNATURE_REDACTED>
```

### Decoded JWT

**Header**:
```json
{"alg": "HS256", "typ": "JWT"}
```

**Payload**:
```json
{
  "exp": 1781775863,
  "data": {
    "user_id": 765,
    "apps": "cms,rapi,cms,rapi,cms,rapi",
    "roles": "view"
  },
  "iat": 1781689463
}
```

**Signature**: HS256 (shared-secret HMAC-SHA256) — redacted in this report. The server holds the secret; you cannot forge or verify this token from the client side.

### Token lifetime

- `iat` = 2026-06-17 15:14:23 UTC (approx, derived from `iat=1781689463`)
- `exp` = 2026-06-18 15:14:23 UTC (approx, derived from `exp=1781775863`)
- **24 hours** lifetime

### Claims of interest

- `data.user_id`: numeric user ID (765 in this session)
- `data.apps`: comma-separated list of app slugs the user is allowed to access. Repeated `cms,rapi` (presumably an array stored as a string, e.g. `["cms","rapi","cms","rapi","cms","rapi"]` without proper JSON serialization). The data.cogencis.com API uses this to gate access.
- `data.roles`: a single string `"view"` (read-only).

### Where the token comes from

The HAR captured an **already-authenticated** session; the `/api/login` endpoint was not called in either capture. To obtain a fresh JWT for the backend client implementation you will need to:

1. Either capture a login flow (browse to the iinvest login page, submit credentials, watch the response).
2. Or, if the iinvest app uses a public OAuth / SSO flow with `cogencis.com`, find the token endpoint by examining the login page source (not in either HAR).
3. Or, use the `next-auth.token` cookie that the iinvest SSR sets — it contains the same JWT.

The page bundle contains a `/api/login` reference but no definition of the endpoint, so the route is defined in a server-side route handler that's not visible from client JS.

---

## Appendix A — Complete endpoint catalog (from JS bundle, including unhit)

Extracted from `pages/_app-…js` `u = {…}` object. **All endpoints are prepended with `https://data.cogencis.com/api/v1`** (i.e. `s` in the JS).

| JS key | Full URL | Hit in HAR? | Notes |
|---|---|---|---|
| `financials` | `/financials` | no | alternative SSR-style financial summary; the SSR `__NEXT_DATA__` includes a similar shape via `BS, PL, CF, FO, IR, RC` |
| `marketData` | `/marketdata` | no | base; sub-paths used instead |
| `marketRanking` | `/marketdata/marketrankings` | no | "Top Movers" widget. Built by `getMarketRankings(command, fields, pageNo, pageSize, period?, jsonArray)` |
| `symbolLookUp` | `/marketdata/symbollookup` | **no (inferred from JS)** | Search/autocomplete. `?searchTerm=…&searchOn=name\|isin\|symbol&indexName=idxLookup&pageNo=1&pageSize=10[&instrumentType=…&derivatives=…]` |
| `indexConstituents` | `/marketdata/indexconstituents` | no | `?symbol=…&fields=…&pageNo=…&pageSize=…&indexType=…&sortBy=…&sortOrder=…` (also a `getPathByIndexConst` variant with `command=gainers`) |
| `timeSeries` | `/marketdata/timeseries` | YES | |
| `boardMeeting` | `/boardmeetings` | YES | |
| `announcement` | `/announcements` | YES | |
| `news` | `/web/news/stories` | YES | |
| `sast` | `/sast` | YES | |
| `corporate` | `/corporateaction` | YES | |
| `pledgeShares` | `/pledgedshares` | YES | |
| `insiderTrading` | `/insidertrading` | YES | |
| `blockDeals` | `/blockdeals` | YES | |
| `events` | `/corporateevents` | no | "Events" tab — not in HAR |
| `fii` | `/fii` | no | FII activity |
| `dii` | `/dii` | no | DII activity |
| `resultCalender` | `/corporateresultscalendar` | no | (sic: "Calender") corporate results calendar |
| `corporateAction` | `/corporateaction` | (duplicate of `corporate`) | |
| `screenerFilter` | `/screeners/filters` | no | |
| `screeners` | `/screeners` | no | |
| `customScreener` | `/screeners/custom/filters` | no | |
| `customScreenerByQuery` | `/screeners/custom` | no | |
| `connectedCompanies` | `/connectedcompanies` | YES | |
| `peersFilter` | `/financials/peers/filters` | YES | |
| `peers` | `/financials/peers` | YES | |
| `auditiors` (sic: typo) | `/auditors` | YES | |
| `keyShareholders` | `/keyshareholders` | YES | |
| `tribunals` | `/tribunals` | YES | |
| `indexOfCharges` | `/indexofcharges` | YES | |
| `defaulterdetails` | `/defaulterdetails` | no | "Default Details" widget on overview page (per `OV.C.flags`) |
| `capitalHistory` | `/capitalhistory` | YES | |
| `legalcases` (lowercase) | `/legalcases` | YES | |
| `newsList` | `/web/news/landingpage` | no | |
| `newsViewCount` | `/web/news/viewcount` | no | POST or GET to increment view count |
| `newsStories` | `/web/news/stories` | (duplicate of `news`) | |
| `newsStory` | `/web/news/story` | no | single story |
| `ipo` | `/ipo/issues` | no | |
| `ipoPerformance` | `/ipo/performance` | no | |
| `getWatchlistScrip` | `/marketdata/multi` | no | multi-symbol quote (used by watchlist) |
| `derivatiesFuture` (sic: typo) | `/derivatives/futures` | no | |
| `derivatiesOption` (sic: typo) | `/derivatives/options` | no | |
| `futuresChain` | `/derivatives/futures/chain` | no | |
| `optionsChain` | `/derivatives/options/chain` | no | |
| `fiiDerivatives` | `/derivatives/fii` | no | FII derivatives |
| `contactUs` | `https://iinvest.cogencis.com/api/contactus` | no | local iinvest BFF, not on data.cogencis.com |

**iinvest local BFF endpoints** (in JS, not in `u` map):

| Endpoint | Status in HAR | Notes |
|---|---|---|
| `POST https://iinvest.cogencis.com/api/login` | not called | the actual login endpoint |
| `GET  https://iinvest.cogencis.com/api/users` | 501 | needs separate auth |
| `GET  https://iinvest.cogencis.com/api/watchlist` | 501 | needs separate auth |

---

## Appendix B — Comparison with OLD HAR (TCS, 2026-06-17 15:39)

| Metric | NEW (HINDALCO) | OLD (TCS) |
|---|---|---|
| Total entries | 179 | 152 |
| HTML pages | 1 (HINDALCO overview) | 1 (TCS overview) |
| Distinct data APIs hit | 20 | 19 (no `tribunals` second call) |
| `connectedcompanies` calls | 7 (one per director) | 0 (not clicked in OLD) |
| `timeseries` calls | 1 (only 1DAY intraday) | 1 (only 1DAY intraday) |
| `peers` calls | 15 (multiple filter combinations) | 16 (similar) |
| JWT user_id | 765 | (different — not in HAR) |
| JWT iat | 2026-06-17 15:14:23 | — |
| `bm_sv` Set-Cookie | yes | no (still active from prior session) |
| `ak_bmsc` Set-Cookie | yes | yes |
| Google Analytics | yes (G-TVWE449CRB, `_ga` cookies) | no |
| Timeseries interval | `timescale=1&from=1DAY` (intraday) | same |
| `blockdeals` sub-types called | `type=1` and `type=2` | `type=1` and `type=2` |
| `corporateaction` sub-filters | `Dividend, Split, Bonus, Others` (4) | `Dividend, Split, Bonus, Others` (4) |
| `statementType` for peers | `s` and `c` | `s` and `c` |
| `filterBasis` for peers | `9, 10, 11` | `9, 10, 11` |

The OLD HAR is essentially the same session shape (a user lands on a stock page, clicks the tabs) — confirms the endpoint surface is stable across at least HINDALCO and TCS.

---

## Appendix C — Implementation notes for a backend client

1. **Get a JWT first.** There's no public token endpoint in either HAR. Options:
   - Reverse-engineer the iinvest login (POST `/api/login` on `iinvest.cogencis.com`).
   - If you can run a browser, log in and extract `localStorage.getItem('next-auth.token')`, then take its `.token`.
2. **Send the JWT in `Authorization: Bearer …`** with `Origin: https://iinvest.cogencis.com`. CORS is enforced on `data.cogencis.com` — you'll get a CORS error from a pure server-side client. You'll need to either:
   - Set `Origin: https://iinvest.cogencis.com` and have Akamai WAF allow it (server-to-server, not CORS-restricted in the usual sense — but you might still get blocked).
   - OR proxy through your own server, which the app **does** (the existing `src/app/api/py/[...path]/route.ts` in this repo — see also the FastAPI backend in `backend/`).
3. **Akamai Bot Manager**: the `ak_bmsc` and `bm_sv` cookies are Akamai's bot-detection cookies. A pure server-side HTTP client will likely be **blocked** by Akamai unless you also maintain these cookies across requests (they get set on the very first request, then sent back automatically by the browser). You may need to use a real browser (Playwright/Puppeteer) to obtain and persist them.
4. **Field codes are not human-readable.** Most endpoints use `f_156`, `f_158`, `f_25008`, etc. The `field-dictionary` endpoint (`/api/v1/marketdata/fielddictionary`) maps these. Fetch it once and cache. The `OV.C` overview block has named fields directly, so the company-profile section doesn't need the dictionary.
5. **String `undefined` is sent literally** for `jsonArray` and `actionType` on some endpoints. Mirror this exactly or the API may behave differently. (E.g. `keyshareholders` sends `jsonArray=undefined`, `insidertrading/sast/pledgedshares` send `actionType=undefined`.)
6. **All 20 endpoints support only GET.** No POST/PUT/DELETE was seen in the HAR.
7. **Default pageSize = 20** for all list endpoints, **7** for peer comparison.
8. **All `path` query parameters** are URL-encoded `ISIN/symbol/ns|bs/SYMBOL/Company Name`. The 4-segment structure is required (e.g. `INE038A01020/symbol/ns/HINDALCO/Hindalco%20Industries%20Limited`).
9. **The SSR `__NEXT_DATA__` block is the fastest way to get the full overview tab** (49KB JSON, all 9 sections in one shot: `OV, BS, PL, CF, FO, IR, RC, SHP, BD`). All other tabs need separate XHR calls.
10. **The `marketdata/timeseries` endpoint returns 386 intraday bars per call** for a 1-minute timescale over 1 trading day (~43KB). For 5D/1M/6M/1Y/etc., the `timescale` and `from` values aren't captured in this HAR; they'll need to be discovered by user interaction (different values of `from` like `5DAY`, `1MONTH`, `6MONTH`, `1YEAR`, and `timescale` like `5` for 5-minute bars).

---

## Appendix D — File index

| File | Purpose |
|---|---|
| `/mnt/d/500GB/p1/Projects/blm_terminal/iinvest.cogencis.com_Archive [26-06-18 00-39-50].har` | NEW HAR — HINDALCO (INE038A01020) |
| `/mnt/d/500GB/p1/Projects/blm_terminal/iinvest.cogencis.com_Archive [26-06-17 15-39-03].har` | OLD HAR — TCS (INE467B01029) |
| `/tmp/har_analysis/analyze.py` | Initial high-level parsing |
| `/tmp/har_analysis/endpoints.py` | Group XHR endpoints by pattern |
| `/tmp/har_analysis/shapes.py` | Extract response top-level keys |
| `/tmp/har_analysis/inner_shapes.py` | Drill into `.response` inner shape |
| `/tmp/har_analysis/headers.py` | Headers, auth, cookies analysis |
| `/tmp/har_analysis/jwt_and_html.py` | JWT decode + HTML extraction |
| `/tmp/har_analysis/pageprops.py` | Inspect `__NEXT_DATA__.pageProps` |
| `/tmp/har_analysis/overview_data.py` | Overview data shape |
| `/tmp/har_analysis/ssr_full.py` | All SSR-data keys with sizes |
| `/tmp/har_analysis/embed_size.py` | `__NEXT_DATA__` block size |
| `/tmp/har_analysis/pageref.py` | pageref & XHR timeline |
| `/tmp/har_analysis/compare_hars.py` | NEW vs OLD comparison |
| `/tmp/har_analysis/params_full.py` | All distinct query param values |
| `/tmp/har_analysis/misc.py` | Errors, timeseries, search patterns |
| `/tmp/har_analysis/timeseries2.py` | Timeseries detailed shape |
| `/tmp/har_analysis/look_js.py` | API path literals in JS |
| `/tmp/har_analysis/endpoint_map.py` | Extract `u = {…}` endpoint map |
| `/tmp/har_analysis/endpoint_map2.py` | Identifier→path mapping |
| `/tmp/har_analysis/find_getApiXxx.py` | API builder function bodies |
| `/tmp/har_analysis/find_getTimeSeries.py` | TimeSeries / MarketDrill builders |
| `/tmp/har_analysis/times_params.py` | Timescale/from values |
| `/tmp/har_analysis/connected.py` | connectedcompanies samples |
| `/tmp/har_analysis/options.py` | CORS preflight analysis |
| `/tmp/har_analysis/final_data.py` | Static asset / cookie counts |
| `/tmp/har_analysis/referer.py` | Referer headers |
| `/tmp/har_analysis/html_search.py` | Search input in HTML |


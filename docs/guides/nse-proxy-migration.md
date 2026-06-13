# NSE proxy migration: `change-ranges` and `symbol-data`

> **Status:** Implemented.
> **Goal:** Reduce Python backend load by serving NSE `change-ranges` and `symbol-data` directly from a Next.js proxy, with the Python backend as a graceful fallback. Browser keeps talking to the Next.js app only — fitting the planned Electron migration.

---

## 0. Decisions

| Question | Decision |
|---|---|
| Fallback header from Next → Python | Identical request (no marker) |
| NSE circuit breaker on the Next side | Full Python parity (`CLOSED → OPEN → HALF_OPEN → CLOSED`) |
| Scope | Only the WS `change-ranges` / `symbol-data` path; Morningstar fair-value `useQueries` and notifications count were left alone |
| Frontend module | **Renamed** `src/lib/marketWs.ts` → `src/lib/nseFetch.ts`; 4 import sites updated |
| AI / MCP consumers | Stay on the Python backend (untouched) |

---

## 1. Data flow

### Before
```
Browser ── WebSocket /ws/market ──► Python FastAPI ──► NSE
        (one per browser tab)
```

### After
```
Browser ── fetch /api/nse/change-ranges|symbol-data ──► Next.js route
                                                          │
                                                          ├──► NSE  (primary)
                                                          │
                                                          └──► Python  (per-symbol fallback)
```

The **browser** still only talks to the Next.js app. NSE is hit from the Next server (closer to the user than the Python host). Python is hit only on per-symbol NSE failure.

---

## 2. Files changed

### 2.1 Added

| Path | Purpose |
|---|---|
| `src/lib/nseTypes.ts` | Shared types, field map, TTL constants, NSE headers, helpers |
| `src/lib/nseThrottle.ts` | TypeScript port of `backend/app/services/nse_rate_limiter.py` (full CLOSED/OPEN/HALF_OPEN parity) |
| `src/lib/nseFetch.ts` | `MarketDataService` singleton with HTTP transport |
| `src/app/api/nse/change-ranges/route.ts` | Next route: cache → NSE → Python fallback |
| `src/app/api/nse/symbol-data/route.ts` | Next route: cache → NSE → Python fallback |
| `backend/app/services/market_data.py` | Shared helpers `bounded_change_ranges` / `bounded_symbol_data` / `fetch_change_ranges_batch` / `fetch_symbol_data_batch` (extracted from `market_ws.py`) |
| `backend/tests/test_market_data_routes.py` | 6 unit tests for the new helpers |

### 2.2 Modified

| Path | Change |
|---|---|
| `src/components/widgets/WatchWidget.tsx` (lines 17–18, 421, 438, 480–488) | `marketWsService` → `marketDataService`; imports re-pointed to `@/lib/nseFetch` and `@/lib/nseTypes` |
| `src/components/widgets/MoversWidget.tsx` (lines 12–13, 118, 124, 148, 154) | Same |
| `src/components/TerminalContainer.tsx` (lines 23, 81) | Same; `onConnectionChange` is preserved (always emits `true`) — see §8 |
| `backend/app/routers/market_ws.py` | Reduced from ~239 lines to ~155 by delegating per-symbol fetch + NaN cleaning + semaphore to the shared helper. No behavioural change for the WS path |
| `backend/app/routers/markets.py` | Added `GET /api/markets/change-ranges` and `GET /api/markets/symbol-data` as REST fallbacks for the Next.js proxy |

### 2.3 Deleted

| Path | Reason |
|---|---|
| `src/lib/marketWs.ts` | Replaced by `nseFetch.ts` |

### 2.4 Intentionally untouched

- `src/app/api/py/[...path]/route.ts` — still used for everything else.
- `src/app/api/py/ws-config/route.ts` — still used by `src/lib/newsSocket.ts:85`.
- `backend/app/routers/market_ws.py` (the WS endpoint itself) — kept; AI / MCP server still call into the WS actions.
- `nse_client_async.get_change_ranges` / `get_symbol_data` — kept; imported by AI chat (`ai_chat_service.py:744, 754`) and used internally by `market_data.py`.
- `WatchWidget.tsx` Morningstar `useQueries` (line 500) and notifications count (line 517) — out of scope.
- `tickDataAtom` in `src/store/terminalStore.ts` — `WatchWidget.tsx` is still the sole writer (`WatchWidget.tsx:442-445`), so the consumer (`PosWidget.tsx:82`) keeps working unchanged.

---

## 3. Per-component notes (what was actually built)

### 3.1 `src/lib/nseTypes.ts`

Moved types verbatim from the old `marketWs.ts` and added the field map, TTL constants, NSE headers, and a `parseChangeRangesRow()` helper that mirrors `nse_client_async.py:55-64, 295-309` + `market_ws.py:64-73`.

Exports:
- `ChangeRanges`, `SymbolDataExtract`, `RawNseSymbolData` interfaces.
- `extractSymbolData(raw)`: maps NSE's `equityResponse[0]` to `{ ltp, pChange, yearHigh, yearLow }`.
- `NSE_FIELD_MAP_CHANGE_RANGES: Record<keyof ChangeRanges, string>` — mirrors the Python field map.
- `parseChangeRangesRow(row)`: applies the field map and replaces `NaN` / `Infinity` with `null`.
- Constants: `NSE_BASE_URL`, `NSE_HEADERS`, `NSE_MAX_SYMBOLS_PER_REQUEST = 50`, `CHANGE_RANGES_TTL_SECONDS = 300`, `SYMBOL_DATA_TTL_SECONDS = 60`.

`oneDayPercent` is included in the `ChangeRanges` interface and the field map key set, but mapped to `''` (NSE's `getYearwiseData` does not return a one-day field) — the route sets it to `null` on the wire.

### 3.2 `src/lib/nseThrottle.ts`

TypeScript port of `backend/app/services/nse_rate_limiter.py:88-261` with full `CLOSED → OPEN → HALF_OPEN → CLOSED` parity.

Exports:
- `class NSEServiceUnavailableError extends Error`
- `function throttledNseCall<T>(endpointName, fn, opts?): Promise<T>`
- `function getCircuitStats(): Record<string, { open, halfOpen, failures, openedAt }>` (for debugging)

Module-level state (per-process, mirrors Python):
- `nseSemaphore: Semaphore` — global NSE concurrency cap, default 2.
- `endpointLocks: Map<string, Promise<void>>` + `getOrCreateSerialPromise(key)` — per-endpoint courtesy delay. The function recurses on the previous tail (instead of holding a single long-lived lock), so a new request that arrives after a previous settles doesn't deadlock.
- `inflight: Map<string, Promise<unknown>>` — request coalescing (identical to Python's `_inflight`).
- `CONSECUTIVE_FAILURES`, `CIRCUIT_OPEN`, `CIRCUIT_OPENED_AT`, `CIRCUIT_HALF_OPEN` — circuit-breaker state, identical semantics to Python (`_record_success`, `_record_failure`, half-open probe on `CIRCUIT_RESET_TIMEOUT`).

Env vars consumed at module load:
```
NSE_CONCURRENCY          = 2
NSE_COURTESY_DELAY       = 1.5
NSE_CIRCUIT_FAIL_MAX     = 5
NSE_CIRCUIT_RESET_TIMEOUT= 60.0
NSE_MAX_RETRIES          = 2
NSE_RETRY_BACKOFF        = 1.0
```

Retriable errors: `TypeError` (fetch network failures), `AbortError`, `DOMException` with `name === "TimeoutError"`. Non-retriable: HTTP 4xx / 5xx (caller goes straight to fallback).

### 3.3 `src/lib/nseFetch.ts`

`MarketDataService` singleton (replaces the old `MarketWebSocketService`). Same public surface so consumers didn't change:

```ts
class MarketDataService {
  public requestChangeRanges(symbols: string[]): void;
  public requestSymbolData(symbols: string[]): void;
  public onChangeRanges(handler): () => void;
  public onSymbolData(handler): () => void;
  public onConnectionChange(handler): () => void;  // always emits true once
  public get isConnected(): boolean;                // always true
}
export const marketDataService = MarketDataService.getInstance();
```

Implementation:
- 50 ms debounce timers (`DEBOUNCE_MS = 50`).
- In-memory client-side TTL caches (5 min / 1 min, mirroring server-side TTLs).
- `flushChangeRanges()` / `flushSymbolData()` build `?symbols=...` and call `fetch('/api/nse/...')`. On HTTP error or non-2xx, the listener is invoked with `null` for each requested symbol.
- `onConnectionChange` emits `true` once on first subscription (queued via `queueMicrotask`); `isConnected` getter returns `true` unconditionally.

Removed from the old `marketWs.ts`:
`WebSocket` field, `connect()`, `openSocket()`, `scheduleReconnect()`, `handleMessage()`, `send()`, `fetchWsUrl()`, `localhostFallback()`, `isAuthenticated`, `reconnectAttempts`, the `/api/py/ws-config` call.

### 3.4 `src/app/api/nse/change-ranges/route.ts` (new)

```ts
export const dynamic = 'force-dynamic';
export const runtime  = 'nodejs';
```

Algorithm:
1. Parse `?symbols=` (CSV → array). Trim, upper-case, drop empty, dedupe, clamp to `NSE_MAX_SYMBOLS_PER_REQUEST`.
2. For each symbol: `cache.get('change-ranges:' + sym)` on hit, else `throttledNseCall('change-ranges', () => fetchNseChangeRanges(sym))`, cache the result on success.
3. On any throwable (including `NSEServiceUnavailableError` from a tripped breaker), call `fetchChangeRangesFromPython(sym)` for **that symbol only**.
4. Return `NextResponse.json({ data: Record<symbol, ChangeRanges | null> })` with status `200` — even if every symbol is `null`. **A `502` is not returned** (see §5).

`fetchNseChangeRanges(sym)`:
- URL: `https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getYearwiseData&symbol=${sym}EQN`.
- `NSE_HEADERS`, `AbortSignal.timeout(15000)`.
- Validate the payload is a non-empty list, apply `parseChangeRangesRow` to the first row.

Python fallback:
- `GET ${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=${encodeURIComponent(sym)}`.
- Headers: `Accept: application/json` only. No marker.
- `AbortSignal.timeout(10000)`.

### 3.5 `src/app/api/nse/symbol-data/route.ts` (new)

Identical structure to §3.4 with:
- URL: `…?functionName=getSymbolData&marketType=N&series=EQ&symbol=${sym}`.
- TTL: `SYMBOL_DATA_TTL_SECONDS` (60).
- Response mapper: `extractSymbolData()` from `nseTypes.ts`.

### 3.6 `backend/app/services/market_data.py` (new)

Shared module replacing the per-symbol logic that previously lived in `market_ws.py`. Public API:

```py
async def fetch_change_ranges_batch(symbols: list[str]) -> dict[str, object]: ...
async def fetch_symbol_data_batch(symbols: list[str])     -> dict[str, object]: ...
```

Internals:
- `clean_nan(obj)` — recursively replaces NaN/Inf with `None` for JSON safety.
- `_fetch_change_ranges_for_symbol()` / `_fetch_symbol_data_for_symbol()` — the per-symbol fetchers. Cache lookup, `throttled_nse_call`, store in `nse_cache`, log + return `None` on failure.
- `bounded_change_ranges()` / `bounded_symbol_data()` — wraps the per-symbol fetcher in `asyncio.Semaphore(10)`.
- `fetch_change_ranges_batch()` / `fetch_symbol_data_batch()` — clamp to `_MAX_SYMBOLS_PER_REQUEST = 50`, drop empty/None entries, gather concurrently, return `{sym: value | null}`.

Module-level setup selects the sync vs async NSE client once at import time based on `USE_ASYNC_NSE`, matching the old `market_ws.py` behaviour.

### 3.7 `backend/app/routers/markets.py` (extended)

Added two REST routes used by the Next.js proxy as a per-symbol fallback:

```py
@router.get("/change-ranges")
async def get_change_ranges(
    symbol: list[str] = Query(default_factory=list, description="NSE symbol (repeatable)"),
) -> dict:
    data = await fetch_change_ranges_batch([s.upper() for s in symbol])
    return {"data": data}

@router.get("/symbol-data")
async def get_symbol_data(
    symbol: list[str] = Query(default_factory=list, description="NSE symbol (repeatable)"),
) -> dict:
    data = await fetch_symbol_data_batch([s.upper() for s in symbol])
    return {"data": data}
```

The 50-symbol clamp is enforced inside `fetch_*_batch()`, not at the route level. The response envelope `{data: ...}` is the same as the Next route's envelope, so the Next→Python fallback is a straight pass-through.

### 3.8 `backend/app/routers/market_ws.py` (modified)

Reduced to thin handlers:
- `_handle_get_change_ranges()` validates the input and calls `fetch_change_ranges_batch(symbols)`, then sends the response.
- `_handle_get_symbol_data()` does the same with `fetch_symbol_data_batch()`.
- `MarketConnectionManager` and the `@router.websocket("/market")` handler are unchanged.
- The 60-line block of `USE_ASYNC_NSE` setup, `_bounded_*`, `_clean_nan`, `_fetch_*_for_symbol` is gone.

No behavioural change for the WS path; the AI / MCP server continues to work via the same WebSocket protocol.

### 3.9 Frontend import-site updates

| File | Lines | Change |
|---|---|---|
| `src/components/widgets/WatchWidget.tsx` | 17, 18 | `from '@/lib/marketWs'` → `from '@/lib/nseFetch'` / `from '@/lib/nseTypes'`; `marketWsService` → `marketDataService` |
| `src/components/widgets/WatchWidget.tsx` | 421, 438, 480, 481, 485, 488 | `marketWsService` → `marketDataService` |
| `src/components/widgets/MoversWidget.tsx` | 12, 13, 118, 124, 148, 154 | Same |
| `src/components/TerminalContainer.tsx` | 23, 81 | Same; behaviour preserved (always emits `true`) |

`tickDataAtom` in `src/store/terminalStore.ts:261` was not modified — `WatchWidget.tsx:442-445` is still its only writer, and `PosWidget.tsx:82` still reads from it.

### 3.10 `backend/tests/test_market_data_routes.py` (new)

6 unit tests, with an autouse fixture that clears `nse_cache` between tests so stubbed client methods aren't masked by previous test runs:

- `test_fetch_change_ranges_batch_returns_mapping`
- `test_fetch_change_ranges_batch_handles_failure` (NSE raises → `None`)
- `test_fetch_change_ranges_batch_empty` (empty / `None` input → `{}`)
- `test_fetch_symbol_data_batch_returns_mapping`
- `test_fetch_symbol_data_batch_handles_failure`
- `test_change_ranges_cache_hit` (verifies the second call within TTL is served from `nse_cache`)

The tests monkeypatch the `get_change_ranges` / `get_symbol_data` attributes on `market_data._active_client` (the client object is bound at import time, so re-patching the module attribute wouldn't affect the `partial(...)` already captured inside the helper).

---

## 4. Cache & throttle contract (parity with Python)

| Knob | Python today | Next after |
|---|---|---|
| Cache TTL change-ranges | 300 s (route) inside 600 s global `nse_cache` | 300 s in-process |
| Cache TTL symbol-data | 60 s (route) inside 600 s global `nse_cache` | 60 s in-process |
| Concurrency | 2 (`NSE_CONCURRENCY`) | 2 |
| Courtesy delay | 1.5 s per endpoint key | 1.5 s per endpoint key |
| In-flight coalescing | yes | yes |
| Circuit breaker | full CLOSED/OPEN/HALF_OPEN | **full parity** |
| Retries | 2 with 1.0 / 2.0 / 4.0 s backoff | same |
| Cache size cap | `TTLCache(maxsize=200)` | unbounded `Map` (single Next process) |

The Next TTLs (300 / 60 s) match Python's route-specific TTLs (`market_ws.py:43-44`), not the global `nse_cache` 600 s — more conservative for NSE; flagged in the PR.

---

## 5. Failure semantics — actual behaviour

| NSE | Python | Per-symbol result | Whole-request status |
|---|---|---|---|
| ok | — | value | 200 |
| fail | ok | Python value | 200 |
| fail | fail | `null` | **200** |
| network down | network down | `null` for each | **200** (not 502) |
| circuit open on Next | ok | Python value | 200 |

**Implementation note:** the original plan called for `502 { error: 'Both NSE and Python backend unavailable' }` when both upstreams were unreachable. The actual implementation returns **`200` with `null` values for each failed symbol** instead. This matches the per-symbol `null` contract used everywhere else in this code path and avoids surfacing a global 5xx for what is fundamentally a partial-failure situation. The frontend's `changeRangesReceived` / `symbolDataReceived` sets and the `isLoading` derivation in `WatchWidget.tsx:554-555` continue to work unchanged.

The `null`-on-failure semantics match the current contract (`market_ws.py:113-114, 134-135`).

---

## 6. Configuration / environment

| Variable | Scope | Default | Notes |
|---|---|---|---|
| `PYTHON_BACKEND_URL` | Next | `http://localhost:4455` | Already used by `/api/py/[...path]/route.ts:20` |
| `NSE_CONCURRENCY` | `nseThrottle.ts` | `2` | New, mirrors Python |
| `NSE_COURTESY_DELAY` | `nseThrottle.ts` | `1.5` | New |
| `NSE_CIRCUIT_FAIL_MAX` | `nseThrottle.ts` | `5` | New |
| `NSE_CIRCUIT_RESET_TIMEOUT` | `nseThrottle.ts` | `60.0` | New |
| `NSE_MAX_RETRIES` | `nseThrottle.ts` | `2` | New |
| `NSE_RETRY_BACKOFF` | `nseThrottle.ts` | `1.0` | New |
| `NSE_CONCURRENCY` etc. | Python `nse_rate_limiter.py` | unchanged | Already env-driven |

No new env vars required for the Python side.

---

## 7. Verification — what was actually run

| Step | Command | Result |
|---|---|---|
| New backend unit tests | `.venv/bin/pytest tests/test_market_data_routes.py -v` | **6 passed** |
| Rate-limiter tests (regression) | `.venv/bin/pytest tests/test_rate_limiter_consolidation.py` | **9 passed** |
| Wider backend suite | `.venv/bin/pytest tests/ -m "not slow" --ignore=tests/test_endpoints.py --ignore=tests/test_mcp.py` | 1106 passed; 28 pre-existing failures (`tests/test_notifications.py` and `tests/test_runtime_split.py` — both fail with `unable to open database file` because the test DB directory is not pre-created; unrelated to this refactor) |
| Frontend build + tests | `npm run build` | **Succeeded**; both new routes registered (`/api/nse/change-ranges`, `/api/nse/symbol-data`); 128 unit tests passed |
| TypeScript check | `npx tsc --noEmit` | Zero errors in any new or modified file (6 pre-existing errors in unrelated files: Jotai `WritableAtom` arity, validator cache, `panelId` prop) |
| Lint | `npm run lint` | Zero issues in new or modified files (50 pre-existing errors in unrelated files) |

**Manual smoke in dev** has not been performed yet (no dev server was running in this session). Recommended before merging:
- Open Watch panel → Network tab: confirm `/api/nse/change-ranges` and `/api/nse/symbol-data` are called; **no** `/api/py/ws-config` call; **no** `ws://…/ws/market` connection.
- 1W / 1M / 3M / 6M / 1Y / 2Y / 3Y / 5Y columns populate identically.
- 52W HIGH / 52W LOW columns populate identically.
- LTP flash (`WatchWidget.tsx:447-469`) still triggers.
- `PosWidget.tsx:82` `tickDataAtom` LTP lookup still works.
- Movers panel: 1w / 1m / 3m / 6m / 1y / 2y / 3y / 5y / 52wh / 52wl columns populate.
- Fallback smoke: `NSE_CIRCUIT_FAIL_MAX=1`, point NSE to an unreachable host, confirm the Next route returns Python-backed results within ~2 s.
- AI / MCP regression: exercise the AI chat flow that uses `get_change_ranges` / `get_symbol_data` (`ai_chat_service.py:744, 754`).

---

## 8. Risks & watch-outs (as built)

- **Multi-process Next deployments** — per-process cache + breaker means two replicas could each fire the same NSE request. Acceptable today (Python has the same characteristic per `cache.py:1-7` comment), flagged for the future.
- **Symbol series** — `series=EQ` is hardcoded in the symbol-data URL (`src/app/api/nse/symbol-data/route.ts`). Some symbols (BE / ST / SM) live in other series. The previous WS didn't handle that either; this refactor preserves the existing behaviour. Out of scope to fix.
- **`isConnected` semantics — realised as predicted.** `TerminalContainer.tsx:81` still calls `marketDataService.onConnectionChange((connected) => setWsConnected(connected))`, which now always fires `true`. The `wsConnected` indicator (`terminalStore.ts`, `wsConnectedAtom`) is therefore decorative. Future cleanup: drop the subscription and the atom, or relabel the indicator.
- **Edge runtime** — explicitly chose `runtime = 'nodejs'`. The 1.5 s courtesy delay, request coalescing, and circuit breaker timers all assume a long-lived Node process; edge has a 25 ms `waitUntil` and 30 s wall clock ceiling that would break them.
- **News socket** — `src/lib/newsSocket.ts:85` is unrelated and still uses `/api/py/ws-config`. Left alone.
- **502 dropped from the failure surface** — see §5; the route now returns 200 with `null` values rather than 5xx.
- **`oneDayPercent` is always `null`** — `getYearwiseData` doesn't return a one-day field; the field is kept in the `ChangeRanges` interface for back-compat with the frontend's `WatchRowData` (`WatchWidget.tsx:38`).

---

## 9. Implementation order — what was done

1. ✅ Added `src/lib/nseTypes.ts`.
2. ✅ Added `src/lib/nseThrottle.ts` (full port of `nse_rate_limiter.py:88-261`).
3. ✅ Added `src/lib/nseFetch.ts` (HTTP transport, public surface unchanged).
4. ✅ Updated the 4 import sites (WatchWidget, MoversWidget, TerminalContainer).
5. ✅ Deleted `src/lib/marketWs.ts`.
6. ✅ Added `src/app/api/nse/change-ranges/route.ts` and `src/app/api/nse/symbol-data/route.ts`.
7. ✅ Extracted shared helpers into `backend/app/services/market_data.py`; `market_ws.py` delegates to it.
8. ✅ Added the two REST fallback routes in `backend/app/routers/markets.py`.
9. ✅ Added `backend/tests/test_market_data_routes.py`; ran `pytest`, `npm run build`, `npm run lint`, `npx tsc --noEmit`.
10. ⏳ Manual smoke in dev — pending. Recommended before merge.

---

## 10. Out of scope (explicitly)

- Morningstar fair-value `useQueries` (`WatchWidget.tsx:500-513`).
- Notifications count `useQuery` (`WatchWidget.tsx:517-529`).
- Migrating AI / MCP server toolset (`ai_chat_service.py:744-789`) — stays on Python.
- Migrating any other NSE endpoint to the Next proxy.
- Multi-process cache sharing for Next.js.
- Hardcoded `series=EQ` symbol-series bug.

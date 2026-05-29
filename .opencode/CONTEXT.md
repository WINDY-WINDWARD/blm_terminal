# CONTEXT.md — Decisions, Rationale & Implementation Details

**Project:** blm_terminal — Live Charting System  
**Last updated:** 2026-05-28

---

## Decision Log

### D1 — Remove OpenAlgo WebSocket entirely (not just disable)

**Decision:** Delete `src/lib/socket.ts` and all references. No fallback, no feature flag.

**Rationale:**
- OpenAlgo WS (`ws://localhost:8765`) is an external dependency not controlled by this project
- It has a CORS problem when the frontend is not on the same machine
- The WS was being used for two purposes: (a) LTP ticks → these are now covered by `marketWs.ts` which connects to the *backend* (`/ws/market`), a service we control; (b) partial intraday candles → NSE has no streaming, so polling replaces this
- Keeping a disabled WS would add confusion and dead code
- `marketWs.ts` already existed and was already used by WatchWidget for symbol data; it just needs to also drive `tickDataAtom` for OrderWidget/PosWidget

### D2 — Poll NSE charting API (backend) instead of streaming

**Decision:** 60s `useQuery` poll for `1h`/`D`, 5min for `W`/`M` during market hours.

**Rationale:**
- NSE charting API (`charting.nseindia.com`) has no WebSocket — it is purely HTTP
- Polling at 60s is sufficient for chart updates (candles are 60-min bars; intra-candle precision not needed)
- Backend acts as a CORS proxy (browser cannot call `charting.nseindia.com` directly due to CORS)
- The existing `/api/py/[...path]` Next.js catch-all proxy route already handles forwarding to Python backend, so no new Next.js API route is needed

### D3 — Store 1h/W/M in a separate table (`ticker_intraday`), not `ticker_daily`

**Decision:** New `ticker_intraday` table with `interval` column.

**Rationale:**
- `ticker_daily` schema assumes `Date` type as the time column and includes `series`, `value`, and technical indicator columns not relevant to intraday/weekly/monthly data
- An `interval` discriminator column on `ticker_intraday` lets us store all three frequencies in one table without multiple tables, while keeping daily separate and clean
- `timestamp` (DateTime UTC) is used instead of `Date` because `1h` candles require time-of-day precision

### D4 — History depth: 90 days for 1h, all history for W/M

**Decision:** `1h` backfill uses `fromDate = now - 90 days`. `W` and `M` use `fromDate = 0`.

**Rationale:**
- 90 days of hourly candles ≈ ~1080 candles — sufficient for chart display and reasonably fast to fetch
- W/M candles are infrequent (52/year for W, 12/year for M) so "all history" is fast and gives the user maximum chart history
- Fetching more than 90 days of 1h data would be slow and the extra data has diminishing value for typical chart analysis

### D5 — Skip 30m interval

**Decision:** 30m interval (chartType=`I`, timeInterval=`30`) not implemented — not shown in toolbar.

**Rationale:** User confirmed this explicitly. Current toolbar design: `1m*(soon)`, `5m*(soon)`, `15m*(soon)`, `1h`, `D`, `W`, `M`. Adding 30m would complicate the UI without clear user demand.

### D6 — Backend market-hours detection for live vs. cache serving

**Decision:** Endpoint checks IST 09:15–15:30 weekdays to decide whether to hit NSE or serve from DB.

**Rationale:**
- During market hours, NSE charting API has the latest partial candle data — always fetch live
- Outside market hours, NSE may return the same data as the DB, and unnecessary polling adds latency and rate-limit risk
- The check is purely time-based (no holiday calendar) — this is acceptable because if today is a holiday NSE will return the same data as yesterday's close, and the DB upsert is idempotent

### D7 — Scripcode caching in memory (module-level dict)

**Decision:** `nse_charting_client.py` maintains a `_scripcode_cache: dict[str, str]` module-level dict.

**Rationale:**
- Scripcode (NSE internal token) never changes for a given symbol
- Avoids an extra HTTP round-trip on every candle fetch
- Cache is warm within a worker process; across restarts it rebuilds lazily (one extra call per symbol per startup, acceptable)
- No DB persistence needed for a lookup that takes <100ms to rebuild

### D8 — Wire connection status through marketWs, not a separate atom

**Decision:** `TerminalContainer` calls `marketWs.onConnectionChange(setWsConnected)` instead of `wsService.onConnectionChange`.

**Rationale:**
- `wsConnectedAtom` is already the correct abstraction — just needs to be fed by `marketWs` instead of `wsService`
- `marketWs` already has `onConnectionChange` support
- No new atoms, no store changes beyond removing the socket import

### D9 — LiveTicker uses movers query data (not tickDataAtom)

**Decision:** `LiveTicker.tsx` drops WS subscription entirely and renders from the existing movers query (gainers/losers 60s poll).

**Rationale:**
- LiveTicker already fetches top gainers/losers every 60s and renders them in a scrolling ticker
- It was additionally subscribing to WS ticks to update individual LTP values in real-time
- Removing this makes LiveTicker simpler, fully self-contained, and consistent with its data source
- 60s staleness is acceptable for a scrolling news-ticker-style display

### D10 — WatchWidget re-requests marketWs data every 30s

**Decision:** `setInterval` in WatchWidget `useEffect` calls `marketWs.requestSymbolData(symbols)` every 30s.

**Rationale:**
- `marketWs` has a server-side TTL of 60s for cached symbol data
- Re-requesting at 30s ensures data is never more than ~30s stale
- Simple and avoids any complex cache invalidation logic

---

## Implementation Details

### `nse_charting_client.py` — Key Design Points

```python
BASE_URL = "https://charting.nseindia.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    "Referer": "https://charting.nseindia.com/?symbol={symbol}-EQ",
}

_scripcode_cache: dict[str, str] = {}

async def get_scripcode(symbol: str) -> str:
    # uses httpx.AsyncClient, caches result
    # symbol passed as "{SYMBOL}-EQ"

async def fetch_candles(
    symbol: str,
    chart_type: str,      # "I", "D", "W", "M"
    time_interval: str,   # "1", "5", "15", "60"
    from_ts: int = 0,     # unix seconds (0 = all history)
    to_ts: int | None = None,   # defaults to now()
) -> list[dict]:
    # returns [{"time_ms": int, "open": float, ...}]
    # 1s sleep between calls to avoid rate limiting
```

### `ticker_warehouse.py` — New Functions

```python
def upsert_intraday(
    symbol: str,
    interval: str,   # "1h", "W", "M"
    rows: list[dict],  # [{"time_ms", "open", "high", "low", "close", "volume"}]
    db: Session,
) -> int:
    # INSERT OR REPLACE into ticker_intraday
    # returns number of rows upserted

def get_intraday(
    symbol: str,
    interval: str,
    from_ts: int | None = None,  # unix ms
    to_ts: int | None = None,    # unix ms
    db: Session,
) -> list[dict]:
    # returns rows from ticker_intraday as dicts with "timestamp" in unix ms

def backfill_intraday_symbol(
    symbol: str,
    intervals: list[str] = ["1h", "W", "M"],
    db: Session,
) -> dict[str, int]:
    # calls nse_charting_client for each interval
    # returns {"1h": N, "W": N, "M": N}
```

### `ticker.py` router — New Endpoint

```python
class IntradayCandleRow(BaseModel):
    timestamp: int   # unix milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: int

class IntradayOHLCVResponse(BaseModel):
    symbol: str
    interval: str
    candles: list[IntradayCandleRow]
    count: int

@router.get("/intraday/{symbol}", response_model=IntradayOHLCVResponse)
async def get_intraday(
    symbol: str,
    interval: str = Query(..., regex="^(1h|W|M)$"),
    from_ts: int | None = None,
    to_ts: int | None = None,
    db: AsyncSession = Depends(get_async_db),
) -> IntradayOHLCVResponse:
    # if is_market_hours(): fetch fresh from NSE → upsert → return
    # else: return from DB
```

### `backgroundtasks.py` — Worker Pattern

```python
def _ticker_intraday_update_sync():
    """Called in a thread. Loops all watchlist symbols and backfills intraday candles."""
    with _SyncSessionLocal() as db:
        symbols = get_watchlist_symbols(db)
    for sym in symbols:
        try:
            counts = asyncio.run(backfill_intraday_symbol(sym, ["1h","W","M"]))
            logger.info(f"[intraday] {sym}: {counts}")
        except Exception as e:
            logger.warning(f"[intraday] {sym} failed: {e}")
        time.sleep(1.0)

async def ticker_intraday_update_worker():
    """Cron: hourly 4–8 PM IST weekdays. Also runs once at startup."""
    # first_run pattern (same as ticker_daily_update_worker)
    # cron: "0 16,17,18,19,20 * * 1-5"
```

### `ChartWidget.tsx` — Structural Change Summary

**Removed:**
- `import { wsService, TickData } from '@/lib/socket'`
- `partialCandleRef`, `lastCumulativeVolumeRef`
- `handleTick` useCallback
- WS subscribe/unsubscribe useEffect (the one calling `wsService.subscribe`)
- `getCandlePeriodSeconds()`, `alignToCandle()` helper functions
- `lastHistBarTimeRef` usage in tick context (was the bug source)

**Added:**
- `type Interval = '1m' | '5m' | '15m' | '1h' | 'D' | 'W' | 'M'`
- `INTRADAY_INTERVALS = ['1h', 'W', 'M']`
- `COMING_SOON_INTERVALS = ['1m', '5m', '15m']`
- `fetchIntradayOHLCV(symbol, interval)` → calls `/api/py/ticker/intraday/{symbol}?interval=...`
- `isMarketHours()` helper using IST timezone check
- Second `useQuery` for intraday: `queryKey: ['intraday-ohlcv', symbol, interval]`
- `refetchInterval` on daily query: `isMarketHours() ? 60_000 : false`
- `useEffect` to render intraday bars: maps `candle.timestamp / 1000` → lightweight-charts `Time`
- "Coming soon" overlay shown when `COMING_SOON_INTERVALS.includes(activeInterval)`

## Implementation Notes (Deviations from Plan)

### `marketWs` export name
The plan referenced `marketWs` but the actual export in `marketWs.ts` is `marketWsService`. All files use `marketWsService` accordingly.

### `TerminalContainer.tsx` — no `connect()` call needed
The plan mentioned wiring `marketWs.onConnectionChange`. In practice `marketWsService` auto-connects when the first subscriber registers, so no explicit `.connect()` call is needed — just registering the `onConnectionChange` handler is sufficient.

### `WatchWidget.tsx` — `onSymbolData` already existed
The existing `onSymbolData` handler (lines 440–472) already handled flash states. Rather than replacing it, we extended it to also feed `tickDataAtom` from within the same callback, keeping the flash logic intact.

### `LiveTicker.tsx` — fully simplified
Removed `tickDataAtom` dependency entirely. The component now only uses `useQuery` for movers — no WS, no atom. The `useAtom` import was removed.

### `ChartWidget.tsx` — `isMarketHours()` uses UTC arithmetic
No `pytz` or timezone library available in the browser. IST is UTC+5:30, so we offset `Date.now()` by `5.5 * 60 * 60 * 1000` ms and check the resulting UTC fields.

### Alembic migration revision chain
The last migration's `revision` ID was `x123456789abk` (inside `zzzzzzzzzzzz_seed_notif_system_config_defaults.py` — filename ≠ revision ID). The new migration `add_ticker_intraday.py` uses `down_revision = "x123456789abk"`.

### Job key for intraday worker
Job key: `"job.ticker_intraday_update"` — matches the `_is_job_enabled` / `update_job_status_sync` pattern used by all other workers.

---

| File | Line(s) | Notes |
|------|---------|-------|
| `ChartWidget.tsx` | 262 | Pre-existing bug: `lastHistBarTimeRef.current ?? candleTime` — fixed by removal |
| `WatchWidget.tsx` | 748–790 | Two `useEffect` blocks for WS subscribe/tick — to be replaced |
| `terminalStore.ts` | top | `import type { TickData } from '@/lib/socket'` — to be replaced with local type |
| `TerminalContainer.tsx` | ~50–80 | `wsService.connect/disconnect/onConnectionChange` — to be replaced |
| `socket.ts` | entire file | ~200 lines — deleted |
| `backgroundtasks.py` | `start_all_workers()` | New worker registered here |

---

## What Was NOT Changed and Why

| File | Decision |
|------|---------|
| `src/lib/marketWs.ts` | Already correct. Extended usage (more callers) but no code changes |
| `backend/app/routers/market_ws.py` | Backend WS router works fine as-is |
| `OrderWidget.tsx`, `PosWidget.tsx` | Only consume `tickDataAtom.ltp` — no direct WS coupling |
| `ticker_daily` table + daily functions | Separate concern — daily bhavcopy pipeline untouched |
| Next.js `/api/py/[...path]/route.ts` | Already proxies to Python backend — no new proxy routes needed |

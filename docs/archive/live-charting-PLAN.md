> **ARCHIVED** — This document describes a completed implementation. It is kept for historical reference only and is no longer maintained.

---

# Live Charting System — Complete Implementation Plan

**Project:** `blm_terminal`  
**Date:** 2026-05-28  
**Status:** Implementation complete — all 15 tasks done, V1–V5 verified ✅

---

## 1. Goal Summary

Replace the OpenAlgo WebSocket (`socket.ts`) with a fully backend-proxied, NSE-native live charting pipeline. Add `1h`, `W`, and `M` candle support stored in SQLite. Fix a pre-existing bug where today's daily candle gets painted on yesterday's bar.

---

## 2. Current Architecture (Before)

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                               │
│                                                              │
│  ChartWidget ──────────────────────────────────────────┐    │
│  WatchWidget ──── tickDataAtom ──── OrderWidget         │    │
│  LiveTicker  ──────────────────── PosWidget             │    │
│  TerminalContainer                                      │    │
│       │                         │                       │    │
│       ▼                         ▼                       │    │
│   socket.ts               marketWs.ts                   │    │
│  (OpenAlgo WS)         (backend /ws/market)             │    │
│   ws://localhost:8765                                   │    │
│       │                                                 │    │
└───────┼─────────────────────────────────────────────────────┘
        │
        ▼
  OpenAlgo Server                     ┌──────────────────────┐
  (external, port 8765)               │  Python Backend       │
                                      │  FastAPI :4455        │
                                      │                       │
                                      │  /ws/market           │
                                      │  /api/ticker/ohlcv    │
                                      │  (daily data only)    │
                                      └──────────────────────┘
```

**Problems:**
- `socket.ts` connects to OpenAlgo on `ws://localhost:8765` — CORS issues, external dependency
- ChartWidget uses WS ticks to paint partial intraday candles → today's candle paints on yesterday's timestamp (bug at `ChartWidget.tsx:262`)
- No `1h`, `W`, `M` interval data — only daily via bhavcopy
- `LiveTicker` uses WS ticks for LTP display

---

## 3. Target Architecture (After)

```
┌─────────────────────────────────────────────────────────────────┐
│                          Browser                                 │
│                                                                  │
│  ChartWidget ──── useQuery ──── /api/py/ticker/intraday/{sym}   │
│                  (60s poll)     (1h/W/M intervals)              │
│                                                                  │
│  ChartWidget ──── useQuery ──── /api/py/ticker/ohlcv/{sym}      │
│  (D interval)    (60s poll)     (daily candles, existing)        │
│                                                                  │
│  WatchWidget ─────────────────────────────────────────────────┐ │
│  LiveTicker  ── existing movers query (60s poll)              │ │
│  TerminalContainer                                            │ │
│       │                                                       │ │
│       ▼                                                       │ │
│   marketWs.ts ─────────────────────────────────────────────┘ │ │
│  (backend /ws/market)         tickDataAtom                     │ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌──────────────────────────────────┐
        │       Python Backend :4455        │
        │                                  │
        │  /ws/market                      │
        │  /ticker/ohlcv/{sym}    (daily)  │
        │  /ticker/intraday/{sym} (NEW)    │
        │                                  │
        │  nse_charting_client.py (NEW)    │
        │    → NSE Charting API            │
        │      charting.nseindia.com       │
        │                                  │
        │  ticker_intraday table  (NEW)    │
        │  (SQLite via SQLAlchemy)         │
        └──────────────────────────────────┘
```

---

## 4. NSE Charting API Reference

**Base URL:** `https://charting.nseindia.com`

### Step 1 — Resolve symbol to scripcode (token)

```
GET /v1/exchanges/symbolsDynamic?symbol=APOLLOHOSP-EQ&segment=

Response:
{
  "status": true,
  "data": [
    {
      "scripcode": "157",
      "symbol": "APOLLOHOSP-EQ",
      "instrumentType": "1"
    }
  ]
}
```

- Symbol format: `{NSE_SYMBOL}-EQ` (e.g., `RELIANCE-EQ`)
- Scripcode is cached in memory — never changes for a given symbol
- Required headers: `Referer: https://charting.nseindia.com/?symbol=SYMBOL-EQ`

### Step 2 — Fetch candles

```
GET /v1/charts/symbolHistoricalData
  ?token=<scripcode>
  &fromDate=<unix_seconds>    (0 = fetch all history)
  &toDate=<unix_seconds>
  &symbol=<SYMBOL-EQ>
  &symbolType=Equity
  &chartType=<I|D|W|M>
  &timeInterval=<1|5|15|30|60|1>

Response:
{
  "status": true,
  "data": [
    { "time": 1748329800000, "open": 6832.15, "high": 6842.0, "low": 6780.0, "close": 6805.3, "volume": 123456 },
    ...
  ]
}
```

### Interval → Parameter Mapping

| UI Interval | chartType | timeInterval | History Depth   |
|-------------|-----------|--------------|-----------------|
| `1m`        | `I`       | `1`          | (coming soon)   |
| `5m`        | `I`       | `5`          | (coming soon)   |
| `15m`       | `I`       | `15`         | (coming soon)   |
| `1h`        | `I`       | `60`         | 90 days         |
| `D`         | `D`       | `1`          | existing daily  |
| `W`         | `W`       | `1`          | all history     |
| `M`         | `M`       | `1`          | all history     |

### Required HTTP Headers

```
Referer: https://charting.nseindia.com/?symbol=SYMBOL-EQ
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...
```

No cookies or auth tokens required.

---

## 5. Database Schema — New Table

```sql
CREATE TABLE ticker_intraday (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       VARCHAR(32)  NOT NULL,
    timestamp    DATETIME     NOT NULL,   -- UTC, stored as integer seconds
    interval     VARCHAR(4)   NOT NULL,   -- "1h", "W", "M"
    open         FLOAT        NOT NULL,
    high         FLOAT        NOT NULL,
    low          FLOAT        NOT NULL,
    close        FLOAT        NOT NULL,
    volume       BIGINT       NOT NULL,
    source       VARCHAR(32)  NOT NULL DEFAULT 'nse_charting',
    created_at   DATETIME     NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE (symbol, timestamp, interval)
);
CREATE INDEX ix_ticker_intraday_symbol   ON ticker_intraday(symbol);
CREATE INDEX ix_ticker_intraday_timestamp ON ticker_intraday(timestamp);
```

---

## 6. Data Flow Diagrams

### 6a. Backfill Flow (background worker, post market close)

```
ticker_intraday_update_worker()
  cron: "0 16,17,18,19,20 * * 1-5" (4–8 PM IST weekdays)
  also runs once at startup
       │
       ▼
  get watchlist symbols from DB
       │
       ├── for each symbol (1s delay between)
       │        │
       │        ▼
       │   backfill_intraday_symbol(symbol, ["1h", "W", "M"])
       │        │
       │        ├── 1h: fromDate = now - 90 days (unix seconds)
       │        ├── W:  fromDate = 0 (all history)
       │        └── M:  fromDate = 0 (all history)
       │             │
       │             ▼
       │        nse_charting_client.fetch_candles()
       │             │
       │             ├── get_scripcode(symbol)  [cached]
       │             └── GET /v1/charts/symbolHistoricalData
       │                      │
       │                      ▼
       │             upsert_intraday(symbol, interval, rows)
       │             → INSERT OR REPLACE into ticker_intraday
       │
       └── log summary: {symbol: {1h: N, W: N, M: N}}
```

### 6b. Live Chart Polling Flow (browser, during market hours)

```
ChartWidget (interval = "1h")
  useQuery(["intraday-ohlcv", symbol, "1h"], refetchInterval: 60_000)
       │
       ▼
  GET /api/py/ticker/intraday/RELIANCE?interval=1h&from_ts=...&to_ts=...
       │   (Next.js catch-all proxy)
       ▼
  FastAPI: GET /ticker/intraday/RELIANCE
       │
       ├── is_market_hours()?
       │    ├── YES → nse_charting_client.fetch_candles() → upsert → return rows
       │    └── NO  → return rows from ticker_intraday DB directly
       │
       ▼
  IntradayOHLCVResponse { symbol, interval, candles: [...], count }
       │
       ▼
  ChartWidget renders bars via lightweight-charts
  (timestamps: Unix ms from API ÷ 1000 → lightweight-charts Time)
```

### 6c. LTP Update Flow (WatchWidget → tickDataAtom)

```
WatchWidget mounts / symbols change
       │
       ▼
  marketWs.requestSymbolData(symbols)
  [30s re-request interval]
       │
       ▼
  marketWs.onSymbolData(handler)
  handler fires when backend /ws/market sends symbol_data
       │
       ▼
  setTickData(prev => ({ ...prev, [`${sym}.NSE`]: { ltp, pChange, ... } }))
       │  (updates tickDataAtom via Jotai)
       ▼
  OrderWidget / PosWidget read tickDataAtom[symbol].ltp
  WatchWidget flash animation on price change
```

### 6d. Connection Status Flow

```
TerminalContainer mounts
       │
       ▼
  marketWs.onConnectionChange((connected) => setWsConnected(connected))
       │
       ▼
  wsConnectedAtom  ──→  CommandBar (green/red dot + tooltip "Market Data Connected")
                   ──→  SettingsWidget (text "Market WS: CONNECTED/DISCONNECTED")
```

---

## 7. API Contract

### New Endpoint: `GET /ticker/intraday/{symbol}`

**Query Parameters:**

| Param      | Type    | Required | Description                        |
|------------|---------|----------|------------------------------------|
| `interval` | string  | Yes      | `1h`, `W`, or `M`                  |
| `from_ts`  | integer | No       | Unix milliseconds (start)          |
| `to_ts`    | integer | No       | Unix milliseconds (end, default now)|

**Response:**

```json
{
  "symbol": "RELIANCE",
  "interval": "1h",
  "candles": [
    {
      "timestamp": 1748329800000,
      "open": 1425.50,
      "high": 1438.00,
      "low": 1420.10,
      "close": 1435.25,
      "volume": 523400
    }
  ],
  "count": 1
}
```

**Behaviour:**
- During market hours (IST 09:15–15:30 weekdays): fetches fresh from NSE charting, upserts, returns updated data
- Outside market hours: serves from `ticker_intraday` DB table
- `from_ts` / `to_ts` filter the returned candles (not the fetch — always full backfill then filter)

---

## 8. Implementation Tasks (ordered)

### Backend Phase

| # | File | Action | Description |
|---|------|--------|-------------|
| 1 | `backend/app/models/ticker.py` | Add model | `TickerIntraday` ORM model |
| 2 | `backend/alembic/versions/<new>.py` | New migration | Create `ticker_intraday` table |
| 3 | `backend/app/services/nse_charting_client.py` | New file | NSE charting API client |
| 4 | `backend/app/services/ticker_warehouse.py` | Extend | `upsert_intraday`, `get_intraday`, `backfill_intraday_symbol` |
| 5 | `backend/app/routers/ticker.py` | Add endpoint | `GET /ticker/intraday/{symbol}` |
| 6 | `backend/app/backgroundtasks.py` | Add worker | `ticker_intraday_update_worker` |

### Frontend Phase

| # | File | Action | Description |
|---|------|--------|-------------|
| 7 | `src/lib/socket.ts` | Delete | Remove OpenAlgo WS entirely |
| 8 | `src/__tests__/mocks/wsService.ts` | Delete | Remove WS mock |
| 9 | `src/store/terminalStore.ts` | Edit | Local `TickData` type, drop socket import |
| 10 | `src/components/TerminalContainer.tsx` | Edit | Wire `marketWs.onConnectionChange` |
| 11 | `src/components/widgets/WatchWidget.tsx` | Edit | Replace WS subscription with `marketWs` |
| 12 | `src/components/LiveTicker.tsx` | Edit | Remove WS, use movers query data for LTP |
| 13 | `src/components/CommandBar.tsx` | Edit | Update tooltip text |
| 14 | `src/components/widgets/SettingsWidget.tsx` | Edit | Update label text |
| 15 | `src/components/widgets/ChartWidget.tsx` | Major rewrite | Add 1h/W/M intervals, polling, remove tick handling |

---

## 9. ChartWidget Interval Toolbar

```
[ 1m* ] [ 5m* ] [ 15m* ] [ 1h ] [ D ] [ W ] [ M ]
                                   ↑    ↑    ↑
                              live polling (60s for 1h/D during mkt hrs, 5min for W/M)

* = "coming soon" overlay shown, click disabled
```

---

## 10. Files to Delete

| File | Reason |
|------|--------|
| `src/lib/socket.ts` | OpenAlgo WS — fully replaced by `marketWs.ts` + polling |
| `src/__tests__/mocks/wsService.ts` | Mock for deleted service |

---

## 11. Files NOT Changed

| File | Reason |
|------|--------|
| `src/lib/marketWs.ts` | Already correct — used more widely, not modified |
| `backend/app/routers/market_ws.py` | Backend WS router — no changes needed |
| `src/components/widgets/OrderWidget.tsx` | Only reads `tickDataAtom.ltp` — unaffected |
| `src/components/widgets/PosWidget.tsx` | Only reads `tickDataAtom.ltp` — unaffected |
| `backend/app/services/ticker_warehouse.py` (daily) | Daily OHLCV functions untouched |

---

## 12. Pre-existing Bug Fixed as Side Effect

**Bug:** `ChartWidget.tsx:262` — `const dailyCandleTime = lastHistBarTimeRef.current ?? candleTime`

This causes WS tick candles to be painted using yesterday's bar timestamp (the last historical bar), making today's candle visually overlap yesterday's.

**Fix:** Automatic — by removing all WS tick handling from `ChartWidget`, the entire partial-candle logic disappears. The chart will only show complete candles from the API response. During market hours, the 60s poll naturally updates the current (partial) candle correctly since the NSE charting API returns the current in-progress bar.

---

## 13. Environment Variable Impact

No new environment variables required. Backend calls NSE charting API directly server-side (no CORS). The variable `NEXT_PUBLIC_OPENALGO_WS_URL` becomes unused and can be removed from `.env.local` (not required — just dead config).

---

## 14. Risk & Mitigations

| Risk | Mitigation |
|------|-----------|
| NSE charting API rate limiting | 1s delay between symbol calls in backfill worker |
| Scripcode resolution failure | `get_scripcode` raises `ValueError` — endpoint returns 404, logged |
| Market hours detection wrong timezone | Use `pytz.timezone("Asia/Kolkata")` consistently |
| `W`/`M` fetching all history is slow | Only done in background worker (not in request path) |
| Stale intraday data on first load (before backfill) | Endpoint falls through to NSE live fetch during market hours |

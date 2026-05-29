# Movers Widget

Displays **Top Gainers** and **Top Losers** for NSE equities in a single scrollable panel. Data is polled every 60 seconds via the Python analytics backend, with per-symbol historical change ranges and 52-week extremes enriched in real time over WebSocket.

---

## Data Sources

| Source | Endpoint | Refresh | Purpose |
|---|---|---|---|
| REST (React Query) | `GET /api/py/market/top-gainers?category=<cat>` | 60 s | Top 20 gaining equities |
| REST (React Query) | `GET /api/py/market/top-losers?category=<cat>` | 60 s | Top 20 losing equities |
| REST (React Query) | `GET /api/py/market/movers-categories` | 24 h stale | Category tab list (key + label pairs) |
| WebSocket (`/ws/market`) | `action: get_change_ranges` | 5-min cache | 1W / 1M / 3M / 6M / 1Y / 2Y / 3Y / 5Y % columns |
| WebSocket (`/ws/market`) | `action: get_symbol_data` | 1-min cache | 52W HIGH / 52W LOW columns (only when those columns are active) |

The WebSocket connection is managed by the `marketWsService` singleton (`src/lib/marketWs.ts`). Row subscriptions are batched with a 50 ms debounce so that all rows mounting at the same time emit a single WS message. The connection URL is fetched once from `/api/py/ws-config`.

---

## Category Tabs

Categories are fetched dynamically. The widget maps raw API keys to short display labels:

| API Key | Display Label |
|---|---|
| `allSec` | ALL |
| `NIFTY` | NIFTY50 |
| `BANKNIFTY` | BANKNIFTY |
| `NIFTYNEXT50` | NEXT50 |
| `SecGtr20` | >₹20 |
| `SecLwr20` | <₹20 |
| `FOSec` | F&O |

Unknown keys fall back to the raw `label` from the API (HTML entities are decoded). The active tab is persisted in `moversCategoryAtom` (session storage, per-tab).

**Backend filtering notes:**
- `allSec` additionally filters to `series == "EQ"` (equity series only).
- Each category returns at most 20 rows sorted by `pChange` (descending for gainers, ascending for losers).

---

## Column System

Columns are user-configurable and persisted in `moversColumnsAtom` (session storage).

**Default set:** `close`, `chg`, `1w`, `1m`, `3m`, `6m`, `1y`

| Key | Header | Source | Notes |
|---|---|---|---|
| `close` | CLOSE | REST (`ltp` / `lastPrice`) | Formatted to 2 decimal places |
| `chg` | CHG% | REST (`pChange`) | Bold, green (positive) / red (negative) |
| `open` | OPEN | REST (`open_price`) | |
| `high` | HIGH | REST (`high_price`) | |
| `low` | LOW | REST (`low_price`) | |
| `vol` | VOL | REST (`trade_quantity`) | Indian short format: K / L / Cr |
| `trnvr` | TRNVR | REST (`turnover`) | ₹ in Crores |
| `ca` | CA | REST (`ca_ex_dt`, `ca_purpose`) | Ex-date shown; full purpose in tooltip |
| `1w` | 1W% | WebSocket `change_ranges` | Color-coded |
| `1m` | 1M% | WebSocket `change_ranges` | |
| `3m` | 3M% | WebSocket `change_ranges` | |
| `6m` | 6M% | WebSocket `change_ranges` | |
| `1y` | 1Y% | WebSocket `change_ranges` | |
| `2y` | 2Y% | WebSocket `change_ranges` | |
| `3y` | 3Y% | WebSocket `change_ranges` | |
| `5y` | 5Y% | WebSocket `change_ranges` | |
| `52wh` | 52W HIGH | WebSocket `symbol_data` | WS request only fires when this column is active |
| `52wl` | 52W LOW | WebSocket `symbol_data` | WS request only fires when this column is active |

Columns can be toggled in the Settings widget. The panel requires a minimum width of 600 px before horizontal scrolling activates.

---

## Persistent State (Jotai Atoms)

Both atoms use `tabStorage` (sessionStorage) for per-tab isolation. They were previously stored in localStorage; stale keys are cleaned up automatically on startup via `OLD_LOCAL_STORAGE_KEYS`.

| Atom | Storage Key | Default | Purpose |
|---|---|---|---|
| `moversColumnsAtom` | `terminal.moversColumns` | `['close','chg','1w','1m','3m','6m','1y']` | Active column set |
| `moversCategoryAtom` | `terminal.moversCategory` | `'allSec'` | Active category tab |

---

## Interactivity

**Row click** — clicking any row:
1. Sets `activeSymbolAtom` to the clicked symbol.
2. Sets `activeExchangeAtom` to `'NSE'`.

This broadcasts the symbol to all other widgets (Chart, Order, Fundamentals, News, etc.) that read from `activeSymbolAtom`.

---

## UI Layout

```
Panel (h-full, flex-col, font-mono, text-xs, overflow-auto)
├── Category tab bar (overflow-x-auto, border-b, active tab in terminal-amber)
├── TOP GAINERS section (flex-1, border-b in terminal-green)
│   └── <table min-w-[600px]>
│       ├── <thead> — green, 9px
│       └── <tbody> — MoverRowComponent per row (amber text, green symbol)
└── TOP LOSERS section (flex-1, border-b in terminal-red)
    └── <table min-w-[600px]>
        ├── <thead> — red, 9px
        └── <tbody> — MoverRowComponent per row (amber text, red symbol)
```

Each `MoverRowComponent`:
- Mounts its own `useChangeRanges(symbol)` hook (WebSocket subscription).
- Mounts `useMoverQuote(symbol, enabled)` only when `52wh` or `52wl` is in the active column set.
- Renders `—` while WebSocket data is loading.

---

## Loading & Empty States

| Condition | Display |
|---|---|
| `gainersLoading \|\| losersLoading` | `"Loading movers..."` centered |
| Both arrays empty after load | `"No data available."` |
| Normal | Both sections rendered with tables |

---

## Backend Implementation Notes

- Router: `backend/app/routers/nonpersistence.py` under the `/api/market` prefix.
- Gainers/losers share one upstream NSE fetch per category via `_get_market_variations_shared()` — concurrent requests coalesce.
- Response normalises field names: `ltp` is aliased as `lastPrice`; both `perChange` and `pChange` are present for backward compatibility.
- The `/api/py/market/movers-categories` endpoint derives its list from NSE's `legends` field and is cached for 24 hours on the client.

---

## Related Files

| Path | Role |
|---|---|
| `src/components/widgets/MoversWidget.tsx` | Widget component (434 lines) |
| `src/lib/marketWs.ts` | `MarketWebSocketService` singleton |
| `src/store/terminalStore.ts` | `moversColumnsAtom`, `moversCategoryAtom` |
| `backend/app/routers/nonpersistence.py` | Top gainers/losers/categories endpoints |

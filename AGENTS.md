# AGENTS.md

Guidelines for AI coding agents working in this repository.

---

## Project Overview

A financial terminal UI built with **Next.js 16 (App Router)**, **React 19**, **TypeScript**,
**Tailwind CSS v4**, **Jotai** for state, and a native **WebSocket** client for real-time data.
Panels host widgets (chart, order entry, positions, watchlist, movers, deals, fundamentals,
settings) backed by a **Next.js API proxy** over the OpenAlgo trading API, with **Prisma +
SQLite** (`better-sqlite3`) for local persistence. A separate **FastAPI** analytics backend
(`backend/`) serves NSE filings/market data via a catch-all `/api/py/[...path]` Next.js proxy.

---

## Commands

### Next.js frontend (run from repo root)

```bash
npm run dev       # Start Next.js dev server
npm run build     # Production build — also runs TypeScript type-check via next build
npm start         # Serve the production build
npm run lint      # ESLint v9 flat config (core-web-vitals + typescript)
```

One-time: generate Prisma client after cloning the repo or when the schema changes:

```bash
npx prisma generate
```

### Python backend (run from `backend/`)

```bash
# One-time setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the FastAPI server
uvicorn main:app --reload --port 8000

# Tests — integration suite; requires server running at http://127.0.0.1:8000
pytest                                    # all tests
pytest tests/test_endpoints.py            # single file
pytest tests/test_endpoints.py::TestMarketTopGainers::test_structure  # single test
pytest -m "not slow"                      # skip NSE-hitting tests (3 s delay each)
BLM_BASE_URL=http://host:port pytest      # override base URL
```

`asyncio_mode = "auto"` is set in `pyproject.toml` — no `@pytest.mark.asyncio` needed.
NSE-hitting tests carry `@pytest.mark.slow`; omit with `-m "not slow"` in CI.

No test framework is configured for the frontend yet. When added, place tests in
`src/__tests__/` or co-locate as `*.test.tsx` / `*.spec.tsx`. Vitest is recommended:

```bash
npx vitest run src/components/CommandBar.test.tsx   # single file
npx vitest run                                       # all tests
```

---

## Directory Structure

```
src/
├── app/
│   ├── api/
│   │   ├── openalgo/              # Proxy routes: rate-limit → cache → OpenAlgoServerClient
│   │   │   ├── positions/route.ts   # POST /api/openalgo/positions
│   │   │   ├── orders/route.ts      # POST /api/openalgo/orders
│   │   │   ├── trades/route.ts      # POST /api/openalgo/trades
│   │   │   ├── funds/route.ts       # POST /api/openalgo/funds
│   │   │   ├── quotes/route.ts      # POST /api/openalgo/quotes
│   │   │   ├── history/route.ts     # POST /api/openalgo/history
│   │   │   ├── placeorder/route.ts  # POST /api/openalgo/placeorder
│   │   │   └── ws-token/route.ts    # GET  /api/openalgo/ws-token
│   │   ├── py/[...path]/route.ts    # Catch-all proxy → PYTHON_BACKEND_URL
│   │   ├── settings/route.ts        # GET/PUT — Prisma UserSettings
│   │   └── watchlist/route.ts       # GET/POST/DELETE — Prisma WatchlistItem
│   ├── globals.css     # Tailwind v4 @theme tokens + @utility animate-ticker
│   ├── layout.tsx      # Server component — wraps app in <Providers>
│   └── page.tsx        # Server component — renders <TerminalContainer>
├── components/
│   ├── widgets/
│   │   ├── ChartWidget.tsx         # Candlestick chart (lightweight-charts)
│   │   ├── DealsWidget.tsx         # Bulk/block deals from Python backend
│   │   ├── FundamentalsWidget.tsx  # Company fundamentals from Python backend
│   │   ├── MoversWidget.tsx        # Top gainers/losers
│   │   ├── OrderWidget.tsx         # Order entry + order book
│   │   ├── PosWidget.tsx           # Positions + P&L
│   │   ├── SettingsWidget.tsx      # App settings (API key, exchange, etc.)
│   │   └── WatchWidget.tsx         # Watchlist with live ticks
│   ├── CommandBar.tsx
│   ├── ErrorBoundary.tsx    # Class component wrapping each widget in Panel.tsx
│   ├── GridSystem.tsx       # Resizable panel grid
│   ├── LiveTicker.tsx       # Scrolling price ticker strip
│   ├── Panel.tsx            # switch-based widget router + ErrorBoundary
│   ├── Providers.tsx        # QueryClientProvider (client component)
│   └── TerminalContainer.tsx
├── generated/
│   └── prisma/              # Generated Prisma client (do not edit manually)
├── lib/
│   ├── api-config.ts         # TTLs and rate limits per endpoint
│   ├── cache.ts              # In-memory TTL cache singleton
│   ├── logger.ts             # Structured logger singleton
│   ├── openalgo-server.ts    # Server-side REST client (timeout, retry, typed errors)
│   ├── openalgo.ts           # Client-side REST client (calls proxy routes)
│   ├── prisma.ts             # Prisma client singleton (globalThis pattern)
│   ├── rate-limiter.ts       # Sliding-window rate limiter singleton
│   ├── socket.ts             # Native WebSocket singleton (WebSocketService + wsService)
│   └── utils.ts              # cn() — clsx + tailwind-merge
└── store/
    └── terminalStore.ts      # All Jotai atoms (single source of truth)
backend/                      # FastAPI analytics service (Python ≥ 3.11, Hatch build)
prisma/schema.prisma          # Models: WatchlistItem, TopMoverSymbol, UserSettings
```

---

## Code Style

### TypeScript

- **Strict mode on** (`"strict": true`). Target `ES2017`, `moduleResolution: "bundler"`, `noEmit: true`.
- Use `unknown` in `catch` blocks — `err: any` is forbidden in new code:
  ```ts
  catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
  }
  ```
- Use `import type` for type-only imports: `import type { NextRequest } from 'next/server'`
- Generic helpers over overloads: see `OpenAlgoServerClient.request<T>()`.
- `socket.io-client` is listed in `package.json` but **not used** — the actual socket layer is
  the native `WebSocket` singleton in `src/lib/socket.ts`. Do not import from `socket.io-client`.

### Imports

- `@/` alias (→ `src/`) for all cross-directory imports; relative `./` only within the same directory.
- Import order (manual — no plugin enforces this):
  1. `react`, `next/*`
  2. Third-party libraries
  3. `@/` internal imports
  4. `./` relative imports
- Named exports everywhere except `app/page.tsx` and `app/layout.tsx` (Next.js requires defaults).

### React Components

- `'use client'` must be the **first line** of every interactive component. Server components
  (`page.tsx`, `layout.tsx`, API routes) have no directive.
- One component per file; filename matches the exported component name (PascalCase).
- Props typed as an inline interface directly above the component: `interface WidgetProps { ... }`.
- Use `cn()` from `@/lib/utils` for conditional or merged Tailwind class strings.

### Naming Conventions

| Entity | Convention | Example |
|---|---|---|
| React components / files | PascalCase | `ChartWidget`, `Panel.tsx` |
| Non-component functions | camelCase | `handleKeyDown`, `handleOrder` |
| Variables / local state | camelCase | `inputVal`, `focusedPanel` |
| Jotai atoms | camelCase + `Atom` suffix | `activeCommandAtom`, `fundsAtom` |
| TypeScript interfaces | PascalCase | `PanelProps`, `OrderParams` |
| Classes | PascalCase | `OpenAlgoClient`, `WebSocketService` |
| Exported singletons | camelCase | `wsService`, `logger`, `rateLimiter` |
| CSS custom properties | kebab-case with prefix | `--color-terminal-bg`, `--font-mono` |
| Tailwind design tokens | kebab-case | `terminal-bg`, `terminal-amber` |
| Widget command strings | UPPER_CASE | `'CHART'`, `'ORDER'`, `'POS'`, `'TOP'` |

### CSS and Tailwind

- Tailwind v4 utilities only. Inline `style={{}}` only for runtime-computed values (e.g. panel pixel widths).
- All design tokens are defined in `src/app/globals.css` under `@theme` — never hardcode hex values.
- Terminal palette: `terminal-amber` (primary), `terminal-green` (profit/buy), `terminal-red` (loss/sell), `terminal-bg` (background), `terminal-gray` (borders/muted).
- The `animate-ticker` utility is defined via `@utility` in `globals.css`; use it for scrolling strips.

### State Management (Jotai)

- All atoms live in `src/store/terminalStore.ts`. Do **not** create atoms in component files.
- Atoms are generically typed: `atom<string>('')`, `atom<Record<string, TickData>>({})`.
- Read-only consumers use `useAtomValue`; read-write consumers use `useAtom`.
- Prefer primitive atoms + derived `atom(get => ...)` over large compound atoms.

### Data Fetching

- Use `useQuery` / `useMutation` from `@tanstack/react-query` for all server state in components.
  Raw `useEffect + useState` for async data is **not acceptable** in new widgets.
- Every OpenAlgo proxy route follows this pipeline:
  **rate-limit → cache check → `OpenAlgoServerClient` → write cache → return JSON**.
- Python backend data is fetched through `/api/py/[...path]`, which forwards the full path and
  query string to `PYTHON_BACKEND_URL`.
- WebSocket subscriptions use the `wsService` singleton (`src/lib/socket.ts`).

### Error Handling

- Proxy routes catch errors and return `{ error: string }` with the appropriate HTTP status.
  Components read `data.error` and surface it in the UI.
- `ErrorBoundary` is already mounted around every widget in `Panel.tsx` — do not add redundant
  render-level try/catch.
- Guard DOM refs before use: `if (!ref.current) return;`
- Register an `'error'` listener whenever adding `WebSocket` / `wsService` subscriptions.

---

## Environment Variables

```
# Server-only (never NEXT_PUBLIC_)
OPENALGO_URL=http://localhost:8800
OPENALGO_API_KEY=<your_api_key>
OPENALGO_TIMEOUT_MS=10000
RATE_LIMIT_PER_MINUTE=60
PYTHON_BACKEND_URL=http://localhost:8000   # used by /api/py/[...path] proxy

# Client-safe
NEXT_PUBLIC_OPENALGO_WS_URL=ws://localhost:8765
NEXT_PUBLIC_OPENALGO_DEFAULT_EXCHANGE=NSE
```

Never commit `.env.local`. The `.gitignore` already excludes `.env*` files.

---

## No Cursor or Copilot Rules

No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` files exist in this repo.

# AGENTS.md

Guidelines for AI coding agents working in this repository.

---

## Project Overview

A financial terminal UI built with **Next.js 16 (App Router)**, **React 19**, **TypeScript**,
**Tailwind CSS v4**, **Jotai** for state, and a native **WebSocket** client for real-time data.
Panels host widgets (chart, order entry, positions, watchlist, movers, deals, large deals,
breakouts, fundamentals, settings) backed by a **Next.js API proxy** over the OpenAlgo trading API,
with **Prisma + SQLite** (`better-sqlite3`) for local persistence (`TopMoverSymbol`, `UserSettings`).
A separate **FastAPI** analytics backend (`backend/`) serves NSE filings/market data via a
catch-all `/api/py/[...path]` Next.js proxy. The backend manages its own SQLite DB via Alembic.

---

## Commands

### Next.js frontend (run from repo root)

```bash
npm run dev       # Start Next.js dev server
npm run build     # Production build — also runs TypeScript type-check via next build
npm start         # Serve the production build
npm run lint      # ESLint v9 flat config (core-web-vitals + typescript)
```

One-time after cloning or schema changes:

```bash
npx prisma generate   # Regenerates src/generated/prisma/ — do not edit manually
```

### Python backend (run from `backend/`)

```bash
# One-time setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the FastAPI server
uvicorn main:app --reload --port 8000

# Tests — integration suite; requires server running at http://127.0.0.1:8000
pytest                                                              # all tests
pytest tests/test_endpoints.py                                      # single file
pytest tests/test_endpoints.py::TestMarketTopGainers::test_structure  # single test
pytest -m "not slow"                                                # skip NSE-hitting tests
BLM_BASE_URL=http://host:port pytest                                # override base URL
```

`asyncio_mode = "auto"` in `pyproject.toml` — no `@pytest.mark.asyncio` needed.
NSE-hitting tests carry `@pytest.mark.slow`; always omit with `-m "not slow"` in CI.

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
│   │   │   ├── placeorder/route.ts  # POST /api/openalgo/placeorder (30 req/min limit)
│   │   │   └── ws-token/route.ts    # GET  /api/openalgo/ws-token
│   │   ├── py/[...path]/route.ts    # Catch-all proxy → PYTHON_BACKEND_URL
│   │   ├── settings/route.ts        # GET/PUT — Prisma UserSettings
│   │   └── watchlist/route.ts       # GET/POST/DELETE — Python backend watchlist
│   ├── globals.css     # Tailwind v4 @theme tokens + @utility animate-ticker
│   ├── layout.tsx      # Server component — wraps app in <Providers>
│   └── page.tsx        # Server component — renders <TerminalContainer>
├── components/
│   ├── widgets/        # ChartWidget, WatchWidget, MoversWidget, OrderWidget, PosWidget,
│   │                   # SettingsWidget, DealsWidget, LargedealsWidget, BreakoutsWidget, FundamentalsWidget
│   ├── CommandBar.tsx, ErrorBoundary.tsx, GridSystem.tsx, LiveTicker.tsx
│   ├── Panel.tsx            # switch-based widget router + ErrorBoundary per widget
│   ├── Providers.tsx        # QueryClientProvider (client component)
│   └── TerminalContainer.tsx
├── generated/prisma/        # Generated Prisma client — do not edit manually
├── lib/
│   ├── api-config.ts         # TTLs and rate limits per endpoint
│   ├── cache.ts              # In-memory TTL cache singleton (Map-backed, lazy expiry)
│   ├── logger.ts             # Structured logger singleton
│   ├── openalgo-server.ts    # Server-side REST client (timeout, retry, typed errors)
│   ├── openalgo.ts           # Client-side REST client (posts to proxy routes)
│   ├── prisma.ts             # Prisma client singleton (globalThis pattern)
│   ├── rate-limiter.ts       # Fixed-window rate limiter (60 req/min; 30 for placeorder)
│   ├── socket.ts             # Native WebSocket singleton (WebSocketService + wsService)
│   └── utils.ts              # cn() — clsx + tailwind-merge
└── store/
    └── terminalStore.ts      # All Jotai atoms — single source of truth
backend/                      # FastAPI analytics service (Python ≥ 3.11, Hatch build)
├── app/routers/              # filings, market, news, screener, stockuniverse, watchlist, ai_summarizer
├── app/services/             # nse_client, screener_client, news_fetcher, moneycontrol_client, etc.
├── app/models/ app/schemas/  # SQLAlchemy models + Pydantic schemas
├── alembic/                  # DB migrations for the backend SQLite DB
└── tests/                    # Integration tests (test_endpoints.py, test_mcp.py, test_mcp_stdio.py)
prisma/schema.prisma          # Models: TopMoverSymbol, UserSettings (watchlist is in Python backend)
prisma.config.ts              # Prisma config (references schema.prisma)
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
- `socket.io-client` is in `package.json` but **not used** — use the native WebSocket singleton
  in `src/lib/socket.ts`. Do not import from `socket.io-client`.

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

- Tailwind v4 utilities only. Inline `style={{}}` only for runtime-computed values (e.g. panel widths).
- All design tokens defined in `src/app/globals.css` under `@theme` — never hardcode hex values.
- Terminal palette: `terminal-amber` (#ffb900, primary), `terminal-green` (#00ff00, profit/buy),
  `terminal-red` (#ff0000, loss/sell), `terminal-bg` (#000000), `terminal-gray` (#333333, borders).
- Font stacks: `--font-sans` (Inter/Geist), `--font-mono` (JetBrains Mono/Consolas).
- The `animate-ticker` utility is defined via `@utility` in `globals.css`; use it for scrolling strips.

### State Management (Jotai)

- All atoms live in `src/store/terminalStore.ts`. Do **not** create atoms in component files.
- Atoms are generically typed: `atom<string>('')`, `atom<Record<string, TickData>>({})`.
- `tickDataAtom` is keyed by `"SYMBOL.EXCHANGE"` strings.
- Read-only consumers use `useAtomValue`; read-write consumers use `useAtom`.
- Prefer primitive atoms + derived `atom(get => ...)` over large compound atoms.

### Data Fetching

- Use `useQuery` / `useMutation` from `@tanstack/react-query` for all server state in components.
  Raw `useEffect + useState` for async data is **not acceptable** in new widgets.
- Every OpenAlgo proxy route follows this pipeline:
  **rate-limit → cache check → `OpenAlgoServerClient` → write cache → return JSON**.
- Python backend data is fetched through `/api/py/[...path]`, which forwards the full path and
  query string to `PYTHON_BACKEND_URL`. The proxy strips unsafe headers and returns 502 on ECONNREFUSED.
- WebSocket subscriptions use the `wsService` singleton (`src/lib/socket.ts`). The service fetches
  the API key server-side from `/api/openalgo/ws-token`, uses exponential backoff (cap 30 s,
  max 10 attempts), and automatically replays subscriptions after reconnect.

### Error Handling

- Proxy routes catch errors and return `{ error: string }` with the appropriate HTTP status.
  Components read `data.error` and surface it in the UI.
- `ErrorBoundary` is already mounted around every widget in `Panel.tsx` — do not add redundant
  render-level try/catch.
- Guard DOM refs before use: `if (!ref.current) return;`
- Register an `'error'` listener whenever adding `WebSocket` / `wsService` subscriptions.

### Python (backend/)

- Python ≥ 3.11; async-first with FastAPI + SQLAlchemy async + `aiosqlite`.
- Pydantic v2 for all request/response schemas (in `app/schemas/`).
- SQLAlchemy models in `app/models/`; Alembic manages all migrations — never edit the DB directly.
- Use `httpx.AsyncClient` for outbound HTTP (NSE, Screener, MoneyControl). No `requests` in async paths.
- Tests are integration tests in `backend/tests/`; `asyncio_mode = "auto"` — no decorator needed.
- Tag NSE-hitting tests with `@pytest.mark.slow`.

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

Never commit `.env.local` or `.env`. Both are excluded by `.gitignore`.

---

## No Cursor or Copilot Rules

No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` files exist in this repo.

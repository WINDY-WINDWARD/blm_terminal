# AGENTS.md

Guidelines for AI coding agents working in this repository.

---

## Project Overview

A financial terminal UI built with **Next.js 16 (App Router)**, **React 19**, **TypeScript**,
**Tailwind CSS v4**, **Jotai** for state, and a native **WebSocket** client for real-time data.
Panels host widgets (chart, order entry, positions, watchlist, top movers, settings) backed by a
**Next.js API proxy** over the OpenAlgo trading API, with **Prisma + SQLite** for local
persistence. A separate **FastAPI** analytics backend (`backend/`) serves NSE filings/market data.

---

## Commands

### Next.js frontend (run from repo root)

```bash
npm run dev       # Start Next.js dev server
npm run build     # Production build (also type-checks via next build)
npm start         # Serve the production build
npm run lint      # ESLint v9 flat config (eslint-config-next/core-web-vitals + typescript)
```

### Python backend (run from `backend/`)

```bash
# One-time setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run the FastAPI server
uvicorn main:app --reload --port 8000

# Tests (pytest-asyncio, asyncio_mode = "auto")
pytest                               # all tests in backend/tests/
pytest tests/test_market.py          # single file
pytest tests/test_market.py::test_fn # single test function
```

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
│   │   ├── openalgo/         # Proxy routes (rate-limit → cache → OpenAlgoServerClient)
│   │   │   ├── positions/route.ts   # POST /api/openalgo/positions
│   │   │   ├── orders/route.ts      # POST /api/openalgo/orders
│   │   │   ├── trades/route.ts      # POST /api/openalgo/trades
│   │   │   ├── funds/route.ts       # POST /api/openalgo/funds
│   │   │   ├── quotes/route.ts      # POST /api/openalgo/quotes
│   │   │   ├── history/route.ts     # POST /api/openalgo/history
│   │   │   ├── placeorder/route.ts  # POST /api/openalgo/placeorder
│   │   │   └── ws-token/route.ts    # GET  /api/openalgo/ws-token
│   │   ├── top-symbols/route.ts
│   │   └── watchlist/route.ts       # GET/POST/DELETE — Prisma-backed
│   ├── globals.css     # Tailwind v4 @theme design tokens
│   ├── layout.tsx      # Server component — wraps app in <Providers>
│   └── page.tsx        # Server component — renders <TerminalContainer>
├── components/
│   ├── widgets/        # ChartWidget, OrderWidget, PosWidget, SettingsWidget, TopWidget, WatchWidget
│   ├── CommandBar.tsx
│   ├── ErrorBoundary.tsx   # Class component wrapping each widget in Panel.tsx
│   ├── Panel.tsx           # switch-based widget router + ErrorBoundary
│   ├── Providers.tsx       # QueryClientProvider (client component)
│   └── TerminalContainer.tsx
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
backend/                      # FastAPI analytics service (Python ≥ 3.11, Poetry/Hatch)
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

### Imports

- `@/` alias (→ `src/`) for all cross-directory imports; relative `./` only within the same directory.
- Import order (manual — no plugin enforces this):
  1. `react`, `next/*`
  2. Third-party libraries
  3. `@/` internal imports
  4. `./` relative imports
- Named exports everywhere except `app/page.tsx` and `app/layout.tsx` (Next.js requires defaults).

### React Components

- `'use client'` must be the **first line** of every interactive component. Server components (`page.tsx`, `layout.tsx`, API routes) have no directive.
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
- All design tokens defined in `src/app/globals.css` under `@theme` — never hardcode hex values.
- Terminal palette: `terminal-amber` (primary), `terminal-green` (profit/buy), `terminal-red` (loss/sell), `terminal-bg` (background), `terminal-gray` (borders/muted).

### State Management (Jotai)

- All atoms live in `src/store/terminalStore.ts`. Do **not** create atoms in component files.
- Atoms are generically typed: `atom<string>('')`, `atom<Record<string, TickData>>({})`.
- Read-only consumers use `useAtomValue`; read-write consumers use `useAtom`.
- Prefer primitive atoms + derived `atom(get => ...)` over large compound atoms.

### Data Fetching

- Use `useQuery` / `useMutation` from `@tanstack/react-query` for all server state in components. Raw `useEffect + useState` for async data is **not acceptable** in new widgets.
- Every proxy route follows this pipeline: **rate-limit → cache check → `OpenAlgoServerClient` → write cache → return JSON**.
- WebSocket subscriptions use the `wsService` singleton (`src/lib/socket.ts`).

### Error Handling

- Proxy routes catch errors and return `{ error: string }` with the appropriate HTTP status. Components read `data.error` and surface it in the UI.
- `ErrorBoundary` is already mounted around every widget in `Panel.tsx` — do not add redundant render-level try/catch.
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

# Client-safe
NEXT_PUBLIC_OPENALGO_WS_URL=ws://localhost:8765
NEXT_PUBLIC_OPENALGO_DEFAULT_EXCHANGE=NSE

# Python analytics backend — used server-side by /api/py/[...path] proxy route
PYTHON_BACKEND_URL=http://localhost:8000
```

Never commit `.env.local`. The `.gitignore` already excludes `.env*` files.

---

## No Cursor or Copilot Rules

No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` files exist in this repo.

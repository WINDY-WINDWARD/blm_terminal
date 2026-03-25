# AGENTS.md

Guidelines for AI coding agents working in this repository.

---

## Project Overview

Financial terminal UI: **Next.js 16 (App Router)**, **React 19**, **TypeScript**, **Tailwind CSS v4**, **Jotai** (with `atomWithStorage`), native **WebSocket** for real-time data.
Widgets: Chart, Watch, Movers, Order, Pos, Settings, Deals, Largedeals, Breakouts, Fundamentals, News, Analysis, Notif.
Backend: **FastAPI** (`backend/`) serves NSE data via `/api/py/[...path]` proxy; manages its own SQLite DB via Alembic.
Local persistence: **Prisma + SQLite** (`better-sqlite3`) for `TopMoverSymbol`, `UserSettings`.

---

## Commands

### Frontend (repo root)
```bash
npm run dev       # dev server
npm run build     # production build + TypeScript check
npm start         # serve production build
npm run lint      # ESLint v9 flat config
npx prisma generate  # regenerate Prisma client
```

### Python backend (`backend/`)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

uvicorn main:app --reload --port 4455        # FastAPI server + MCP server (same port)

pytest                              # all tests
pytest tests/test_endpoints.py      # single file
pytest tests/test_endpoints.py::TestMarketTopGainers::test_structure  # single test
pytest -m "not slow"                # skip NSE-hitting tests
BLM_BASE_URL=http://host:port pytest  # override base URL
```
`asyncio_mode = "auto"` in pyproject.toml — no `@pytest.mark.asyncio` needed. Tag NSE tests with `@pytest.mark.slow`.

---

## Directory Structure

```
src/
├── app/api/
│   ├── openalgo/    # proxy routes → rate-limit → cache → OpenAlgoServerClient
│   ├── py/[...path]/route.ts   # catch-all → PYTHON_BACKEND_URL
│   ├── settings/route.ts       # GET/PUT Prisma UserSettings
│   ├── watchlist/route.ts      # single watchlist
│   ├── watchlists/route.ts     # multiple watchlists
│   ├── notifications/route.ts  # GET/POST
│   └── notifications/[id]/route.ts  # PUT/DELETE
├── components/widgets/  # ChartWidget, WatchWidget, MoversWidget, OrderWidget, PosWidget, SettingsWidget, DealsWidget, LargedealsWidget, BreakoutsWidget, FundamentalsWidget, NewsWidget, AnalysisWidget, NotifWidget
├── lib/        # api-config, cache, logger, openalgo-server, openalgo, prisma, rate-limiter, socket, utils
└── store/terminalStore.ts  # all Jotai atoms
backend/  # FastAPI (Python ≥ 3.11)
├── app/routers/   # markets, news, screener, stockuniverse, watchlist, ai_summarizer, notifications, corporatefilings, morningstar
├── app/services/  # nse_client, screener_client, moneycontrol_client, morningstar_client
├── app/models/, app/schemas/
├── app/backgroundtasks.py  # fair value sync, notification worker
└── tests/
prisma/schema.prisma
blm-mcp-bundle/  # Claude Desktop MCP plugin (29 tools)
```

---

## Code Style

### TypeScript
- **Strict mode on**. Use `unknown` in `catch` blocks:
  ```ts
  catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
  }
  ```
- Use `import type` for type-only imports.
- `socket.io-client` in package.json but **not used** — use native WebSocket in `src/lib/socket.ts`.

### Imports
- `@/` alias for cross-directory; relative `./` only within same directory.
- Order: 1) react/next/*, 2) third-party, 3) @/ internal, 4) ./ relative.
- Named exports except `page.tsx`/`layout.tsx`.

### React Components
- `'use client'` **first line** of every interactive component.
- One component per file; filename matches component name (PascalCase).
- Props as inline interface above component.
- Use `cn()` from `@/lib/utils`.

### Naming
| Entity | Convention | Example |
|--------|------------|---------|
| Components/files | PascalCase | `ChartWidget` |
| Functions/variables | camelCase | `handleKeyDown` |
| Jotai atoms | camelCase + `Atom` | `activeCommandAtom` |
| Interfaces | PascalCase | `PanelProps` |
| Widget commands | UPPER_CASE | `'CHART'`, `'NOTIF'` |

### State (Jotai)
- All atoms in `src/store/terminalStore.ts`. Use `atomWithStorage` for persistence.
- Read-only: `useAtomValue`; read-write: `useAtom`.
- Prefer primitive atoms + derived `atom(get => ...)`.

### Data Fetching
- Use `useQuery`/`useMutation` from `@tanstack/react-query`. Never raw `useEffect + useState`.
- Force refresh: `queryClient.invalidateQueries()` or `queryClient.refetchQueries()`.
- WebSocket: use `wsService` singleton from `src/lib/socket.ts`.

### Error Handling
- Proxy routes return `{ error: string }`. Components read `data.error`.
- `ErrorBoundary` wraps every widget in `Panel.tsx`.
- Guard DOM refs: `if (!ref.current) return;`

### Python
- Async-first: FastAPI + SQLAlchemy async + `aiosqlite`.
- Pydantic v2 for schemas.
- Alembic for migrations.
- Use `httpx.AsyncClient` (not `requests`) for outbound HTTP.
- Morningstar: uses `rookiepy` for browser cookies, stores `morningstar_id` in StockUniverse.

---

## Environment Variables

```
# Server-only (never NEXT_PUBLIC_)
OPENALGO_URL, OPENALGO_API_KEY, OPENALGO_TIMEOUT_MS, RATE_LIMIT_PER_MINUTE
PYTHON_BACKEND_URL=http://localhost:8000

# Client-safe
NEXT_PUBLIC_OPENALGO_WS_URL, NEXT_PUBLIC_OPENALGO_DEFAULT_EXCHANGE
```

Never commit `.env.local` or `.env` — both in `.gitignore`.

---

## No Cursor or Copilot Rules

No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` files exist in this repo.
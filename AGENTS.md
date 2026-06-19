# AGENTS.md

Guidelines for AI coding agents working in this repository.

---

## Project Overview

Financial terminal UI: **Next.js 16 (App Router)**, **React 19**, **TypeScript**, **Tailwind CSS v4**, **Jotai** (with `atomWithStorage`), native **WebSocket** for real-time data.
Widgets: Chart, Watch, Movers, Order, Pos, Settings, Deals, Largedeals, Breakouts, Fundamentals, News, Analysis, Notif, Ai, Announcements, Portfolio, Scan, Screener, Docs.
Backend: **FastAPI** (`backend/`) serves NSE data via `/api/py/[...path]` proxy; manages its own SQLite DB via Alembic.

### External data providers

- **NSE India** — quotes, OHLC, 52-week highs/lows, volume gainers, corporate filings (primary)
- **screener.in** — fundamentals (P/E, ROCE, ROE, market cap, quarterly results) — requires Chrome session cookie via rookiepy
- **morningstar.in** — fair value estimate, uncertainty rating — requires rookiepy cookies
- **iinvest.cogencis.com** — backup/enrichment for the FDM widget **and primary source for company news**: 18 read-only data endpoints (announcements, board meetings, corporate actions, insider trading, pledged shares, key shareholders, legal cases, block deals, news, peer comparison, OHLC timeseries). Auth is **automatic** — the iinvest frontend's own JS bundle ships a public AES-256 key that yields a view-role guest JWT via `/api/login`. No user action required. The `/api/v1/news/stories` (full) endpoint is faster and deterministic, so it's the default for the NewsWidget's company tab and the `get_company_news` MCP tool. **iinvest does NOT pre-tag sentiment/threat** — NLP is run locally via `app/services/nlp_service.analyze_article_dict` on each article after fetch, same as the MoneyControl and RSS flows. MoneyControl stays as a fallback (and for breadth). See `docs/reference/backend/iinvest.md` for architecture and `docs/guides/iinvest-integration.md` for the integration guide.

---

## Commands

### Frontend (repo root)
```bash
npm run dev       # dev server
npm run build     # production build + TypeScript check
npm start         # serve production build
npm run lint      # ESLint v9 flat config
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
│   ├── watchlist/route.ts      # single watchlist
│   ├── watchlists/route.ts     # multiple watchlists
│   ├── notifications/route.ts  # GET/POST
│   ├── notifications/[id]/route.ts  # PUT/DELETE
│   ├── announcements/route.ts  # NSE corporate announcements
│   ├── event-calendar/route.ts # Event calendar
│   ├── filing-xml/route.ts     # Corporate filing XML
│   ├── jobs/route.ts           # Background job monitoring
│   └── stockuniverse/errors/route.ts  # Stock universe error tracking
├── components/widgets/  # ChartWidget, WatchWidget, MoversWidget, OrderWidget, PosWidget, SettingsWidget, DealsWidget, LargedealsWidget, BreakoutsWidget, FundamentalsWidget, NewsWidget, AnalysisWidget, NotifWidget, AiWidget, AnnouncementsWidget, PortfolioWidget, ScanWidget, ScreenerWidget, DocsWidget
├── lib/        # api-config, cache, logger, marketWs, newsSocket, openalgo-server, openalgo, rate-limiter, screenerTql, utils, widgetDocs
└── store/terminalStore.ts  # all Jotai atoms
backend/  # FastAPI (Python ≥ 3.11)
├── app/routers/   # markets, market_ws, news, news_ws, screener, iinvest, stockuniverse,
│                  # watchlist, ai_summarizer, ai_chat, notifications, corporatefilings,
│                  # morningstar, announcements, valuation, portfolio, ticker, jobs,
│                  # system_config, nonpersistence, mcp_server
├── app/services/  # nse_client, nse_client_async, nse_rate_limiter, nse_charting_client,
│                  # screener_client, iinvest_client, iinvest_html_parser,
│                  # moneycontrol_client, morningstar_client,
│                  # news_fetcher, news_aggregator, news_sources, rss_parser,
│                  # ai_summarizer, ai_chat_service, indicators, momentum, returns,
│                  # ticker_warehouse, tql_parser, nlp_service, cache, cookie_loader
├── app/models/, app/schemas/
├── app/orchestrator.py  # central background worker manager
├── app/backgroundtasks.py  # fair value sync, notification worker, stock universe sync
└── tests/
blm-mcp-bundle/  # Claude Desktop MCP plugin (52 tools: 32 base + 20 iinvest_*)
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
- `socket.io-client` in package.json but **not used** — use native WebSocket via `src/lib/marketWs.ts` (market ticks) and `src/lib/newsSocket.ts` (news feed).

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
- WebSocket: use `wsService` singleton from `src/lib/marketWs.ts`.

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
PYTHON_BACKEND_URL=http://localhost:4455

# Client-safe
NEXT_PUBLIC_OPENALGO_WS_URL, NEXT_PUBLIC_OPENALGO_DEFAULT_EXCHANGE
```

Never commit `.env.local` or `.env` — both in `.gitignore`.

---

---

## Background Worker Architecture

### Daemon Workers vs. Orchestrator Pipeline

Daemon workers (cron-based, managed by `_runtime.py`) and the orchestrator startup pipeline share `_pipeline_lock`. A startup race is possible:

- **Workers that depend on pipeline data**: `ticker_daily_update_worker`, `ticker_scores_worker`, `ticker_indicators_worker`
- **Safety mechanism**: `_startup_pipeline_done` (threading.Event) — workers call `_wait_for_startup_event()` before entering their cron loop. The orchestrator sets the event after `_execute_pipeline` completes (Stage 7 done).
- **Lifecycle**: `backend/app/workers/lifecycle.py` re-exports `_startup_pipeline_done`. Import via `from app.workers.lifecycle import _startup_pipeline_done`.
- **Test**: `tests/test_pipeline_sync.py` verifies the startup pipeline-safe integration.

### Job Progress Tracking in UI

The `/api/py/jobs` endpoint exposes background job status. For `parallel_sync`-based jobs (e.g., W/M weekly/monthly sync):

- `parallel_sync._emit_progress` updates both pipeline progress AND the individual `job_key` status (percentage + message).
- Data sync functions (`_ticker_intraday_update_sync`, etc.) accept an optional `job_key` parameter and call `update_job_status_sync` after each batch.
- The orchestrator passes `job_key="job.ticker_weekly_monthly_update"` to relevant stage lambdas.

---

## No Cursor or Copilot Rules

No `.cursorrules`, `.cursor/rules/`, or `.github/copilot-instructions.md` files exist in this repo.
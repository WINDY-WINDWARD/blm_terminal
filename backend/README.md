# BLM Analytics — Python FastAPI Backend

This FastAPI service provides NSE India analytics used by the BLM Terminal frontend. It fetches and caches NSE data (corporate filings, market snapshots, news, stock universe, watchlist) and exposes a REST surface under `/api/*`, plus a streamable HTTP MCP server at `/api/mcp`.

This README explains how to run the backend locally and lists all available endpoints with example requests.

---

## Prerequisites

- Python 3.11+
- A virtual environment (venv) or similar isolation
- Network access to `https://www.nseindia.com`

## Project layout (relevant files)

- `main.py` — FastAPI app entrypoint + Alembic migration runner
- `app/config.py` — runtime settings (loaded from `.env`)
- `app/database.py` — async SQLAlchemy engine, `Base`, and `get_db()` dependency
- `app/models/` — ORM models (`corporatefilings.py`, `news.py`, `stockuniverse.py`, `watchlist.py`, `notification.py`)
- `app/schemas/` — Pydantic v2 request/response schemas (one file per domain)
- `app/routers/` — API routers:
  - `markets.py` — market snapshots (gainers, losers, deals, breakouts, 52w, volume)
  - `market_ws.py` — WebSocket `/ws/market` for live tick streaming
  - `corporatefilings.py` — NSE quarterly results CSV cache
  - `nonpersistence.py` — additional short-lived market snapshots
  - `stockuniverse.py` — DB-backed stock universe CRUD
  - `watchlist.py` — persistent watchlist (used by Next.js `/api/watchlist` proxy)
  - `news.py` — news fetching and caching
  - `news_ws.py` — WebSocket `/ws/news` for live news streaming
  - `screener.py` — Screener.in fundamentals proxy + TQL scan
  - `ai_summarizer.py` — OpenAI-backed summarizer
  - `ai_chat.py` — AI chat endpoints
  - `notifications.py` — watchlist price alerts (read, dismiss)
  - `morningstar.py` — Morningstar fair value proxy
  - `announcements.py` — NSE corporate announcements
  - `valuation.py` — stock valuation data
  - `portfolio.py` — portfolio data
  - `ticker.py` — ticker warehouse data
  - `jobs.py` — background job monitoring
  - `system_config.py` — system configuration KV store
  - `mcp_server.py` — FastMCP server mounted at `/api/mcp`
- `app/services/` — outbound HTTP clients and utilities:
  - `nse_client.py` / `nse_client_async.py` — NSE session bootstrap + HTTP helpers (sync + async)
  - `nse_rate_limiter.py` — circuit breaker + rate limiting for NSE API
  - `nse_charting_client.py` — NSE OHLCV intraday charting data
  - `screener_client.py` — Screener.in scraper
  - `news_fetcher.py` / `news_aggregator.py` — news fetching + multi-source aggregation
  - `news_sources.py` / `rss_parser.py` — news source definitions + RSS parsing
  - `moneycontrol_client.py` — MoneyControl market/stock data
  - `morningstar_client.py` — Morningstar India fair values (uses `rookiepy` for browser cookies)
  - `ai_summarizer.py` / `ai_chat_service.py` — LLM summarization and chat
  - `indicators.py` / `momentum.py` / `returns.py` — technical indicators and return calculations
  - `ticker_warehouse.py` — tick data warehouse
  - `tql_parser.py` — TQL (Terminal Query Language) parser for scan widget
  - `nlp_service.py` — NLP for news entity extraction and sentiment
  - `cache.py` — in-memory caching layer
  - `cookie_loader.py` — cookie loading for authenticated scrapers
- `app/orchestrator.py` — central background worker manager
- `app/mcp_server.py` — MCP tool definitions (streamable HTTP, mounted at `/api/mcp`)
- `app/backgroundtasks.py` — scheduled tasks: fair value sync, notification worker, stock universe sync
- `alembic/` — Alembic migration environment (`env.py`, `versions/`)
- `alembic.ini` — Alembic configuration
- `.env.example` — example environment variables

---

## Environment

Copy `backend/.env.example` to `backend/.env` and adjust values as needed. Important variables:

- `ENV` — environment mode.
  - **Development modes**: `development` (default), `dev`, `local`, `test`, `testing`. Allows local development fallbacks.
  - **Non-development / Strict modes**: `production`, `prod`, `staging` (or any other string). Enables strict fail-closed security checks.
- `SECRET_KEY` — strong secret key used for signing JWT authentication tokens (min 16 chars). Required in non-development mode.
  - Generate via OpenSSL: `openssl rand -hex 32`
  - Generate via Python: `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `ADMIN_PASSWORD` — password used to bootstrap the default `admin` user on a fresh database (when the `users` table is empty). Required in non-development mode.
  - Example: `ADMIN_PASSWORD="YourStrongAdminPassword123!"`
- `NSE_BASE_URL` — base URL for NSE (default: `https://www.nseindia.com`)
- `DB_PATH` — SQLite DB file path used by this backend (default: `./data.db`)
- `PORT` — port the server listens on (default: `4455`)
- `NSE_REQUEST_DELAY_MS` — polite delay between NSE requests (ms)
- `NSE_CACHE_TTL_SECONDS` — how long fetched data is considered fresh (seconds)
- `LOG_LEVEL` — logging level (INFO/DEBUG)

Additionally, the Next.js frontend uses an internal proxy to reach this service. In the Next app set:

- `PYTHON_BACKEND_URL=http://localhost:4455` (server-only env variable used by `/api/py/*` proxy)

---

## Install & run (developer)

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate # or for Windows PowerShell: .\.venv\bin\Activate.ps1
pip install -e ".[dev]"

# copy and edit .env as needed
cp .env.example .env

# run the server (reload in dev)
uvicorn main:app --reload --port ${PORT:-4455}
```

### Running tests

Tests are an integration suite — they require the server running at `http://127.0.0.1:4455`.
`asyncio_mode = "auto"` is set in `pyproject.toml`; no `@pytest.mark.asyncio` decorator is needed.

```bash
pytest                                                                # all tests
pytest tests/test_endpoints.py                                        # single file
pytest tests/test_endpoints.py::TestMarketTopGainers::test_structure  # single test
pytest -m "not slow"                                                  # skip NSE-hitting tests
BLM_BASE_URL=http://host:port pytest                                  # override base URL
```

Tag any test that hits NSE upstream with `@pytest.mark.slow`; CI always runs with `-m "not slow"`.

Notes:
- On every startup the app runs `alembic upgrade head` automatically — all pending migrations are applied before the server accepts requests.
- No production process manager is included here; for production consider using Gunicorn/UVLoop or containerization.

---

## How the Next.js frontend talks to this backend

The Next app contains a server-side proxy at `/api/py/[...path]` that forwards requests to this backend. Example:

- Frontend request: `GET /api/py/market/top-gainers`
- Backend receives: `GET http://localhost:4455/api/market/top-gainers`

This keeps the Python service's URL server-only and avoids CORS from the browser.

---

## Endpoints

All endpoints exposed by this service are mounted under `/api` (except `/health`). The Next.js proxy maps `/api/py/*` to these.

Base URL (dev): `http://localhost:4455`

1) Health

- `GET /health`
  - Response: `{ "status": "ok" }`
  - Example:
    ```bash
    curl http://localhost:4455/health
    ```

2) Corporate filings (cached CSV)

- `GET /api/corporatefilings/{symbol}`
  - Returns a pipe-delimited CSV (`text/csv`) containing corporate filing/quarterly-result data cached per symbol.
  - Behavior: if cached data for `{symbol}` is older than the configured TTL (see `.env`), the service fetches a fresh CSV from NSE, updates the cache, and returns the CSV.
  - Example:
    ```bash
    curl -v "http://localhost:4455/api/corporatefilings/RELIANCE" -o RELIANCE_filings.csv
    ```

3) Market (non-persisted snapshots)

These endpoints live under `/api/market` and are intended for short-lived snapshots. The backend enforces a courtesy delay and an internal short TTL to avoid flooding NSE.

- `GET /api/market/top-gainers` — today's top gainers (returns JSON array)
- `GET /api/market/top-losers` — today's top losers (returns JSON array)
- `GET /api/market/bulk-deals/{symbol}` — bulk deals for `{symbol}` (JSON array)
- `GET /api/market/block-deals/{symbol}` — block deals for `{symbol}` (JSON array)
- `GET /api/market/high-short-interest` — stocks with high short interest (JSON array)
 - `GET /api/market/52week-low` — 52-week low stocks snapshot (JSON object, cached 3h)
 - `GET /api/market/52week-high` — 52-week high stocks snapshot (JSON object, cached 3h)

Examples:

```bash
curl http://localhost:4455/api/market/top-gainers
curl http://localhost:4455/api/market/bulk-deals/TCS
```

4) Stock universe (DB-backed)

- `GET /api/stockuniverse` — return all stock universe records (JSON array of objects)
- `GET /api/stockuniverse/{symbol}` — return a single record for `symbol` (404 if not found)
- `GET /api/stockuniverse/search/{prefix}` — search by symbol/company prefix
- `GET /api/stockuniverse/errors` — grouped stock-universe error records, including `ticker_error`
- `PUT /api/stockuniverse/errors/{symbol}/reset-ticker` — clear `ticker_error` and reset the ticker failure counter

Ticker backfill notes:
- Weekly/monthly startup backfill uses DB consensus to decide which symbols are stale.
- Symbols that fail ticker backfill 3 times are marked `ticker_error` and excluded from future ticker runs until reset.

Examples:

```bash
curl http://localhost:4455/api/stockuniverse
curl http://localhost:4455/api/stockuniverse/RELIANCE
curl http://localhost:4455/api/stockuniverse/search/INF
curl http://localhost:4455/api/stockuniverse/errors
```

5) Watchlist (DB-backed, used by Next.js frontend)

- `GET    /api/watchlist` — return all watchlist items
- `POST   /api/watchlist` — add a symbol (`{"symbol": "RELIANCE", "exchange": "NSE"}`)
- `DELETE /api/watchlist/{id}` — remove by ID
- `GET    /api/watchlists` — list all watchlists (multiple watchlists support)
- `POST   /api/watchlists` — create a new watchlist (`{"name": "My Watchlist"}`)
- `GET    /api/watchlists/{id}` — get a specific watchlist with its items
- `PUT    /api/watchlists/{id}` — rename a watchlist
- `DELETE /api/watchlists/{id}` — delete a watchlist and its items

6) Notifications (watchlist price alerts)

Notifications are triggered when watchlist stocks hit 52-week highs/lows, volume breakouts, top gainers/losers, bulk/block/short deals, or insider trades.

- `GET /api/notifications?watchlist_id={id}` — get unread notifications for a watchlist (newest first)
- `DELETE /api/notifications/{notif_id}?watchlist_id={id}` — mark a notification as read (soft delete)
- `DELETE /api/notifications?watchlist_id={id}&all=true` — mark all notifications as read for a watchlist
- `DELETE /api/notifications?watchlist_id={id}` — delete all notifications for a watchlist

**Trigger types** (11 total):
| Trigger | Description |
|---------|-------------|
| `52w_high_breakout` | Stock hit new 52-week high |
| `52w_low_breakout` | Stock hit new 52-week low |
| `volume_breakout` | Volume spike vs weekly average |
| `top_gainer` | Stock among top gainers |
| `top_loser` | Stock among top losers |
| `bulk_deal` | Bulk deal executed |
| `block_deal` | Block deal executed |
| `short_deal` | Short deal executed |
| `insider_buy` | Insider purchase detected |
| `insider_sell` | Insider sale detected |
| `insider_unknown` | Unknown insider activity |

**Dev endpoint** (triggers notification cycle manually):
- `POST /api/notifications/trigger` — runs the full notification cycle (for testing)

7) News

- `GET /api/news/global` — latest cached global news items (MoneyControl)
- `GET /api/news/company/{symbol}` — news for a specific company symbol
- `POST /api/news/company` — fetch and store news for a company symbol

  **Request body (both mc_url fields are optional):**
  ```json
  {
    "symbol": "RELIANCE",
    "mc_url": "https://www.moneycontrol.com/..."   // optional — auto-resolved if omitted
  }
  ```

  The `mc_url` parameter is optional. If omitted, the backend automatically resolves it via:
  1. StockUniverse table (cached)
  2. MoneyControl autocomplete API
  3. Fallback map (for known symbols like RELIANCE, INFY, TCS, etc.)

  **Response:** Returns an array of news articles with fields: `url`, `title`, `text`, `publish_date`, `fetched_at`, `company_symbol`, `source`.

  **Examples:**
  ```bash
  # Fetch news for INFY (auto-resolves URL)
  curl -X POST http://localhost:4455/api/news/company \
    -H "Content-Type: application/json" \
    -d '{"symbol": "INFY"}'

  # Fetch news for TITAN (resolves via autocomplete API)
  curl -X POST http://localhost:4455/api/news/company \
    -H "Content-Type: application/json" \
    -d '{"symbol": "TITAN"}'

  # Fetch news with explicit URL
  curl -X POST http://localhost:4455/api/news/company \
    -H "Content-Type: application/json" \
    -d '{"symbol": "RELIANCE", "mc_url": "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI"}'

  # Get cached company news
  curl http://localhost:4455/api/news/company/INFY

  # Get global news
  curl http://localhost:4455/api/news/global
  ```

7) Screener (fundamentals)

- `GET /api/screener/search?q=reliance` — search Screener.in for companies
- `GET /api/screener/company/{slug}` — company fundamentals (requires Screener auth)
- `GET /api/screener/trades/{slug}` — insider trades (requires Screener auth)
- `GET /api/screener/quarters/{slug}` — quarterly results (requires Screener auth)

8) Morningstar (fair values)

- `GET /api/morningstar/fairvalue/{symbol}` — get fair value for a symbol from Morningstar India
- `GET /api/morningstar/search?q={symbol}` — resolve a symbol to its Morningstar ID

**Examples:**
```bash
# Get fair value for TCS
curl http://localhost:4455/api/morningstar/fairvalue/TCS

# Search for Morningstar ID
curl http://localhost:4455/api/morningstar/search?q=reliance
```

The fair values are cached in the `stockuniverse` table. A background task syncs fair values nightly for all symbols in the watchlist and periodically for the entire stock universe.

9) Proxy via Next.js (developer convenience)

- If you run the Next.js dev server, the repo contains `src/app/api/py/[...path]/route.ts` which maps e.g.
  - `GET /api/py/market/top-gainers` → `http://localhost:4455/api/market/top-gainers`

Example — via Next.js dev server:

```bash
curl http://localhost:3000/api/py/market/top-gainers
```

---

## MCP Server (Model Context Protocol)

The backend exposes a streamable HTTP MCP server at `/api/mcp`. This provides programmatic access to market data plus portfolio and watchlist actions via the MCP protocol, suitable for LLM integrations.

**Transport:** Streamable HTTP (mounted inside FastAPI)  
**Path:** `/api/mcp`  
**Startup:** The MCP server shares the same lifespan as the FastAPI app — migrations, cache cleanup, stock-universe scheduler, and screener session initialization all run once at startup.

### Available MCP Tools (37)

| Tool | Description |
|---|---|
| `health_check` | Service health status |
| `get_top_gainers` | Today's top gainers on NSE |
| `get_top_losers` | Today's top losers on NSE |
| `get_bulk_deals` | Bulk deals for one or multiple symbols |
| `get_block_deals` | Block deals for one or multiple symbols |
| `get_largedeal_snapshot` | Full largedeal snapshot (bulk/short/block) |
| `get_change_ranges` | Percentage changes over multiple timeframes |
| `get_symbol_data` | Live symbol data from NSE |
| `get_52week_low_stocks` | 52-week low stocks snapshot |
| `get_52week_high_stocks` | 52-week high stocks snapshot |
| `get_volume_gainers` | Volume gainers snapshot |
| `get_high_short_interest` | Stocks flagged for high short-selling interest |
| `get_company_quarterly_results` | Quarterly financial results as CSV (structured) |
| `screener_search` | Search screener.in for companies |
| `screener_company` | Company fundamentals from screener.in (requires auth) |
| `screener_trades` | Insider trades, bulk/block deals from screener.in (requires auth) |
| `list_stock_universe` | All stock universe records |
| `get_stock_universe` | Single or bulk stock universe records by symbol |
| `search_stock_universe` | Search stock universe by prefix |
| `optimize_portfolio` | Optimize a portfolio from NSE symbols and return weights/statistics |
| `create_watchlist` | Create a new named watchlist |
| `add_watchlist_item` | Add a single symbol to a watchlist |
| `bulk_replace_watchlist` | Replace all items in a watchlist with a new symbol set |
| `list_watchlist` | Get all items in the default watchlist |
| `get_watchlist_symbols` | Distinct symbols from the default watchlist |
| `remove_watchlist_item` | Remove an item from the default watchlist by ID |
| `list_watchlists` | List all user-created watchlists |
| `get_watchlist_items` | All items in a specific watchlist by ID |
| `get_notifications` | Unread notifications for a watchlist |
| `get_global_notifications` | Unread global NSE scan alerts across all stocks |
| `get_morningstar_fairvalue` | Morningstar fair value estimate for one or multiple symbols |
| `get_global_news` | Latest global news from MoneyControl and RSS sources |
| `get_company_news` | Company-specific news with NLP analysis |
| `list_industries` | All NSE industries with market cap, PE, and sentiment |
| `list_sectors` | All NSE sectors with market cap, PE, and sentiment |
| `get_industry_stocks` | All stocks in a given industry by slug |
| `get_sector_stocks` | All stocks in a given sector by slug |

**Note:** AI chat endpoints (`/api/ai/*`) are **not** exposed via MCP.

### Testing MCP

Use the MCP Inspector for local development:

```bash
cd backend
source .venv/bin/activate
uv run mcp dev app/mcp_server.py
```

Or call the JSON-RPC endpoint directly:

```bash
curl -X POST http://localhost:4455/api/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## Operational notes & caveats

- NSE requires careful HTTP headers and cookies. The `nse_client` module bootstraps a session by first visiting the NSE homepage and reuses cookies. Avoid heavy parallel scraping.
- The backend uses an async SQLAlchemy engine with `aiosqlite`; the DB file must be writable by the process.
- For production, run behind a reverse proxy, persist the DB or use a managed DB, and secure the server with proper access controls.

---

## Background Tasks

The backend runs several scheduled tasks defined in `app/backgroundtasks.py`:

### 1. Morningstar Fair Value Sync

Two async tasks sync fair values from Morningstar India:

- **`sync_watchlist_fair_values()`** — Runs at startup and periodically. Fetches fair values for all symbols in watchlists.
- **`sync_all_fair_values()`** — Runs once daily. Fetches fair values for the entire stock universe and resolves missing Morningstar IDs.

Both tasks use `rookiepy` to obtain browser cookies for Morningstar's authenticated API.

**Dev trigger:**
```python
from app.backgroundtasks import sync_watchlist_fair_values, sync_all_fair_values
# Call directly in a Python shell
```

### 2. Notification Worker

The notification worker monitors watchlist stocks for triggering events:

- **`notification_cycle_full()`** — Full check (all 11 trigger types) — runs hourly during market hours
- **`notification_cycle_reduced()`** — Reduced check (volume, 52w) — runs outside market hours

Triggers include: 52-week high/low breakouts, volume breakouts, top gainers/losers, bulk/block/short deals, insider trades.

- **Dev endpoint:** `POST /api/notifications/trigger` — manually triggers the notification cycle
- **Read notifications:** `GET /api/notifications?watchlist_id={id}`
- **Dismiss:** `DELETE /api/notifications/{notif_id}?watchlist_id={id}` or `DELETE /api/notifications?watchlist_id={id}&all=true`
- **Cleanup:** Read notifications older than 30 days are hard-deleted automatically

### 3. Stock Universe Sync

Runs periodically to populate the stock universe with NSE symbols and metadata.

---

## Database migrations

This project uses **Alembic** for schema migrations. All DDL is version-controlled; `create_all` is no longer used.

### How it works at startup

When the server starts, `main.py` calls `alembic upgrade head` via a sync thread before accepting any requests. This means:

- **Fresh install** — Alembic creates all tables from scratch and stamps the DB at `head`.
- **Existing DB without migration history** (legacy) — the startup helper detects the absence of `alembic_version`, stamps the DB at the `initial_schema` revision, then applies only the revisions that followed.
- **Already up-to-date DB** — `upgrade head` is a no-op (completes in milliseconds).

No manual migration step is needed in any of these cases.

### Migration history

```
<base>  →  aaf83c15d9f1  initial_schema
           ↓
        b7c94d23e8a2  last_update_time_nullable   ← head
```

View the full history at any time:

```bash
alembic history
alembic current   # shows which revision the live DB is on
```

---

### Adding a new column to an existing table

1. Edit the ORM model in `app/models/`:

   ```python
   # example: add isin to StockUniverse
   isin: Mapped[str | None] = mapped_column(String(20), nullable=True)
   ```

2. Autogenerate a migration:

   ```bash
   alembic revision --autogenerate -m "add_isin_to_stock_universe"
   ```

3. Review the generated file in `alembic/versions/`. For SQLite, column additions use `batch_alter_table` automatically (already configured via `render_as_batch=True`).

4. Apply immediately (optional — the server will also apply it on next start):

   ```bash
   alembic upgrade head
   ```

5. Commit the new revision file alongside the model change.

---

### Adding a new table

1. Create a new ORM model in `app/models/`, inheriting from `Base`:

   ```python
   from app.database import Base

   class MyNewTable(Base):
       __tablename__ = "my_new_table"
       id: Mapped[int] = mapped_column(primary_key=True)
       ...
   ```

2. Import the model in `alembic/env.py` so Alembic can see it:

   ```python
   from app.models import my_new_module  # noqa: F401
   ```

3. Autogenerate and review:

   ```bash
   alembic revision --autogenerate -m "add_my_new_table"
   # review alembic/versions/<rev>_add_my_new_table.py
   alembic upgrade head
   ```

---

### Modifying a column (type, nullability, rename)

SQLite does not support `ALTER COLUMN` natively. Alembic handles this transparently via **batch mode** (configured globally with `render_as_batch=True`): it recreates the table under a temporary name, copies data, drops the original, and renames.

```bash
alembic revision --autogenerate -m "make_sector_pe_not_null"
# Alembic emits a batch_alter_table block automatically
alembic upgrade head
```

For renames, autogenerate cannot infer intent — edit the generated file manually:

```python
with op.batch_alter_table("stock_universe") as batch_op:
    batch_op.alter_column("old_name", new_column_name="new_name", ...)
```

---

### Dropping a column or table

Autogenerate detects removals, but Alembic suppresses them by default to prevent accidental data loss. To enable:

```python
# in alembic/env.py _CONTEXT_OPTS, add:
"include_object": lambda obj, name, type_, reflected, compare_to: True,
```

Or write the `drop_column` / `drop_table` call manually in the revision file.

Always write a safe `downgrade()` function that restores the column/table if the migration needs to be rolled back:

```bash
alembic downgrade -1   # roll back one revision
alembic downgrade base  # roll back everything (destructive!)
```

---

### Rolling back a migration

```bash
alembic downgrade -1          # one step back
alembic downgrade aaf83c15d9f1  # back to a specific revision
alembic history               # list all revisions for reference
```

---

### Key files

| File | Purpose |
|---|---|
| `alembic.ini` | Alembic config — sets `sqlalchemy.url` from `settings.db_path` |
| `alembic/env.py` | Migration runtime — imports `Base`, all models, configures batch mode and type comparison |
| `alembic/versions/` | One `.py` file per revision; commit all of these |
| `main.py` `_run_migrations_sync()` | Calls `upgrade head` at every server startup |


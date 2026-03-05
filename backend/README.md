# BLM Analytics — Python FastAPI Backend

This lightweight FastAPI service provides NSE India analytics used by the BLM Terminal frontend. It fetches and caches NSE data (corporate filings CSVs, market snapshots, and the stock universe) and exposes a small REST surface under `/api/*`.

This README explains how to run the backend locally and lists all available endpoints with example requests.

---

## Prerequisites

- Python 3.11+ recommended
- A virtual environment (venv) or similar isolation
- Network access to `https://www.nseindia.com`

## Project layout (relevant files)

- `main.py` — FastAPI app entrypoint
- `app/config.py` — runtime settings (loaded from `.env`)
- `app/database.py` — async SQLAlchemy engine, `Base`, and `get_db()` dependency
- `app/models/` — ORM models (`corporatefilings.py`, `stockuniverse.py`)
- `app/routers/` — API routers (`corporatefilings.py`, `nonpersistence.py`, `stockuniverse.py`)
- `app/services/nse_client.py` — NSE HTTP client and helpers
- `.env.example` — example environment variables

---

## Environment

Copy `backend/.env.example` to `backend/.env` and adjust values as needed. Important variables:

- `NSE_BASE_URL` — base URL for NSE (default: `https://www.nseindia.com`)
- `DB_PATH` — SQLite DB file path used by this backend (default: `./data.db`)
- `PORT` — port the server listens on (default: `8000`)
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
source .venv/bin/activate
pip install -e ".[dev]"

# copy and edit .env as needed
cp .env.example .env

# run the server (reload in dev)
uvicorn main:app --reload --port ${PORT:-4455}
```

Notes:
- The app will create the SQLite database file indicated by `DB_PATH` and create tables on startup via `create_all_tables()`.
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

Examples:

```bash
curl http://localhost:4455/api/market/top-gainers
curl http://localhost:4455/api/market/bulk-deals/TCS
```

4) Stock universe (DB-backed)

- `GET /api/stockuniverse` — return all stock universe records (JSON array of objects)
- `GET /api/stockuniverse/{symbol}` — return a single record for `symbol` (404 if not found)
- `GET /api/stockuniverse/search/{prefix}` — search by symbol/company prefix

Examples:

```bash
curl http://localhost:4455/api/stockuniverse
curl http://localhost:4455/api/stockuniverse/RELIANCE
curl http://localhost:4455/api/stockuniverse/search/INF
```

5) Proxy via Next.js (developer convenience)

- If you run the Next.js dev server, the repo contains `src/app/api/py/[...path]/route.ts` which maps e.g.
  - `GET /api/py/market/top-gainers` → `http://localhost:4455/api/market/top-gainers`

Example — via Next.js dev server:

```bash
curl http://localhost:3000/api/py/market/top-gainers
```

---

## Operational notes & caveats

- NSE requires careful HTTP headers and cookies. The `nse_client` module bootstraps a session by first visiting the NSE homepage and reuses cookies. Avoid heavy parallel scraping.
- The backend uses an async SQLAlchemy engine with `aiosqlite`; the DB file must be writable by the process.
- Alembic migrations are not included in this README — if you rely on migrations, wire `alembic/env.py` to import `app.database.Base.metadata`.
- For production, run behind a reverse proxy, persist the DB or use a managed DB, and secure the server with proper access controls.

---

If you want, I can also:

- add a `requirements.txt` or `constraints.txt` for pip installs,
- add a small `docker-compose.yml` for running Next.js + the Python backend together,
- generate a minimal test suite for the routers (pytest + pytest-asyncio).


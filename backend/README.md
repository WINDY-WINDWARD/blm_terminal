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
- `app/backgroundtasks.py` — nightly stock universe sync scheduler
- `alembic/` — Alembic migration environment (`env.py`, `versions/`)
- `alembic.ini` — Alembic configuration
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
- For production, run behind a reverse proxy, persist the DB or use a managed DB, and secure the server with proper access controls.

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
| `alembic/env.py` | Migration runtime — imports `Base`, both models, configures batch mode and type comparison |
| `alembic/versions/` | One `.py` file per revision; commit all of these |
| `main.py` `_run_migrations_sync()` | Calls `upgrade head` at every server startup |



- add a `requirements.txt` or `constraints.txt` for pip installs,
- add a small `docker-compose.yml` for running Next.js + the Python backend together,
- generate a minimal test suite for the routers (pytest + pytest-asyncio).


# Background Task Offloading Plan

## Problem

Four background tasks currently run as `asyncio.create_task()` coroutines on the **same event loop** that handles HTTP requests:

| Task | Trigger | Lock held during |
|---|---|---|
| `stock_universe_scheduler` | Startup + daily midnight | `_db_lock` — entire symbol list iteration (thousands of symbols, each with a 1s sleep) |
| `news_scheduler` | Startup + every 5 min | `_db_lock` — global crawl (6 pages) + periodic crawl (1 page) |
| `watchlist_news_scheduler` | Startup + every 5 min | `_db_lock` — per-symbol news fetch with 2s sleep between symbols |
| `market_data_scheduler` | Startup + every 5 min (market hours only) | `_db_lock` — MoneyControl sector/industry fetch |

### Impact

- `_db_lock` is an `asyncio.Lock` — while held, **all** request handlers that need DB access are blocked
- `_nse_lock` in `nonpersistence.py` is also `asyncio.Lock` — NSE rate-limiting in background tasks competes with NSE requests from HTTP handlers
- `populate_stock_universe` at startup (first run) can take **30–60+ minutes**, blocking the event loop for that duration
- All scheduler loops (`while True: await asyncio.sleep(...)`) still run on the main event loop, competing with request handling

---

## Solution

Move all four background tasks into native `threading.Thread` workers, completely off the event loop.

```
┌──────────────────────────────────────────────────────────────┐
│  FastAPI / Uvicorn event loop (main thread)                   │
│  - Handles all HTTP requests                                   │
│  - On startup: spawns 4 daemon threads                        │
│  - On shutdown: signals shutdown + joins threads              │
└──────────────────────────────────────────────────────────────┘
         │ thread-safe Event / threading.Lock
         ▼
┌──────────────────────────────────────────────────────────────┐
│  BackgroundWorkerThread (daemon)                              │
│  - Owns its own NSEClient instance (no shared HTTP client)    │
│  - Owns its own sync SQLAlchemy Session                       │
│  - No asyncio.Lock — thread-safe primitives only              │
│  - Plain `while True: time.sleep(...)` loop                   │
└──────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Sync DB sessions for workers** — `aiosqlite` sessions cannot cross thread boundaries. Workers use `sqlalchemy.orm.sessionmaker(sync_engine)` instead.
2. **Thread-safe shutdown** — `threading.Event` signals workers to exit cleanly; no `asyncio.CancelledError` handling needed.
3. **Isolated NSE clients** — each worker creates its own `NSEClient` instance to avoid sharing the `httpx` async client.
4. **No `asyncio.Lock` in workers** — replaced with `threading.Lock` for the rare case a worker accesses shared in-memory state.
5. **MCP / router locks untouched** — `_nse_lock` in `nonpersistence.py` and `mcp_server.py` remain `asyncio.Lock` (correct for async context). They run on the event loop and will not contend with worker threads.

---

## Changes by File

### 1. `app/database.py`

**Add:** sync engine for background workers.

```python
# New — plain sync engine for use by background worker threads.
# Wraps the same SQLite file as the async engine.
_sync_engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
)

@sa_event.listens_for(_sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

_SyncSessionLocal = sessionmaker(bind=_sync_engine)
```

---

### 2. `app/backgroundtasks.py`

**Replace** the `async def` schedulers with plain `def` worker functions that run in threads.

#### Remove at top of file
```python
# REMOVE:
_db_lock = asyncio.Lock()
```

#### Remove all `async def` schedulers; add thread-safe sync versions

**`populate_stock_universe_sync()`** — plain `def` using `_SyncSessionLocal`:

```python
def populate_stock_universe_sync() -> None:
    """Thread-safe version using sync DB sessions and to_thread for NSE calls."""
    stock_list: list[str] = list(await_to_thread(_nse_client.get_stock_list))
    # ... same logic but:
    #   - use _SyncSessionLocal() instead of AsyncSessionLocal()
    #   - use time.sleep() instead of asyncio.sleep()
    #   - use threading.Lock() instead of asyncio.Lock
```

**`stock_universe_worker()`** — `while True: time.sleep(...)` loop:

```python
def stock_universe_worker() -> None:
    """Run in a daemon thread. Calls populate_stock_universe at startup then daily."""
    _populate_stock_universe_sync()
    while not _db_shutdown.is_set():
        wait = _seconds_until_midnight()
        if _db_shutdown.wait(timeout=wait):  # interruptible sleep
            break
        _populate_stock_universe_sync()
```

**`news_worker()`, `watchlist_news_worker()`, `market_data_worker()`** — same pattern.

**Helper for blocking NSE calls from a thread:**

```python
def await_to_thread(awaitable) -> Any:
    """Run an async awaitable in the default executor and return the result."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(awaitable)
    finally:
        loop.close()
```

#### New shutdown mechanism

```python
_db_shutdown = threading.Event()

def stop_all_workers(timeout: float = 10.0) -> None:
    _db_shutdown.set()
    for t in _worker_threads:
        t.join(timeout=timeout)
```

---

### 3. `main.py`

**Remove** background tasks imports (no longer used):

```python
# REMOVE:
from app.backgroundtasks import (
    market_data_scheduler,
    news_scheduler,
    stock_universe_scheduler,
    watchlist_news_scheduler,
)
```

**In `lifespan()` — replace `asyncio.create_task()` with thread spawning:**

```python
from app.backgroundtasks import start_all_workers, stop_all_workers

# In lifespan startup:
worker_threads = start_all_workers()
cleanup_task = await start_cache_cleanup()  # stays async — only iterates in-memory dict

# In lifespan shutdown:
cleanup_task.cancel()
stop_all_workers(timeout=10.0)
```

**Add `_ensure_watchlist_data` call via `asyncio.to_thread`** (already done, keep as-is).

---

### 4. `app/routers/nonpersistence.py`

**No changes needed.** The `_nse_lock` and `_throttled_call` are already async-safe and run on the event loop. Worker threads don't share the `httpx` session with this router.

---

## Summary of Changes

| File | Lines changed (approx) | Nature |
|---|---|---|
| `app/database.py` | +20 | Add `_sync_engine`, `_SyncSessionLocal`, PRAGMA event handler |
| `app/backgroundtasks.py` | -150 / +180 | Convert all 4 schedulers from `async def` to `def`, swap locks, swap sleep, add threading primitives |
| `main.py` | -15 / +15 | Replace `asyncio.create_task()` with `threading.Thread` spawn/join |

**Total net: ~+50 lines**, with significantly better runtime isolation.

---

## Startup Behavior Change

| Before | After |
|---|---|
| `stock_universe_scheduler` runs **synchronously** at startup inside `lifespan` — first HTTP request waits 30–60+ min | `stock_universe_worker` runs in a **daemon thread** — HTTP requests served immediately |

> **Note:** If you want the old blocking-at-startup behavior for `stock_universe` (e.g., to populate data before serving any requests), add a `wait_for_initial_sync: bool = True` option to `start_all_workers()` that calls `populate_stock_universe_sync()` directly in the lifespan before spawning the worker thread.

---

## Verification Plan

```bash
cd backend
source .venv/bin/activate

# Start server — should accept requests immediately
uvicorn main:app --reload --port 4455

# In another terminal, check startup logs show workers started
tail -f logs/backend.log | grep -E "worker|scheduler|started"

# Make a request while background work runs — should be fast
curl http://localhost:4455/health

# Check that DB writes from workers don't block API requests
# (monitor request latency with the access logger in logs/backend.log)
```

---

## Rollback Plan

If issues arise, revert `main.py` and `app/backgroundtasks.py` to the `asyncio.create_task()` approach. The `app/database.py` addition (sync engine) is harmless — it doesn't affect async paths.

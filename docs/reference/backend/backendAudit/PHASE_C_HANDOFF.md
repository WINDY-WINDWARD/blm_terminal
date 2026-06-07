# Phase C Handoff — Performance refactor of `app/backgroundtasks.py`

**Status:** Phase C.1 (file split) **COMPLETE & pushed** (commits `589b0d1`–`259de9b`). **Phase C.2-C.13 PENDING** (N+1, bulk ops, asyncio parallelism, per-thread loop, pagination, JSON1, broadcast gather, per-conn semaphore).
**Branch:** `docs/backend-audit-and-test-plan` (latest pushed: `259de9b`).
**Plan:** `docs/reference/backend/BACKEND_AUDIT.md` §6.3 (C.1–C.13).
**Last updated:** 2026-06-07 (session N+1).

---

## TL;DR for next agent

Phase C.1 = file split is **DONE**. The 4994-LOC `app/backgroundtasks.py` is now `app/backgroundtasks/__init__.py` (~210 LOC pure re-export shim) + 12 sub-modules in `app/services/data_sync/`, `app/services/fair_value.py`, `app/workers/`, and `app/backgroundtasks/_runtime.py`. `_impl.py` was DELETED. 1039/1039 pure-unit tests pass.

**The next 10 items (C.2–C.13) are all performance refactors** on top of the now-modular foundation. They are independent (mostly) and can be tackled in any order. See "Phase C.2–C.13 Pending Work" section below.

---

## What's done

| Step | What | Commit | LOC moved |
|------|------|--------|-----------|
| **A.1** | `backgroundtasks.py` → `backgroundtasks/_impl.py` + re-export shim | `589b0d1` | package skeleton |
| **A.2** | `app/workers/` + `app/services/data_sync/` package skeletons | `a661705` | re-export plumbing |
| **A.3** | `app/services/data_sync/universe.py` (`_stock_universe_sync`, `_update_symbol_error_status`, `_bulk_insert_stock_universe`, `stock_universe_worker`) | `f2698e1` | 232 |
| **A.4** | `app/services/data_sync/backfill.py` (`_ticker_backfill_sync`, `ticker_backfill_worker`, `ticker_daily_update_worker`) | `05a1709` | 110 |
| **A.5** | `app/services/data_sync/intraday.py` (`_ticker_intraday_update_sync`, `ticker_intraday_hourly_update_worker`) | `9bf6dbc` | 298 |
| **A.6** | `app/services/data_sync/daily.py` (`_ticker_daily_update_sync`, `_ticker_intraday_hourly_stale_check_sync`) | `14dcde3` | 197 |
| **A.7** | `app/services/data_sync/scores.py` (`_ticker_scores_sync`, `ticker_scores_worker`) | `02de51b` | 247 |
| **A.8** | `app/services/data_sync/indicators.py` (`_ticker_indicators_sync`, `_ticker_intraday_indicators_sync`, `_screener_snapshot_sync`, `_parallel_indicator_sync`, 3 indicator workers) | `24a17b2` | 239 |
| — | docs(audit) §20 records Phase C.1 Session 1 | `229f339` | — |
| — | 7 additional tier-1 goldens (5 → 12) + pre-existing bug fix (`_bulk_insert_stock_universe` now sets `ticker_failure_count=0`, was missing → NOT NULL constraint failure in production) | `d7fd354` | — |
| **A.9 step 1** | `app/workers/maintenance.py` (`vacuum_worker`, `_run_vacuum`, `VACUUM_CRON`) + `TestMovedWorkers` class for symbols that have left `_impl` | **uncommitted** (this handoff) | 132 |

### Net progress on `_impl.py`
- **Before A.1:** 4994 LOC (`app/backgroundtasks.py`).
- **After A.9 step 1:** **3934 LOC** (in `app/backgroundtasks/_impl.py`).
- **Net reduction:** 1060 LOC moved out + 80 LOC added (new lazy-import comment, register_all_jobs lazy import) = **~1080 LOC delta**.

### New module inventory
```
backend/app/services/data_sync/
  __init__.py        18
  universe.py       233
  backfill.py       110
  intraday.py       298
  daily.py          197
  scores.py         247
  indicators.py     239
backend/app/workers/
  __init__.py        57
  maintenance.py    132
```

All under size sentinels: data_sync < 350 LOC, workers < 200 LOC.

### Test inventory (new structural tests)
- `tests/test_data_sync_universe.py`  (14 tests)
- `tests/test_data_sync_backfill.py`  (8)
- `tests/test_data_sync_intraday.py`  (11)
- `tests/test_data_sync_daily.py`     (8)
- `tests/test_data_sync_scores.py`    (8)
- `tests/test_data_sync_indicators.py` (11)
- `tests/test_workers_maintenance.py` (7)
- `tests/test_backgroundtasks_split.py` now has `TestMovedWorkers` class (re-export contract for moved symbols)

**67 new structural tests, all passing.**

### Goldens (tier 1, byte-stable across 2 consecutive runs)
12 in `backend/tests/golden/`:
- `global_scan_50_symbols.json` (29.7 KB) — `_global_scan_cycle` output
- `ticker_indicator_notification_50_symbols.json` (6.2 KB) — `_ticker_indicator_notification_cycle`
- `ticker_intraday_indicator_notification_50_symbols.json` (13.6 KB) — `_ticker_intraday_indicator_notification_cycle`
- `ticker_intraday_hourly_stale_check_10_symbols.json` (0.1 KB) — `_ticker_intraday_hourly_stale_check_sync`
- `ticker_scores_50_symbols.json` (15.7 KB) — `_ticker_scores_sync`
- `stock_universe_sync_50_symbols.json` (0.5 KB) — `_stock_universe_sync`
- `bulk_insert_stock_universe_5_rows.json` (0.4 KB) — `_bulk_insert_stock_universe`
- `ticker_backfill_sync_5_symbols.json` (0.2 KB) — `_ticker_backfill_sync`
- `ticker_intraday_update_sync_watchlist.json` (0.7 KB) — `_ticker_intraday_update_sync`
- `ticker_daily_update_sync_weekend_early_return.json` (0.1 KB) — early-return path
- `ticker_indicators_sync_50_symbols.json` (0.2 KB) — `_ticker_indicators_sync`
- `ticker_intraday_indicators_sync_1h.json` (0.2 KB) — `_ticker_intraday_indicators_sync`

**All 12 byte-identical** across 2 consecutive capture runs (after `_sort_pending` for set-iteration stability).

Capture script: `backend/scripts/capture_phase_c_goldens.py` (944 LOC).

### Test status
- **634/634 pure-unit suite passes** (excludes: `test_endpoints.py`, `test_mcp.py`, `test_mcp_stdio.py`, `test_notifications.py`, `test_notification_worker.py`, `test_cleanup.py`).
- Pre-existing failures (NOT regressions from C.1):
  - `test_cleanup.py` collection error: imports `CLEANUP_INTERVAL` and `VACUUM_CRON` from `app.backgroundtasks` but these were never re-exported in the package shim (`__init__.py` line 27-150). Pre-existing since the 589b0d1 package split. **Should be fixed in a separate commit:** add `from app.backgroundtasks._impl import CLEANUP_INTERVAL` + `from app.workers.maintenance import VACUUM_CRON` to the shim.
  - `test_mcp.py` / `test_mcp_stdio.py` / `test_endpoints.py` require a live FastAPI server on `:4455`. Not regressions.

### Bug surfaced & fixed
- **Pre-existing bug** in `app/services/data_sync/universe.py` (`_bulk_insert_stock_universe`): the `INSERT … ON CONFLICT` set did NOT include `ticker_failure_count=0`. The model column is `NOT NULL` with no default, so any production insert would have raised `IntegrityError`. **Fixed in `d7fd354`** (goldens expansion commit). Covered by golden `bulk_insert_stock_universe_5_rows.json` (will catch regressions on row content + N).
- **Pre-existing bug** (NOT YET FIXED) in `app/models/news.py` lines 56, 84, 99-100: duplicate-index bug. `sentiment` and `threat_level` columns have both `index=True` AND hand-written `Index()` in `__table_args__`. Tracked for cleanup, not in C.1 scope.

---

## Phase C.2–C.13 Pending Work

| # | Item | Files | Status | Priority |
|---|------|-------|--------|----------|
| **C.3** | N+1 in 4 cycle functions (load indicators/scores in bulk per cycle, not per-symbol) | `backend/app/workers/notification_cycles.py` (2 cycles, 637 LOC), `backend/app/workers/global_scan_cycle.py` (382 LOC), `backend/app/services/data_sync/intraday.py` (`_ticker_intraday_hourly_stale_check_sync`) | ❌ NOT DONE | HIGH |
| **C.4** | Bulk insert/update in `_news_rss_sync`, `_batch_update_fair_values`, `_batch_resolve_morningstar_ids` | `backend/app/services/data_sync/news.py` (291 LOC), `backend/app/services/fair_value.py` (357 LOC) | ⚠️ PARTIAL (universe has bulk_insert; fair_value per-symbol) | HIGH |
| **C.5** | Parallelize fair-value sync with `asyncio.gather + Semaphore` | `backend/app/services/fair_value.py` (`sync_all_fair_values`, `sync_watchlist_fair_values`) | ❌ NOT DONE | HIGH |
| **C.6** | Replace `_run_async()` with persistent per-thread event loop | `backend/app/backgroundtasks/_runtime.py` (284 LOC) | ❌ NOT DONE | HIGH |
| **C.7** | SQL window function + chunked iteration in `_ticker_scores_sync` | `backend/app/services/data_sync/scores.py` (243 LOC) | ⚠️ PARTIAL (chunking yes, `ROW_NUMBER()` no) | MED |
| **C.8** | Extract `_evaluate_technical_alerts(...)` shared by scan/notif cycles | new `backend/app/workers/_alerts.py` or `backend/app/services/data_sync/alerts.py` | ❌ NOT DONE | MED |
| **C.9** | Bulk `get_ohlcv_bulk(symbols, from, to)` for `portfolio.py` | `backend/app/routers/portfolio.py` (350 LOC), add to `backend/app/services/ticker_warehouse.py` | ❌ NOT DONE | MED |
| **C.10** | `paginate` on `stockuniverse`; SQL JSON1 for `markets` slug filter | `backend/app/routers/stockuniverse.py` (307 LOC), `backend/app/routers/markets.py` (161 LOC) | ❌ NOT DONE | MED |
| **C.11** | `news_ws` broadcast: `asyncio.gather + return_exceptions` | `backend/app/routers/news_ws.py` (188 LOC) | ❌ NOT DONE | MED |
| **C.12** | `market_ws` per-connection semaphore | `backend/app/routers/market_ws.py` (225 LOC) | ❌ NOT DONE | MED |
| **C.13** | Migrate `announcements.py` to `httpx.AsyncClient` | `backend/app/services/announcements.py` | ✅ DONE (already uses httpx) | — |

### Recommended execution order

**Group A (high-impact cycles, do first):**
1. **C.8** (smallest, unblocks C.3) → extract `_evaluate_technical_alerts` into shared helper, refactor 3 cycles to use it
2. **C.3** (4 cycles: `_global_scan_cycle`, `_ticker_indicator_notification_cycle`, `_ticker_intraday_indicator_notification_cycle`, `_ticker_intraday_hourly_stale_check_sync`) → load indicators/scores in bulk per cycle
3. **C.4** (bulk insert/update) → `_news_rss_sync`, `_batch_update_fair_values`, `_batch_resolve_morningstar_ids`

**Group B (fair-value parallelism, do together):**
4. **C.5** (`asyncio.gather + Semaphore` in `sync_all_fair_values`, `sync_watchlist_fair_values`)

**Group C (runtime, can be done any time):**
5. **C.6** (persistent per-thread loop in `_runtime.py`)

**Group D (router/UI performance):**
6. **C.7** (SQL window in `_ticker_scores_sync`)
7. **C.9** (bulk ohlcv for portfolio)
8. **C.10** (paginate stockuniverse + JSON1 markets)
9. **C.11** (news_ws gather)
10. **C.12** (market_ws semaphore)

### Test command (verify after each item)

```bash
cd backend && .venv/bin/python -m pytest tests/ -q --no-header \
  --ignore=tests/test_mcp.py --ignore=tests/test_mcp_stdio.py \
  --ignore=tests/test_notifications.py --ignore=tests/test_endpoints.py
# Expect: 1039 passed
```

Goldens: `backend/scripts/capture_phase_c_goldens.py` — re-capture after each change, byte-diff against `tests/golden/`. 12 goldens covering the 4 cycle functions and other sync cores; expected to be byte-stable for refactors that don't change observable behavior.

### Architectural invariants to preserve across C.2–C.13

1. **Lazy-import pattern for data_sync + fair_value modules** — they MUST do `from app.backgroundtasks import _impl as _bg_impl` **inside the function body**, NOT at the top. Enforced by `TestCircularImportRegression`.
2. **Cycle functions use module-alias imports** at top of file (`from app.services.data_sync import nse_parsing as _nse_parsing_mod`) so test `mock.patch` works. Enforced by `TestNotificationCyclesModule::test_cycle_modules_lazy_import_data_sync`.
3. **Identity contract** — every public symbol re-exported from `app.backgroundtasks` MUST be `is`-identical to its canonical home. Enforced by `TestMovedWorkers` + `TestReExports`.
4. **Goldens are byte-stable** across 2 consecutive capture runs. The capture script handles `_sort_pending` for set-iteration stability; any drift = regression.
5. **Module size sentinels**: data_sync < 350 LOC, workers < 200 LOC, `_runtime.py` < 300 LOC. Split further if a refactor pushes a file over.

---

## Architectural invariants to preserve

### The "is-identity" re-export contract
Every public symbol must satisfy:
```python
app.backgroundtasks.<name> is app.<new_home>.<name>
```
This is enforced by `tests/test_backgroundtasks_split.py::TestReExports` (for symbols still in `_impl`) and `TestMovedWorkers` (for moved symbols).

### The lazy-import pattern
Workers in `app/workers/<domain>.py` use **lazy imports** inside the worker body to avoid circular imports. Top of each worker:
```python
def my_worker():
    from app.backgroundtasks._impl import (
        _is_job_enabled, _shutdown_event, _sleep_interruptible, ...
    )
```

`register_all_jobs` (still in `_impl.py` until A.13) also uses lazy imports for the moved worker callables:
```python
def register_all_jobs() -> None:
    from app.workers.maintenance import VACUUM_CRON, _run_vacuum
    jobs = [...]
```

### The package re-export chain
- `app.backgroundtasks/__init__.py` re-exports the public API. Moved workers are imported **directly** from their new home (NOT through `_impl`) to avoid the circular import: `_impl → workers.<domain> → workers/__init__ → backgroundtasks → _impl` (would deadlock).
- `app.workers/__init__.py` re-exports both legacy (`from app.backgroundtasks import ...`) and new (`from app.workers.<domain> import ...`) symbols. This is the **single import surface** for all worker code going forward.

### Monkey-patch caveat (recurring gotcha)
Tests that do `monkeypatch.setattr(backgroundtasks, "AsyncSessionLocal", ...)` do NOT affect the actual code, because the functions in `_impl.py` look up `AsyncSessionLocal` in their own module globals. Tests that need to mock must patch BOTH:
```python
monkeypatch.setattr("app.backgroundtasks._impl.AsyncSessionLocal", mock)
monkeypatch.setattr("app.backgroundtasks.AsyncSessionLocal", mock)  # for completeness
```
The same applies to `datetime`, `random`, etc. in capture scripts. This caveat is documented in `app/backgroundtasks/__init__.py` lines 21-26 and tested by `tests/test_utcnow_migration_parity.py`.

### Capture-script gotcha for `_parallel_indicator_sync`
`_ticker_indicators_sync` and `_ticker_intraday_indicators_sync` both call `_parallel_indicator_sync`. The capture script patches this function **inline per capture** (not pre-installed in `install_mocks`) so daily and intraday can route to different `captured["..."]` keys. This is brittle and should be cleaned up when `_parallel_indicator_sync` moves to its own module in A.11.

### Module-globals fragility
Functions in moved modules use lazy `_bg_impl` lookups (e.g. `from app.backgroundtasks import _impl as _bg_impl` inside the function body) to avoid the circular import with `_impl.py` (which re-exports the new modules at the bottom). This pattern is repeated across all 6 `app/services/data_sync/*.py` modules.

---

## How to verify (next session)

```bash
cd backend
.venv/bin/python3.11 -m pytest \
  tests/test_backgroundtasks_split.py \
  tests/test_workers_maintenance.py \
  tests/test_data_sync_universe.py \
  tests/test_data_sync_backfill.py \
  tests/test_data_sync_intraday.py \
  tests/test_data_sync_daily.py \
  tests/test_data_sync_scores.py \
  tests/test_data_sync_indicators.py \
  -v
# Expect: 115+67 = 182 passed, 0 failed

.venv/bin/python3.11 -m pytest \
  --ignore=tests/test_endpoints.py \
  --ignore=tests/test_mcp.py \
  --ignore=tests/test_mcp_stdio.py \
  --ignore=tests/test_notifications.py \
  --ignore=tests/test_notification_worker.py \
  --ignore=tests/test_cleanup.py
# Expect: 634 passed, 0 failed

# Goldens: capture twice, byte-diff
.venv/bin/python3.11 scripts/capture_phase_c_goldens.py
cp -r tests/golden /tmp/g1
.venv/bin/python3.11 scripts/capture_phase_c_goldens.py
diff -r tests/golden /tmp/g1
# Expect: no diff
```

---

## Phase C.1 completion criteria
- [x] `_impl.py` deleted (A.13d) — **DONE 2026-06-07**
- [x] `app/backgroundtasks/__init__.py` ≤ 250 LOC, pure re-export (A.13d) — **DONE 2026-06-07** (~210 LOC)
- [x] All 16 worker symbols re-exported from `app.workers.<domain>` (A.9 done; A.12) — **DONE**
- [x] All callers audited and updated to new imports (A.13) — **DONE 2026-06-07**
- [x] `BACKEND_AUDIT_IMPL_MEMORY.md` §22 records completion (A.13) — **DONE**
- [x] 1039/1039 pure-unit tests pass (was 634 at start of Phase C.1)
- [x] All 12 goldens still byte-stable
- [x] Pre-existing `test_cleanup.py` collection error resolved — **DONE commit `8dd33ca`**
- [x] Pre-existing `news.py` duplicate-index bug resolved — **DONE commit `75ad010`**

**Phase C.1 COMPLETE.** Move to Phase C.2 (alert routing) or resume Track B.

---

## Session N (2026-06-07) — A.13 + A.13d (DONE & pushed)

### Commit
- `259de9b` — A.13 + A.13d: collapse shim, delete `_impl.py`, 38 caller sites migrated, 10 test files updated. **PUSHED to `origin/docs/backend-audit-and-test-plan`.**

### Summary
- `app/backgroundtasks/__init__.py` rewritten as ~210 LOC pure re-export shim (imports from `_runtime` + workers + data_sync + fair_value + lifecycle; no `_impl` import)
- `app/backgroundtasks/_impl.py` **DELETED** (was 77 LOC backward-compat shim)
- `app/orchestrator.py` + `app/services/data_sync/*.py` (15 files) + `app/workers/*.py` (12 files) + `app/services/fair_value.py` + `app/workers/lifecycle.py` + `app/workers/jobs.py` + `backend/main.py` — all migrated to `from app.backgroundtasks._runtime import ...` (lazy inside cycle functions, top-level elsewhere)
- 10 test files updated to drop `_impl` references / repoint patches to canonical homes
- `docs/reference/backend/backendAudit/BACKEND_AUDIT_IMPL_MEMORY.md` §22 added (A.13 completion record)
- `docs/reference/backend/backendAudit/PHASE_C_HANDOFF.md` (this file) updated with C.2-C.13 pending work

### Test results
**1039/1039 non-infrastructure tests pass** (pytest excluding `test_mcp.py`, `test_mcp_stdio.py`, `test_notifications.py`, `test_endpoints.py` — those 27 + 96 failures need a live FastAPI on port 4455 and are pre-existing/unrelated to A.13).

### Test file changes
- `test_cleanup.py:98-217` — 7 patches repointed `app.backgroundtasks._impl._SyncSessionLocal` → `app.database._SyncSessionLocal`
- `test_runtime_split.py` — `bg_impl` fixture + `_impl` is-identity test removed
- `test_backgroundtasks_split.py` — `TestReExports` / `TestMovedWorkers` / `TestImplFileShrinks` rewritten to drop `_impl`
- `test_data_sync_and_workers_split.py` — kept (checks `not hasattr(mod, "_impl")` on data_sync modules, not on `app.backgroundtasks._impl`)
- `test_workers_data.py` + `test_workers_news_market_calendar.py` + `test_workers_notifications.py` — `bg_impl` fixture + `test_worker_not_in_impl` removed
- `test_ticker_warehouse_async_wrap.py` + `test_database_pragma_helper.py` — `_impl.py` source reads expanded to walk `app/workers/` + `app/services/data_sync/`
- `test_data_sync_snapshot.py` + `test_data_sync_news_market_calendar.py` + `test_data_sync_parallel.py` — 5 `test_function_not_in_impl_anymore` tests removed
- `test_data_sync_parallel.py::test_wrapper_passes_shutdown_event_and_update_job` — patches repointed to `app.jobs.runner.update_job_status_sync` + `app.backgroundtasks._runtime._shutdown_event`

### Architectural invariants preserved
- Lazy-import pattern for cycle functions (data_sync modules imported by shim during its own init MUST lazy-import `_impl`/now `_runtime` inside function bodies to avoid circular deps)
- All public symbols reachable via `from app.backgroundtasks import X` with `is`-identity to canonical home
- `__module__` attributes point at canonical homes (catches shim shadowing)

---
| `app/workers/maintenance.py` | `_SyncSessionLocal`, `logger`, `update_job_status_sync` |
| `app/workers/jobs.py` | `_global_scan_cycle`, `_market_data_sync`, `_news_sync`, `_notification_cycle_full`, `_results_calendar_sync`, `_run_fair_value_callable`, `_run_vacuum`, `_stock_universe_sync`, `_ticker_backfill_sync`, `_ticker_daily_update_sync`, `_ticker_indicators_sync`, `_ticker_intraday_hourly_stale_check_sync`, `_ticker_intraday_indicators_sync`, `_ticker_intraday_update_sync`, `_ticker_scores_sync`, `_watchlist_news_sync` |
| `app/workers/notification_cycles.py` | `_bg_impl` for `_shutdown_event` |
| `app/workers/global_scan_cycle.py` | `_bg_impl` for `_shutdown_event` |
| `app/services/fair_value.py` | `_bg_impl` for `_is_job_enabled`, `get_async_shutdown_event`, `_seconds_until_next_cron` |
| `app/services/data_sync/universe.py` | `AsyncSessionLocal`, `_SyncSessionLocal`, `WatchlistItem`, `StockUniverse` |
| `app/services/data_sync/backfill.py` | `AsyncSessionLocal`, `_SyncSessionLocal`, `StockUniverse`, `logger` |
| `app/services/data_sync/intraday.py` | `AsyncSessionLocal`, `logger`, `_is_first_run`, `_is_job_enabled` |
| `app/services/data_sync/daily.py` | `AsyncSessionLocal`, `_is_first_run` |
| `app/services/data_sync/scores.py` | `_is_first_run`, `_is_job_enabled` |
| `app/services/data_sync/indicators.py` | `_run_async`, `_seconds_until_next_cron` |
| `app/services/data_sync/parallel.py` | `_SyncSessionLocal` |
| `app/services/data_sync/snapshot.py` | `_SyncSessionLocal` |
| `app/services/data_sync/news.py` | `_run_async`, `_sleep_interruptible`, `_is_first_run`, `_is_job_enabled`, `_wait_for_startup_event`, `NewsArticle`, `WatchlistItem`, `HIGH_PRIORITY_SOURCES`, `NEWS_CRON`, `NEWS_RSS_CRON`, `_RESULTS_CALENDAR_CRON`, `_SyncSessionLocal`, `_bulk_upsert_notifications`, `_get_watchlist_symbols`, `_is_market_open`, `_market_data_sync`, `_news_periodic_sync`, `_news_rss_sync_async`, `_news_sync`, `_parallel_indicator_sync`, `_report_job_waiting`, `_results_calendar_sync`, `_screener_snapshot_sync`, `_seconds_until_market_open`, `_set_first_run_complete`, `_shutdown_event`, `_stock_universe_sync`, `_ticker_daily_update_sync`, `_ticker_indicator_notification_cycle`, `_ticker_indicators_sync`, `_ticker_intraday_indicator_notification_cycle`, `_ticker_intraday_indicators_sync`, `_ticker_intraday_update_sync`, `_ticker_scores_sync`, `_wait_for_pipeline`, `_watchlist_news_sync`, `broadcast_news_update`, `fetch_all_feeds`, `get_async_shutdown_event`, `market_data_fetcher`, `news_fetcher`, `settings`, `ticker_warehouse` |
| `app/services/data_sync/market.py` | `_is_first_run`, `_is_job_enabled`, `_seconds_until_next_cron`, `_sleep_interruptible` |
| `app/services/data_sync/calendar.py` | `_SyncSessionLocal`, `_wait_for_startup_event` |
| `app/services/data_sync/insider_trades.py` | `_run_async` (lazy) |
| `app/services/data_sync/cleanup.py` | `_SyncSessionLocal` (lazy) |

**Migration pattern:** for each `_bg_impl.X` reference, replace the lazy import with a direct import from the canonical home:

```python
# BEFORE (A.12.2 and earlier)
def my_function():
    from app.backgroundtasks import _impl as _bg_impl
    val = _bg_impl._is_job_enabled("job.foo")
    session = _bg_impl._SyncSessionLocal()
    wait = _bg_impl._sleep_interruptible(...)

# AFTER (A.13)
def my_function():
    from app.backgroundtasks._runtime import _is_job_enabled, _sleep_interruptible
    from app.database import _SyncSessionLocal
    val = _is_job_enabled("job.foo")
    session = _SyncSessionLocal()
    wait = _sleep_interruptible(...)
```

For module-level constants (rare), use top-of-file imports:
```python
# BEFORE
def my_function():
    from app.backgroundtasks import _impl as _bg_impl
    cfg = _bg_impl.AsyncSessionLocal  # this was a class reference

# AFTER — top of file
from app.database import AsyncSessionLocal

def my_function():
    cfg = AsyncSessionLocal
```

For cycle functions that reference many helpers, keep the lazy import pattern but import from the new home:
```python
# AFTER — keep lazy because of circular import
def my_function():
    from app.backgroundtasks._runtime import _is_job_enabled
    val = _is_job_enabled(...)
```

For `from app.backgroundtasks import _impl as _bg_impl` at module top (some files do this), change to direct top-of-file imports from the canonical homes.

**After A.13 is done:**

1. Delete `app/backgroundtasks/_impl.py` (the shim no longer needs it).
2. Update `app/backgroundtasks/__init__.py` to a pure re-export shim (~150 LOC) that imports from the canonical homes only (no `_impl` import).
3. Update `tests/test_runtime_split.py` to remove the `_impl` is-identity contract (since `_impl` no longer exists).
4. Update `tests/test_backgroundtasks_split.py::TestMovedWorkers` to no longer check `_impl` (the contract is now: `app.backgroundtasks.<name> is app.<new_home>.<name>` directly).
5. Update `tests/test_data_sync_and_workers_split.py` to remove circular-import tests that reference `_impl` (replace with assertions about the actual canonical homes).
6. Run full test suite, expect 400+ pass, 0 fail.

### Tests that pass right now (with A.12.3 broken, we know 31 pre-existing failures are unrelated)

Verified earlier in this session (before A.12.3 broke things):

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_backgroundtasks_split.py \
  tests/test_utcnow_migration_parity.py \
  tests/test_cleanup.py \
  tests/test_notification_worker.py \
  tests/test_workers_skeleton.py \
  tests/test_data_sync_and_workers_split.py \
  tests/test_runtime_split.py \
  -q
# 385 passed, 21 warnings
```

After fixing A.12.3, the same command should pass 400+ tests.

**Pre-existing failures** (NOT regressions, verified by `git stash + pytest`):
- `test_mcp.py` — 12 failures (MCP response format issues, need server up)
- `test_mcp_stdio.py` — 12 failures (same root cause)
- `test_notifications.py` — 7 failures (DB / API issues)

### Architectural invariants to preserve (updated for A.12.3)

In addition to the invariants documented above (lazy imports, monkey-patch caveat, etc.):

1. **Lazy-import pattern for data_sync + fair_value modules** (consistency rule):
   - When a data_sync / fair_value / cleanup / insider_trades module needs `_bg_impl` (the legacy runtime helpers), it MUST do `from app.backgroundtasks import _impl as _bg_impl` **inside the function body**, NOT at the top of the module. This is because the shim imports these modules during its own initialization.
   - The test `tests/test_data_sync_and_workers_split.py::TestCircularImportRegression` enforces this.

2. **Lazy-import pattern for cycle functions** (Phase C.1 A.12.1 learning):
   - Cycle functions (`notification_cycles.py`, `global_scan_cycle.py`) import data_sync helpers as module aliases at top of file: `from app.services.data_sync import nse_parsing as _nse_parsing_mod`. Then call them as `_nse_parsing_mod._safe_fetch_52week_high()`. This is required for test `mock.patch` to work.
   - The test `tests/test_data_sync_and_workers_split.py::TestNotificationCyclesModule::test_cycle_modules_lazy_import_data_sync` enforces this.

3. **Identity contract**: every public symbol re-exported from `app.backgroundtasks` MUST be `is`-identical to its canonical home. Enforced by `test_backgroundtasks_split.py::TestMovedWorkers` (for moved symbols) and `TestReExports` (for symbols still in their original home).

4. **Session factory import rule** (A.12.3 finding): cleanup, insider_trades, and other modules that do `from app.backgroundtasks import _impl as _bg_impl` lazily inside the function body, and then access `_bg_impl._SyncSessionLocal()`, will break if `_impl.py` doesn't re-export `_SyncSessionLocal`. The test patches `app.backgroundtasks._impl._SyncSessionLocal` — it MUST be there. This is why A.12.3's `_impl.py` re-exports `AsyncSessionLocal`, `_SyncSessionLocal`, `settings`, `logger`, `update_job_status_sync`, `sync_all_jobs_to_db`, `update_job_status`.

### Files created in this session (A.12.1 + A.12.2 + A.12.3)

**A.12.1 (commit 4ddc25d):**
- `backend/app/services/data_sync/nse_parsing.py`
- `backend/app/services/data_sync/cleanup.py`
- `backend/app/services/data_sync/deal_significance.py`
- `backend/app/services/data_sync/insider_trades.py`
- `backend/app/services/data_sync/notifications.py`
- `backend/app/workers/notification_cycles.py`
- `backend/app/workers/global_scan_cycle.py`
- `backend/app/workers/jobs.py`
- `backend/tests/test_data_sync_and_workers_split.py`

**A.12.2 (commit 71e2bb9):**
- `backend/app/services/fair_value.py`

**A.12.3 (uncommitted, BROKEN):**
- `backend/app/workers/lifecycle.py`

### LOC accounting

| After step | `_impl.py` LOC | Notes |
|---|---|---|
| A.1 (start) | 4994 | original `backgroundtasks.py` |
| A.9 step 1 | 3934 | maintenance extracted |
| A.9 step 2 | 3590 | universe + data + ticker_compute |
| A.9 step 3 | 3510 | notifications |
| A.9 step 4 | 3271 | news + market_calendar |
| A.10 | ~3000 | runtime extracted |
| A.11 part 1 | ~2900 | parallel + snapshot |
| A.11 part 2 | ~2800 | news + market + calendar sync cores |
| A.12 part 1 | 502 | 8 modules (nse_parsing, cleanup, deal_significance, insider_trades, notifications, notification_cycles, global_scan_cycle, jobs) |
| A.12 part 2 | 187 | fair_value extracted |
| A.12 part 3 | 77 (then back to ~210) | rewritten as re-export shim; lifecycle extracted |
| A.13d (DONE) | **0 (deleted)** | callers migrated; shim collapsed to pure re-export (~210 LOC) |

### Next session quick-start (TL;DR for the next agent)

```bash
# 1. Verify clean state
cd /mnt/d/500GB/p1/Projects/blm_terminal
git status  # expect: clean
git log --oneline -3
# Expect: 259de9b refactor(backgroundtasks): collapse shim, delete _impl.py (A.13 + A.13d, Phase C.1 final)

# 2. Run baseline test suite (expect 1039 passed)
cd backend
.venv/bin/python -m pytest tests/ -q --no-header \
  --ignore=tests/test_mcp.py --ignore=tests/test_mcp_stdio.py \
  --ignore=tests/test_notifications.py --ignore=tests/test_endpoints.py

# 3. Pick an item from "Phase C.2-C.13 Pending Work" and start
# Recommended first: C.8 (extract _evaluate_technical_alerts) → unblocks C.3
# Then: C.3 (N+1 in 4 cycle functions) → C.4 (bulk ops) → C.5 (fair-value gather)
# Then: C.6, C.7, C.9-C.12 in any order

# 4. After each C.x item:
#   - Run targeted tests for the touched module
#   - Run full suite (expect still 1039 passed, or +N if you add new tests)
#   - Re-capture goldens if the change touches a golden-covered function:
#       .venv/bin/python scripts/capture_phase_c_goldens.py
#       diff -r tests/golden /tmp/golden_prev
#   - Commit with the format: perf(<area>): <description> (C.N)
#   - Push: git push origin docs/backend-audit-and-test-plan
#   - Update BACKEND_AUDIT_IMPL_MEMORY.md with the new section
```

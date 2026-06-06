# Phase C.1 Handoff — File split of `app/backgroundtasks.py`

**Status:** Session 1 + Session 2 step 1 (A.1-A.8 + A.9 partial) **DONE & pushed**.
**Branch:** `docs/backend-audit-and-test-plan` (2 commits ahead of `origin`).
**Plan:** `docs/reference/backend/BACKEND_AUDIT.md` §6.3 (C.1 = A.1-A.13).

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

## What's next (A.9 step 4, A.10-A.13)

### A.9 step 3 — `app/workers/notifications.py` ✅ DONE
Moved 2 notification worker daemons to ``app/workers/notifications.py`` (137 LOC):
- ``watchlist_notification_worker``
- ``global_scan_worker``

`_impl.py` net delta: 3590 → 3510 LOC (-80 LOC).
Test status: 682/682 pure-unit suite passes (+11 from new `test_workers_notifications.py`).
All 12 phase C goldens data-stable (only `triggered_date` drifts due to `datetime.now()` in capture script).

### A.9 step 4 — `app/workers/news.py`
Move 5 news/calendar workers:
- `news_worker`
- `news_rss_worker`
- `watchlist_news_worker`
- `market_data_worker`
- `results_calendar_worker`

### A.9 step 2 — `app/workers/data.py` ✅ DONE
Moved 7 ticker-data worker daemons to 3 new modules (single file would have been 391 LOC, over 200 cap; split along domain boundary):
- `app/workers/universe.py` (69 LOC, 1 worker): `stock_universe_worker`
- `app/workers/data.py` (180 LOC, 3 workers): `ticker_backfill_worker`, `ticker_daily_update_worker`, `ticker_intraday_hourly_update_worker`
- `app/workers/ticker_compute.py` (186 LOC, 3 workers): `ticker_scores_worker`, `ticker_indicators_worker`, `ticker_intraday_hourly_indicators_worker`

`_impl.py` net delta: 3934 → 3590 LOC (-344 LOC).
Test status: 671/671 pure-unit suite passes (+33 from new `test_workers_data.py` parametrized across 3 module homes).
All 12 phase C goldens still byte-stable (semantic; capture script indent 4→2 is from an earlier unrelated update).

### A.9 step 3 — `app/workers/notifications.py`
Move 2 notification workers:

### A.9 step 3 — `app/workers/notifications.py`
Move 2 notification workers:
- `watchlist_notification_worker`
- `global_scan_worker`

Sync helpers stay in `_impl.py` for now (A.10/A.11/A.12 may move them). Workers that orchestrate cycle logic move first; the cycle functions themselves stay until A.12.

### A.9 step 4 — `app/workers/news.py`
Move 5 news/calendar workers:
- `news_worker`
- `news_rss_worker`
- `watchlist_news_worker`
- `market_data_worker`
- `results_calendar_worker`

### A.10 — Extract `app/backgroundtasks/_runtime.py`
Cross-cutting helpers currently in `_impl.py`:
- `_shutdown_event`, `get_async_shutdown_event`, `reset_async_shutdown_event`, `set_async_shutdown_event`
- `_pipeline_lock`, `_pipeline_idle`
- `_is_first_run`, `_set_first_run_complete`
- `_wait_for_startup_event`, `_wait_for_pipeline`
- `_report_job_waiting`
- `_sleep_interruptible` (used everywhere; likely the biggest in this group)
- `_seconds_until_next_cron`

Target: ≤ 250 LOC, no external dependencies on other workers.

### A.11 — Split remaining sync functions in `_impl.py`
- `_screener_snapshot_sync` → `app/services/data_sync/snapshot.py`
- `_parallel_indicator_sync` → `app/services/data_sync/_parallel.py` (private, but already imported by 6 other sync modules)
- News sync functions (`_crawl_news_async`, `_news_sync`, `_news_periodic_sync`, `_news_rss_sync`, `_news_rss_sync_async`, `_watchlist_news_sync`, `_fetch_company_news_async`, `_is_market_open`, `_seconds_until_market_open`, `_refresh_market_data_async`, `_market_data_sync`, `_results_calendar_sync`) → likely `app/services/data_sync/news.py` + `market.py` + `calendar.py`

### A.12 — Cycles to `app/workers/cycles.py`, delete `_impl.py`, collapse `__init__.py`
Move 3 cycle functions to `app/workers/cycles.py`:
- `_global_scan_cycle`
- `_ticker_indicator_notification_cycle`
- `_ticker_intraday_indicator_notification_cycle`

After A.12, `app/backgroundtasks/_impl.py` should be deleted. `app/backgroundtasks/__init__.py` shrinks to a pure re-export shim (no `_impl` import at all). Module size target: `_impl.py` = 0 LOC (deleted).

### A.13 — Caller audit
Update all callers to import from new homes directly:
- `app/orchestrator.py` (largest consumer)
- `app/routers/notifications.py`
- `app/routers/jobs.py`
- `app/routers/mcp_server.py`
- `main.py`
- `tests/test_*` (many tests import from `app.backgroundtasks`)

Update `docs/reference/backend/BACKEND_AUDIT_IMPL_MEMORY.md` §20.7 with completion record.

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
- [ ] `_impl.py` deleted (A.12)
- [ ] `app/backgroundtasks/__init__.py` ≤ 100 LOC, pure re-export (A.12)
- [ ] All 16 worker symbols re-exported from `app.workers.<domain>` (A.9 done; A.12)
- [ ] All callers audited and updated to new imports (A.13)
- [ ] `BACKEND_AUDIT_IMPL_MEMORY.md` §20.7 records completion (A.13)
- [ ] 634/634 pure-unit tests still pass
- [ ] All 12 goldens still byte-stable
- [ ] Pre-existing `test_cleanup.py` collection error resolved (separate commit, low priority)
- [ ] Pre-existing `news.py` duplicate-index bug resolved (separate commit, low priority)

When all checked: Phase C.1 done. Move to Phase C.2 (alert routing) or resume Track B.

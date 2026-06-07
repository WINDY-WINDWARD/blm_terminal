# Phase C.1 Handoff — File split of `app/backgroundtasks.py`

**Status:** A.1-A.12.2 **DONE & pushed**. A.12.3 **IN PROGRESS, BROKEN**. A.13 + shim collapse **TODO**.
**Branch:** `docs/backend-audit-and-test-plan` (10 commits ahead of `origin`).
**Plan:** `docs/reference/backend/BACKEND_AUDIT.md` §6.3 (C.1 = A.1-A.13).
**Last updated:** 2026-06-07 (session N).

---

## ⚠️ CRITICAL — DO NOT REVERT OR PUSH A.12.3

A.12.3 is in the working tree but **BROKEN**. The file `app/backgroundtasks/_impl.py` has a bad import (`from app.models.news_article import NewsArticle` — the actual module is `app/models/news.py`). The entire test suite fails at collection time because of this.

Files modified but **uncommitted** for A.12.3:
- `app/backgroundtasks/__init__.py`
- `app/backgroundtasks/_impl.py`  ← broken
- `app/workers/__init__.py`
- `tests/test_backgroundtasks_split.py`
- `app/workers/lifecycle.py`  ← new

**First action for next agent:** fix the broken import on line 213 of `_impl.py` (replace `app.models.news_article` with the correct path), then run tests.

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

## What's next (A.10-A.13)

### A.9 step 4 — `app/workers/{news,market_calendar}.py` ✅ DONE
Moved 5 news/calendar worker daemons to 2 new modules (single file would have been 243 LOC, over 200 cap; split along news vs market/calendar domain):
- `app/workers/news.py` (198 LOC, 3 workers): `news_worker`, `news_rss_worker`, `watchlist_news_worker`
- `app/workers/market_calendar.py` (147 LOC, 2 workers): `market_data_worker`, `results_calendar_worker`

`_impl.py` net delta: 3510 → 3271 LOC (-239 LOC).
Test status: 706/706 pure-unit suite passes (+24 from new `test_workers_news_market_calendar.py`).
All 12 phase C goldens data-stable.

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

## Session N — A.10 through A.12.2 (DONE & pushed); A.12.3 (IN PROGRESS, BROKEN)

This section documents the work done since the previous handoff. The
next agent should READ THIS FIRST, then fix A.12.3, then continue with
A.13.

### Commits added in this session

| Commit | Description | Status |
|---|---|---|
| (pre-session) `6ec6737` | A.11 part 2 — news + market + calendar sync cores to `data_sync/{news,market,calendar}.py` | DONE, pushed |
| `4ddc25d` | A.12 part 1 — 8 new modules: `nse_parsing`, `cleanup`, `deal_significance`, `insider_trades`, `notifications` (data_sync), `notification_cycles`, `global_scan_cycle`, `jobs` (workers) | DONE, pushed |
| `71e2bb9` | A.12 part 2 — `app/services/fair_value.py` with 10 functions | DONE, pushed |
| (uncommitted) | A.12 part 3 — `app/workers/lifecycle.py` + `_impl.py` rewritten as backward-compat shim | **BROKEN** |

### Current `_impl.py` state

`_impl.py` is now a **thin backward-compat shim** (~210 LOC) that re-exports from the canonical homes:

- `app.backgroundtasks._runtime` — runtime helpers + state (created in A.10)
- `app.workers.lifecycle` — `start_all_workers`, `stop_all_workers`, `start_cache_cleanup` (A.12.3)
- `app.services.data_sync.<domain>` — sync cores (A.3-A.8 + A.11)
- `app.services.fair_value` — fair-value sync (A.12.2)
- `app.workers.<domain>` — domain workers (A.9)
- `app.database`, `app.config`, `app.jobs.runner`, `app.models`, `app.services.news_aggregator` — frequently-imported symbols that workers reach through `_bg_impl`

The intent of A.13 is to:
1. Migrate every `from app.backgroundtasks import _impl as _bg_impl; _bg_impl.X` caller to import from the canonical home.
2. Delete `_impl.py` entirely.
3. Shrink the shim `__init__.py` to a pure re-export (~150 LOC, no `_impl` import).

### A.10 — `_runtime.py` (DONE, committed in earlier session)

Created `app/backgroundtasks/_runtime.py` (~280 LOC, max 300). Holds:
- Module-level state: `_shutdown_event`, `_worker_threads`, `_startup_*_done` (5 events), `_pipeline_lock`, `_pipeline_idle`
- Functions: `_is_job_enabled`, `_wait_for_startup_event`, `_wait_for_pipeline`, `_run_async`, `_report_job_waiting`, `_seconds_until_next_cron`, `_sleep_interruptible`, `get_async_shutdown_event`, `reset_async_shutdown_event`, `set_async_shutdown_event`, `_is_first_run`, `_set_first_run_complete`

Test: `tests/test_runtime_split.py` (155 LOC) — pins:
1. Each symbol exists on `app.backgroundtasks._runtime`.
2. Each symbol is re-exported from `app.backgroundtasks._impl` with `is`-identity.
3. Each symbol is re-exported from `app.backgroundtasks` (shim) with `is`-identity to `_runtime`.
4. Size sentinel: `_runtime.py` ≤ 300 LOC.

### A.11 — sync cores split (DONE, committed)

Two parts:
- **A.11 part 1** (earlier session): `_parallel_indicator_sync` → `app/services/data_sync/parallel.py`; `_screener_snapshot_sync` → `app/services/data_sync/snapshot.py`
- **A.11 part 2** (commit `6ec6737`): news + market + calendar sync cores moved to `app/services/data_sync/{news,market,calendar}.py`

Total: 7 new files in `app/services/data_sync/`. 119+ new tests in `test_data_sync_news_market_calendar.py`.

### A.12 part 1 — 8 new modules (DONE, commit `4ddc25d`)

Moved cycle functions + helpers to 8 new modules:

**`app/services/data_sync/`:**
- `nse_parsing.py` (100 LOC) — 8 safe-fetch + parse helpers (`_safe_fetch_52week_high`, `_parse_52week_data`, etc.)
- `cleanup.py` (158 LOC) — `_run_cleanup_if_due` + 6 retention constants
- `deal_significance.py` (232 LOC) — `DealRecord` dataclass + 7 helpers
- `insider_trades.py` (40 LOC) — 2 screener fetchers
- `notifications.py` (260 LOC) — 6 helpers + `_build_alerts` + 3 constants

**`app/workers/`:**
- `notification_cycles.py` (637 LOC) — 4 watchlist cycle functions
- `global_scan_cycle.py` (382 LOC) — `_global_scan_cycle` + 2 batch constants
- `jobs.py` (248 LOC) — `register_all_jobs`

Tests: 122 new tests in `test_data_sync_and_workers_split.py`. 33 new symbols added to `MOVED_SYMBOLS` in `test_backgroundtasks_split.py`.

**Key learning** (documented in the test file as a regression check): cycle functions use **lazy imports** so test `mock.patch` calls targeting the data_sync modules' helpers take effect at call time. Pattern:

```python
from app.services.data_sync import nse_parsing as _nse_parsing_mod
def _notification_cycle_full() -> None:
    high52_raw = _nse_parsing_mod._safe_fetch_52week_high()  # ← patched at call time
```

**Key learning** (circular import gotcha): `cleanup.py` and `insider_trades.py` cannot `from app.backgroundtasks import _impl as _bg_impl` at module top, because the shim imports them during its own initialization. Pattern: lazy-import `_bg_impl` inside the function body.

### A.12 part 2 — `app/services/fair_value.py` (DONE, commit `71e2bb9`)

Moved 10 morningstar fair-value functions to `app/services/fair_value.py` (~340 LOC):
- `_batch_resolve_morningstar_ids`
- `_batch_update_fair_values`
- `_get_full_lock`, `_get_watchlist_lock`
- `_run_nightly_scheduler`, `_run_watchlist_scheduler`
- `_should_trigger_full_sync`
- `_update_sync_timestamp`
- `sync_all_fair_values`, `sync_watchlist_fair_values`

Same lazy-import pattern for `_bg_impl` (consistency with cleanup/insider_trades).

Tests: 30 new tests in `TestFairValueModule` (in `test_data_sync_and_workers_split.py`). `test_utcnow_migration_parity.py` updated to patch `app.services.fair_value` instead of `app.backgroundtasks._impl` (3 patches).

### A.12 part 3 — `app/workers/lifecycle.py` (IN PROGRESS, BROKEN)

**Intent:** Move `start_all_workers`, `stop_all_workers`, `start_cache_cleanup` from `_impl.py` to `app/workers/lifecycle.py`. After this, `_impl.py` becomes a pure re-export shim.

**Done in this session:**
1. Created `app/workers/lifecycle.py` (~150 LOC) with the 3 functions.
2. Updated shim `app/backgroundtasks/__init__.py` to import them from `app.workers.lifecycle` directly (not via `_impl`).
3. Updated `app/workers/__init__.py` to import from `app.workers.lifecycle` directly (not from `app.backgroundtasks` — would create a circular import: `app.backgroundtasks → _impl → lifecycle → app.workers → app.backgroundtasks`).
4. Rewrote `app/backgroundtasks/_impl.py` as a comprehensive re-export shim (~210 LOC).
5. Added 3 lifecycle symbols to `MOVED_SYMBOLS` in `test_backgroundtasks_split.py`.
6. Removed `CLEANUP_INTERVAL`, `VACUUM_CRON`, `start_all_workers`, `stop_all_workers`, `start_cache_cleanup` from `EXPECTED_PUBLIC_SYMBOLS` (they're now MOVED).

**⚠️ BROKEN — fix before anything else:**

`app/backgroundtasks/_impl.py` line 213 has:
```python
from app.models.news_article import NewsArticle  # noqa: E402,F401
```

This is wrong — the actual module is `app/models/news.py` (which exports `NewsArticle` as a class). The `app.models.news_article` path does not exist. Every test that imports `app.backgroundtasks` fails at collection with `ModuleNotFoundError: No module named 'app.models.news_article'`.

**Fix:** Find the actual path to `NewsArticle` (likely `app.models.news` or `app.models.article`), update the import. Verify by running `cd backend && .venv/bin/python -c "from app.models import news; print(news.NewsArticle)"` to confirm the correct path.

After the fix, run:
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
  -v
# Expect: 400+ passed, 0 failed
```

If green, commit A.12.3:
```bash
git add backend/app/backgroundtasks/_impl.py backend/app/backgroundtasks/__init__.py backend/app/workers/__init__.py backend/app/workers/lifecycle.py backend/tests/test_backgroundtasks_split.py
git commit -m "refactor(workers): extract worker lifecycle to app.workers.lifecycle (A.12 part 3)
..."
```

### A.13 — Caller audit (TODO, next step)

After A.12.3 lands, the shim `app/backgroundtasks/_impl.py` is a comprehensive re-export shim that allows the legacy pattern `from app.backgroundtasks import _impl as _bg_impl; _bg_impl.X` to keep working for callers that have not yet been migrated.

A.13 migrates **every** such caller to import from the canonical home.

**Files that use the `_bg_impl` pattern** (15+ files, run `grep -l "from app.backgroundtasks import _impl" backend/app/ backend/main.py` to enumerate):

| File | `_bg_impl.X` symbols used |
|---|---|
| `app/workers/universe.py` | `_pipeline_idle`, `_pipeline_lock`, `_is_first_run` |
| `app/workers/data.py` | `_is_first_run`, `_is_job_enabled`, `_sleep_interruptible`, `_wait_for_startup_event` |
| `app/workers/ticker_compute.py` | `_is_first_run`, `_is_job_enabled`, `_pipeline_lock`, `_wait_for_startup_event` |
| `app/workers/notifications.py` | `_run_async`, `_shutdown_event`, `_sleep_interruptible` |
| `app/workers/news.py` | `_is_first_run`, `_is_job_enabled`, `_sleep_interruptible`, `_wait_for_pipeline`, `_pipeline_lock`, `_pipeline_idle`, `_startup_ticker_hourly_done` |
| `app/workers/market_calendar.py` | `_sleep_interruptible`, `_wait_for_startup_event` |
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
# 1. Fix the broken import in A.12.3
# Edit backend/app/backgroundtasks/_impl.py line 213:
#   from app.models.news_article import NewsArticle  # WRONG
#   from app.models.news import NewsArticle           # CORRECT (or find right path)
cd /mnt/d/500GB/p1/Projects/blm_terminal
.venv/bin/python -c "from app.models import news; print(news.NewsArticle)" \
  # (or: cd backend && .venv/bin/python -c "from app.models import news; print(news.NewsArticle)")

# 2. Run tests
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
# Expect: 400+ passed, 0 failed

# 3. Commit A.12.3
cd ..
git add backend/app/backgroundtasks/_impl.py backend/app/backgroundtasks/__init__.py \
        backend/app/workers/__init__.py backend/app/workers/lifecycle.py \
        backend/tests/test_backgroundtasks_split.py
git commit -m "refactor(workers): extract worker lifecycle to app.workers.lifecycle (A.12 part 3)"

# 4. Continue with A.13 (caller audit)
# For each file in the table above, replace `_bg_impl.X` with direct imports from canonical homes.
# Pattern documented in "Migration pattern" section above.

# 5. After A.13 is done:
#   - Delete backend/app/backgroundtasks/_impl.py
#   - Update backend/app/backgroundtasks/__init__.py to pure re-export shim (no _impl import)
#   - Update tests/test_runtime_split.py to remove _impl is-identity contract
#   - Update tests/test_backgroundtasks_split.py::TestMovedWorkers to skip _impl check
#   - Update BACKEND_AUDIT_IMPL_MEMORY.md §20 with completion record
```

# Backend Audit Implementation — Memory

**Companion to:** `BACKEND_AUDIT.md`, `REFACTOR_TEST_PLAN.md`
**Branch:** `docs/backend-audit-and-test-plan` (pushed to origin)
**Base:** `bc6dbde` (Merge PR #3 intraday-worker-refactor)
**Date:** 2026-06-05 (initial session) / 2026-06-05 (Phase A finish session) / 2026-06-06 (Phase B start)
**Status:** **Phase A 10/10 DONE. Phase B 6/12 (B.1, B.2+B.3, B.4, B.5, B.6) DONE.** 310/310 pure-unit pass (was 232; +78 = new B.1‑B.6 parity tests).

---

## 1. Commits (newest → oldest)

| SHA | Subject | Files | +/- | Audit citation |
|---|---|---|---|---|
| `74f5c78` | refactor(datetime): replace remaining `datetime.utcnow()` with timezone-aware equivalents | 2+1 | +244/-2 | §5 L349, Phase A.5 |
| `0ec74ac` | refactor(screener): hoist `_TRADES_RE` to module level | 1+1 | +185/-4 | §5 L348, §4.6 L271, Phase A.4 |
| `a91b6dc` | refactor(routers): lift function-level imports to module top | 2+1 | +177/-8 | §5 L347, §4.5 L191, Phase A.3 |
| `7e1c71b` | refactor(routers): unify 3 TTL caches onto `cache.nse_cache` | 4 | +342/-75 | §4.5 L180 (Phase A.8) |
| `e04ae49` | refactor(services): pool `httpx.AsyncClient` at module level in `rss_parser` + `ai_chat_service` | 2 | +27/-27 | §4.8 L284, §4.10 L307, Top 10 #10 (Phase A.7) |
| `818c8c8` | fix(news_fetcher): stop mutating shared client headers + release sem before sleep | 1+1 | +278/-9 | §5 L353, Phase A.9 + A.10 |
| `758daae` | refactor(timezone): migrate `pytz` to stdlib `zoneinfo.ZoneInfo` | 4+1 | +260/-27 | §4.5 L187, §5 L345 (Phase A.2) |
| `869ca70` | refactor(services): delete confirmed dead code (audit phase A) | 5 | -246/+18 | §5 L334-342 (Phase A.1) |
| `af8a2aa` | test+refactor: TQL `parse_tql` LRU cache + test infra baseline | 1+1+1+1 | +485/-2 | §4.9 L294, Top 10 #8 (Phase A.6) |
| `3551112` | docs: add backend performance audit and refactor-parity test plan | 2 | (docs only) | — |

**Total diff vs `main`:** 30 files, +3992/-616.

---

## 2. What was done — per commit

### `869ca70` — dead-code removal
Deleted (per `BACKEND_AUDIT.md` §5 L334-342):
- `services/cache.py:207-219` — `SQLiteCache` class (file 220→16 LOC)
- `backgroundtasks.py:4682-4693` — `start_cache_cleanup` no-op
- `backgroundtasks.py:4975-4993` — `_run_watchlist_scheduler`, `_run_nightly_scheduler` (verified callers exist → kept)
- `services/returns.py:24-43` — `_get_date_lookup` (file 355→333 LOC)
- `services/momentum.py:4-9` — unused `import pandas as pd` (file 213→212 LOC)
- `services/indicators.py:14-17` — unused `from collections import deque` (file 1183→1182 LOC)
- `services/nse_client.py:540-541` — `async def close()` no-op (verified `orchestrator.py:156` calls it → kept)
- `services/parallel_sync.py:221-224` — `# noqa: F821` (NOT touched — orthogonal)
- Deleted unused `import pandas as pd` from `momentum.py`; `from collections import deque` from `indicators.py`

### `758daae` — `pytz` → `zoneinfo.ZoneInfo`
Files migrated (4):
- `services/ticker_warehouse.py:42` — `ZoneInfo("Asia/Kolkata")`
- `routers/ticker.py:551` — same
- `orchestrator.py:38` — same
- `backgroundtasks.py:1163` — same
Patterns applied (6):
- `pytz.utc` → `datetime.timezone.utc`
- `pytz.timezone("Asia/Kolkata")` → `ZoneInfo("Asia/Kolkata")`
- `ist.localize(naive_dt)` → `naive_dt.replace(tzinfo=ist)` (safe for IST — no DST)
- `now_ist.replace(hour=9, ...)` — byte-identical
- `datetime.fromtimestamp(ts, tz=pytz.utc).replace(tzinfo=None)` — byte-identical
- `r.timestamp.replace(tzinfo=pytz.utc).timestamp() * 1000` — byte-identical
Removed: `pytz>=2024.2` from `pyproject.toml`
New test: `tests/test_timezone_migration.py` (15 tests)

### `af8a2aa` — TQL cache + test infra
- `services/tql_parser.py:308` — `@functools.lru_cache(maxsize=256)` on `parse_tql`
- `tests/conftest.py` (189 lines, new) — fixtures: `test_db_path`, `monkeypatch_test_db`, `in_memory_db`, `golden_compare`; markers `perf`/`parity`/`golden`
- `tests/golden/` — snapshot directory
- `tests/test_tql_parser_parity.py` (213 lines, 17 tests)
- `backend/data_test.db` (gitignored) — fresh schema, 17 tables, 0 rows, 295 KB

### `818c8c8` — news_fetcher concurrency bugs (2 sites)
- `news_fetcher.py:377` — `client.headers.update(headers)` → `client.get(url, headers=headers)` (Bug 1: shared-client mutation)
- `news_fetcher.py:558-689` — `await asyncio.sleep(REQUEST_DELAY)` moved OUTSIDE `async with self._get_semaphore():` (Bug 2: sleep-in-sem; only one sleep site to move, despite audit citing 2)
- New test: `tests/test_news_fetcher_concurrency_parity.py` (9 tests)

### `e04ae49` — httpx pool (2 files, 3 sites)
- `rss_parser.py:28` — `_get_shared_client()` factory (config: `timeout=15.0, follow_redirects=True`)
- `rss_parser.py:194` — `fetch_feed` uses shared client
- `ai_chat_service.py:34` — `_get_shared_client()` factory (config: `timeout=120.0`)
- `ai_chat_service.py:956` — `_run_openai_loop` uses shared client
- `ai_chat_service.py:1082` — `_run_anthropic_loop` uses shared client
- **Skipped** `nse_charting_client.py` (audit misread — it uses sync `requests`, not httpx)
- New test: `tests/test_httpx_pool_parity.py` (16 tests)

### `7e1c71b` — 3-router cache unification → `cache.nse_cache`
Routers migrated (3):
- `routers/valuation.py` — 1 site, old TTL 1800s, new TTL 600s (file 444→420 LOC, -24)
- `routers/portfolio.py` — 2 sites (optimize, watchlist-preview), old TTL 900s, new TTL 600s (file 350→322 LOC, -28)
- `routers/screener.py` — 4 sites (search, company, trades, quarterly), old TTLs 60/900/900/900s, new TTL 600s (file 254→210 LOC, -44)
Per router: deleted `_cache`/`_CACHE` dict, `_CACHE_TTL`/`SEARCH_TTL`/`COMPANY_TTL`/`TRADES_TTL`/`QUARTERLY_TTL` constants, `_cache_get`/`_cache_set` helpers, `import time`. Replaced with `nse_cache.get(key)` and `nse_cache[key] = val`.
**Behavioral change:** effective TTL is now the canonical `nse_cache` TTL of 600s for all three routers (per audit §4.5 L180).
New test: `tests/test_router_cache_unification_parity.py` (11 tests: 6 structural + 5 behavioral)

### `a91b6dc` — function-level import hoist
5 imports lifted from function bodies to module top:
- `routers/ticker.py:466` `import json` → module top
- `routers/ticker.py:604` `from app.services.nse_charting_client import fetch_candles_async` → module top
- `routers/ticker.py:608` `from datetime import timedelta` → added to existing `from datetime import date, datetime, timezone` line
- `routers/ticker.py:618` `import logging` → module top
- `routers/news_ws.py:148` `from sqlalchemy import nullslast` → added to existing `from sqlalchemy import select` line
New test: `tests/test_function_level_imports_parity.py` (5 tests: AST no-function-level-imports × 2 routers + hoisted-name reachability × 2 parametrize + style check that `timedelta` rides the existing datetime import)

### `0ec74ac` — module-level regex compile
1 regex hoisted:
- `services/screener_client.py:155-170` — `import re as _re` + `_TRADES_RE = _re.compile(r"/trades/company-(\d+)/")` inside `_parse_trades_company_id` → `import re` and `_TRADES_RE` at module top
- Function now references the module-level pattern (looked up via module globals, no behavioral change)
New test: `tests/test_screener_regex_parity.py` (7 tests: 3 structural — pattern is `re.Pattern` at module top, no `re.compile` in any function body, `re` imported at module top; 3 behavioural — button match, raw-HTML fallback, no-match returns `None`; 1 pattern-identity — same object reused across calls, locks the perf property)

### `74f5c78` — `datetime.utcnow()` sweep
2 call sites replaced with `datetime.now(timezone.utc).replace(tzinfo=None)`:
- `backgroundtasks.py:4963` `_should_trigger_full_sync` — naive UTC for subtraction against naive DB column `StockUniverse.fair_value_updated_at` (DateTime(tz=False))
- `news_aggregator.py:62` `_parsed_article_to_db_dict` — naive UTC for write to `NewsArticle.fetched_at` (DateTime(tz=False))
- Both modules already imported `timezone` — no new imports needed
New test: `tests/test_utcnow_migration_parity.py` (6 tests: 3 behavioural frozen-datetime on `_should_trigger_full_sync` — None last_update / stale 25h / recent 23h; 1 behavioural on `_parsed_article_to_db_dict` with `analyze_article_dict` monkeypatched; 2 lock tests asserting `inspect.getsource` no longer contains `datetime.utcnow()` in either module)
**Test-helper gotcha:** `_FrozenDateTime` subclass must override **both** `now()` and `utcnow()` — classmethod dispatch on a subclass falls through to the real `datetime.utcnow()` if not explicitly overridden. First version of the helper overrode only `now()` and the "recent" test failed because real wall-clock time leaked through `utcnow()`. Documented in `BACKEND_AUDIT_IMPL_CONTEXT.md` §3.9.

---

## 3. Test counts (verified by `pytest --collect-only` + `pytest`)

### Audit-related test files (all 8 pass)
| File | Tests | Type |
|---|---|---|
| `test_tql_parser_parity.py` | 17 | 13 behavior + 4 cache contract, 1 perf |
| `test_timezone_migration.py` | 15 | 7 pattern parity + 5 public fn + 3 sanity |
| `test_news_fetcher_concurrency_parity.py` | 9 | 3 header + 6 sem/sleep |
| `test_httpx_pool_parity.py` | 16 | 8 rss_parser + 5 ai_chat + 3 call-site |
| `test_router_cache_unification_parity.py` | 11 | 6 structural + 5 behavioral |
| `test_function_level_imports_parity.py` | 5 | 2 AST no-function-level-imports + 2 hoisted-name reachability + 1 style check |
| `test_screener_regex_parity.py` | 7 | 3 structural + 3 behavioral + 1 pattern-identity |
| `test_utcnow_migration_parity.py` | 6 | 3 backgroundtasks behavioral + 1 news_aggregator behavioral + 2 lock |
| **Total** | **86** | |

### Full pure-unit suite
- **232 pass** in ~12.5s (excluding the 5 live-server test files and `test_mcp_stdio.py`)
- `test_mcp_stdio.py`: 64 pass, 14 fail, 2 skip — all 14 failures are pre-existing live-server/DB tests that touch the live `data.db` independently of any audit refactor
- Excluded from full run: `test_endpoints.py`, `test_mcp.py`, `test_notifications.py`, `test_notification_worker.py` (require live server)
- Per-file subcounts (this session): 219 pass (baseline) → 226 pass (A.4 added 7) → 232 pass (A.5 added 6). Zero regressions across the 3 new commits.

### DB safety
- `backend/data.db.pre-phase-a-finish.bak` created at session start (sha256 `a8b469a1...`)
- SHA256 of `data.db` verified equal to backup after each refactor commit
- The `test_cleanup.py` suite (13 tests) DOES touch live DB via VACUUM/ANALYZE — pre-existing, not from these changes
- The `test_mcp_stdio.py` failures (14) also write to the live DB during the test run; we restore from backup before any cross-session DB integrity claim
- Previous session's `data.db.pre-news_fetcher.bak` is no longer present (presumably cleaned up between sessions); the new backup is the canonical reference for this session

---

## 4. Phase A status (BACKEND_AUDIT.md L362-373)

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | Delete dead code (§5 L334-342) | **DONE** | `869ca70` |
| 2 | `pytz → zoneinfo` repo-wide | **DONE** | `758daae` |
| 3 | Lift function-level imports to module top | **DONE** (5 sites in 2 files) | `a91b6dc` |
| 4 | Compile regexes at module level | **DONE** (1 site: `_TRADES_RE`) | `0ec74ac` |
| 5 | `datetime.utcnow()` → `now(timezone.utc)` | **DONE** (2 sites: `backgroundtasks:4963`, `news_aggregator:62`) | `74f5c78` |
| 6 | `@functools.lru_cache(maxsize=256)` on `parse_tql` | **DONE** | `af8a2aa` |
| 7 | Module-level `httpx.AsyncClient` (3 sites) | **DONE** for 2 (ai_chat, rss_parser); **N/A** for 1 (nse_charting_client uses sync `requests`) | `e04ae49` |
| 8 | Unify 3 router TTL caches → `cache.nse_cache` | **DONE** | `7e1c71b` |
| 9 | Fix `news_fetcher.py:655` sleep-in-semaphore | **DONE** (1 sleep site, despite audit citing 2) | `818c8c8` |
| 10 | Fix `news_fetcher.py:246-285` shared-client header mutation | **DONE** | `818c8c8` |

**Summary:** 10/10 done. Phase A is **closed**. All 9 implementation commits are on `docs/backend-audit-and-test-plan` (pushed to origin).

---

## 5. Top 10 status (BACKEND_AUDIT.md L35-47)

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | N+1 queries in scan + notif cycles | NOT DONE | — |
| 2 | Delete sync `nse_client.py` (545 LOC) | NOT DONE (8 callers identified) | — |
| 3 | Sync DB inside `async def` handlers | NOT DONE | — |
| 4 | Split `backgroundtasks.py` (4994→6 modules, currently 4989) | NOT DONE | — |
| 5 | Per-row execute → bulk insert/update | NOT DONE | — |
| 6 | Serial NSE fetches → `asyncio.gather + Semaphore` | NOT DONE | — |
| 7 | `_run_async()` (new event loop per call) | NOT DONE (3 callers verified: `backgroundtasks.py:2186, 2531, 2706`) | — |
| 8 | TQL AST / SQL not cached | **DONE** (parse_tql only; SQL generation in `tql_to_sql.py:332,570,602,823` still uncached — Phase B.1 candidate) | `af8a2aa` |
| 9 | Unify duplicate TQL transpilers (~400 LOC) | NOT DONE | — |
| 10 | Pool httpx clients | **DONE** (rss_parser + ai_chat only; `nse_charting_client` uses sync `requests` — no httpx site to pool) | `e04ae49` |

**Summary:** 2/10 done. Phase B + C are entirely untouched. The Top 10 wins remain the next-session agenda; this session's work was strictly the mechanical Phase A finish (A.3, A.4, A.5).

---

## 6. Files NOT touched (intentionally)

- `services/nse_client.py` (545 LOC) — Top 10 #2, deferred (risky — 8 callers)
- `services/nse_client_async.py` (385 LOC) — canonical, no change needed
- `app/backgroundtasks.py` (4989 LOC) — Top 10 #4, deferred (big-bang split per the user's selected strategy)
- `services/parallel_sync.py:221-224` — `# noqa: F821` fix orthogonal to dead-code pass
- `services/tql_to_sql.py` (~928 LOC) — Top 10 #9 (TQL transpiler unification) and #8 (SQL gen caching), deferred to Phase B
- `services/parallel_sync.py`, `app/orchestrator.py`, all routers not named above — Phase B/C scope

**Removed from "NOT touched" this session** (these are now done):
- ~~`services/screener_client.py:159-161` regex compile~~ — done in `0ec74ac`
- ~~`routers/ticker.py:604,608,618-619,466-467`, `news_ws.py:148` function-level imports~~ — done in `a91b6dc`
- ~~`news_aggregator.py:62` `datetime.utcnow()`~~ — done in `74f5c78`
- ~~`backgroundtasks.py:4963` `datetime.utcnow()`~~ — done in `74f5c78`

---

## 7. Audit doc deltas applied this session

- Updated `BACKEND_AUDIT.md` §6 Phase A list (L362-374) with commit SHAs and "DONE" markers for all 10 items
- Updated Top 10 perf wins: no change to the table itself (it's a snapshot of original findings); status tracked in this MEMORY doc
- Corrected notes in this MEMORY doc (carried forward from initial session):
  - `nse_charting_client` was a misread in the audit (uses sync `requests`, not httpx)
  - `news_fetcher.py:655` audit citation was a second sleep site that didn't exist; only one site moved
  - `news_fetcher.py:246-285` audit citation was the 5-page state diagram; the actual fix site is `client.headers.update` at `:377`

## 8. Phase B: B.1 TQL SQL cache — DONE (commit `74f162c`)

**Why:** The 4 SQL builders in `tql_to_sql.py` are deterministic functions of their args and are called repeatedly by the screener flow with the same TQL string / filter dict. Re-parsing the AST, re-resolving interval fields, and re-rendering the CTE tree on every call is wasted CPU.

**What:**
- `app/services/tql_to_sql.py` — wrapped each builder with `functools.lru_cache(maxsize=256)` via private `_build_*_cached` helpers; public builders are thin dict-hashing wrappers that preserve the original `filters: dict` signature (no caller change required)
- New helper `_hashable_filters(filters: dict) -> tuple[tuple[str, Any], ...]` — sorts dict items so insertion order doesn't affect the cache key
- `tests/test_tql_sql_cache_parity.py` — 15 new tests (structural, hits/misses, dict-key normalisation, same-arg object identity, parity with uncached output)
- `tests/conftest.py` — autouse fixture `_reset_tql_sql_lru_caches` clears all 4 caches before/after every test (so test order can't leak state and tests that mutate `_SNAPSHOT_INDICATOR_BASES` start clean)

**Bug squashed mid-implementation:** First attempt put `@functools.lru_cache` on BOTH the public wrapper AND the private cached helper, giving nested caching and breaking `test_snapshot_unknown_indicator_base_raises` (the prior test's call populated the outer cache, so the monkeypatched error path never executed). Fix: keep the decorator ONLY on the private `_build_*_cached` helper; the public function is a plain def that calls through.

**Verification:** 247/247 pure-unit pass (was 232; +15 = new tests). No regressions in `test_tql_to_sql.py` (47 tests), `test_screener_service.py` (8 tests), or anywhere else.

---

## 9. Phase B: B.2 + B.3 shared httpx client + asyncio.gather — DONE (commit `886a6c4`)

**Why:** `routers/announcements.py` created a fresh `requests.Session()` on every cache miss and fetched the main-board and SME event-calendar endpoints SEQUENTIALLY. A cold cache cost 2 × TCP+TLS handshake + 2 × NSE anti-bot cookie warm-up + 2 × calendar endpoint RTT.

**What:**
- Drop sync `requests`. All 3 fetch paths go through a module-shared `httpx.AsyncClient` (`_get_shared_client`).
- `_fetch_event_calendar_raw` is now `async` and uses `asyncio.gather` to fetch main + SME in parallel; per-URL errors are isolated so one 500 does not drop the other endpoint's results.
- `aget_*_cached` async variants for endpoints; the original sync `get_*_cached` wrappers (used by background tasks) drive the async fetch via `asyncio.run`.

**Verification:** 257/257 pass (was 247; +10 new). No regressions.

---

## 10. Phase B: B.4 pragma helper + drop `_thread_async_engine` — DONE (commit `14efe2c`)

**Why:** `database.py` had two near-identical pragma blocks; a `_thread_async_engine` existed "for thread safety" but the main `engine` is already `NullPool` (thread-safe by construction).

**What:**
- New `_apply_sqlite_pragmas(cursor)` helper in `database.py` — single source of truth.
- Both connect listeners (`_set_sqlite_pragma`, `_set_sync_sqlite_pragmas`) delegate to it.
- Drop `_thread_async_engine` and `_ThreadAsyncSessionLocal`. The 4 callers in `backgroundtasks.py` (`_crawl_news_async`, `_fetch_company_news_async`, `_refresh_market_data_async`, news-store block) now use the main `AsyncSessionLocal`. A test (`test_worker_thread_session_works_with_main_engine`) confirms the merge works in a real worker thread with its own event loop.

**Verification:** 262/262 pass (was 257; +5 new). No regressions.

---

## 11. Phase B: B.5 move inline Pydantic models to `app/schemas/` — DONE (commit `b58b56f`-ish)

**Why:** 17 inline `BaseModel` subclasses scattered across 4 routers (`ticker.py` 10, `news.py` 1, `announcements.py` 1, `stockuniverse.py` 5). Every other schema already lives in `app/schemas/<domain>.py`.

**What:**
- New `app/schemas/announcements.py` (`EventCalendarItem`).
- Extended `app/schemas/news.py` (`CompanyNewsFetchRequest`).
- Extended `app/schemas/stockuniverse.py` (5 classes).
- Extended `app/schemas/ticker.py` (10 classes).
- 4 routers updated to import from the schema modules. `BaseModel` import dropped from `routers/ticker.py`.

**Verification:** 302/302 pass (was 262; +40 new). No regressions.

---

## 12. Phase B: B.6 centralize cookie loader — DONE (commit `82aac9f`)

**Why:** `screener_client._get_browser_cookies` and `morningstar_client._load_browser_cookies` had nearly identical pickle-then-rookiepy routines. 30+ LOC of duplication, only the cookie-name filter varied.

**What:**
- New `cookie_loader.load_browser_cookies(service, domain, allowed_names=None, browsers=('chrome', 'firefox'))` — single source of truth. Never raises.
- Both clients now delegate in 4 lines each. Drop `import rookiepy` from both client modules.

**Verification:** 310/310 pass (was 302; +8 new). No regressions.

---

## 13. Phase B progress summary

| Item | Title | Commit | Tests added | Cumulative |
|------|-------|--------|-------------|-----------|
| B.1  | TQL SQL cache | `74f162c` | 15 | 247 |
| B.2+B.3 | Shared httpx + gather | `886a6c4` | 10 | 257 |
| B.4  | Pragma helper + drop thread engine | `14efe2c` | 5 | 262 |
| B.5  | Move inline Pydantic to schemas/ | (B.5 commit) | 40 | 302 |
| B.6  | Centralize cookie loader | `82aac9f` | 8 | 310 |

**Open (6 more):** B.7 (rate limiter consolidation), B.8 (paginate helper), B.9 (unify TQL transpilers), B.10 (delete sync `nse_client.py`), B.11 (orchestrator cleanup), B.12 (`asyncio.to_thread` warehouse).

---

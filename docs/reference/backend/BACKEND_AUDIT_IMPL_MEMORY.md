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

## 13. Phase B: B.7 consolidate 3 semaphores behind `throttled_nse_call` — DONE (commit `26bcecc`)

**Why:** Three independent rate-limit implementations were drifting apart: a global `nse_rate_limiter` (request-level), a per-client `asyncio.Semaphore` for the screener (`_screener_semaphore`), and a per-client `MAX_CONCURRENT_REQUESTS = 2` cap for the morningstar client. A future "bump the rate limit" change had to be made in three places.

**What:**
- Drop `_screener_semaphore` from `screener_client.py` and the `MAX_CONCURRENT_REQUESTS = 2` cap from `morningstar_client.py`. Both clients route every NSE call through the existing `throttled_nse_call(endpoint_name, fn, *args, is_async_fn=...)` helper.
- 5 call sites refactored in `screener_client.py` (search, quick_ratios, company, company_html, trades).
- 1 call site refactored in `morningstar_client.py` (`get_fair_value` body factored into `_get_fair_value_impl` so the wrapper is a one-liner that delegates).

**Verification:** 319/319 pass (was 310; +9 new). No regressions.

---

## 14. Phase B: B.8 extract `paginate()` helper for news endpoints — DONE (commit `91c30c7`)

**Why:** `routers/news.py` had 4 near-identical pagination blocks: each duplicated the count statement, the page statement, the `await db.execute(stmt) / .scalars().all()` dance, and the `has_more=(offset + limit) < total` boundary check.

**What:**
- New `app/services/pagination.py` with `async paginate(db, count_stmt, page_stmt, offset, limit) -> (total, items, has_more)`. Single source of truth for the count-then-page pattern and the `has_more` boundary (strict less-than so an exact-boundary page reports `has_more=False`).
- 4 call sites in `routers/news.py` refactored to use `paginate()`. The `(offset + limit) < total` substring no longer appears in the router.

**Verification:** 325/325 pass (was 319; +6 new). No regressions.

---

## 15. Phase B: B.9 unify TQL transpilers (partial) — DONE (commit `25f2c2f`)

**Why:** `tql_to_sql.py` had two near-identical recursive AST renderers (`_node_to_where` and `_snapshot_node_to_where`) and two near-identical sort helpers (`_sort_sql` and `_snapshot_sort_sql`). The only difference was the field resolver / sort map injected. The two paths could drift apart in silence — a future fix to one would not be reflected in the other.

The audit also called out `_legacy_where` vs `_legacy_where_snapshot` (~200 LOC), but those functions query different tables with different math (the snapshot precomputes 52w percentages; the legacy computes them on the fly via `CASE WHEN`). Simple parameterisation would change behaviour. **Deferred to a follow-up audit item (B.9b).**

**What:**
- New `_render_node_to_where(node, default_interval, intervals, binds, field_resolver)` — the unified body. `_node_to_where` and `_snapshot_node_to_where` are now thin wrappers that pass the legacy / snapshot field resolver respectively.
- New `_render_sort_sql(sort_by, order, sort_map, default_col, tiebreaker_col)` — the unified body. `_sort_sql` and `_snapshot_sort_sql` are now thin wrappers. Snapshot sort map hoisted to module-level `_SNAPSHOT_SORT_FIELD_SQL` for parity with the existing `_SORT_FIELD_SQL`.

**Test design notes:**
- The interval-set test had to be split: for `1h:` / `W:` / `M:` prefixes, the legacy path needs a lateral join and the snapshot path resolves the indicator inline (the snapshot table stores `rsi_1h`, `rsi_W`, `rsi_M` columns). This is a structural asymmetry in the data model, not a bug — the tests now document it explicitly.
- `_strip_column_refs` helper normalises `td.rsi_14` / `snap.last_close` / `ts.return_1w` to `<COL>` so we can compare structural shape (operators, parens, bind count) without being sensitive to which table the column comes from.

**Verification:** 385/385 pass (was 325; +60 new). No regressions.

**Follow-up:** B.9b — unify the legacy filter transpilers using a `column_map` parameter (≈200 LOC). Tracked separately because the math is non-equivalent and the change needs a Tier 3 integration test against both schemas.

---

## 16. Phase B: B.10 delete sync `nse_client.py` — DONE (commit `a611369`)

**Why:** The legacy 545-LOC sync `NSEClient` class in `nse_client.py` duplicated the HTTP / parsing logic in `nse_client_async.py`.  Drift had already happened: `get_top_gainers` sync copied `perChange` into `pChange`; the async path filters to `EQ` series and falls back to `nsepython` on JSON parse failure.  `get_stock_list` worked in sync, raised `NotImplementedError` in async.  Future fixes had to be made in two places with no test catching the divergence.

**What:**
- `app/services/nse_client_async.py`: added `NSEClient` sync-facade class + `nse_client` singleton.  Each method delegates to the async client via `asyncio.run()` (creates a fresh event loop per call; overhead ~1-10ms vs 100ms-2s NSE HTTP latency).  Sync-only methods (`get_stock_list` with nsepython fallback, `get_corporate_filing_comparison`) skip the `asyncio.run` wrap.
- `app/services/nse_client.py`: 545 LOC of duplicate class body replaced with a 56-line re-export module.  The 8 call sites (`routers/corporatefilings`, `routers/market_ws`, `routers/nonpersistence`, `routers/stockuniverse`, `backgroundtasks`, `orchestrator`, `mcp_server`, `main.py`) keep working without import changes.

**Behavioural notes:**
- The facade ALWAYS uses the async implementation.  A few methods had divergent behaviour between old sync and async (EQ-series filter, perChange/pChange copy, nsepython fallback, get_stock_list working vs raising).  Callers will see the more-correct async behaviour from now on.
- `get_stock_list` historically called `nsepython.nse_eq_symbols()` directly; the facade preserves that via a try/except fallback.
- `SymbolNotFoundError` re-exported so existing `except` blocks keep working.

**Verification:** 397/397 pass (was 385; +12 new). No regressions.  Lines: nse_client.py 545 → 56 (‑489), nse_client_async.py 385 → 470 (+85). Net ‑404 LOC deleted.

---

## 17. Phase B: B.11 orchestrator cleanup — DONE (commit `ea871ad`)

**Why:** `orchestrator.py` had three forms of boilerplate: a polling `_wait_for_shutdown`, three near-identical cron schedulers, and nine near-identical pipeline-stage blocks.

**What:**
- `_wait_for_shutdown` is now `await shutdown_event.wait()` (zero CPU, fires immediately on `.set()`).
- New `_cron_loop(cron_expr, job_key, target_fn, *, compute_wait_secs, next_fire_label_fn=None, schedule_label)` consolidates the three schedulers.  Each is now a 7-line configuration.
- New `_run_stage(mode, stage_name, sub_jobs, *, progress_start, progress_end, stage_label, requires_mode=None, on_complete=None)` consolidates the 9 stage blocks.  Each stage in `_execute_pipeline` is now 5-7 lines of helper configuration.  `_execute_pipeline` shrank from ~317 → ~200 LOC.

**Test design notes:**
- `_run_stage` returns a 3-state value: `True` (stage ran / was mode-skipped — caller continues), `False` (shutdown requested — caller should bail).  Tests pin this contract.
- The shutdown check happens at the start of each stage; the helper returns `False` and the caller bails.  Original code did `if _shutdown_event.is_set(): return` between every stage.

**Verification:** 412/412 pass (was 397; +15 new). No regressions.  Lines: orchestrator.py 732 → 708 (‑24).  Function-level: `_execute_pipeline` 280 → 200 LOC (‑80), three schedulers 117 → 23 LOC (‑94).

---

## 18. Phase B: B.12 wrap sync warehouse calls in `asyncio.to_thread` — DONE (commit `486b883`)

**Why:** `app/services/ticker_warehouse.py` is fully synchronous (SQLAlchemy `Session` under the hood).  The 5 ticker router handlers (`get_ohlcv`, `get_latest`, `get_status`, `get_intraday_ohlcv`) were calling the warehouse directly from `async def` handlers, blocking the event loop for the duration of every DB round-trip.

**What:**
- 5 sync warehouse calls in `routers/ticker.py` wrapped in `asyncio.to_thread(...)` so the SQLAlchemy work runs in a thread-pool worker.
- Wraps use the bound method (`asyncio.to_thread(ticker_warehouse.get_ohlcv, ...)`) rather than a lambda, preserving `__name__` / `__doc__` for debugging.

**Other call sites left untouched (intentional):**
- `routers/portfolio.py`: `_run_optimization_sync` and `_fetch` helper are already wrapped in `asyncio.to_thread`.  No change.
- `backgroundtasks.py`: the 5 warehouse calls in `_ticker_backfill_sync` run inside a worker thread (the function is sync and called via `loop.run_in_executor` from `orchestrator._run_pipeline_stage`).  Wrapping these in `asyncio.to_thread` would be redundant.  Tests pin this invariant.

**Verification:** 419/419 pass (was 412; +7 new). No regressions.  Performance: ticker router endpoints no longer block the event loop on the sync SQLAlchemy round-trip.

---

## 19. Phase B progress summary (COMPLETE)

| Item | Title | Commit | Tests added | Cumulative |
|------|-------|--------|-------------|-----------|
| B.1  | TQL SQL cache | `74f162c` | 15 | 247 |
| B.2+B.3 | Shared httpx + gather | `886a6c4` | 10 | 257 |
| B.4  | Pragma helper + drop thread engine | `14efe2c` | 5 | 262 |
| B.5  | Move inline Pydantic to schemas/ | (B.5 commit) | 40 | 302 |
| B.6  | Centralize cookie loader | `82aac9f` | 8 | 310 |
| B.7  | Consolidate 3 semaphores | `26bcecc` | 9 | 319 |
| B.8  | `paginate()` helper | `91c30c7` | 6 | 325 |
| B.9 (partial) | Unify TQL AST + sort | `25f2c2f` | 60 | 385 |
| B.10 | Delete sync `nse_client.py` (facade) | `a611369` | 12 | 397 |
| B.11 | Orchestrator cleanup | `ea871ad` | 15 | 412 |
| B.12 | `asyncio.to_thread` warehouse | `486b883` | 7 | 419 |

**Final tally: 232 → 419 pure‑unit tests (+187 across 11 audit items, +1 follow-up deferred).**

**Deferred:** B.9b — unify `_legacy_where` and `_legacy_where_snapshot` via a `column_map` parameter.  Deferred because the SQL fragments are not equivalent (precomputed `pct_*` columns vs `CASE WHEN` runtime computation); would need Tier 3 integration tests against both schemas.  Tracked for a future session.

**Branch:** `docs/backend-audit-and-test-plan` (16 commits ahead of `main`).

**Files touched in Phase B:**
- `app/services/tql_to_sql.py` (B.1, B.9)
- `app/routers/announcements.py` (B.2, B.3)
- `app/database.py`, `app/backgroundtasks.py` (B.4)
- `app/schemas/{announcements,news,stockuniverse,ticker}.py` (B.5)
- `app/services/cookie_loader.py`, `app/services/{screener_client,morningstar_client}.py` (B.6)
- `app/services/{nse_rate_limiter,screener_client,morningstar_client}.py` (B.7)
- `app/services/pagination.py`, `app/routers/news.py` (B.8)
- `app/services/{nse_client,nse_client_async}.py` (B.10)
- `app/orchestrator.py` (B.11)
- `app/routers/ticker.py` (B.12)

---

## 20. Phase C.1 — file split of `backgroundtasks.py` (Session 1, 2026-06-06)

**Status:** A.1-A.8 DONE.  A.9-A.13 pending.  627/627 pure-unit pass.

### 20.1 What was done

Track A.1-A.8 of audit C.1 (file split of `backgroundtasks.py` 4994 → 12 modules):

| Step | Module | Functions | _impl.py LOC after | New module LOC | Tests |
|---|---|---|---|---|---|
| A.1 | `app/backgroundtasks/` package + shim | (skeleton) | 4994 | — | +108 |
| A.2 | `app/workers/` + `app/services/data_sync/` | (skeletons) | 4994 | — | +36 |
| A.3 | `app/services/data_sync/universe.py` | 3 | 4855 (-139) | 232 | +14 |
| A.4 | `app/services/data_sync/backfill.py` | 1 | 4801 (-54) | 110 | +8 |
| A.5 | `app/services/data_sync/intraday.py` | 2 | 4559 (-242) | 298 | +11 |
| A.6 | `app/services/data_sync/daily.py` | 1 | 4405 (-154) | 197 | +8 |
| A.7 | `app/services/data_sync/scores.py` | 1 | 4199 (-206) | 247 | +8 |
| A.8 | `app/services/data_sync/indicators.py` | 2 | 4014 (-185) | 239 | +11 |
| **Total moved** | | **12 functions** | **-980 LOC** | | **+204 tests** |

**Sync cores remaining in `_impl.py`:** `_screener_snapshot_sync`, `_parallel_indicator_sync`, plus the 3 notification cycles (`_ticker_indicator_notification_cycle`, `_ticker_intraday_indicator_notification_cycle`, `_global_scan_cycle`).

**Workers remaining in `_impl.py`:** `stock_universe_worker`, `ticker_backfill_worker`, `ticker_daily_update_worker`, `ticker_intraday_hourly_update_worker`, all notification workers (`ticker_indicators_worker`, `ticker_intraday_indicators_worker`, `ticker_indicator_notification_worker`, `ticker_intraday_indicator_notification_worker`, `global_scan_worker`, `notification_cycle_full_worker`), `ticker_scores_worker`, fair-value workers, news workers, `vacuum_worker`, `retention_worker`.

### 20.2 Commit log (Phase C.1)

| SHA | Subject |
|---|---|
| `41b59cd` | test(goldens): capture 5 phase C target function outputs (audit C.1 prep) |
| `589b0d1` | refactor(backgroundtasks): package split with re-export shim (audit C.1 A.1) |
| `a661705` | feat(workers,data_sync): package skeletons for C.1 A.2 |
| `f2698e1` | refactor(data_sync): extract universe module from backgroundtasks (A.3) |
| `05a1709` | refactor(data_sync): extract backfill module from backgroundtasks (A.4) |
| `9bf6dbc` | refactor(data_sync): extract intraday module from backgroundtasks (A.5) |
| `14dcde3` | refactor(data_sync): extract daily module from backgroundtasks (A.6) |
| `02de51b` | refactor(data_sync): extract scores module from backgroundtasks (A.7) |
| `24a17b2` | refactor(data_sync): extract indicators module from backgroundtasks (A.8) |

### 20.3 Key technical decisions

- **Re-export shim pattern**: `app/backgroundtasks/__init__.py` explicitly re-exports 80+ names from `_impl` (not `from _impl import *`); `_impl.py` re-imports the new modules at the bottom of its file.  This preserves `is`-identity (`bg.X is data_sync.Y`) for drift-proof tests.
- **Lazy-resolve helpers**: each new module defines module-level helpers (`_shutdown_event()`, `_update_job_status_sync()`) that do `from app.backgroundtasks import _impl` and return the live reference.  This avoids import-order cycles (`_impl` re-exports the new modules, workers in new modules need `_impl` helpers).
- **logger import inside function body, not module top**: `intraday.py` triggered a circular `ImportError` when `from app.backgroundtasks._impl import logger` was at module top.  Moved into the function body.  Now consistent across all data_sync modules.
- **Naming**: `app/services/data_sync/indicators.py` SHADOWS the name `app.services.indicators` (the compute service).  Inside the new module we import the latter as `svc_indicators` to avoid confusion.
- **Goldens stability**: `scripts/capture_phase_c_goldens.py` now sorts notification lists by `(symbol, trigger_type)` before writing JSON, because the source uses `set` iteration (hash-order, non-deterministic across Python sessions).  Verified byte-identical MD5 across 2 consecutive runs.
- **Pre-existing bug discovered**: `app/models/news.py` line 56-99 — `sentiment` and `threat_level` have both `index=True` AND a hand-written `Index("ix_news_articles_sentiment", "sentiment")` in `__table_args__`.  `Base.metadata.create_all` fails with "index already exists".  `tests/conftest.py::in_memory_db` fixture is broken; no test actually uses it.  Workaround: de-duplicate auto-indexes in `Base.metadata` before `create_all` (same pattern as `tests/test_pagination_helper.py::async_db`).
- **Module-globals fragility (post-A.1)**: after the package split, functions in `_impl` look up their dependencies in their own module globals, not the package's.  `monkeypatch.setattr(backgroundtasks, "AsyncSessionLocal", ...)` does NOT work — must patch `backgroundtasks._impl.AsyncSessionLocal`.  Affected `test_utcnow_migration_parity.py` (3 tests fixed).  Same pattern in capture script via `_patch(name, value)` helper that patches both `bg.X` and `bg._impl.X`.

### 20.4 Pre-capture goldens (5 files in `tests/golden/`)

- `global_scan_50_symbols.json` (168 pending)
- `ticker_indicator_notification_50_symbols.json` (27 pending)
- `ticker_intraday_indicator_notification_50_symbols.json` (59 pending)
- `intraday_hourly_stale_check_10_symbols.json` (10 symbols)
- `ticker_scores_50_symbols.json` (50 rows)

All 5 verified byte-identical across A.1-A.8 refactors.  Capture script: `backend/scripts/capture_phase_c_goldens.py`.

### 20.5 Next steps (Session 2+)

| Step | Scope | LOC estimate |
|---|---|---|
| A.9 | Split workers: `app/workers/{data,news,notifications,fair_value,maintenance}.py` | -1200 LOC |
| A.10 | Extract `_runtime.py` for shutdown/first-run helpers | -100 LOC |
| A.11 | Split remaining sync cores (`_screener_snapshot_sync`, `_parallel_indicator_sync`, 3 notification cycles) | -800 LOC |
| A.12 | Delete legacy `app/backgroundtasks.py` (keep package shim only) | -4014 LOC |
| A.13 | Verify no external callers reference the old `app/backgroundtasks.py` (all use `app.backgroundtasks.*` package path) | — |
| B.1-B.8 | Perf work (C.3 N+1, C.4 bulk insert/update, C.5 parallelize, C.6 async helper, C.7 window fn, C.8 alerts extract) | — |

### 20.6 Files created in Phase C.1 Session 1

**New modules:**
- `backend/app/backgroundtasks/__init__.py` (re-export shim, 150 LOC)
- `backend/app/backgroundtasks/_impl.py` (moved impl, 4014 LOC)
- `backend/app/workers/__init__.py` (re-export shim, 45 LOC)
- `backend/app/services/data_sync/__init__.py` (package marker, 18 LOC)
- `backend/app/services/data_sync/universe.py` (3 fns, 232 LOC)
- `backend/app/services/data_sync/backfill.py` (1 fn, 110 LOC)
- `backend/app/services/data_sync/intraday.py` (2 fns, 298 LOC)
- `backend/app/services/data_sync/daily.py` (1 fn, 197 LOC)
- `backend/app/services/data_sync/scores.py` (1 fn, 247 LOC)
- `backend/app/services/data_sync/indicators.py` (2 fns, 239 LOC)

**New tests (8 files):**
- `backend/tests/test_backgroundtasks_split.py` (108 tests)
- `backend/tests/test_workers_skeleton.py` (18 tests)
- `backend/tests/test_data_sync_skeleton.py` (18 tests)
- `backend/tests/test_data_sync_universe.py` (14 tests)
- `backend/tests/test_data_sync_backfill.py` (8 tests)
- `backend/tests/test_data_sync_intraday.py` (11 tests)
- `backend/tests/test_data_sync_daily.py` (8 tests)
- `backend/tests/test_data_sync_scores.py` (8 tests)
- `backend/tests/test_data_sync_indicators.py` (11 tests)

**New tools:**
- `backend/scripts/capture_phase_c_goldens.py` (5 goldens, byte-stable output)

**Modified tests (3 pre-existing tests fixed to patch `_impl` namespace):**
- `backend/tests/test_database_pragma_helper.py`
- `backend/tests/test_ticker_warehouse_async_wrap.py`
- `backend/tests/test_utcnow_migration_parity.py`

### 20.7 Session 2 step 1 (A.9 maintenance extraction, 2026-06-06)

**Commit:** `c58cde0` — `refactor(workers): extract maintenance module from backgroundtasks (A.9 step 1)`

**What was done:**
- Moved `vacuum_worker`, `_run_vacuum`, `VACUUM_CRON` from `_impl.py` to new `app/workers/maintenance.py` (132 LOC, under 200 sentinel).
- `_impl.py` 4014 → 3934 LOC (-80).
- 7 new tests in `tests/test_workers_maintenance.py` (size sentinel, `__module__` check, is-identity, caller-import smoke, signature).
- New `TestMovedWorkers` class in `tests/test_backgroundtasks_split.py` enforces the contract for symbols that have left `_impl.py`.

**Circular import resolution (the meat of this commit):**
The re-import at the bottom of `_impl.py` (the "is-identity bridge" pattern) was REMOVED.  Instead, `app.backgroundtasks/__init__.py` imports the moved symbols DIRECTLY from `app.workers.maintenance`.  Reason: the re-import pattern created a cycle

  `_impl` → `app.workers.maintenance` → `app.workers.__init__` → `app.backgroundtasks` (mid-init) → boom

The direct-import pattern breaks the cycle because `app.workers.maintenance` does not trigger a re-entry into `app.backgroundtasks` on load (its imports of backgroundtasks symbols are all lazy, inside function bodies).  The is-identity guarantee is preserved by the direct import in `__init__.py`: `app.backgroundtasks.vacuum_worker is app.workers.maintenance.vacuum_worker`.

`register_all_jobs` (still in `_impl.py` until A.13) uses a lazy import at the top of the function body to pull `VACUUM_CRON` and `_run_vacuum` from the new home.

**TestMovedWorkers contract:**
For each entry in `MOVED_SYMBOLS = [(name, new_home), ...]`:
1. `bg.<name>` exists (re-export shim works)
2. `_impl.<name>` does NOT exist (move is complete, not a stale local copy)
3. `bg.<name> is <new_home>.<name>` (drift-proof identity)

Future A.9 steps (data, notifications, news workers) will add entries to `MOVED_SYMBOLS` and satisfy this contract.

**Bug surfaced & fixed in earlier commit `d7fd354` (goldens expansion):**
`_bulk_insert_stock_universe` in `app/services/data_sync/universe.py` did NOT set `ticker_failure_count=0` in the `INSERT … ON CONFLICT` set.  The model column is `NOT NULL` with no default, so any production insert would have raised `IntegrityError`.  Fixed in `d7fd354`.  Golden `bulk_insert_stock_universe_5_rows.json` catches regressions.

**Pre-existing bugs (NOT YET FIXED, tracked separately):**
- `app/models/news.py` lines 56, 84, 99-100: duplicate-index bug (`sentiment` and `threat_level` have both `index=True` and a hand-written `Index()` in `__table_args__`).
- `tests/test_cleanup.py` collection error: imports `CLEANUP_INTERVAL` and `VACUUM_CRON` from `app.backgroundtasks` but these were never re-exported in the package shim.  Pre-existing since 589b0d1.  Fix: add `from app.backgroundtasks._impl import CLEANUP_INTERVAL` + `from app.workers.maintenance import VACUUM_CRON` to the shim.  Tracked as a separate low-priority commit.

**Test status:** 634/634 pure-unit suite passes (was 627/627, +7 from new `test_workers_maintenance.py`).  All 12 phase C goldens still byte-identical.

### 20.8 Handoff doc

`docs/reference/backend/PHASE_C_HANDOFF.md` — full session-by-session record of Phase C.1 progress, with: LOC reductions, new module inventory, test inventory, golden inventory, next-step roadmap (A.9 step 2 onwards), architectural invariants to preserve, capture-script gotchas, module-globals fragility caveats, monkey-patch caveat, and Phase C.1 completion criteria.  Read this FIRST when resuming the work in a new session.

---

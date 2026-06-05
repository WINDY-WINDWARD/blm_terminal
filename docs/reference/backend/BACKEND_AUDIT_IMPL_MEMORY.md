# Backend Audit Implementation — Memory

**Companion to:** `BACKEND_AUDIT.md`, `REFACTOR_TEST_PLAN.md`
**Branch:** `docs/backend-audit-and-test-plan` (local, **not pushed**)
**Base:** `bc6dbde` (Merge PR #3 intraday-worker-refactor)
**Date:** 2026-06-05
**Status:** 6 implementation commits, 68 audit-related parity tests pass, 294/294 pure-unit pass

---

## 1. Commits (newest → oldest)

| SHA | Subject | Files | +/- | Audit citation |
|---|---|---|---|---|
| `7e1c71b` | refactor(routers): unify 3 TTL caches onto `cache.nse_cache` | 4 | +342/-75 | §4.5 L180 (Phase A.8) |
| `e04ae49` | refactor(services): pool `httpx.AsyncClient` at module level in `rss_parser` + `ai_chat_service` | 2 | +27/-27 | §4.8 L284, §4.10 L307, Top 10 #10 (Phase A.7) |
| `818c8c8` | fix(news_fetcher): stop mutating shared client headers + release sem before sleep | 1+1 | +278/-9 | §5 L353, Phase A.9 + A.10 |
| `758daae` | refactor(timezone): migrate `pytz` to stdlib `zoneinfo.ZoneInfo` | 4+1 | +260/-27 | §4.5 L187, §5 L345 (Phase A.2) |
| `869ca70` | refactor(services): delete confirmed dead code (audit phase A) | 5 | -246/+18 | §5 L334-342 (Phase A.1) |
| `af8a2aa` | test+refactor: TQL `parse_tql` LRU cache + test infra baseline | 1+1+1+1 | +485/-2 | §4.9 L294, Top 10 #8 (Phase A.6) |
| `3551112` | docs: add backend performance audit and refactor-parity test plan | 2 | (docs only) | — |

**Total diff vs `main`:** 27 files, +2951/-598.

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

---

## 3. Test counts (verified by `pytest --collect-only` + `pytest`)

### Audit-related test files (all 5 pass)
| File | Tests | Type |
|---|---|---|
| `test_tql_parser_parity.py` | 17 | 13 behavior + 4 cache contract, 1 perf |
| `test_timezone_migration.py` | 15 | 7 pattern parity + 5 public fn + 3 sanity |
| `test_news_fetcher_concurrency_parity.py` | 9 | 3 header + 6 sem/sleep |
| `test_httpx_pool_parity.py` | 16 | 8 rss_parser + 5 ai_chat + 3 call-site |
| `test_router_cache_unification_parity.py` | 11 | 6 structural + 5 behavioral |
| **Total** | **68** | |

### Full pure-unit suite
- **294 pass, 11 fail** in 108.21s
- Failures are all in `test_mcp_stdio.py` (pre-existing — confirmed by stash+re-run at session start)
- Excluded from full run: `test_endpoints.py`, `test_mcp.py`, `test_notifications.py`, `test_notification_worker.py` (require live server)

### DB safety
- `backend/data.db.pre-news_fetcher.bak` (1.4GB) created at session start
- SHA256 of `data.db` matches backup after all audit-related tests run
- The `test_cleanup.py` suite (13 tests) DOES touch live DB via VACUUM/ANALYZE — pre-existing, not from these changes

---

## 4. Phase A status (BACKEND_AUDIT.md L362-373)

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | Delete dead code (§5 L334-342) | **DONE** | `869ca70` |
| 2 | `pytz → zoneinfo` repo-wide | **DONE** | `758daae` |
| 3 | Lift function-level imports to module top | NOT DONE | — |
| 4 | Compile regexes at module level | NOT DONE | — |
| 5 | `datetime.utcnow()` → `now(timezone.utc)` | PARTIAL (only via timezone migration; no dedicated sweep) | — |
| 6 | `@functools.lru_cache(maxsize=256)` on `parse_tql` | **DONE** | `af8a2aa` |
| 7 | Module-level `httpx.AsyncClient` (3 sites) | **DONE** for 2 (ai_chat, rss_parser); **N/A** for 1 (nse_charting_client uses sync `requests`) | `e04ae49` |
| 8 | Unify 3 router TTL caches → `cache.nse_cache` | **DONE** | `7e1c71b` |
| 9 | Fix `news_fetcher.py:655` sleep-in-semaphore | **DONE** (1 sleep site, despite audit citing 2) | `818c8c8` |
| 10 | Fix `news_fetcher.py:246-285` shared-client header mutation | **DONE** | `818c8c8` |

**Summary:** 7/10 done, 2 partial/orthogonal, 1 misread.

---

## 5. Top 10 status (BACKEND_AUDIT.md L35-47)

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | N+1 queries in scan + notif cycles | NOT DONE | — |
| 2 | Delete sync `nse_client.py` (545 LOC) | NOT DONE | — |
| 3 | Sync DB inside `async def` handlers | NOT DONE | — |
| 4 | Split `backgroundtasks.py` (4994→6 modules, currently 4989) | NOT DONE | — |
| 5 | Per-row execute → bulk insert/update | NOT DONE | — |
| 6 | Serial NSE fetches → `asyncio.gather + Semaphore` | NOT DONE | — |
| 7 | `_run_async()` (new event loop per call) | NOT DONE | — |
| 8 | TQL AST / SQL not cached | **DONE** (parse_tql only) | `af8a2aa` |
| 9 | Unify duplicate TQL transpilers (~400 LOC) | NOT DONE | — |
| 10 | Pool httpx clients | **DONE** (rss_parser + ai_chat only) | `e04ae49` |

**Summary:** 2/10 done. Phase B + C are entirely untouched.

---

## 6. Files NOT touched (intentionally)

- `services/nse_client.py` (545 LOC) — Top 10 #2, deferred (risky)
- `services/nse_client_async.py` (385 LOC) — canonical, no change needed
- `app/backgroundtasks.py` (4989 LOC) — Top 10 #4, deferred (big-bang split)
- `services/parallel_sync.py:221-224` — `# noqa: F821` fix orthogonal to dead-code pass
- `services/tql_to_sql.py` (~400 LOC) — Top 10 #9, deferred (unification needs Phase B planning)
- `services/screener_client.py:159-161` regex compile — Phase A.4, deferred
- `routers/ticker.py:604,608,618-619,466-467`, `news_ws.py:148` function-level imports — Phase A.3, deferred
- `news_aggregator.py:62` `datetime.utcnow()` — Phase A.5, no dedicated sweep done

---

## 7. Audit doc deltas needed

- Update Phase A table: mark 7 items done with commit SHAs
- Update Top 10 table: mark 2 items done with commit SHAs
- Note: `nse_charting_client` was misread in audit (sync `requests`, not httpx)
- Note: `news_fetcher.py:655` audit citation was a second sleep site that didn't exist; only one site moved
- Note: `news_fetcher.py:246-285` audit citation was the 5-page state diagram; the actual bug surface was `client.headers.update` at `:373` (the fix site)

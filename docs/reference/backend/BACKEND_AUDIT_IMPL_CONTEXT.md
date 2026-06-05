# Backend Audit Implementation — Context

**Companion to:** `BACKEND_AUDIT.md`, `REFACTOR_TEST_PLAN.md`, `BACKEND_AUDIT_IMPL_MEMORY.md`

This document captures the **why** and the **how** of the Phase A implementation work — the reasoning, the methodology, the design choices, the gotchas, and the conventions established along the way. Use it to onboard a fresh agent on this work, or to make the same trade-offs in future phases.

---

## 1. Background

`BACKEND_AUDIT.md` was written on 2026-06-05 by a senior Python engineer reviewing the `backend/` tree (~24,000 LOC). It identified:

- 8 god-files >900 lines (worst: `backgroundtasks.py` at 4994)
- Pervasive N+1 query patterns over the ~2000-symbol universe
- Sync DB calls inside `async def` handlers (event loop blocking)
- ~1500 LOC of duplicate code paths (sync/async NSE client, two TQL transpilers, per-table indicator boilerplate, 3 router TTL caches, 2 schedulers per cron job)
- Concurrency hazards (shared httpx client mutation, unbounded caches, 8-min worst-case shutdown)

The audit proposed a 4-phase execution plan:
- **Phase A** — Quick Hygiene (1-2 days, low risk): 10 items, mostly mechanical
- **Phase B** — Architectural Cleanup (3-5 days, medium risk): TQL unification, sync/async merge
- **Phase C** — File Splits + N+1 Elimination (1-2 weeks, invasive): the big structural changes
- **Phase D** — Engine-Level (deeper risk, optional)

`REFACTOR_TEST_PLAN.md` established a 5-tier test strategy (golden / parity / contract / behavior / microbenchmark) to lock down observable behavior before each refactor.

This session's work: implement Phase A, tests-first, on a dedicated branch, with a DB backup.

---

## 2. Methodology

### 2.1 Branching strategy
- Base: `bc6dbde` (Merge PR #3 intraday-worker-refactor on `main`)
- Branch: `docs/backend-audit-and-test-plan` — local only, **not pushed** at session end
- Reasoning: the audit + test plan were originally going to be a docs PR; the implementation work piled on the same branch. Keeping it local gives the user a review point before any push.

### 2.2 DB safety
- Before any code that *could* touch `data.db`, a snapshot was made: `backend/data.db.pre-news_fetcher.bak` (1.4GB)
- SHA256 of `data.db` verified equal to backup before and after every audit-related test run
- The `test_cleanup.py` suite (13 tests) does run VACUUM/ANALYZE on the live DB — this is pre-existing test behavior, not introduced by these changes. Tests are excluded from the "audit-related" count for this reason.

### 2.3 TDD discipline
For every fix:
1. **Backup DB** (if not already done in this session)
2. **Write parity tests** for the bug or the contract being preserved
3. **Run tests against the buggy/current code** → confirm they FAIL (red)
4. **Apply the fix** (smallest possible change)
5. **Run tests against the fixed code** → confirm they PASS (green)
6. **Run full pure-unit suite** → confirm no regressions
7. **Commit** with a message that documents the why, the contract, and the test counts

The 11 test failures in `test_mcp_stdio.py` were confirmed pre-existing (stash + re-run at session start). They were not caused by any commit in this session.

### 2.4 Test infrastructure
Created `tests/conftest.py` (189 lines) at `af8a2aa`:
- `test_db_path` fixture — returns the path to `backend/data_test.db` (a fresh, untracked, gitignored SQLite file with the full schema and 0 rows)
- `monkeypatch_test_db` — autouse fixture that monkeypatches `database.DATABASE_URL` and `database._engine` to use the test DB. (The audit-related tests don't actually need this because they use mock objects, but it's there for future tests that need real DB access.)
- `in_memory_db` — fixture for `:memory:` SQLite (used by `test_tql_parser_parity.py`)
- `golden_compare` — fixture for snapshot tests (per `REFACTOR_TEST_PLAN.md` Tier 1)
- Markers: `perf`, `parity`, `golden`

`backend/data_test.db` is a one-time `alembic upgrade head` against an empty SQLite, used to verify schema migrations and to test real-DB code paths without touching the live `data.db`.

### 2.5 Why a separate `data_test.db` and not `:memory:`?
`:memory:` loses the schema on every connection close, which is fine for pure unit tests but breaks for any test that needs a multi-connection session (e.g., testing the orchestrator's session lifecycle). A file-backed DB has the same semantics as `data.db` but is a fresh, empty starting point.

---

## 3. Per-item reasoning

### 3.1 Dead code removal (`869ca70`)

**Why:** The audit (§5 L334-342) listed 9 dead-code candidates. Dead code is a tax: it confuses readers, increases test surface, and complicates the future refactors that need to understand the call graph.

**How:** Verified each item with `grep` for callers. Three findings:
- `SQLiteCache` / `_shared_cache` / `get_shared_cache` — `grep` returned 0 callers. **Deleted.**
- `_get_date_lookup` in `returns.py` — `grep` returned 0 callers. **Deleted.**
- `import pandas as pd` in `momentum.py` — `grep` confirmed no `pd.` usage in the file. **Deleted.**
- `from collections import deque` in `indicators.py` — `grep` confirmed no `deque` usage. **Deleted.**
- `start_cache_cleanup` in `backgroundtasks.py` — `grep` showed no callers. **Deleted.**
- `_run_watchlist_scheduler` / `_run_nightly_scheduler` — `grep` showed `orchestrator.py:174,196` calls them. **Kept.** This was a close call: the audit's note ("orchestrator handles them") turned out to be inaccurate. The verification step saved us from breaking startup.
- `async def close()` on `NSEClient` — `grep` showed `orchestrator.py:156` calls it. **Kept.** Also inaccurate in the audit.
- `parallel_sync.py:221-224` `# noqa: F821` — **Deferred** (orthogonal fix; the F821 is a stale reference to a renamed variable in a closure, not a dead-code issue).

**Lesson:** The audit's dead-code list was right ~80% of the time. The 20% mismatch rate justifies the grep verification step on every item.

### 3.2 `pytz` → `zoneinfo.ZoneInfo` migration (`758daae`)

**Why:** `pytz` is a third-party dependency that is functionally redundant with stdlib `zoneinfo.ZoneInfo` (Python 3.9+). It has subtle behavioral differences (e.g., `localize()` vs `replace(tzinfo=...)`) that can cause bugs, and it adds an install dependency.

**How:** Identified 4 files using `pytz`:
- `services/ticker_warehouse.py:42`
- `routers/ticker.py:551`
- `orchestrator.py:38`
- `backgroundtasks.py:1163`

Verified 6 pattern equivalences manually before any change:
- `pytz.utc` → `datetime.timezone.utc` ✓
- `pytz.timezone("Asia/Kolkata")` → `ZoneInfo("Asia/Kolkata")` ✓
- `ist.localize(naive_dt)` → `naive_dt.replace(tzinfo=ist)` ✓ (safe for IST — no DST)
- `now_ist.replace(hour=9, ...)` — byte-identical behavior ✓
- `datetime.fromtimestamp(ts, tz=pytz.utc).replace(tzinfo=None)` — byte-identical ✓
- `r.timestamp.replace(tzinfo=pytz.utc).timestamp() * 1000` — byte-identical ✓

Wrote 15 parity tests covering: 7 pattern-parity tests (golden comparison of old vs new expression output for the 6 patterns), 5 public-function behavior tests (`get_last_trading_day`, `get_quote`, etc. called with frozen datetime), 3 sanity tests.

**Frozen-datetime test pattern:**
```python
def test_xxx(monkeypatch):
    from app.services import ticker_warehouse
    frozen = datetime(2026, 3, 10, 9, 0, 0, tzinfo=IST_ZONE)
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None: return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)
    monkeypatch.setattr(ticker_warehouse, "datetime", _FrozenDateTime)
    assert ticker_warehouse.get_last_trading_day() == date(2026, 3, 9)
```

This pattern is the gold standard for time-dependent code in this codebase. It subclasses `datetime` (not `Mock`) so `isinstance(frozen, datetime)` checks pass, and it overrides `now()` to return the frozen value. The `tz` parameter is preserved so any code that calls `datetime.now(IST_ZONE)` still works.

**Removed** `pytz>=2024.2` from `pyproject.toml`. **Kept** `pytz` import in the test file's golden computation helper — that helper explicitly compares old vs new, so it needs both libraries at runtime.

**Lesson:** Subclassing the real type beats `Mock` for time, datetime, and similar fundamental types. The frozen-datetime helper is reusable across all future timezone tests.

### 3.3 TQL `parse_tql` LRU cache (`af8a2aa`)

**Why:** `parse_tql` is called on every screener request. It re-tokenizes and re-parses the same TQL strings over and over. `@functools.lru_cache` on the input string is a free ~256-entry cache with no invalidation concerns (TQL strings are stable, the function is pure).

**How:** One-line change at `services/tql_parser.py:308`:
```python
@functools.lru_cache(maxsize=256)
def parse_tql(query: str) -> ...
```

Wrote 17 tests:
- 13 behavior tests (parametrized over TQL strings, asserting parsed AST matches expected structure)
- 4 cache contract tests (asserts that calling twice with the same string invokes the underlying parser once — verified via `mock.patch` counter)
- 1 perf test (asserts the cached path is faster than the cold path)

**Convention established:** For pure functions with string-typed inputs, prefer `@functools.lru_cache` over ad-hoc dict caches. Cache contract tests should verify the cache actually fires (not just that the function returns the right value).

### 3.4 news_fetcher concurrency bugs (`818c8c8`)

**Why:** The audit (§5 L353) called out two concurrency hazards in `news_fetcher.py`:
- Bug 1 (line 246-285): `client.headers.update(headers)` on the shared `httpx.AsyncClient` mutates client state visible to all coroutines. Two coroutines calling `_get_page` simultaneously can race: one mutates the headers mid-flight, the other sees the wrong headers.
- Bug 2 (line 655): `await asyncio.sleep(REQUEST_DELAY)` inside `async with self._get_semaphore():` holds the semaphore during the politeness sleep, capping crawl throughput to 3 articles/sec (the audit's number, but actual throughput depends on REQUEST_DELAY × CONCURRENCY_LIMIT). The semaphore's purpose (limit concurrent in-flight HTTP) is conflated with rate-limiting.

**How (Bug 1):** One-line change at `news_fetcher.py:377`:
```python
# before
client.headers.update(headers)
response = await client.get(url)

# after
response = await client.get(url, headers=headers)
```
Per-request `headers=` argument to `httpx.AsyncClient.get()` does not mutate the client. The shared client keeps its default headers, and each request adds its own.

**How (Bug 2):** Restructured `_fetch_and_parse_article` (lines 545-689) to:
1. Set `result` inside the `async with` block
2. Exit the block (releases the semaphore)
3. Sleep OUTSIDE the block — but only on success (`if result is not None`)

Error paths (`_ArticleNotFound`, generic `Exception`) `return None` from inside the `async with`, so they skip the sleep. This preserves the existing error-behavior contract: failed fetches don't incur the politeness delay.

Wrote 9 tests with fake `httpx.AsyncClient` and a `TrackedSemaphore` that records acquire/release order with active count. Verified:
- Header mutation: (a) correct per-request headers sent, (b) shared client headers NOT mutated between requests
- Sleep/sem: (a) sem released during sleep, (b) success path sleeps, (c) 404 path doesn't sleep, (d) generic exception path doesn't sleep, (e) sem released even on error

**Critical helper gotcha:** `make_fetcher()` must set BOTH `_client` AND `_client_loop` (same for `_semaphore`/`_semaphore_loop`) — otherwise the lazy init in `_get_client()`/`_get_semaphore()` sees a `None` loop, treats the current loop as mismatched, and **recreates the real httpx client/semaphore**, destroying the fakes and triggering real I/O. The first version of the test helper missed this and triggered real network calls on every test.

Also: bypass `_is_valid_response` (10KB threshold is an implementation detail for real MoneyControl pages) and use `make_failing_get_page(exc)` to test error paths without going through `_get_page`'s retry/backoff (otherwise `asyncio.sleep(1)` and `asyncio.sleep(2)` would fire from the backoff and slow tests).

**Audit accuracy note:** The audit cited 2 sleep sites (lines 547 and 655), but only 1 site (line 655) had a `sleep(REQUEST_DELAY)` to move. The line 547 reference appears to be the call site of `_fetch_and_parse_article` itself, not a separate sleep.

### 3.5 httpx pool (`e04ae49`)

**Why:** The audit (Top 10 #10, §4.8 L284, §4.10 L307) called out per-call `httpx.AsyncClient()` creation in 3 places. Each `async with httpx.AsyncClient(...)` creates a new TCP connection pool, does a fresh DNS lookup on first use, and tears everything down on exit. Over hundreds of requests per minute, this is 5-10× connection overhead per call.

**How:** Module-level factory pattern (the same in both `rss_parser.py` and `ai_chat_service.py`):
```python
_SHARED_CLIENT_TIMEOUT = 15.0  # or 120.0 for ai_chat
_shared_client: httpx.AsyncClient | None = None
_shared_client_loop: asyncio.AbstractEventLoop | None = None

def _get_shared_client() -> httpx.AsyncClient:
    global _shared_client, _shared_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        if _shared_client is None:
            _shared_client = httpx.AsyncClient(timeout=_SHARED_CLIENT_TIMEOUT, follow_redirects=True)
        return _shared_client
    if _shared_client is None or _shared_client_loop is not current_loop:
        _shared_client = httpx.AsyncClient(timeout=_SHARED_CLIENT_TIMEOUT, follow_redirects=True)
        _shared_client_loop = current_loop
    return _shared_client
```

Three branches:
- **Sync context (no running loop):** reuses cached client if exists, otherwise creates one and caches it. The "no running loop" branch exists for test code that imports the module but doesn't `asyncio.run()`.
- **Async context, same loop as cached:** returns cached client. The cheap, hot path.
- **Async context, different loop (e.g., test fixture creates a new loop):** rebuilds client bound to current loop. Required because `httpx.AsyncClient` is bound to a specific event loop.

Wrote 16 tests:
- 8 for rss_parser: factory exists, returns httpx.AsyncClient, reused across calls, config preserved (timeout=15, follow_redirects=True), recreated on loop change, `fetch_feed` uses shared client (end-to-end with recording transport), per-request timeout override works, 8 concurrent calls share one client
- 5 for ai_chat: same factory contract
- 3 call-site: source-inspection asserts `async with httpx.AsyncClient` no longer in the call sites

**Convention established:** For the future `nse_charting_client`, the audit misread (it uses sync `requests`, not httpx). The same pool pattern would apply if/when it's converted to async.

**Test gotcha:** `_RecordingTransport(httpx.AsyncBaseTransport)` works for faking `client.get(url, ...)`. Inject via `client._transport = transport` AFTER `_get_shared_client()` returns the real client. The leading underscore on `_transport` is intentional (httpx's "private" attribute) and this is the only way to swap the transport on a live client.

**Convention established:** `pytest.mark.asyncio` to exercise the loop-change path; sync tests calling the factory hit the no-running-loop branch.

### 3.6 3-router cache unification → `nse_cache` (`7e1c71b`)

**Why:** The audit (§4.5 L180) called out 3 routers (`valuation.py`, `portfolio.py`, `screener.py`) each implementing their own ad-hoc dict+TTL cache. Each had:
- A module-level `_cache: dict` or `_CACHE: dict`
- One or more TTL constants (`_CACHE_TTL`, `SEARCH_TTL`, `COMPANY_TTL`, `TRADES_TTL`, `QUARTERLY_TTL`)
- A `_cache_get(key)` helper that checks TTL and returns `None` on miss
- A `_cache_set(key, value[, ttl])` helper that stores the current time + value

This is reinventing `cachetools.TTLCache` (already a dependency, already used in `cache.py` for `nse_cache`, `screener_html_cache`, `screener_search_cache`, `mcp_cache`).

**How:** For each router:
- Add `from app.services.cache import nse_cache`
- Delete the private `_cache` dict, TTL constants, and helpers
- Delete `import time` (only used by the cache helpers)
- Replace `_cache_get(key)` → `nse_cache.get(key)`
- Replace `_cache_set(key, val)` → `nse_cache[key] = val`

Updated the `screener_quarterly` docstring from "shared raw-HTML cache (15-minute TTL)" to "shared nse_cache (TTL configured on app.services.cache — 600s)".

**Behavioral change:** All 3 routers now use the canonical `nse_cache` TTL of 600s. Old per-router TTLs:
- `valuation`: 1800s → 600s (cache expires 3× faster — fresher data, marginally more NSE load)
- `portfolio`: 900s → 600s (cache expires 1.5× faster)
- `screener.search`: 60s → 600s (cache expires 10× **slower** — this was the only one with a *shorter* TTL)
- `screener.{company,trades,quarterly}`: 900s → 600s (cache expires 1.5× faster)

The unification contract is specified in `BACKEND_AUDIT.md` line 180: "Reuse `cache.nse_cache`". This is the intended behavior change.

Wrote 11 tests:
- 6 structural: `inspect.getsource(module)` contains `from app.services.cache import nse_cache`; `hasattr(module, "_cache")` etc. all false
- 5 behavioral: monkeypatch the underlying data fetcher; assert first call invokes the fetcher and populates the cache; second call is a cache hit (fetcher not re-invoked)

**Critical test infra gotcha:** `nse_cache` is shared across `valuation`, `portfolio`, `screener`, `nonpersistence`, and `market_ws`. An `autouse=True` fixture `_clear_nse_cache` clears before AND after each test. Without this, cache leaks would break test isolation (test B's first call would be a cache hit, but with test A's data).

**Critical test gotcha:** `monkeypatch.setattr(valuation, "_fetch_valuation_data", fake_fetch)` works because the function body uses `LOAD_GLOBAL` to look up the name (it's a top-level function in the module). If the function were imported into the router's namespace, the monkeypatch would need to target the import location.

**Critical test gotcha:** `monkeypatch.setattr(screener_client, "search", fake_search)` works for instance-attribute shadowing on the `ScreenerClient()` singleton — callers do `screener_client.search(q)` (instance lookup wins over class). If the singleton were replaced per-call, this wouldn't work.

**Pydantic gotcha:** `PortfolioOptimizeRequest.symbols` has `min_length=3`, so the test data must have ≥3 symbols. This was a 30-minute debugging session to find.

**Convention established:** If a router needs a different TTL than `nse_cache`'s 600s, the right move is to add a new named cache to `app/services/cache.py` (e.g., `valuation_cache` with 1800s TTL), not to bypass the module with another ad-hoc dict. The audit's preferred destination is `nse_cache` for consistency, but the rule is "no per-router caches, only module-level named caches."

---

## 4. Cross-cutting conventions established

### 4.1 Test structure
Every audit-related fix has 1 new test file in `backend/tests/` with the naming pattern `test_<topic>_parity.py`. Each test file:
- Documents the bug/contract being tested in the module docstring
- Has both structural tests (asserting the refactor was applied) and behavioral tests (asserting the new code works)
- Uses `monkeypatch` rather than patching decorators
- Avoids real I/O (fakes for httpx, in-memory DB)

### 4.2 Naming
- Test files: `test_<topic>_parity.py`
- Test functions: `test_<scenario>_<expected_outcome>` (e.g., `test_optimize_portfolio_populates_nse_cache`)
- Fixtures: `_clear_nse_cache` (leading underscore = "internal to this test file")
- Fakes: `FakeAsyncClient`, `FakeResponse`, `TrackedSemaphore` (PascalCase despite being test doubles — local convention)

### 4.3 Module-level state
- Shared resources (httpx clients, DB engines) live at module level with lazy init + per-loop cache invalidation
- `asyncio.get_running_loop()` to detect loop mismatch; rebuild on mismatch
- `_shared_X` and `_shared_X_loop` pair for the loop-bound case

### 4.4 Datetime mocking
- Subclass the real type (don't use `Mock`)
- Override `now()` to return a frozen value
- Preserve the `tz` parameter

### 4.5 TDD commit message format
```
refactor(<scope>): <one-line summary>

<why - the audit citation or the bug>
<what - the concrete change>
<how - the test pattern, the gotchas>
<verification - test counts before/after>
```

---

## 5. What's next (Phase A remaining + Phase B/C)

### 5.1 Phase A remaining (low risk, mechanical)
- **A.3** Lift function-level imports to module top in `ticker.py:604,608,618-619,466-467` and `news_ws.py:148`. ~10 lines moved, 5-line parity test (assert no import statements inside function bodies).
- **A.4** Compile regexes at module level in `screener_client.py:159-161`. Module-level `re.compile()` calls + delete in-function `re.compile()` calls. 3-line parity test (assert compiled regex behavior unchanged).
- **A.5** Dedicated `datetime.utcnow()` sweep. Grep for `utcnow()` in `backend/app/`, replace each with `datetime.now(timezone.utc).replace(tzinfo=None)`. 1-line parity test per call site (frozen datetime).

### 5.2 Top 10 perf wins (Phase B/C, high risk)
Ordered by impact / risk ratio:
1. **#2 Delete sync `nse_client.py` (545 LOC)** — pure deletion, low risk IF all callers are migrated to `nse_client_async`. Pre-flight: `grep` for `NSEClient` and `nse_client\.` imports.
2. **#6 Serial NSE → `asyncio.gather + Semaphore`** in `routers/announcements.py:100-190` — 2 URLs fetched sequentially on cache miss. Replace with `asyncio.gather`. 1-line parity test (record call timing).
3. **#10 Pool httpx in more places** (any remaining per-call `httpx.AsyncClient()`) — already established pattern, just apply to more sites.
4. **#1 N+1 query fix** — per-symbol DB loops. Need a query-count parity test (instrument the session to count queries).
5. **#9 Unify TQL transpilers** — `tql_to_sql.py` has 2-3 duplicate transpilers. High LOC win (~400), medium risk. Need contract tests for every (TQL → SQL) pair.
6. **#3 Async wrap warehouse** — `ticker_warehouse` has sync DB calls; wrap with `asyncio.to_thread` or split into sync DB layer + async I/O layer.
7. **#4 Split `backgroundtasks.py` (4989 LOC)** — biggest single file. Split per responsibility (`data_sync/`, `notif/`, `valuation/`, etc.). High risk; do last.
8. **#5 Bulk insert/update** — replace per-row `execute()` with `executemany()` or `INSERT ... ON CONFLICT DO UPDATE`. Performance test (measure throughput on 1000 rows).
9. **#7 `_run_async()`** — find all `asyncio.run()` calls inside async paths and replace with proper await. May not exist in the current code (audit citation may be stale).

### 5.3 Estimated effort
- Phase A remaining: ~2 hours total
- Top 10 #2 (delete sync NSE): ~1 hour (verification + deletion)
- Top 10 #6 (asyncio.gather announcements): ~30 minutes
- Top 10 #9 (unify TQL transpilers): ~1 day (needs contract tests)
- Top 10 #1 (N+1 fix): ~2 days
- Top 10 #4 (split backgroundtasks): ~1 week

---

## 6. Open questions for the user

1. **TTL unification contract** — was the move to canonical 600s for all 3 routers intended? The audit says yes, but the screener.search TTL change (60s → 600s) is a 10× slowdown in cache freshness.
2. **`nse_charting_client` sync `requests`** — should this be converted to `httpx.AsyncClient`? It's used by `charting_router` for live chart data. If yes, the same module-level pool pattern applies.
3. **`_run_async()`** — does this function actually exist? The audit's citation is unclear. `grep -rn "def _run_async" backend/app/` should answer this.
4. **Phase B/C sequencing** — should the next session tackle #2 (delete sync NSE) as a low-risk confidence-builder, or jump to #6 (asyncio.gather announcements) for a quicker win?
5. **Push strategy** — push `docs/backend-audit-and-test-plan` as-is and start Phase B on a new branch, or keep accumulating commits on the audit branch for a single review?

---

## 7. References

- `BACKEND_AUDIT.md` — the audit doc
- `REFACTOR_TEST_PLAN.md` — the 5-tier test strategy
- `tests/conftest.py` — test infrastructure (fixtures, markers)
- `tests/golden/` — Tier 1 snapshot directory
- `tests/test_indicator_parity.py` — model for old-vs-new comparison tests
- `tests/test_tql_to_sql.py` — model for SQL transpiler tests

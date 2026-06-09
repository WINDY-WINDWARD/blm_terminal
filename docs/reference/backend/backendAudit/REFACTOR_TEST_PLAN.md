# Refactor-Parity Test Plan

**Goal:** Lock down every function's observable behavior BEFORE refactoring so that a green test run after each refactor step proves behavioral parity. Each function in the audit gets one or more tests, structured so a new implementation can be substituted in without rewriting the test.

**Conventions discovered in the codebase:**
- `pyproject.toml` declares `asyncio_mode = "auto"`, `testpaths = ["tests"]`, marker `slow`.
- Existing pattern: `tests/test_*.py` is a mix of pytest + standalone scripts; `test_indicator_parity.py` is the model for "old vs new" comparison tests.
- No `conftest.py` exists yet — fixtures are inlined per file.
- `test_indicator_sync_parallel.py` shows the pattern for testing threading topology with in-memory queues + stubbed callables.
- `test_tql_to_sql.py` shows the pattern for SQL transpiler tests: in-memory SQLite fixture with minimal seeded schema, then assert SQL text + bind values + execution results.

---

## 1. Test Plan Architecture (5 tiers)

### Tier 1 — Golden / Snapshot Tests
**Purpose:** Capture exact output of every public function. Diff'd on every test run. Establishes the "baseline" BEFORE any refactor.
**Storage:** `tests/golden/*.json` (per-function).
**Library:** `pytest` + `pytest-snapshot` (or hand-rolled dict comparison).

### Tier 2 — Parity Tests (old vs new)
**Purpose:** Old and new implementations run side-by-side; assert identical output. Bridge for the refactor period; deleted once old impl is gone.
**Pattern:** Inspired by `test_indicator_parity.py`. Parametrized inputs, tolerance field, structural deep-diff.

### Tier 3 — Contract Tests
**Purpose:** Each public function's *contract* (preconditions, postconditions, invariants, edge cases). Runs against current impl AND any future impl.
**Pattern:** Parametrized over input equivalence classes (empty, single, many, NULL, max-int, special chars, etc.).

### Tier 4 — Integration / Pipeline Tests
**Purpose:** End-to-end pipeline stage runs against a seeded in-memory DB; assert final state matches expected.
**Pattern:** In-memory SQLite fixture (see `test_tql_to_sql.py:451-540` for shape).

### Tier 5 — Performance Regression Tests
**Purpose:** Cap execution time so a refactor that quietly O(n²)'s a loop fails CI.
**Mark:** `pytest.mark.perf` (run on a schedule, not every PR).

---

## 2. Test Infrastructure (new)

Add **one** `tests/conftest.py` to remove duplication and enable Tier 1-4:

```python
# tests/conftest.py  (sketch only — not for commit in plan mode)
- fixtures/golden: round-trip JSON compare helper
- fixtures/in_memory_db: in-memory SQLite with full schema + seed
- fixtures/seed_universe: 200-symbol universe (banking/IT/auto mix)
- fixtures/seed_ohlcv: 252 trading days for 10 symbols
- fixtures/seed_intraday: 1h + W + M candles for 5 symbols
- fixtures/seed_news: 50 articles across 10 symbols
- fixtures/stub_nse_client: replaces NSEClient with deterministic canned responses
- fixtures/async_to_thread: helper to run sync functions async for parity tests
- markers: "perf" (new), "parity" (new)
- session-wide monkey-patch of `time.sleep` to no-op during tests
```

Add **`tests/golden/`** directory with:
- `.gitkeep`
- one `.json` per public function under test (see §3 for the inventory)
- schema documented in `tests/golden/README.md`

Add **`pytest-snapshot` to dev deps** in `pyproject.toml`.

---

## 3. Parity Test Inventory (mapped to audit)

Each row is one test (or test class). The audit numbered each finding; here is the parity-test plan for each.

### 3.1 TQL transpilers (audit §4.9, items 8-9) — HIGH RISK refactor

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `tql_parser.parse_tql(tql_str)` | `test_tql_parser_parity.py` | 2 (parity: regex / recursive) | AST shape equivalence, raises same `TQLSyntaxError` on bad input |
| `tql_to_sql._node_to_where` | `test_tql_to_sql_node_parity.py` | 2 (parity: legacy vs snapshot) | SQL string + binds identical for 200 TQL samples (sector/PE/RSI/MACD/interval-prefixed) |
| `tql_to_sql._snapshot_node_to_where` | same file | 2 (parity with above) | Same samples produce semantically equivalent SQL on `ticker_screener_snapshot` table |
| `tql_to_sql._legacy_where` | same file | 2 (parity) | 30 legacy filter dicts (rsi_min, pe_max, above_sma50, …) produce same SQL |
| `tql_to_sql._sort_sql` / `_snapshot_sort_sql` | same file | 2 (parity) | All sort fields + ASC/DESC |
| `tql_to_sql.build_tql_query` / `build_snapshot_tql_query` | `test_tql_to_sql.py` (extend) | 4 (integration) | SQLite execution returns same row set |

**Before refactor:** run the existing `test_tql_to_sql.py:813` suite as-is — already green.
**Refactor method:** unify the two transpilers behind one parameterized function; re-run; new test asserts same output for `td.*` and `snap.*` aliases.

---

### 3.2 Indicator code (audit §4.6, indicators.py) — HIGH RISK

The existing `test_indicator_parity.py:71-117` already covers the series-vs-per-row rewrite. Extend it to cover:

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `_calculate_rsi` (scalar) vs `_series_rsi` (vector) | `test_indicator_parity.py` (extend) | 2 | For n=60..2000, every position's RSI identical to 1e-6 |
| `_calculate_macd` (scalar) vs `_series_macd` (vector) | same | 2 | Same |
| `_series_bollinger` | same | 2 | Per-row band vs whole-series `out[i]` identical |
| `_compute_from_window` (legacy) | same | 2 | Already covered |
| `compute_indicators_for_latest_candle(daily)` | `test_latest_candle_parity.py` (new) | 2 (parity: full-history vs windowed) | Scalar `latest` value matches `series_out[-1]` for 50 symbols × 4 seeds |
| `compute_indicators_for_latest_candle(intraday)` | same | 2 | Same for 1h/W/M intervals |
| `prepare_daily_indicator_updates` vs `prepare_intraday_indicator_updates` | `test_prepare_parity.py` (new) | 2 (parity) | Generated SQL + binds identical when given same OHLCV |
| `flush_daily_indicator_updates` vs `flush_intraday_indicator_updates` | same | 2 | After flush, both tables reflect the same indicator values |
| `get_indicators` vs `get_intraday_indicators` | same | 2 | JSON output shape identical given same source data |

**Refactor method:** parameterize both daily/intraday by `(model, order_col, flush_sql)`. Tests use the SAME parametrize to verify parity.

---

### 3.3 NSE / external clients (audit §4.7) — MEDIUM RISK

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `NSEClient.get_*` (sync) | `test_nse_client_parity.py` (new) | 2 (parity: sync vs async impl) | Async client wrapped in `asyncio.to_thread` returns same dict for all endpoints |
| `NSEClientAsync.get_*` | same | 1 (golden) | JSON of canned NSE responses (3-5 fixtures) — captures today's shape |
| `NSEChartingClient.fetch_candles` | `test_nse_charting_parity.py` (new) | 1 (golden) | Candle list JSON for 10 symbols × 3 intervals |
| `MorningstarClient.get_fair_value` | `test_morningstar_parity.py` (new) | 1 (golden) | Fair value response shape |
| `ScreenerClient.get_company_html` | `test_screener_client_parity.py` (new) | 1 (golden) | Parsed metrics dict (PE, sector, …) |
| Cookie loader | `test_cookie_loader.py` (new) | 4 (integration with rookiepy mock) | Returns `dict[str, str]` for given browser domain |

**Fixture:** `stub_nse_client` (`tests/fixtures/nse_responses/`) — saved real NSE response payloads (redacted) replayed via `httpx.MockTransport` or `aioresponses`.

**Refactor method:** delete sync `nse_client.py`, route through async. The parity test passes if the JSON output is identical. If a behavioral difference is found, decide consciously.

---

### 3.4 Warehouse (audit §4.6, ticker_warehouse.py) — MEDIUM RISK

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `get_ohlcv(symbol, from, to)` | `test_warehouse_parity.py` (new) | 4 (integration) | Returns same list of dicts for 10 symbols, 4 date ranges, 3 intervals |
| `get_latest_candle(symbol)` | same | 4 | Latest row matches `get_ohlcv` last element |
| `bulk_update_via_bhavcopy` | same | 4 | After bulk update, `get_ohlcv` returns identical rows for all symbols in bhavcopy |
| `get_warehouse_status` (god-function) | same | 1 (golden) | Entire 200-line response captured as golden JSON. Refactor splits it; golden stays the contract. |
| `compute_indicators_for_latest_candle` | covered in §3.2 | | |
| `_backfill_symbol_equity_history` | `test_backfill_parity.py` (new) | 2 (parity with cached NSE) | End-state DB rows match historical reference run |

**Refactor method:** split `get_warehouse_status` into `_daily_stats` / `_intraday_stats` / `_days_behind_breakdown`. Tests assert that the composed response equals the golden JSON.

---

### 3.5 Momentum / Returns / Universe rankings (audit §4.6) — HIGH RISK

These are the most aggressive refactors (per-symbol → single window-function SQL).

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `returns_service.get_returns(symbol)` | `test_returns_parity.py` (new) | 2 (parity: per-symbol SQL vs new grouped query) | For 50 symbols, every return period (1d/1w/1m/3m/6m/1y) matches to 1e-4 |
| `returns_service.get_universe_returns()` | same | 2 | Full universe output (per-sector breakdown) identical |
| `returns_service.get_sector_returns()` | same | 2 | Same |
| `returns_service.get_streak_tracking()` | same | 2 | Streak lengths identical (use small fixture, hand-compute expected) |
| `momentum_service.get_momentum_score(symbol)` | `test_momentum_parity.py` (new) | 2 (parity) | Single-symbol score identical to leaderboard-index lookup |
| `momentum_service.get_momentum_leaderboard()` | same | 2 | Full leaderboard identical |
| `momentum_service._percentile_rank` | same | 2 | Sort-once vs sort-every-call produce same rank |

**Fixture strategy:** freeze 200-symbol universe with hand-computed expected returns (or replay from a saved DB). Use `pd.testing.assert_frame_equal` for DataFrame comparison.

---

### 3.6 News pipeline (audit §4.6 + §4.10) — MEDIUM RISK

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `news_fetcher.crawl_and_store` | `test_news_parity.py` (new) | 2 (parity: with/without semaphore sleep fix) | Same articles stored in DB |
| `news_fetcher._fetch_and_parse_article` | same | 1 (golden) | Parsed article dict (10 fixture HTML files) |
| `news_aggregator.fetch_and_process_source` | `test_news_aggregator_parity.py` (new) | 2 (parity: serial vs gather+to_thread) | DB rows identical; timing benchmarked in §3.10 |
| `rss_parser.parse_feed` | `test_rss_parity.py` (new) | 1 (golden) | 20 RSS fixture XML files |
| `nlp_service.analyze_sentiment` | `test_nlp_parity.py` (new) | 1 (golden) | Sentiment + entities for 50 text fixtures |
| `nlp_service.extract_entities` | same | 1 | Same |
| `cookie_loader.load_cookies_for(domain)` | `test_cookie_loader.py` | 1 | Mocked rookiepy returns expected dict |

---

### 3.7 Orchestrator / Background tasks (audit §4.2, §4.3) — HIGH RISK but heavy

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `Orchestrator.run_pipeline(STARTUP)` | `test_orchestrator_parity.py` (new) | 4 (integration with stubbed workers) | All 6 stages executed in order, all gate events set, final job status = "idle" |
| `Orchestrator.run_pipeline(NIGHTLY)` | same | 4 | Same; W/M stages additionally run |
| `Orchestrator._cron_loop` (extracted) | same | 4 | Unit test: cron expression, target fn, job key → fires at correct UTC, idempotent |
| `Orchestrator._run_stage` (extracted) | same | 4 | Unit test: stage name, progress start/end, fn → updates progress correctly |
| `Orchestrator._wait_for_shutdown` | same | 4 | Unit test: returns when event set (verify replaced `while/asyncio.sleep`) |
| `_global_scan_cycle` | `test_scan_parity.py` (new) | 2 (parity: per-symbol loop vs bulk IN-query) | Same alerts produced for fixed 200-symbol fixture |
| `_ticker_indicator_notification_cycle` | same | 2 | Same |
| `_ticker_intraday_indicator_notification_cycle` | same | 2 | Same |
| `_ticker_intraday_hourly_stale_check_sync` | same | 2 | Same |
| `start_all_workers` / `stop_all_workers` | `test_workers_lifecycle.py` (new) | 4 | All 14 workers start; shutdown completes within 5s (no 8-min worst case) |
| `_run_pipeline_stage` | `test_orchestrator_parity.py` | 4 | Acquires pipeline lock, runs fn, sets idle event |

**Refactor method:**
- Before refactor: capture golden state of `_global_scan_cycle` etc. (run on seeded DB, snapshot alert list).
- Refactor: replace per-symbol loop with `WHERE symbol IN (SELECT symbol FROM ticker_scores)`.
- After refactor: same test passes if output is identical.
- Move sync cores to `app/services/data_sync/`. Tests import from the new location but assertions unchanged.

---

### 3.8 Job Runner / Registry (audit §4.4) — LOW RISK

| Function | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `update_job_status` (async) | `test_job_runner_parity.py` (new) | 2 (parity: async vs sync version) | Same DB row written |
| `update_job_status_sync` | same | 1 (golden) | Retry behavior on lock — use `sqlite3.connect` lock-storm fixture |
| `trigger_job` (force=True) | same | 4 | Either kills running job (after refactor) or logs warning (current). Test pinned to the decided contract. |
| `JobRegistry` | `test_job_registry.py` (new) | 3 (contract) | register/get/list_all/get_by_name/is_running/set_running semantics. Add `clear()` for test isolation. |

---

### 3.9 Routers (audit §4.5) — HIGH RISK (request path)

Existing `tests/test_endpoints.py:968` is integration (requires running server). Add **contract tests** for each refactored endpoint:

| Endpoint | Test file | Tier | What's locked |
|----------|-----------|------|--------------|
| `GET /api/ticker/{symbol}/ohlcv` | `test_router_parity.py` (new) | 4 (integration) | Response shape: `await asyncio.to_thread(get_ohlcv)` vs new async get_ohlcv identical |
| `GET /api/ticker/{symbol}/latest` | same | 4 | Same |
| `GET /api/ticker/warehouse/status` | same | 1 (golden) | Captures current 200-line response; refactor preserves shape |
| `GET /api/portfolio` | same | 4 | Per-symbol price-fetch N+1 fix: response identical, timing bounded |
| `GET /api/screener/trades/{symbol}` | same | 4 | Move DB write out of GET; response shape unchanged |
| `GET /api/stockuniverse` | same | 4 | Add pagination: response now `{"items": [...], "total": N, "limit": L, "offset": O}` — assert backward-compat shim or documented break |
| `GET /api/markets/{slug}/stocks` | same | 4 | SQL JSON1 filter produces same symbol set as Python filter |
| `GET /api/news/{company}` | same | 4 | Empty list returned with 200 (not 404) |
| `WS /ws/news` | `test_ws_broadcast_parity.py` (new) | 4 | With N clients, broadcast message received by all within X ms (perf bound) |
| `WS /ws/market` | same | 4 | Per-connection semaphore enforced |

**Refactor method:** wrap sync warehouse calls in `asyncio.to_thread`. Test asserts response shape and timing identical.

---

### 3.10 Performance Regression Tests (Tier 5)

Each refactor that claims an N+1 / memory / parallel fix gets a perf test:

| Area | Test file | Marker | Bound |
|------|-----------|--------|-------|
| `_ticker_scores_sync` memory | `test_perf_scores.py` | `perf` | 2000-symbol seed loads in < 5s, peak RSS < 500 MB |
| `_global_scan_cycle` | `test_perf_scan.py` | `perf` | 200-symbol seed completes in < 10s |
| `parallel_indicator_sync` throughput | `test_perf_parallel.py` | `perf` | 1000 items completes in < 30s on CI |
| NSE client (after sync deletion) | `test_perf_nse.py` | `perf` | 50 sequential calls in < 15s with stubbed network |
| TQL parser+transpiler | `test_perf_tql.py` | `perf` | 1000 TQL strings parse+render in < 2s |
| News crawl semaphore fix | `test_perf_news.py` | `perf` | 100 articles in < 15s (was capped at 3/s) |

CI schedule: nightly via `pytest -m perf`; not on every PR.

---

## 4. Test Plan by Refactor Phase (from audit §6)

### Phase A — Quick Hygiene (1-2 days)
- **Add** `tests/conftest.py` with the new fixtures (§2).
- **Add** `tests/golden/` + Tier 1 golden tests for: `nse_client_async.get_*`, `rss_parser.parse_feed`, `nlp_service.analyze_sentiment`, `nse_charting.fetch_candles`, `morningstar.get_fair_value`, `warehouse.get_warehouse_status`.
- **Add** `test_indicator_parity.py` extensions for all 9 indicators.
- **Verify** the existing 6331 LOC of tests still pass.

### Phase B — Architectural Cleanup (3-5 days)
- **Add** Tier 2 parity tests for TQL transpilers (§3.1) BEFORE unifying.
- **Run** all golden + parity tests. Green = baseline captured.
- **Refactor** TQL transpilers to single parameterized function.
- **Run** all tests. Green = refactor is behavior-preserving.
- **Add** Tier 2 parity tests for sync vs async NSE client (capture both, then delete sync).
- **Add** Tier 4 orchestrator contract tests for `_cron_loop` and `_run_stage` BEFORE extracting them.
- **Add** `test_router_parity.py` for sync-warehouse-call endpoints BEFORE wrapping in `to_thread`.

### Phase C — File Splits + N+1 (1-2 weeks)
- **Add** `test_scan_parity.py` BEFORE refactoring `_global_scan_cycle` etc.
- **Capture** golden scan output on 200-symbol seeded DB.
- **Refactor** per-symbol loops to `WHERE symbol IN (...)`.
- **Run** parity tests. Adjust SQL semantics only if parity is broken — never silently.
- **Add** Tier 5 perf tests for each hot path.
- **Add** `test_orchestrator_parity.py` BEFORE splitting `backgroundtasks.py`.
- **Run** `pytest -m perf` to capture baseline timings.

### Phase D — Engine-level (optional)
- Tier 4 pipeline tests with TickerScreenerSnapshot as primary source.
- Tier 5 perf tests for the new event-loop-based workers.

---

## 5. CI Integration

Add to `.github/workflows/` (or equivalent):

```yaml
- name: Unit + contract + parity tests
  run: pytest -m "not slow and not perf" --maxfail=1

- name: Golden snapshot update
  if: github.event.label == 'update-snapshots'
  run: pytest --snapshot-update

- name: Performance regression (nightly only)
  if: github.event.schedule
  run: pytest -m perf
```

**Pre-refactor checklist for any PR:**
1. Did you add a Tier 2 parity test for the new vs old behavior?
2. Did you update golden snapshots? (If yes, the diff is in the PR for review.)
3. Did you add a Tier 5 perf test if claiming a perf fix?
4. Is the new code reachable from the existing `tests/test_endpoints.py` integration suite?

---

## 6. Test File Layout (proposed)

```
tests/
├── conftest.py                          # NEW: shared fixtures
├── test_indicator_parity.py             # EXTEND: cover all 9 indicators
├── test_indicator_sync_parallel.py      # existing
├── test_tql_to_sql.py                   # EXTEND with more edge cases
├── test_tql_parser_parity.py            # NEW
├── test_tql_to_sql_node_parity.py       # NEW
├── test_nse_client_parity.py            # NEW
├── test_nse_charting_parity.py          # NEW
├── test_morningstar_parity.py           # NEW
├── test_screener_client_parity.py       # NEW
├── test_cookie_loader.py                # NEW
├── test_warehouse_parity.py             # NEW
├── test_backfill_parity.py              # NEW
├── test_returns_parity.py               # NEW
├── test_momentum_parity.py              # NEW
├── test_latest_candle_parity.py         # NEW
├── test_prepare_parity.py               # NEW
├── test_news_parity.py                  # NEW
├── test_news_aggregator_parity.py       # NEW
├── test_rss_parity.py                   # NEW
├── test_nlp_parity.py                   # NEW
├── test_scan_parity.py                  # NEW
├── test_orchestrator_parity.py          # NEW
├── test_workers_lifecycle.py            # NEW
├── test_job_runner_parity.py            # NEW
├── test_job_registry.py                 # NEW
├── test_router_parity.py                # NEW
├── test_ws_broadcast_parity.py          # NEW
├── test_perf_scores.py                  # NEW (perf)
├── test_perf_scan.py                    # NEW (perf)
├── test_perf_parallel.py                # NEW (perf)
├── test_perf_nse.py                     # NEW (perf)
├── test_perf_tql.py                     # NEW (perf)
├── test_perf_news.py                    # NEW (perf)
├── golden/                              # NEW: 30+ JSON files
│   ├── README.md
│   ├── nse_async_*.json
│   ├── rss_*.json
│   ├── nlp_*.json
│   ├── warehouse_status_*.json
│   └── …
├── fixtures/                            # NEW
│   ├── nse_responses/                   # redacted real responses
│   ├── rss_xml/                         # 20 RSS XMLs
│   ├── news_html/                       # 10 article HTMLs
│   └── seed_db.py                       # 200-symbol universe seeder
├── test_endpoints.py                    # existing
├── test_notifications.py                # existing
├── test_cleanup.py                      # existing
├── test_mcp.py                          # existing
└── …                                    # existing
```

---

## 7. Quick-Start: Capture Baseline THIS WEEK (before any refactor)

To get parity coverage fast without designing every test in advance:

1. **Today:** Create `tests/conftest.py` with the 4 core fixtures (golden helper, in-memory DB, seed universe, stub NSE).
2. **Today:** Add `tests/golden/` with JSON snapshots of:
   - `warehouse.get_warehouse_status()` response
   - 5 NSE async client responses
   - 5 TQL query SQL outputs
3. **Tomorrow:** Add Tier 5 perf tests for `_global_scan_cycle`, `_ticker_scores_sync`, `parallel_indicator_sync`, news crawl.
4. **Day 3:** Add Tier 2 parity tests for sync vs async NSE client + indicator scalar vs vector.
5. **Day 4:** Run full suite. This is now the "pre-refactor baseline".

**Result:** ~2,000 LOC of new tests + ~3,000 LOC of fixtures/golden. Every subsequent Phase A/B/C/D change must keep these green.

---

## 8. Open Questions

- `pytest-snapshot` vs `syrupy` vs hand-rolled: codebase has no preference. Recommend `pytest-snapshot` for simplicity.
- Should golden files be committed? **Yes** — that's the whole point. They're the contract.
- Should we run the full existing `test_endpoints.py:968` integration suite (requires running server) in CI? **Yes**, but in a separate job.
- For tests that need to call NSE real endpoints (e.g. cookie loader with rookiepy), should we mock or run live? **Mock** — mark with `slow` if live.
- For `test_orchestrator_parity.py`, do we need to run the full 6-stage pipeline, or is it sufficient to test each stage independently? Recommend **both**: a fast "stage contract" suite + a slow "full pipeline" suite.

---

**End of Plan.**

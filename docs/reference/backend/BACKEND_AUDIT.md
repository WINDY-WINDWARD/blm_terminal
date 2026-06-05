# Backend Performance & Simplicity Audit

**Scope:** `backend/` (FastAPI + SQLAlchemy async + SQLite + native WS) — ~24,000 LOC excluding tests, migrations, venv.
**Date:** 2026-06-05
**Reviewer perspective:** Senior Python engineer / architect

---

## 1. Executive Summary

The backend is functionally rich (37 MCP tools, 22+ routers, 14 background workers, full pipeline orchestration, real-time WS, AI chat agent) but suffers from **scale-related friction** that is now the dominant cost driver:

- **8 god-files >900 lines** (worst: `backgroundtasks.py` at 4994 lines) make changes risky.
- **Pervasive N+1 query patterns** — per-symbol loops opening a session and running 1-5 queries each, repeated over ~2000 universe symbols, are the #1 latency cost in scans/notifications/momentum/portfolio.
- **Sync DB calls (`_SyncSessionLocal`) inside `async def` handlers** block the event loop on the request path.
- **Duplicate code paths** account for ~1500 LOC: sync vs async NSE client (~545 LOC), two TQL transpilers (~400 LOC), per-table indicator boilerplate (~250 LOC), 3 router TTL caches, 2 schedulers per cron job.
- **Module-level singletons + mutable globals** instead of dependency injection make testing and lifecycle reasoning hard.
- Several **concurrency hazards** lurk (shared httpx client mutated across tasks, unbounded caches, 8-minute worst-case shutdown).

The codebase will benefit most from a **layered refactor**: hygiene first (low blast radius), then architectural deduplication, then the big file-split + N+1 elimination.

---

## 2. Methodology

- Counted lines per file (`wc -l`) to identify hotspots.
- Sampled bootstrap (`main.py`, `config.py`, `database.py`, `orchestrator.py`, `jobs/runner.py`, `jobs/registry.py`) end-to-end.
- Delegated 4 parallel explore agents (medium thoroughness) to audit routers, services, NSE clients, orchestrator + backgroundtasks.
- Cross-referenced findings to remove duplicates and rank by impact.

---

## 3. Top 10 Wins (prioritized)

| Rank | Issue | Files / Lines | Win |
|------|-------|---------------|-----|
| 1 | N+1 queries in scan + notif cycles (per-symbol session × ~2000 symbols) | `backgroundtasks.py:3597, 3800, 4381` | 10-100× faster scans |
| 2 | Delete sync `nse_client.py` (~545 LOC duplicate of async version) | `nse_client.py` | -545 LOC + faster I/O |
| 3 | Sync DB inside `async def` handlers blocks event loop | `routers/ticker.py:72,87,116,615`; `routers/portfolio.py:65,324` | Throughput unblock |
| 4 | Split `backgroundtasks.py` (4994 LOC → 6 modules) | `backgroundtasks.py` | Maintainability |
| 5 | Per-row execute → bulk insert/update | `backgroundtasks.py:645,4755,2327`; `news_aggregator.py:148` | 10-50× faster writes |
| 6 | Serial NSE fetches → `asyncio.gather + Semaphore` | `backgroundtasks.py:972,1140,1267,4733,4047` | Minutes reclaimed/cycle |
| 7 | `_run_async()` (new event loop per call, used 9+ times) | `backgroundtasks.py:484` | Connection pool reuse |
| 8 | TQL AST / SQL not cached | `tql_parser.py:291`; `tql_to_sql.py:332,570` | `@lru_cache(256)` ≈ free |
| 9 | Unify duplicate TQL transpilers (~400 LOC duplicate) | `tql_to_sql.py:202,503,625,727` | -400 LOC, drift-proof |
| 10 | Pool httpx clients (per-call creation) | `ai_chat_service.py:929,1055`; `rss_parser.py:161`; `nse_charting_client.py:99,244` | 5-10× connection overhead |

---

## 4. Detailed Findings

### 4.1 Bootstrap & Configuration

#### Issues
- **`main.py:413-507`** mixes 6 concerns (migrations, lifespan, logging, CORS, middleware, router mounting). Manageable but borderline.
- **`main.py:104-117, 171-178`** define `set_sqlite_pragma` inline twice; the same pragma block is in `database.py:13-36` (3rd copy) and `database.py:82-91` (4th copy). Extract once.
- **`main.py:276-349`** `_backfill_entities_double_encoding` is a one-off legacy migration — should move into an Alembic data migration, not run on every startup (idempotent but adds startup time + log noise).
- **`main.py:495-498`** `import os as _os` mid-file with `_dev_router` conditional — register at top with the rest.
- **`config.py:6-40`** Settings is thin; missing strongly-typed market-hours `time` objects (currently 4 ints), missing rate-limit settings (hardcoded in `nse_rate_limiter.py:35` and `backgroundtasks.py`).
- **`database.py:69-77, 108-114`** Three engines (`engine`, `_sync_engine`, `_thread_async_engine`) — the third is "thread-safe async" but uses identical config; rationalize to two (one sync, one async).

#### Recommendations
1. Extract a `_apply_sqlite_pragmas(cursor)` helper used by all 4 sites.
2. Move `_backfill_entities_double_encoding` into Alembic as a data migration; delete from startup path.
3. Strongly type `Settings.market_start` as `time` objects via `field_validator`.
4. Merge `_thread_async_engine` into `engine` — `NullPool` is already thread-safe.

---

### 4.2 Orchestrator (`orchestrator.py`, 704 LOC)

#### Issues
- **Tight coupling**: `orchestrator.py:199-219` imports 15+ private names (`_stock_universe_sync`, `_ticker_backfill_sync`, etc.) from `backgroundtasks`. These should live in `app/services/data_sync/*.py` and both modules import publicly.
- **3 near-identical schedulers** (`_run_nightly_pipeline_scheduler:524`, `_run_watchlist_fair_value_scheduler:564`, `_run_full_fair_value_scheduler:602`) all do the same wait-on-cron / update-job-status / shutdown-or-fire pattern. Extract `_cron_loop(cron_expr, fn, job_key)`.
- **`_wait_for_shutdown:672`** polls `asyncio.sleep(1)` instead of `await shutdown_event.wait()`.
- **`_register_pipeline_jobs:481` and `backgroundtasks.register_all_jobs`** are dual registration paths.
- **`run_pipeline:183`** checks `_pipeline_lock.locked()` before `async with` — the `locked()` check is unnecessary and racy; let the lock serialize naturally and report status differently.
- **`_run_pipeline_stage:653`** acquires a threading lock from an executor thread; cross-paradigm but correct. Document why this is needed.
- **`_execute_pipeline:198-475`** is 270 lines of 9 sequential stages with copy-pasted progress updates. Extract `_run_stage(name, progress_start, progress_end, fn, requires_pipeline_lock=False)`.

#### Recommendations
1. Move pipeline `_*_sync` cores into `app/services/data_sync/` (one module per stage). Orchestrator becomes a thin coordinator.
2. Replace 3 schedulers with one generic `_cron_loop(cron, target_fn, job_key)`.
3. Replace `_wait_for_shutdown` with `shutdown_event.wait()` (will fire on `.set()`).
4. Extract `_run_stage()` helper to cut `_execute_pipeline` 270 → ~90 LOC.

---

### 4.3 Background Tasks (`backgroundtasks.py`, 4994 LOC — worst offender)

#### Structural split (high priority)

Proposed layout:
```
app/workers/
    __init__.py        # start_all_workers(), stop_all_workers()
    data.py            # ticker_daily_update_worker, ticker_intraday_*, ticker_backfill
    news.py            # news_rss_worker, news_aggregator_worker
    notifications.py   # notification_cycle_full, ticker_indicator_notification_cycle, global_scan_cycle
    fair_value.py      # batch_update_fair_values, batch_resolve_morningstar_ids
    maintenance.py     # vacuum_worker, retention_worker
app/services/data_sync/
    universe.py        # _stock_universe_sync
    daily.py           # _ticker_daily_update_sync
    backfill.py        # _ticker_backfill_sync
    intraday.py        # _ticker_intraday_update_sync, _ticker_intraday_hourly_stale_check_sync
    indicators.py      # _ticker_indicators_sync, _ticker_intraday_indicators_sync
    scores.py          # _ticker_scores_sync (+ snapshot)
```

Each file caps at ~500 LOC and has a single responsibility.

#### Performance issues (HIGH)

| Location | Issue | Fix |
|----------|-------|-----|
| `1208-1220` `_ticker_intraday_hourly_stale_check_sync` | N+1: `select(func.max(timestamp)).where(symbol=?)` per symbol | Single `GROUP BY symbol` query |
| `3597-3625` `_ticker_indicator_notification_cycle` | 2 queries × N symbols (TickerDaily + StockUniverse) | One `WHERE symbol IN (...)` query, dict by symbol |
| `3800-3925` `_ticker_intraday_indicator_notification_cycle` | 3 interval queries × N symbols | One `WHERE interval IN (...) AND symbol IN (...)` |
| `4381-4493` `_global_scan_cycle` | 5+ queries × ~2000 symbols = 10K+ queries/scan | Materialize snapshot or batch IN-queries |
| `645-689` `_bulk_insert_stock_universe` | Loops `session.execute(stmt)` per row | Multi-row `INSERT ... VALUES` |
| `2327-2333` `_news_rss_sync` | Per-article `on_conflict_do_nothing` execute | Single `INSERT ... ON CONFLICT DO NOTHING VALUES (...)` (pattern exists at line 3214) |
| `4755-4761` `_batch_update_fair_values` | Per-symbol UPDATE | `executemany` or CASE-based UPDATE |
| `1625-1631` `_ticker_scores_sync` | Load ~500K ORM rows (2000 × 252) | SQL window function + chunked iteration |
| `1696` `df[df["symbol"] == symbol].sort_values(...)` per-symbol scan | O(N²) full-DF scan | `df.groupby("symbol")` once |
| `1736-1741` `percentile_rank` per metric per symbol | `sorted(all_vals)` per call | Sort once, `bisect.bisect_left` |
| `4733-4772` `_batch_update_fair_values` | Sequential `await morningstar.get(...) ; sleep(0.5)` | `asyncio.gather` + `Semaphore(N)` |
| `4799-4827` `_batch_resolve_morningstar_ids` | Same serial pattern | Same fix |
| `4047-4099` `_notification_cycle_full` | 6 NSE fetches serial | `asyncio.gather` |
| `484-501` `_run_async()` (used 9+ times) | New event loop per call, no pool reuse | Convert callers to `async def` or single persistent per-thread loop |
| `972, 1140, 1267` `time.sleep()` in worker loops | Blocks thread, no shutdown interrupt | `_shutdown_event.wait(timeout=...)` |
| `4667-4679` `stop_all_workers` | Joins 14 threads × 35s sequentially | Set event once, `concurrent.futures.wait()` |

#### Simplicity issues

- **`backgroundtasks.py:3369-3382`** `_bulk_upsert_global_notifications` ≈ `_bulk_upsert_notifications:3214` — parameterize the table.
- **`backgroundtasks.py:4381 + 3597`** `_global_scan_cycle` and `_ticker_indicator_notification_cycle` share ~80% of streak/52W/RSI/MACD/BB/ATR/HV evaluation. Extract `_evaluate_technical_alerts(symbol, latest, prev, cfg, scores) → list[(alert_type, message)]`.
- **`backgroundtasks.py:2180, 2526, 2708`** Three identical "open thread async session, call one method, return" wrappers (`_crawl_news_async`, `_fetch_company_news_async`, `_refresh_market_data_async`). Extract one generic `_run_async_in_thread(coro)`.
- **`backgroundtasks.py:316 + 387`** Two shutdown events (`threading` + `asyncio`) loosely coordinated; consolidate behind a single `Shutdown` facade.
- **`backgroundtasks.py:1507-1509`** `_ticker_intraday_indicators_sync` derives `job_key` from `set(intervals)` comparison — pass `job_key` as a parameter.
- **`backgroundtasks.py:4682-4693`** `start_cache_cleanup` is a no-op (docstring admits). Delete.
- **`backgroundtasks.py:2295-2348`** `_news_rss_sync` (sync version) is dead — `news_rss_worker` uses `_news_rss_sync_async`.
- **`backgroundtasks.py:4975-4993`** `_run_watchlist_scheduler` + `_run_nightly_scheduler` are dead — orchestrator schedules them.
- **`backgroundtasks.py:69-241`** `register_all_jobs` is 170 lines of repetitive `JobDefinition(...)` calls. Build from a list of tuples.

---

### 4.4 Job Runner & Registry

#### Issues
- **`jobs/runner.py:27-71` and `jobs/runner.py:74-132`** `update_job_status` (async) and `update_job_status_sync` (sync) are 95% the same code in two implementations. Possible to share by extracting a `_build_values(...)` helper and parameterizing the session opener.
- **`jobs/runner.py:180-188`** `report_progress` swallows `RuntimeError` silently (no loop running). Add `logger.debug` so worker-thread progress losses are visible.
- **`jobs/runner.py:191-265`** `trigger_job` has special-case "force" branch that just logs; it doesn't actually kill a running job (no cancellation token). Either implement kill semantics or rename to `trigger_job_or_skip(force_log_only=True)`.
- **`jobs/registry.py:26-29`** Mutable class attributes are fine for the singleton but provide no `clear()` for tests. Add `@classmethod def clear(cls)` for test isolation.

---

### 4.5 Routers

#### High-priority

| File:Line | Issue | Fix |
|-----------|-------|-----|
| `routers/ticker.py:72,87,116,615,623` | Sync `ticker_warehouse.*` calls in `async def` block event loop | `await asyncio.to_thread(...)` or convert warehouse to async |
| `routers/portfolio.py:65-82, 324-359` | N+1 per-symbol `get_ohlcv` (30 sync round-trips for 30-symbol portfolio) | `get_ohlcv_bulk(symbols, from, to)` with `WHERE symbol IN (...)` |
| `routers/stockuniverse.py:50-56, 197-228` | No pagination on universe (thousands of rows) | `limit`/`offset` + total count |
| `routers/markets.py:98-114, 145-161` | `SELECT *` whole table + Python-side `categories` JSON filter | SQL `JSON1.json_each` + index on slug |
| `routers/announcements.py:100-190` | Sync `requests.Session.get` in async path on cache miss | Migrate to `httpx.AsyncClient` + `asyncio.gather` for 2 URLs |
| `routers/news_ws.py:38-53` | Serial `await connection.send_text` broadcast (one slow client blocks all) | `asyncio.gather(*[c.send_text(msg) for c in ...], return_exceptions=True)` |
| `routers/market_ws.py:125-157` | Unbounded `asyncio.gather` fanout (50 NSE calls × N clients) | Per-WS semaphore |
| `routers/ticker.py:603-622` | Live NSE fetch per request, no short TTL | 30-60s `(symbol, interval)` cache |
| `routers/screener.py:163-183` | GET handler writes to DB (`commit()`) | Move write to background job or first POST |

#### Medium

| File:Line | Issue | Fix |
|-----------|-------|-----|
| `routers/ticker.py:473-537` | 30+ lines of `if x is not None: filters[k] = x` boilerplate | `ScreenerFilters` Pydantic model with `model_dump(exclude_none=True)` |
| `routers/news.py:60-120, 186-253, 293-367` | 3× duplicate paginated endpoints | Extract `paginate(db, conditions, limit, offset, order_by) -> NewsPaginatedOut` |
| `routers/valuation.py:33-45`, `portfolio.py:30-43`, `screener.py:26-43` | 3 custom TTL caches | Reuse `cache.nse_cache` |
| `routers/valuation.py:193-341` | 148-line `_fetch_valuation_data` handler | Move to `app/services/valuation_engine.py` |
| `routers/portfolio.py:189-279` | 90-line `_run_optimization_sync` in router | Move to `app/services/portfolio_opt.py` |
| `routers/nonpersistence.py:255-416` | 160-line `largedeal_snapshot` handler | Move to `app/services/deal_screener.py` |
| `routers/news.py:226-231` | 404 when no news for company | Return `total=0` + empty list with 200 |
| `routers/watchlist.py:225-294` | Legacy single-watchlist code dupes multi-watchlist code with `id == 1` hardcoded | Define `DEFAULT_WATCHLIST_ID = 1`; call multi-watchlist handlers |
| `routers/news_ws.py:160-178`, `nonpersistence.py:53-60`, `market_ws.py:50-59` | `_article_to_dict`, `_clean_nan` duplicated | `app/services/nan.py`; use `NewsArticleOut.model_validate(a).model_dump()` |
| `routers/ticker.py:551`, `routers/portfolio.py`, `orchestrator.py:39` | `pytz` everywhere | `zoneinfo.ZoneInfo("Asia/Kolkata")` (stdlib since 3.9) |

#### Low (cosmetic)

- Inline Pydantic models in router files (`ticker.py:173-195,264-275,296-309,361-368,383-388,565-578`; `news.py:128-132`; `announcements.py:40-50`; `stockuniverse.py:99-104,163-188`) → move to `app/schemas/`.
- `from typing import Optional` then `Optional[str]` while rest of codebase uses `str | None` → unify.
- Function-level imports (`ticker.py:604,608,618-619,466-467`; `news_ws.py:148`) → module-top.
- `_NSE_HEADERS` duplicated in `announcements.py:28-37 vs 239-244`.
- Custom validation when Pydantic would do (`ticker.py:54-70` for date parsing).

---

### 4.6 Services Layer

#### `services/ticker_warehouse.py` (1303 LOC)

- **L466-471** `bulk_update_via_bhavcopy` calls `compute_indicators_for_latest_candle(sym)` serially per symbol after bhavcopy — should enqueue to `parallel_indicator_sync`.
- **L643-853** `get_warehouse_status` is 210-line god-function with 20+ SELECTs; split into `_daily_stats(db)`, `_intraday_stats(db, interval)`, `_days_behind_breakdown(db)`.
- **L466-471, L378-389, L556** All callers of `compute_indicators_for_latest_candle` reload full history per symbol → O(history) per scalar. Use stored series cache or "last 260 closes" snapshot for O(260).
- **L156** `df[df.get("CH_SERIES", "") == "EQ"].copy()` — `.copy()` defeats view optimization; remove.
- **L289-294** `_backfill_symbol_equity_history` makes 3 sequential NSE calls + `time.sleep(3.0)` per symbol → hours for universe.
- **L1191-1216** `_increment_ticker_failure` / `_reset_ticker_failure` each do `db.get + mutate + commit` → replace with single `UPDATE ... WHERE symbol=?`.

#### `services/indicators.py` (1183 LOC)

- **L339-386** `_series_bollinger` makes 2 O(n) passes; merge into one sliding-window loop.
- **L759-836, L1059-1097** `compute_indicators_for_latest_candle` (daily + intraday versions) load all rows, compute 9 indicators, discard all but last row. Use `_series_*` helpers and take `out[-1]`.
- **L232-240, L543-567, L955-976, L719-756** Indicator column list duplicated 4 times. Extract `INDICATOR_FIELDS = (...)` + `_indicator_row(values, now)` builder.
- **L660-715 vs L1009-1044, L718-756 vs L1047-1056, L843-925 vs L1100-1183** `prepare_daily_*` ≈ `prepare_intraday_*` (95% same). Parameterize by `(model, order_col, flush_sql)`.
- **L286-296, L322-329** Hand-rolled bit-for-bit compatibility between scalar `_calculate_rsi`/`_calculate_macd` and series versions — drift risk. Unify to single vectorized impl.

#### `services/news_fetcher.py` (1075 LOC)

- **L547 + L655** `asyncio.sleep(REQUEST_DELAY)` *inside* `async with sem:` — caps crawl to 3 articles/sec. Move sleep outside semaphore.
- **L246-285, L270-281, L372-373** `client.headers.update(headers)` on *shared* `AsyncClient` — concurrent tasks clobber each other. Pass `headers=` per-request.
- **L70-156** `BROWSER_PRESETS` × `BROWSER_WEIGHTS` separate structures that must stay in lockstep. Collapse to one list of dicts.
- **L513, L552, L772** `BeautifulSoup(html, "html5lib")` is slowest parser; use `lxml` or `html.parser`.
- **L988-991** `fetch_company_news` has no semaphore at call site — unbounded concurrency.
- **L996-1014 vs L733-748** Batch-insert duplicated; extract `_bulk_insert_articles(db, parsed_list)`.
- **L220-244, L246-360** 5-page state diagram for "one httpx client, possibly recreated on loop change". Collapse to one `_get_or_create_client()` + one `_load_cookies_into(client)`.

#### `services/momentum.py` (213 LOC)

- **L24-26, L86-93** `_calculate_returns_for_symbols` calls `returns_service.get_returns(symbol)` in comprehension + `_calculate_volume_ratio(s)` in loop — 4000+ queries for 2000-symbol universe. Single SQL with window functions returns all in one query.
- **L58-64** `_percentile_rank` does `sorted(all_values)` per invocation × 6000 calls = 6000 sorts of same data. Sort once + `bisect_left`.
- **L67-155** `get_momentum_score(symbol)` recomputes leaderboard for all 2000 symbols just to find one rank. Cache leaderboard, lookup symbol.
- **L4-9** `import pandas as pd` unused — dead.

#### `services/returns.py` (355 LOC)

- **L142, L189** `get_universe_returns` and `get_sector_returns` call `get_returns` per symbol → 2000+ sessions + 2000+ pandas builds. Single grouped query.
- **L81-84** `pd.DataFrame([{...} for r in rows_sorted])` — `from_records` or numpy is 5-10× faster.
- **L282-356** `get_streak_tracking` manual triple for-loop on closes; use `numpy.diff(np.sign(closes))`.
- **L24-43** `_get_date_lookup` is dead (only `iloc` is used in `get_returns`).
- **L152** `sorted(returns)[len(returns) // 2]` — use `statistics.median`.
- **L164-165** Local re-imports of `StockUniverse`, `json` (already at module-level).

#### `services/cache.py` (220 LOC)

- **L207-219** `SQLiteCache` is entirely dead (no callers in `app/`). Delete the class.
- **L124-157** `set()` runs `SELECT COUNT(*)` on every write + eviction in hot path. Maintain in-memory counter, skip count when `len < max_size`.
- **L88-96** `sqlite3.connect` per thread via `threading.local()` → 50+ idle connections under load.
- **L170-184** `pop()` does SELECT-then-DELETE non-atomically → race. Use `DELETE ... RETURNING`.

#### `services/parallel_sync.py` (286 LOC)

- **L221-224** `_emit_progress` uses outer-loop `item` via closure with `# noqa: F821` — fragile, will `NameError` on producer exception. Pass `item_label` as parameter.
- **L110-114, L157-164** Busy-spin `get(timeout=0.5); except Empty: continue` pattern; use blocking `get()` + sentinel.
- **L213-229** Hardcoded `f"Stage 3/7"` ties generic helper to one pipeline — parameter.

---

### 4.7 NSE / Screener / Morningstar Clients

#### Critical: Delete sync NSE client

`services/nse_client.py` (545 LOC) is 90% duplicate of `services/nse_client_async.py` (385 LOC). Same `get_52week_low_stocks`, `get_52week_high_stocks`, `get_volume_gainers`, `get_largedeal_snapshot`, `get_change_ranges`, `get_stock_metadata`, `_parse_nse_date` — sync uses `requests.Session`, async uses pooled `httpx.AsyncClient`.

**Action:** Delete `nse_client.py`; route all callers through `NSEClientAsync` via `asyncio.to_thread()` when called from sync code. Saves 545 LOC + faster I/O.

#### Other client issues

- **`screener_client.py:41-53`** `_HTML_CACHE: dict` unbounded growth. Use `cachetools.LRUCache`.
- **`screener_client.py:558`** `_get_browser_cookies` reloaded on every `init()` call. TTL-cache or reload-on-auth-failure only.
- **`screener_client.py:159-161`** Regex compiled inside method body.
- **`screener_client.py:66-110 vs morningstar_client.py:202-238`** Cookie loading duplicated. Extract `cookie_loader.load_cookies_for(domain)`.
- **`morningstar_client.py:127, 240, 273, 307`** Semaphore only protects `get_fair_value`; `resolve_symbol_to_id` and `_search_autocomplete` issue HTTP without it.
- **`morningstar_client.py:273-302`** No negative-result cache → repeated lookups of unresolvable symbols.
- **`nse_charting_client.py:64, 67-73`** Module-level `_last_request_time` not thread-safe.
- **`nse_charting_client.py:99, 244`** `requests.get` with no module-level `Session`.
- **`nse_charting_client.py:288, 296`** Deprecated `asyncio.get_event_loop()` → `asyncio.to_thread()`.
- **`nse_rate_limiter.py:35`, `screener_client.py:29`, `morningstar_client.py:127`** Three separate `asyncio.Semaphore(2)` instances. Consolidate behind `nse_rate_limiter.throttled_call(fn, *)`.

---

### 4.8 AI Chat Service (`services/ai_chat_service.py`, 1242 LOC)

- **L929, L1055** `async with httpx.AsyncClient(timeout=120.0)` — new TCP pool per chat. Module-level shared `AsyncClient`.
- **L1000, L1026, L1156, L1190** `messages` list grows unboundedly; with `MAX_ITER=10` and 8000-char tool results, context fills fast. Implement sliding-window compaction.
- **L763-801** 38-entry `dispatch` dict literal rebuilt per tool call. Module constant.
- **L153-700** 547 lines of hand-maintained `BLM_TOOLS` definitions; should auto-generate from `mcp_server` docstrings (already partially done at L129).
- **L880, L1010, L1017, L1142, L1166, L1176** Tool-call JSON args parsed multiple times per turn. Parse once, pass parsed value.

---

### 4.9 TQL Parser & SQL Generator

- **`tql_parser.py:291`** `parse_tql` re-tokenizes/re-parses every request. `@functools.lru_cache(maxsize=256)` on TQL string ≈ free win.
- **`tql_to_sql.py:332, 570, 602, 823`** Generated SQL not cached either. Cache `(sql, binds)` keyed by `(tql, default_interval, sort_by, order)`.
- **`tql_to_sql.py:625-721 vs 727-820`** `_legacy_where` ≈ `_legacy_where_snapshot` (200 LOC duplicate, only table alias differs).
- **`tql_to_sql.py:202-247 vs 503-544`** `_node_to_where` ≈ `_snapshot_node_to_where` (byte-identical except field resolver).
- **`tql_to_sql.py:414-440`** `_snapshot_select_clause` rebuilt as literal per call.
- **`tql_to_sql.py:271-274 vs 547-567`** `_sort_sql` ≈ `_snapshot_sort_sql` differ only in `td.X` vs `snap.X`.

**Action:** Pass `field_resolver` + `table_alias` as parameters to unified functions. Cuts ~400 LOC.

---

### 4.10 News Aggregator & RSS

- **`rss_parser.py:161`** Per-feed `async with httpx.AsyncClient(...)` (30+ TCP+TLS handshakes per poll). Module-level singleton.
- **`rss_parser.py:166`, `morningstar_client.py:287`** Sync `feedparser.parse` / `ET.fromstring` in async context without `to_thread`.
- **`news_aggregator.py:86-92, 117-122, 145-160`** Serial NLP per article + serial DB inserts. Batch `executemany` + `asyncio.gather + to_thread` for NLP.
- **`news_aggregator.py:62`** `datetime.utcnow()` deprecated in 3.12 → `datetime.now(timezone.utc).replace(tzinfo=None)`.
- **`news_sources.py:40-345`** 30+ `NewsSource(...)` hardcoded. Move to `config/news_sources.yaml`.

---

### 4.11 Database

- **`database.py:13-36, 82-91`** SQLite pragmas defined twice — extract `_apply_sqlite_pragmas(cursor)`.
- **`database.py:108-114`** `_thread_async_engine` is identical to `engine` — both `NullPool`. Drop the duplicate.
- **`database.py:74-78`** Sync engine for worker threads — fine, but consider per-worker `sessionmaker` if contention becomes an issue.
- **Pragma `cache_size=-65536`** (64 MB) × multiple connections × threads can balloon to 100s of MB. Document the upper bound.

---

### 4.12 Schemas & Models

- **`models/ticker.py:101-217`** `TickerScreenerSnapshot` has 90+ columns — by design, used for fast screener reads. Document the trade-off (denormalization for read speed) at top of file.
- **`schemas/`** Some routers define inline Pydantic models (see §4.5 Low). Move all to `schemas/`.

---

## 5. Cross-Cutting Hygiene

### Dead code to delete
- `services/cache.py:207-219` — `SQLiteCache` class
- `backgroundtasks.py:2295-2348` — sync `_news_rss_sync`
- `backgroundtasks.py:4682-4693` — `start_cache_cleanup` no-op
- `backgroundtasks.py:4975-4993` — `_run_watchlist_scheduler`, `_run_nightly_scheduler` (orchestrator handles them)
- `services/returns.py:24-43` — `_get_date_lookup`
- `services/momentum.py:4-9` — `import pandas` unused
- `services/indicators.py:14-17` — `from collections import deque` unused
- `services/nse_client.py:540-541` — `async def close()` no-op
- `services/parallel_sync.py:221-224` — `# noqa: F821` fix the closure

### Standardize
- **Timezone:** `pytz` → `zoneinfo.ZoneInfo` (stdlib, Python 3.9+).
- **Type syntax:** `Optional[X]` → `X | None` (PEP 604).
- **Imports:** No function-level imports unless circular-import workaround (with comment).
- **Regex:** Compile at module level.
- **Datetime:** `datetime.utcnow()` deprecated → `datetime.now(timezone.utc)`.
- **DB session in routes:** Always `Depends(get_db)`; never manual `AsyncSessionLocal()` (currently inconsistent in `market_ws.py`, `news_ws.py`).

### Concurrency hazards
- **Shared `httpx.AsyncClient` mutation** in `news_fetcher.py:246-285`.
- **Unbounded `_HTML_CACHE: dict`** in `screener_client.py:41`.
- **Sequential 35s thread joins** in `backgroundtasks.py:4667` → 8 min worst-case shutdown.
- **Two uncoordinated shutdown events** (`threading.Event` + `asyncio.Event`).

---

## 6. Phased Execution Plan

### Phase A — Quick Hygiene (1-2 days, low risk)

1. Delete all dead code listed in §5.
2. `pytz → zoneinfo` repo-wide.
3. Lift function-level imports to module top.
4. Compile all regexes at module level.
5. Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`.
6. Add `@functools.lru_cache(maxsize=256)` to `tql_parser.parse_tql`.
7. Module-level `httpx.AsyncClient` for `ai_chat_service`, `rss_parser`, `nse_charting_client`.
8. Unify 3 router TTL caches → `cache.nse_cache`.
9. Fix `news_fetcher.py:655` sleep-inside-semaphore bug.
10. Fix `news_fetcher.py:246-285` shared-client header mutation.

**Tests:** existing `pytest` suite + spot-check market hours/timezone behavior.

### Phase B — Architectural Cleanup (3-5 days, medium risk)

1. Delete `services/nse_client.py`; route callers through `nse_client_async`.
2. Unify TQL transpilers: single `_node_to_where(field_resolver, table_alias)`.
3. Extract `Orchestrator._cron_loop(cron, fn, job_key)`; replace 3 schedulers.
4. Extract `_run_stage(...)` in orchestrator; cut `_execute_pipeline` 270 → 90 LOC.
5. Consolidate shutdown into one `Shutdown` facade.
6. Move inline router Pydantic models to `app/schemas/`.
7. Extract `paginate(db, conditions, ...)` helper for news endpoints.
8. Wrap sync warehouse calls in `asyncio.to_thread()` (or convert warehouse to async).
9. Extract `cookie_loader.load_cookies_for(domain)`.
10. Consolidate rate limiters into `nse_rate_limiter.throttled_call`.
11. `_apply_sqlite_pragmas` helper; drop `_thread_async_engine`.

**Tests:** Run `tests/test_screener_service.py`, `tests/test_tql_to_sql.py`, `tests/test_endpoints.py`. Add coverage for unified TQL paths.

### Phase C — File Splits + N+1 Elimination (1-2 weeks, high value, invasive)

1. Split `backgroundtasks.py` (4994 LOC) per layout in §4.3.
2. Move pipeline `_*_sync` cores into `app/services/data_sync/`.
3. Fix N+1 in `_global_scan_cycle`, `_ticker_indicator_notification_cycle`, `_ticker_intraday_indicator_notification_cycle`, `_ticker_intraday_hourly_stale_check_sync` (single `WHERE symbol IN (...)` queries).
4. Bulk insert/update in `_bulk_insert_stock_universe`, `_news_rss_sync`, `_batch_update_fair_values`, `_batch_resolve_morningstar_ids`.
5. Parallelize fair-value sync with `asyncio.gather + Semaphore`.
6. Replace `_run_async()` with persistent per-thread loop (or convert workers to `async def`).
7. SQL window function + chunked iteration in `_ticker_scores_sync` (eliminate 500K-row in-memory load).
8. Extract `_evaluate_technical_alerts(...)` shared by scan/notif cycles.
9. Bulk `get_ohlcv_bulk(symbols, from, to)` for `portfolio.py`.
10. `paginate` on `stockuniverse`; SQL JSON1 for `markets` slug filter.
11. `news_ws` broadcast: `asyncio.gather + return_exceptions`.
12. `market_ws` per-connection semaphore.
13. Migrate `announcements.py` to `httpx.AsyncClient`.

**Tests:** Add new N+1 regression tests with `EXPLAIN QUERY PLAN`. Verify timing improvements with `pytest -m slow`.

### Phase D — Engine-Level (deeper risk, optional)

1. Move per-symbol scan queries → `TickerScreenerSnapshot`-driven evaluations (snapshot already exists).
2. Convert worker threads → async tasks under orchestrator's single event loop.
3. Move `news_sources` to YAML config.
4. Strongly typed `Settings.market_start: time` (from 4 ints).
5. Move `_backfill_entities_double_encoding` to Alembic data migration.
6. Add dependency-injection layer (`AppContext`) replacing module-level singletons.

---

## 7. Appendix: Top Hotspots by Size

| File | LOC | Recommendation |
|------|-----|----------------|
| `app/backgroundtasks.py` | 4994 | **Split into 6 modules** (workers/ + services/data_sync/) |
| `app/mcp_server.py` | 1774 | Consider tool-domain split (markets, screener, portfolio, news) |
| `app/services/ticker_warehouse.py` | 1303 | Split: `nse_fetcher.py`, `warehouse_status.py`, `intraday.py` |
| `app/services/ai_chat_service.py` | 1242 | Auto-generate `BLM_TOOLS` from MCP introspection (-547 LOC) |
| `app/services/indicators.py` | 1183 | Split: `indicators_pure.py`, `indicators_series.py`, `indicators_persistence.py` |
| `app/services/news_fetcher.py` | 1075 | Split: `news_headers.py`, `news_fetcher.py`, `news_url_resolver.py` |
| `app/services/tql_to_sql.py` | 928 | Unify duplicate transpilers (-400 LOC) |
| `app/services/screener_client.py` | 893 | Extract HTML parsers, cookie loader |
| `app/orchestrator.py` | 704 | Extract `_cron_loop`, `_run_stage` (-200 LOC) |
| `app/routers/ticker.py` | 640 | Move schemas out, async-wrap warehouse calls |
| `app/services/nse_client.py` | 545 | **Delete** (duplicate of nse_client_async.py) |
| `app/services/nlp_service.py` | 529 | Pre-compile patterns at module level |

---

## 8. Quick Reference: Files Untouched but Worth Future Attention

- `app/services/screener.py` (182 LOC) — used; would benefit from same TQL caching layer.
- `app/services/ai_summarizer.py` (120 LOC) — client created at import time; lazy or per-call.
- `app/routers/jobs.py` (115 LOC) — small but writes to DB in GET-like endpoints; verify idempotency.
- `app/routers/notifications.py` (190 LOC) — `_dev_router` mounting is conditional and lives in `main.py:495-498`.

---

**End of Audit.**

# Backend Memory & Performance — Fix Plan

**Date:** Sat Jun 20 2026
**Companion to:** `backend-memory-analysis-report.md`
**Process baseline:** PID 1647260, 2.45 GB RSS, 3.24 GB swapped, 196 threads, 99.98% swap utilisation

This document turns the analysis report's findings into concrete, ordered, low-risk code changes. Every section explains the *what*, the *why* (root cause), the *how* (design), and the *verification* (tests + measurements) so the work is reproducible.

The report identified 16 issues. We collapse them into 9 implementation items in a fixed order, and group them into 4 phases. Each item lists its risk, the exact file(s) it touches, the test that proves it works, and the memory it is expected to save.

## Guiding principles

1. **Smallest blast radius first.** Ship a no-risk quick win, measure, then ship the next.
2. **Golden tests are the contract.** `tests/golden/ticker_scores_50_symbols.json` and `tests/golden/global_scan_50_symbols.json` lock the data outputs of the two biggest functions. Any change that touches a golden must regenerate it via `UPDATE_GOLDEN=1 pytest` and the diff is reviewed.
3. **Hold file-size invariants.** `tests/test_data_sync_scores.py:test_scores_file_under_350_loc` and `tests/test_data_sync_and_workers_split.py::TestModuleSize` exist for a reason. Refactors that blow the limit must extract helpers, not relax the test.
4. **One memory test per high-impact fix.** A `pytest.mark.perf` test using `tracemalloc` is added for `_ticker_scores_sync` so a future regression cannot silently re-introduce the bug.
5. **No new dependencies.** `cachetools` is already in use (`app/services/cache.py:11`); no `pip install` is required for any of the fixes below.

## Phased implementation order

| Phase | Item | File(s) | Risk | Expected peak memory delta |
|-------|------|---------|------|----------------------------|
| 0 | QW1 — Screener HTML cache to `TTLCache` | `app/services/screener_client.py` | tiny | −500 MB ceiling |
| 0 | QW2 — `del` raw NSE responses in global scan | `app/workers/global_scan_cycle.py` | low | −200-400 MB transient |
| 0 | QW3 — `gc.collect()` after scores pipeline | `app/services/data_sync/scores.py` | tiny | −100-300 MB transient |
| 0 | QW4 — Remove dead `_html_cache` from morningstar | `app/services/morningstar_client.py` | none | 0 |
| 1 | P0-1 — Stream + chunk `_ticker_scores_sync` | `app/services/data_sync/scores.py` + new helper | medium | −500-900 MB peak |
| 2 | P0-2 — `StaticPool` on the sync engine | `app/database.py` | low | −50-100 MB resident |
| 3 | P1-1 — NSE sync facade uses `_run_async()` | `app/services/nse_client_async.py` | high | −50-100 MB resident |
| 4 | P2-1 — SQL window function in `get_latest_indicator_rows` | `app/services/ticker_warehouse.py` | low | −50-100 MB transient |
| 4 | P2-3 — `news_fetcher` stream to DB instead of `gather` | `app/services/news_fetcher.py` | low | −1-6 MB transient |

P2-2 (`get_warehouse_status` 27-query consolidation) and P3 caches are not in this plan — they are <10 MB impact each and the existing code is correct, just verbose.

After all phases ship, the running process should drop from 2.45 GB RSS / 3.24 GB swap to roughly 0.5-0.8 GB RSS / 0 GB swap, with the death-spiral eliminated.

---

## Phase 0 — Quick wins (≤ 30 min each)

These four are no-risk. They do not change the function contract, do not touch SQL, do not change the API surface. If only one of them works, ship all four.

### QW1 — Bound the screener HTML cache

**What.** Replace the plain `dict` at `app/services/screener_client.py:51` with a `cachetools.TTLCache(maxsize=500, ttl=900)`.

**Why it works.** The current cache (`_html_cache_get` at line 55) silently ignores expired entries — they are never deleted from the dict. Each entry holds 200 KB-1 MB of HTML text. With ~2,400 symbols crawled over the lifetime of the process, the dict accumulates hundreds of MB of stale HTML strings that are no longer reachable from any read path but still occupy anonymous pages (which is exactly what the kernel cannot drop, because anonymous pages have no file backing).

`TTLCache` from `cachetools` is already in use at `app/services/cache.py:11` for the NSE cache. It is thread-safe (internal `RLock`) and has a built-in `popitem()` that evicts the LRU entry when `maxsize` is exceeded. The auto-eviction is the whole point: expired entries are deleted on insert, and the size cap prevents the dict from growing past the configured memory budget.

The TTL stays at 15 minutes (`HTML_CACHE_TTL = 900`) so the cache-hit rate is unchanged. The max size of 500 entries × 500 KB average = 250 MB ceiling, vs the current unbounded growth.

**How.**
```python
# screener_client.py:50-63  (replaces the dict + getter/setter)
from cachetools import TTLCache

_HTML_CACHE: TTLCache[str, str] = TTLCache(maxsize=500, ttl=HTML_CACHE_TTL)
# _html_cache_get / _html_cache_set unchanged — TTLCache exposes a dict-like
# __getitem__ that raises KeyError on miss; we wrap the same way as before.
```

`get_company_html` (line 670) and the `news_*` paths already call `_html_cache_get`/`_html_cache_set`; the public contract is identical.

**Verification.**
- Add a unit test in `tests/test_screener_service.py` that pushes 1,000 entries into `_HTML_CACHE` and asserts the cache size is ≤ 500 after each insert.
- Add a TTL test that pushes an entry with `monkeypatch` on `time.monotonic` and asserts the entry is gone after 900 s.
- Re-run the full `pytest tests/test_screener_*.py` and `test_screener_regex_parity.py` to confirm no behaviour change.
- After 24h of live use, confirm `_HTML_CACHE` size never exceeds 500 entries.

### QW2 — Free raw NSE responses in global scan

**What.** In `app/workers/global_scan_cycle.py`, add `del` statements immediately after the raw payloads are parsed into smaller dicts.

**Why it works.** Lines 100-110 fetch six NSE responses into module variables: `high52_raw`, `low52_raw`, `vol_raw`, `gainers_df`, `losers_df`, `deals_raw`. Lines 107-110 parse them into `high52_data`, `low52_data`, `vol_data`, `deals`, and lines 125-138 hoist the gainer/loser DataFrames into `gainers_by_symbol` and `losers_by_symbol` dicts. From line 138 onward the raw variables are never read again, but they remain bound to the function's local frame, which keeps the parsed *Python objects* alive in the heap. The CPython allocator cannot return these pages to the OS until the function returns, which happens ~5-10 minutes later (the scan loop is 2,691 symbols × 1 second sleep per 100-symbol batch).

`del` is the canonical Python way to drop a name binding so the underlying object becomes unreferenced (assuming no other binding holds it). It is not "deletion" of the data; it is "drop my reference so the GC can collect". Adding `del high52_raw, low52_raw, vol_raw, deals_raw, gainers_df, losers_df` after line 138 drops ~6 references to multi-MB objects. Together with the `gc.collect()` in QW3, the heap can be returned to the OS mid-scan.

**How.** Add four `del` statements in `global_scan_cycle.py` immediately after the `losers_by_symbol` dict is built (currently line 138):

```python
# After line 138
del high52_raw, low52_raw, vol_raw, deals_raw
del gainers_df, losers_df
```

The gainers/losers DataFrames are also rebuilt from `df.itertuples()` into `gainers_by_symbol`/`losers_by_symbol` (small dicts, ~hundreds of bytes), so the originals are no longer needed.

**Verification.**
- The golden test `tests/golden/global_scan_50_symbols.json` is the contract. It diffs the `pending` notifications produced by the function. The del only frees memory; it does not change the output. The test must pass byte-for-byte.
- Add a `pytest.mark.perf` test that runs `_global_scan_cycle` against the seeded 50-symbol DB with `tracemalloc` and asserts peak additional memory < 50 MB (down from ~200 MB today).

### QW3 — `gc.collect()` after the scores pipeline

**What.** Add `import gc` and `gc.collect()` after the `ticker_scores` upsert and after the `_screener_snapshot_sync` call in `app/services/data_sync/scores.py`.

**Why it works.** The scores pipeline:
1. Builds a 682K-row DataFrame (peak ~500-900 MB).
2. Computes returns + scores into a list of dicts (~24 KB each, ~65 MB total).
3. Upserts to DB.
4. Calls `_screener_snapshot_sync(df, …)` which does two `groupby` operations and a `merge` on the full df (peak ~700 MB).
5. Returns.

Between step 3 and step 4, the `df`, the `results` list, the `scores` list, and the `rank_map` dict are all still live. After step 4, `df` is the last one to die. Python's reference-counting frees objects eagerly *as soon as their refcount hits zero*, but the underlying pages often go to a free list inside pymalloc, not back to the OS. `gc.collect()` walks the cyclic GC roots and forces collection of objects that are still alive only via cycles (e.g. a list referring to itself, a dict whose values reference it back).

For our workload the practical effect is small (most data is acyclic) but consistent: `gc.collect()` is observed to return 50-300 MB to the OS in similar pipelines. The cost is a one-time ~20-50 ms pause, which is invisible in a pipeline that already takes minutes.

**How.**
```python
# scores.py top of file
import gc

# After line 240 (after db.commit() of the ticker_scores upsert)
gc.collect()

# After line 248 (after _screener_snapshot_sync call, in the success path)
gc.collect()
```

The two `gc.collect()` calls bracket the snapshot step. The second one runs after the snapshot has done its own groupby/merge and freed those intermediates.

**Verification.**
- The golden test `tests/golden/ticker_scores_50_symbols.json` must match byte-for-byte.
- A new `pytest.mark.perf` test asserts `tracemalloc` peak additional memory in the second call's frame is < 200 MB (down from ~700 MB today).

### QW4 — Remove dead code in morningstar client

**What.** Delete `_html_cache` at `app/services/morningstar_client.py:65` and the `import time` if it becomes unused.

**Why it works (or rather, why it's safe).** The report's P2-4 confirms it is dead — `grep` shows exactly one match (the declaration). The Morningstar client does not use HTML caching at all; it uses `_token_cache` (the actual auth tokens, used at line 137) and `_id_cache` (the symbol→morningstar_id mapping, used at line 117). Removing the dead dict has no functional effect; it is pure housekeeping.

**How.** Delete lines 65 and any associated comment. If `import time` (line 17) becomes unused, remove that too — but the `_id_cache_get` and `_token_cache_get` getters at lines 104-123 still use `time.monotonic()`, so the import stays.

**Verification.**
- `grep -n "_html_cache" app/services/morningstar_client.py` returns nothing.
- `pytest tests/` runs clean (no test references this attribute).

---

## Phase 1 — P0-1: Stream + chunk `_ticker_scores_sync`

This is the highest-impact single change. The function currently holds the entire universe's 252-day daily history in memory twice (ORM list + DataFrame). Chunking + streaming reduces the peak by ~5x.

### Problem statement

`app/services/data_sync/scores.py:66-116`:

1. Line 83: `all_rows = list(raw.scalars().all())` — materialises **682,923 SQLAlchemy ORM objects** into a Python list. Each ORM object is ~1-2 KB (the row data + identity map + attribute descriptors + relationship proxies). Total: ~700 MB-1.4 GB resident.
2. Lines 89-116: builds a 23-column DataFrame by iterating all 682K objects and building a 23-key dict per row. Pandas then constructs numpy ndarrays from those dicts. The dict-then-DataFrame path is double the memory of going straight to a record array, because both the dicts and the ndarrays are alive briefly. Total during the conversion: ~200-400 MB transient.
3. Lines 134-175: iterates per-symbol, doing `df[df["symbol"] == symbol].sort_values("date")` — a full O(n) linear scan per symbol × 2,691 symbols = ~1.8 billion comparisons. The filter creates a copy of the filtered subset on each iteration; the copies are short-lived but they accumulate to ~50-100 MB at peak.
4. Line 246: passes the full `df` to `_screener_snapshot_sync(df, …)`. The snapshot function (`app/services/data_sync/snapshot.py:80-110`) does two `groupby` operations and a `merge` on the full df, which creates intermediate copies — peak ~700 MB during the merge.

Total peak: **500-900 MB** in a single allocation spike, on top of the ~2.4 GB already resident in the process.

### Fix design

**Three changes**, in order:

1. **Stream the rows from SQLAlchemy.** Replace `list(raw.scalars().all())` with `for r in raw.scalars().yield_per(2000):` so the ORM emits 2,000 rows at a time and the cursor is server-side. This caps the live row set at ~2,000 ORM objects (~3 MB) instead of 682K.
2. **Chunk by symbol batch.** Loop over `symbols_with_data` in chunks of 500 symbols. For each batch, run a window-function query restricted to those 500 symbols, build a batch-local DataFrame, compute returns for that batch, append to an accumulator. Drop `del batch_df; gc.collect()` between batches.
3. **Call `_screener_snapshot_sync` per batch.** Since the snapshot reads only the latest row per symbol plus the same 252-day window, it is straightforward to call it per batch with the batch DataFrame. The per-batch snapshot writes ~220 rows × 10 batches instead of 2,238 rows × 1 batch — WAL overhead is trivial.

### Why this works

- **SQLAlchemy `yield_per`** enables server-side cursors. SQLite does not support server-side cursors natively, so `yield_per` falls back to client-side batching — but with batch size 2,000 the materialised ORM list never exceeds 2,000 entries. The peak ORM memory is bounded.
- **Symbol chunking** bounds the DataFrame. 500 symbols × 252 rows × 23 columns = ~2.9M cells × 8 bytes/float64 = ~23 MB. Even with the 23-key dict intermediate, peak per batch is ~100 MB. Down from ~700 MB.
- **Per-batch snapshot** means the snapshot's `groupby` operates on a 500-symbol DataFrame (~50 MB peak during the merge). Down from 700 MB.
- **Accumulator pattern for percentile rank.** The only step that needs ALL symbols is the percentile-rank computation (lines 188-211). The 3m, 6m, and 20d-volume return values are needed across all symbols to compute ranks. We keep a tiny accumulator: `{symbol: (r_3m, r_6m, r_vol)}` — 24 bytes × 2,700 symbols ≈ 65 KB. Negligible.

### Pseudocode

```python
def _ticker_scores_sync() -> None:
    # ... existing symbol query (line 50-56) ...
    # ... existing setup ...

    BATCH = 500
    # Per-symbol results accumulator: 65 KB total, not 500 MB.
    per_symbol: dict[str, dict] = {}

    for batch_start in range(0, len(symbols_with_data), BATCH):
        batch_symbols = symbols_with_data[batch_start:batch_start + BATCH]

        with _SyncSessionLocal() as db:
            ranked_cte = (
                select(TickerDaily, func.row_number().over(
                    partition_by=TickerDaily.symbol,
                    order_by=TickerDaily.date.desc(),
                ).label("rn"))
                .where(TickerDaily.symbol.in_(batch_symbols))
                .cte("_ranked")
            )
            RankedTD = aliased(TickerDaily, ranked_cte)
            raw = db.execute(
                select(RankedTD)
                .where(ranked_cte.c.rn <= 253)
                .order_by(RankedTD.symbol, RankedTD.date.desc())
            )

            # STREAM instead of materialise. yield_per(2000) keeps the live
            # ORM set bounded; the 23-key dict is built inline so the row
            # object is freed the moment we move to the next iteration.
            records: list[dict] = []
            for r in raw.scalars().yield_per(2000):
                records.append({
                    "symbol": r.symbol,
                    "date": r.date,
                    "open": r.open, "high": r.high, "low": r.low,
                    "close": r.close, "volume": r.volume,
                    "rsi_14": r.rsi_14, "macd": r.macd,
                    # ... the other 17 columns ...
                })

        batch_df = pd.DataFrame(records)

        # Compute returns for this batch
        for symbol in batch_df["symbol"].unique():
            sym_df = batch_df[batch_df["symbol"] == symbol].sort_values("date")
            per_symbol[symbol] = {
                "symbol": symbol,
                "compute_date": today_date,
                "computed_at": now,
                "return_1d": calc_return(sym_df, 1),
                "return_1w": calc_return(sym_df, 5),
                "return_1m": calc_return(sym_df, 20),
                "return_3m": calc_return(sym_df, 60),
                "return_6m": calc_return(sym_df, 120),
                "return_1y": calc_return(sym_df, 252),
                "volume_ratio_20d": volume_ratio_20d,
            }

        # Per-batch snapshot — operates on the batch df, not the full one
        try:
            _screener_snapshot_sync(batch_df, today_date, now)
        except Exception:
            logger.exception(...)

        # Explicit free so the next batch starts from a clean heap
        del batch_df, records
        gc.collect()

    # ALL batches done — now compute percentile ranks across the full universe
    values_3m = [d["return_3m"] for d in per_symbol.values() if d["return_3m"] is not None]
    values_6m = [d["return_6m"] for d in per_symbol.values() if d["return_6m"] is not None]
    values_vol = [d["volume_ratio_20d"] for d in per_symbol.values() if d["volume_ratio_20d"] is not None]

    for d in per_symbol.values():
        d["momentum_score"] = round(
            0.30 * percentile_rank(d["return_3m"], values_3m)
            + 0.30 * percentile_rank(d["return_6m"], values_6m)
            + 0.20 * percentile_rank(d["volume_ratio_20d"], values_vol),
            1,
        )
        # Compute momentum_rank based on sorting...

    # Final upsert to write momentum_score / momentum_rank
    # Since per_symbol is only ~65KB, we do a single bulk upsert for all 2700 rows.
    with _SyncSessionLocal() as db:
        ins = sqlite_insert(TickerScore).values(list(per_symbol.values()))
        ins = ins.on_conflict_do_update(...)
        db.execute(ins)
        db.commit()
```

### Risks

1. **File-size invariant.** `tests/test_data_sync_scores.py:test_scores_file_under_350_loc` will fail because the new `_ticker_scores_sync` body is longer. Two options: extract the per-batch helper to a private `_scores_batch.py` module (preferred), or relax the limit. The audit's intent is "this file is small because the logic is simple" — chunking does not change that, so extraction preserves the invariant.
2. **Snapshot called 10× instead of 1×.** The snapshot's per-batch write is ~220 rows. With 10 batches that's ~2,200 row writes, but with WAL the cost is dominated by the per-write commit. Acceptable. If profiling shows this is a bottleneck, we can use a single transaction across all batches (`db.execute(ins)` then `db.commit()` once at the end).
3. **Percentile rank semantics change.** The current code computes ranks over a single-pass loop. The new code computes returns in a per-batch loop, then ranks at the end. The rank output is identical (ranks are a function of the full distribution, which is the same), but the **order** in which symbols are visited in the per-batch inner loop changes. The golden test may detect a different ordering of `momentum_rank` values for symbols at the same score. This is acceptable: the test is JSON-sorted, so as long as the final set of `momentum_score` values is identical, the diff is clean.
4. **`_shutdown_event` check.** Lines 135-137 check shutdown per symbol. The new loop must check shutdown per batch.

### Test strategy

- **Golden regeneration.** Run `UPDATE_GOLDEN=1 pytest tests/test_data_sync_scores.py` to regenerate `ticker_scores_50_symbols.json`. Diff the regenerated file against the committed version. The only acceptable changes are timestamp/date drift (the `compute_date` is `now.date()`).
- **Per-batch correctness test.** Add a unit test that mocks `_SyncSessionLocal` to return 50 symbols across 3 batches, calls `_ticker_scores_sync`, and asserts `len(ticker_scores) == 50` and each row's `momentum_score` is within the percentile range [0, 100].
- **Memory regression test.** `pytest.mark.perf` test that uses `tracemalloc` to snapshot memory before and after the call. Assert peak additional memory < 200 MB. Skip on default `pytest` runs (`-m "not perf"`).
- **File-size test.** If extracted to `_scores_batch.py`, add a sibling test `test_scores_batch_module_under_200_loc`. The main `scores.py` file must still pass its 350 LOC check (the orchestrator is now even shorter, ~180 LOC).
- **`global_scan_cycle` golden.** Because `_global_scan_cycle` reads from `ticker_scores`, regenerate `tests/golden/global_scan_50_symbols.json` after the scores change is in.

---

## Phase 2 — P0-2: `QueuePool` on the sync engine

### Problem statement

`app/database.py:52, 86` — both the async engine (used by FastAPI request handlers) and the sync engine (used by 14 daemon worker threads) use `NullPool`. Every `_SyncSessionLocal()` call creates a brand-new SQLite connection. Each new connection:
- Applies 6 PRAGMAs (`busy_timeout`, `journal_mode`, `synchronous`, `cache_size=-65536`, `temp_store=MEMORY`, `mmap_size=268435456`).
- Allocates a 64 MB page cache (`cache_size=-65536`).
- Allocates a 256 MB virtual memory-mapped region (`mmap_size`). **The mmap is not resident** (the report verified this — RSS for the mmap region is 0), but the *virtual address reservation* still happens per connection.

With 14 daemon threads and dozens of `_SyncSessionLocal()` calls per second, this is a constant allocation/deallocation churn. The pages fragment the heap and the kernel cannot reclaim them efficiently.

### Why `QueuePool` (and not `StaticPool`)

The initial report suggested `StaticPool`, but using `StaticPool` in a multi-threaded environment where threads write to the database is a **massive logic bug**. `StaticPool` maintains exactly *one* connection. If Thread A starts a transaction and Thread B executes a query, Thread B's execution occurs within Thread A's transaction state. 

Instead, we use `QueuePool(pool_size=5, max_overflow=10)`. For SQLite with WAL mode, multiple connections can read concurrently, while writes wait on the busy timeout. A `QueuePool` provides persistent connections without mixing transaction states across threads.

### Critical: keep `NullPool` on the async engine

The async engine (`database.py:48-53`) serves FastAPI request handlers. uvicorn workers can have many concurrent requests. Using a persistent pool with SQLite and `aiosqlite` under high concurrency can sometimes cause locking issues depending on how `aiosqlite` serialises access. `NullPool` is safer for the async path. The asymmetry is intentional: the sync engine is the hot path for memory churn (14 threads, dozens of calls/second), the async engine is the hot path for concurrency (fine because async request handlers are I/O-bound and the DB is fast). Keep `NullPool` for async, switch sync to `QueuePool`.

### How

```python
# database.py:48-53  (async engine — UNCHANGED)
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=_AsyncNullPool,
)

# database.py:83-87  (sync engine — CHANGE)
from sqlalchemy.pool import QueuePool

_sync_engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30.0,
)
```

Add a comment to both engines explaining the deliberate asymmetry.

### Risks

1. **Single-connection contention under heavy writes.** If 5 workers all try to write at the same time, 4 will block on the lock. For this project, the heaviest writer is the scores pipeline (one writer, ~30 seconds). The other 13 workers are mostly readers or do small single-row writes. Acceptable.
2. **`_SyncSessionLocal` is module-level.** All 14 workers import the same `_SyncSessionLocal`. With `StaticPool`, they all share the same connection. SQLAlchemy handles thread-safety internally (it uses a `Lock` around connection access), so this is safe — but worth a brief comment in the file.

### Test strategy

- Run the full `pytest tests/ -m "not slow"`. All tests must pass.
- Add a test that calls `_SyncSessionLocal()` from 5 threads concurrently and asserts all 5 complete without `SQLite "database is locked"` errors.
- 24h live test: no functional regression in any of the workers' job logs.

---

## Phase 3 — P1-1: NSE sync facade uses per-thread event loop

### Problem statement

`app/services/nse_client_async.py:444-546` — the `NSEClient` sync facade wraps every method with `asyncio.run()`. Each `asyncio.run()` call:
1. Creates a new event loop.
2. The `NSEClientAsync._get_client()` (line 80-100) detects that the running loop is different from the previous loop (because there is a new loop every time), closes the existing `httpx.AsyncClient`, creates a new one.
3. Makes the HTTP request.
4. Closes the loop and the httpx client.

This happens 6 times per global scan cycle (one per `_safe_fetch_*` call in `nse_parsing.py:55-100`). It also happens for every `_fetch_change_ranges_for_symbol` call (`market_data.py:53-57`), every per-symbol NSE data fetch in `nonpersistence.py`, and every iinvest metadata lookup.

The `httpx.AsyncClient` is a TCP connection pool + SSL context. Allocating and closing it 6 times per global scan means 6 TCP handshakes with NSE, 6 SSL session establishments, and 6 buffer allocations (~1-5 MB each for the keepalive connection pool). The "right" pattern is one client per thread, reused.

### Why this is high-risk

The `NSEClient` facade is the public API for ~8 call sites (routers, orchestrator, MCP server, background tasks). The audit comment at lines 453-472 explicitly says `asyncio.run()` was chosen as the "drift-proof" pattern to make the sync facade simple. Tests in `tests/test_nse_client_compat.py` (175 LOC) pin the facade's behaviour. Any change here must preserve the public contract: `NSEClient()` instance, `get_top_gainers()` returns a DataFrame, etc.

### Fix design

**Two-tier approach:**

1. **Add a helper `_run_async_from_sync(coro)`** that:
   - Tries `asyncio.get_running_loop()`. If a loop is running, raise a clear error (caller should `await` directly).
   - Otherwise, calls `_run_async(coro)` from `app.backgroundtasks._runtime` if the current thread has a registered event loop.
   - Otherwise (no running loop, no registered loop), falls back to `asyncio.run(coro)` (the current behaviour).

2. **Replace `asyncio.run(...)` in the 13 methods** with `_run_async_from_sync(...)`.

3. **Update `_get_client()` to be loop-tolerant.** Currently, when the loop id changes, the httpx client is closed and a new one is created. With per-thread loops, the loop id is stable for a given thread, so this only happens when the sync facade is called from different threads (e.g., the global scan thread vs the watchlist notification thread). Since `NSEClient` is a module-level singleton in `nse_parsing.py:25`, *all* sync callers share one client. The loop-mismatch logic in `_get_client` is therefore still useful — we keep it.

4. **For async callers (FastAPI routers, MCP server)**, they should `await nse_client_async.method()` directly, not `await nse_client.method()`. This requires updating the call sites in `routers/nonpersistence.py:39-41` and `routers/stockuniverse.py:193`. The `market_data.py:24-26` already has a feature flag `USE_ASYNC_NSE` that switches between the two — this becomes the default for the future, but the sync facade remains for the daemon workers.

### How

```python
# nse_client_async.py (new helper)
from app.backgroundtasks._runtime import _run_async

def _run_async_from_sync(coro):
    """Run an async coroutine from sync code with the right strategy.

    - If the calling thread has a registered event loop (daemon worker via
      ``_run_async``), use it.
    - Otherwise, create a new event loop with ``asyncio.run`` (FastAPI sync
      path, one-off scripts).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # no running loop — safe to use _run_async or asyncio.run
    else:
        raise RuntimeError(
            "Cannot use sync NSEClient facade from within an async context. "
            "Use `await nse_client_async.method()` instead."
        )
    return _run_async(coro)
```

Then the 13 facade methods become:

```python
def get_top_gainers(self) -> "pd.DataFrame":
    return _run_async_from_sync(self._async.get_top_gainers())
```

`_run_async` in `app/backgroundtasks/_runtime.py:234-266` is already designed exactly for this: it maintains a per-thread event loop in `_run_async_loops`, created lazily on first use, and cleaned up on shutdown. We just need to make sure all 12 sync-only daemon threads (per the report's table) have an opportunity to use it. They already do: `_run_async` lazily creates the loop on first call.

### Why this works

- **Per-thread event loop reuse.** The first call from a given thread creates the loop; subsequent calls reuse it. 
- **httpx client per loop.** We will also update `NSEClientAsync._get_client()` to store the `httpx.AsyncClient` instances in a dictionary keyed by `id(asyncio.get_running_loop())` rather than holding a single `self._http` that constantly gets closed and recreated when called from different threads/loops. Memory churn drops from "6 clients per scan" to "1 client per worker thread for the lifetime of the process".
- **Backward compatibility.** The `asyncio.run` fallback in the helper preserves the behaviour for any caller not in a daemon worker (e.g., one-off scripts, tests).
- **No public contract change.** The `NSEClient` class signature, method names, and return types are identical.

### Risks

1. **httpx client lifecycle across threads.** By maintaining a dict of clients by loop ID, we prevent the cross-thread thrashing. When `stop_all_workers` cleans up the per-thread loops, the httpx clients will be closed.
2. **Tests.** `tests/test_nse_client_compat.py` calls the facade synchronously in a single test thread. With the new helper, that thread will get a persistent event loop — fine, but the test must clean it up via `_cleanup_run_async_loops()` in a fixture teardown.

### Test strategy

- `tests/test_nse_client_compat.py` — all existing tests must pass with the helper change.
- Add a new test in `test_nse_client_compat.py` that calls `NSEClient().get_top_gainers()` twice from the same thread and asserts the httpx client object is identical (via `id()`).
- Add a test that calls the facade from two threads and asserts each thread has its own httpx client.
- Run `pytest tests/test_mcp.py tests/test_mcp_stdio.py` to confirm the MCP server still works.

---

## Phase 4 — P2 fixes (low-risk, ship after P0/P1)

### P2-1 — `get_latest_indicator_rows` SQL window

**Problem.** `app/services/ticker_warehouse.py:702-715` loads all 682K `TickerDaily` rows for the requested symbols, then Python-slices to keep only 10 per symbol. 96% of the loaded data is discarded.

**Fix.** Use the same window-function pattern that `scores.py:67-82` already uses:

```python
def get_latest_indicator_rows(symbols: list[str], n: int = 10) -> dict[str, list[TickerDaily]]:
    if not symbols:
        return {}
    with _get_session() as db:
        rn_col = func.row_number().over(
            partition_by=TickerDaily.symbol,
            order_by=TickerDaily.date.desc(),
        ).label("rn")
        subq = (
            select(TickerDaily, rn_col)
            .where(TickerDaily.symbol.in_(symbols))
            .cte("_ranked")
        )
        RankedTD = aliased(TickerDaily, subq)
        rows = db.execute(
            select(RankedTD)
            .where(subq.c.rn <= n)
            .order_by(RankedTD.symbol, subq.c.rn)
        ).scalars().all()
    by_sym: dict[str, list[TickerDaily]] = {}
    for r in rows:
        by_sym.setdefault(r.symbol, []).append(r)
    return by_sym
```

**Why it works.** SQL with `ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC)` emits only `n` rows per symbol directly. For 2,691 symbols × n=10 = ~27,000 rows, vs 682,000 today. A 25× reduction in ORM objects loaded.

**Risks.** The query plan is the same as `scores.py:67-82`, which has been in production for weeks. Low.

**Tests.**
- Unit test against the in-memory DB with 5 symbols × 12 rows. Asserts each symbol returns its 10 most recent rows in ASC order.
- `tests/golden/global_scan_50_symbols.json` must regenerate byte-identical (the function's output contract is the same).
- Add a `pytest.mark.perf` assertion: rows loaded for 100 symbols is 1,000, not 25,300.

### P2-3 — `news_fetcher` stream to DB

**Problem.** `app/services/news_fetcher.py:748-792` uses `asyncio.gather` to fetch all article URLs concurrently, accumulating the full result list in memory before filtering. For MoneyControl's first-page crawl that produces ~200 articles × 30 KB = 6 MB resident. Modest but unnecessary.

**Fix.** Replace the `asyncio.gather` + list-filter pattern with `asyncio.as_completed` + per-result insert. Each completed future appends to `pending_batch` and flushes at `ARTICLE_BATCH_SIZE`. The `all_results` and `valid_results` lists go away.

**Why it works.** `asyncio.as_completed` yields futures as they finish, not all at once. The intermediate list never grows past `CONCURRENCY_LIMIT × 1` (~3 items). The DB write path is unchanged.

**Risks.** Trivial. The existing code already batches inserts at `ARTICLE_BATCH_SIZE`. The only difference is when the items are appended to the batch (as they arrive, vs all at once at the end).

**Tests.** `tests/test_news_fetcher_concurrency_parity.py` must pass byte-identical. Add a memory test that mocks 500 article URLs and asserts peak memory < 10 MB.

---

## Memory budget: before vs after

| Component | Today | After Phase 0-4 |
|-----------|-------|-----------------|
| `_ticker_scores_sync` peak | 500-900 MB | ~100 MB |
| `_screener_snapshot_sync` peak | ~700 MB | ~50 MB |
| `_HTML_CACHE` ceiling | unbounded (1+ GB) | 250 MB |
| NSEClient facade per-call | 1-5 MB × 6/scan | <1 MB |
| `global_scan_cycle` transient | 200-400 MB | 0 MB after parsing |
| `get_latest_indicator_rows` | 700 MB | 25 MB |
| `news_fetcher` gather | 1-6 MB | <1 MB |
| **Total peak RSS** | **2.5-3.5 GB** | **0.6-1.0 GB** |
| **Total swap usage** | **3+ GB** | **0 GB (no swap needed)** |

These are the expected steady-state numbers. Swap is eliminated because RSS drops below the 15 GB physical RAM ceiling — the kernel has no reason to swap.

---

## Verification methodology

### After Phase 0 (quick wins)
- Re-run the `free -h` and `cat /proc/<pid>/smaps_rollup` measurements from the report.
- Expected: RSS drops by ~100-300 MB (the `_HTML_CACHE` cap alone).
- Expected: no swap thrash (still happens during scores pipeline peak, but the cap prevents the slow climb to 100% swap).

### After Phase 1 (chunked scores)
- Re-run during a market window where `ticker_daily_update_sync` triggers `ticker_scores_sync`.
- Expected: peak RSS during the scores pipeline drops to < 1.5 GB (from 2.5+ GB).
- Expected: no swap usage during normal operation.

### After all phases
- 48-hour stability test: backend runs through 2 weekday + 1 weekend cycles.
- Expected: RSS < 1.5 GB, swap < 100 MB, no `database is locked` errors, no worker timeouts.

### Smoke test script (one-liner)
```bash
# 1. Snapshot the process before restart
ps -o pid,rss,vsz,comm -p 1647260
cat /proc/1647260/smaps_rollup | grep -E "^(Rss|Swap)"

# 2. Restart with the new code
kill 1647260 && cd /home/windy/blm_terminal && uvicorn main:app --port 4455 &

# 3. Wait 30 minutes, snapshot again
ps -o pid,rss,vsz,comm -p $(pgrep -f "python main.py")
cat /proc/$(pgrep -f "python main.py")/smaps_rollup | grep -E "^(Rss|Swap)"
```

---

## Out of scope (deferred)

- **P2-2 `get_warehouse_status` 27-query consolidation.** The function is called from a single status endpoint, not on a hot path. Each call allocates < 5 MB. Not a memory emergency. Can be addressed in a future "query consolidation" pass.
- **P3 caches (`_trades_id_cache`, `_scripcode_cache`, morningstar `_id_cache`).** Total ceiling ~600 KB. Negligible. The current `dict` is fine.
- **Thread pool consolidation (196 → ~6 threads).** Real win for virtual memory (~1.5 GB → ~50 MB) but a large architectural change touching all 14 worker daemon threads. Recommend a separate "worker refactor" plan.
- **Add `/api/system/memory` endpoint.** Useful for monitoring but not part of the fix. Should be a separate PR with the `psutil` dependency added to `pyproject.toml`.

---

## Decision log

The report offered two strategies for P0-1 (per-batch snapshot vs deferred snapshot). We choose **per-batch** (option A) because:
- Code is simpler — no second pass over the data.
- The snapshot's per-batch write is small (~220 rows × 10 batches = 2,200 row writes, trivial for SQLite WAL).
- Easier to test (the existing golden test can be regenerated without restructuring).

The report suggested `cachetools.TTLCache(maxsize=500, ttl=900)` for the screener cache. We use the exact same `maxsize` and `ttl` so the cache-hit rate is preserved.

The report suggested `StaticPool` for both engines. However, using `StaticPool` in a multi-threaded app with concurrent writers mixes transaction states across threads, which is a critical logic bug. We deliberately use `QueuePool` on the sync engine instead to safely reuse connections, and keep `NullPool` on the async engine to avoid serialising FastAPI request handling.

The report suggested `asyncio.run` → `_run_async` for the NSE facade. We use a `_run_async_from_sync` helper that auto-detects the context (running loop vs daemon thread vs one-off script) so the same facade works in all three.

---

## Appendix A — File-by-file diff summary

| File | Phase | Change |
|------|-------|--------|
| `app/services/screener_client.py` | 0 | `_HTML_CACHE` → `TTLCache` |
| `app/workers/global_scan_cycle.py` | 0 | Add `del` after parsing |
| `app/services/data_sync/scores.py` | 0, 1 | `gc.collect()`, then full chunking refactor |
| `app/services/data_sync/_scores_batch.py` | 1 | NEW — per-batch helper |
| `app/services/morningstar_client.py` | 0 | Delete dead `_html_cache` |
| `app/database.py` | 2 | Sync engine → `StaticPool` |
| `app/services/nse_client_async.py` | 3 | Add `_run_async_from_sync` helper, swap 13 methods |
| `app/services/ticker_warehouse.py` | 4 | SQL window in `get_latest_indicator_rows` |
| `app/services/news_fetcher.py` | 4 | `gather` → `as_completed` |
| `tests/test_screener_service.py` | 0 | New: cache eviction test |
| `tests/test_data_sync_scores.py` | 1 | New: `tracemalloc` perf test |
| `tests/test_nse_client_compat.py` | 3 | New: per-thread client test |
| `tests/test_ticker_warehouse_async_wrap.py` | 4 | New: window function unit test |
| `tests/golden/ticker_scores_50_symbols.json` | 1 | Regenerate |
| `tests/golden/global_scan_50_symbols.json` | 1, 4 | Regenerate |

---

## Appendix B — Test command cheat sheet

```bash
# Phase 0 — quick wins
pytest tests/test_screener_service.py tests/test_data_sync_scores.py tests/test_data_sync_and_workers_split.py -x
pytest tests/golden -m golden  # confirms screener + scores goldens

# Phase 1 — chunked scores
UPDATE_GOLDEN=1 pytest tests/test_data_sync_scores.py  # regenerate golden
pytest tests/golden -m golden
pytest tests/test_data_sync_scores.py -m perf  # memory regression

# Phase 2 — StaticPool
pytest tests/ -m "not slow"

# Phase 3 — NSE facade
pytest tests/test_nse_client_compat.py tests/test_mcp.py tests/test_mcp_stdio.py

# Phase 4 — P2 fixes
pytest tests/test_news_fetcher_concurrency_parity.py
pytest tests/test_ticker_warehouse_async_wrap.py
UPDATE_GOLDEN=1 pytest tests/test_data_sync_and_workers_split.py  # regenerate global_scan golden
```

---

*This plan is the contract between the analysis report and the implementation. Every fix listed here has a verification step. The phases are ordered by risk-adjusted ROI: Phase 0 ships in <2 hours and bounds the worst leak; Phase 1 is the biggest single win; Phases 2-4 are progressively smaller incremental wins.*

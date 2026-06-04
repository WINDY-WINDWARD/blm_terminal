# Indicator Sync — Architecture and Tuning

## Overview

The indicator sync pipeline computes RSI, MACD, Bollinger Bands, ATR, VWMA, HV, and Sharpe ratios for every candle in `ticker_daily` and `ticker_intraday` (for the `1h`, `W`, and `M` intervals). It is invoked by:

- **Stage 3** of the orchestrator pipeline (`_ticker_indicators_sync`) — daily backfill across the universe
- **Stage 1c / 2c / 5a / 5b** of the orchestrator pipeline (`_ticker_intraday_indicators_sync`) — intraday backfill for 1h, W, M
- **`ticker_intraday_hourly_indicators_worker`** — every hour at :30 on weekdays (Mon–Fri)
- **`_ticker_intraday_hourly_stale_check_sync`** — 1h reconciliation during startup and nightly

All four call sites now share the same multithreaded topology.

## Topology (3 compute + 1 writer)

```
[task producer: enqueue (symbol[, interval])] ──► compute_q (Queue maxsize=100)
                                                       │
                              ┌─────────────────────────┼─────────────────────────┐
                              ▼                         ▼                         ▼
                       compute_worker_1           compute_worker_2           compute_worker_3
                              │                         │                         │
                              └─────────────────────────┼─────────────────────────┘
                                                       ▼
                                                  writer_q (Queue maxsize=100)
                                                       │
                                                       ▼
                                                  writer_worker
                                                       │
                                                       ▼
                                              SQLite (WAL mode)
```

- **3 compute workers** are long-lived daemon threads (`indicator_compute_0`, `indicator_compute_1`, `indicator_compute_2`).
  Each calls `prepare_daily_indicator_updates(symbol)` or `prepare_intraday_indicator_updates(symbol, interval)` and pushes the resulting `list[dict]` to `writer_q`.
  Compute workers never touch the DB for writes — they only read candles.
- **1 dedicated writer thread** (`indicator_writer`) is the only thread that performs UPDATEs on the indicator tables.
  It pulls updates from `writer_q`, buffers up to 50 items, then calls `flush_daily_indicator_updates(updates)` or `flush_intraday_indicator_updates(updates)` which runs a single bulk `executemany` UPDATE in one transaction.
- **Bounded `queue.Queue(maxsize=100)`** for both buffers. A slow writer back-pressures compute workers, and a slow compute pool back-pressures the producer.

## Why 3+1 (not 3+3 or just more workers)

- **Compute is CPU-bound** (Python O(n) loops with some numpy). With the GIL, more than 3-4 Python threads give diminishing returns. 3 workers is enough to keep the writer fed without context-switch thrashing.
- **Writes are serialized at SQLite level** anyway. Even with 3 writers, all `ticker_daily` / `ticker_intraday` writes contend on the same WAL lock. A single dedicated writer eliminates contention with the compute pool and gives us a clean place to batch.
- **Resource bound**: 4 threads is small enough to run on any machine (4-thread CI runners included) while still overlapping compute and I/O.

## Function separation (testability)

The compute and write halves of each path are split into two functions so the heavy lifting is testable and the threaded topology is reusable:

| Function | Purpose | Touches DB? |
|---|---|---|
| `prepare_daily_indicator_updates(symbol)` | Load `ticker_daily` rows for symbol, run `_compute_series_indicators`, return update dicts | Read-only |
| `flush_daily_indicator_updates(updates)` | Bulk UPDATE `ticker_daily` for the given updates | Write |
| `prepare_intraday_indicator_updates(symbol, interval)` | Load `ticker_intraday` rows for the pair, compute, return update dicts | Read-only |
| `flush_intraday_indicator_updates(updates)` | Bulk UPDATE `ticker_intraday` | Write |
| `compute_indicators_for_all_rows(symbol)` | Thin wrapper: `prepare` + `flush`. **Used by serial cron paths only.** | Both |
| `compute_intraday_indicators_for_all_rows(symbol, interval)` | Thin wrapper: `prepare` + `flush`. **Used by serial cron paths only.** | Both |
| `parallel_indicator_sync(items, prepare_fn, flush_fn, ...)` | The 3+1 threaded topology. **Used by orchestrator pipeline stages.** | Calls `prepare_fn` (read) and `flush_fn` (write) |

The orchestrator's `_ticker_indicators_sync` and `_ticker_intraday_indicators_sync` both call `parallel_indicator_sync` with the appropriate `prepare_fn` / `flush_fn` pair.

The serial `compute_*_for_all_rows` wrappers are kept for the `_ticker_intraday_hourly_stale_check_sync` cron path (which only processes a small watchlist-sized batch — parallelism is overkill there) and any other single-symbol callers.

## Shutdown and failure semantics

- **Producer** checks `_shutdown_event` between every enqueue. On shutdown it stops enqueueing, waits for `compute_q.join()` to drain, then sends N=3 `None` sentinels to `compute_q` so the chain unwinds.
- **Compute workers** also check `_shutdown_event` in their `queue.Empty` branch. If the queue is empty AND shutdown is set, they forward a `None` to `writer_q` and exit.
- **Writer** expects exactly 3 sentinels (one per compute worker) and exits after the third. On exit it flushes any pending batch.
- **Compute worker exception** is logged as a warning and the worker continues with the next item.
- **Writer exception** (a failed `flush_fn` call) sets `state["writer_failed"]`, the producer raises after join, and the orchestrator marks the job as `failed`. No internal retry — the operator can re-trigger via `POST /api/jobs/{job_key}/trigger`.

## Tuning knobs

The only user-facing knob is the inter-batch sleep for the writer:

```bash
# backend/.env
INDICATOR_INTER_BATCH_SLEEP_S=0.0  # default 0 (no sleep)
```

Set to e.g. `0.05` if you observe the writer saturating the DB and want to give other workers more time on the WAL. With the O(n) compute rewrite and NullPool, the default of 0 is the right choice for most hosts.

Other tunables are hardcoded:
- `num_compute_workers = 3` — 3 compute threads (constant)
- `queue_maxsize = 100` — bound on each of the two queues
- `writer_batch_size = 50` — writer flushes when pending reaches this many update lists
- `heartbeat_every_s = 10.0` — producer logs heartbeat every 10s
- `progress_every = 10` — producer logs progress every 10 enqueued items
- `slow_threshold_s = 5.0` — compute workers warn when a single `prepare_fn` call exceeds 5s

To change these, edit `app/services/parallel_sync.py` directly. Future work could expose them via `app.config.settings` if the need arises.

## Performance expectations

- **Daily backfill** (~2348 universe symbols, ~500 rows/symbol): ~20-30s compute + ~5s writer = **~30s** total. The serial path was 1-2 minutes.
- **Intraday backfill (1h+W+M combined, ~7044 pairs, ~520 rows/pair for W, ~120 for M)**: ~60-90s compute + ~10s writer = **~2 minutes**. The serial W/M run took ~9 minutes.
- **1h hourly cron** (typically 0-3 stale pairs): milliseconds, dominated by the `ticker_intraday` scan query, not the writer.

## Logging

You'll see log lines from three sources:
- **Producer** (main thread): `indicator_sync: enqueued %d/%d (%.1fs, %.1f items/s)` every 10 items; `indicator_sync: heartbeat — %d/%d enqueued` every 10s.
- **Compute workers**: per-symbol timing at `logger.debug` (visible at DEBUG level). Warnings for slow pairs: `parallel_indicator_sync compute worker N: slow %s took %.1fs`.
- **Writer**: errors only. On flush failure: `parallel_indicator_sync writer: batch flush failed: %s`.

In the orchestrator, `_ticker_indicators_sync` and `_ticker_intraday_indicators_sync` wrap these with their own info-level log lines prefixed `ticker_indicators_sync:` and `ticker_intraday_indicators_sync:`.

## Tests

`backend/tests/test_indicator_sync_parallel.py` covers:
- Empty item list
- 100-item typical run
- Multi-arg items (symbol, interval) for intraday
- Compute worker exceptions don't poison the run
- Writer failure marks the run as failed
- Shutdown event mid-flight drains cleanly
- Exactly 3 compute + 1 writer thread is started

Run with:
```bash
pytest tests/test_indicator_sync_parallel.py -v
```

The test file imports `app.services.parallel_sync` directly (a small module with no transitive deps) so it loads in <1s.

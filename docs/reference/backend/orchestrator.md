# Background Task Orchestrator

## Overview

A central **Orchestrator** coordinates all background data pipelines in the BLM Analytics backend. It enforces a strict execution order for startup and nightly synchronization while leaving independent workers (news, market data, fair value, hourly intraday) to self-manage their own schedules.

Two pipeline modes exist:

- **STARTUP** — runs once when the server boots, priming the data warehouse from cold.
- **NIGHTLY** — runs every day at 23:00 IST, refreshing the warehouse after market close.

Both pipelines follow the same ordered stages, with the nightly run additionally downloading the official NSE bhavcopy before backfilling gaps and syncing weekly/monthly candles.

---

## What Changed

### Before

Background workers were launched as 12 independent daemon threads plus two asyncio schedulers. Each worker owned its own first-run flag, cron sleep logic, and startup gate logic:

- `main.py` imported nine different functions from `backgroundtasks.py` just to start and stop workers.
- Morningstar fair-value sync, the nightly scheduler, and the watchlist scheduler were scattered across `main.py` and `backgroundtasks.py`.
- Startup ordering was enforced by four `threading.Event` objects wired directly into each worker's `while` loop, making the dependency graph implicit and hard to trace.
- There was no single callable or API to "run the full pipeline on demand."
- Intraday / weekly / monthly candle backfill and indicator computation had no coordination with the daily pipeline, leading to potential race conditions at startup.

### After

A single `Orchestrator` class lives in `app/orchestrator.py` and owns the entire lifecycle:

- `orchestrator.start()` — called from `main.py` lifespan, replaces all previous scattered startup calls.
- `orchestrator.stop()` — graceful shutdown of all asyncio tasks and worker threads.
- `orchestrator.run_pipeline(mode)` — executes the ordered pipeline with an asyncio lock to prevent overlap.
- Two new registry jobs (`job.pipeline.startup` and `job.pipeline.nightly`) allow manual triggering via the existing `POST /api/jobs/{job_key}/trigger` endpoint.
- A new hourly startup gate (`_startup_ticker_hourly_done`) ensures `ticker_intraday_hourly_indicators_worker` waits for `ticker_intraday_hourly_update_worker` to finish its first candle backfill before computing 1h indicators.
- **1h stale-check + backfill** is now part of both startup and nightly pipelines (Stage 2c), so watchlist hourly candles are reconciled before the daily indicators/scores stages run.
- **Weekly/Monthly (W/M) candles + indicators** are now part of the nightly pipeline (Stage 5a/5b), not standalone workers. This guarantees fresh W/M data before the nightly scan runs.

`main.py` is now ~20 lines of lifespan logic instead of ~45, with a single import.

---

## Why This Change Was Needed

1. **Implicit ordering is fragile.** When startup sequencing is spread across 12 worker loops, a change to one worker can silently break the dependency chain for another.

2. **No on-demand full sync.** If data became stale for any reason, there was no API to say "run the entire refresh sequence now." Each stage had to be triggered individually.

3. **Night-time orchestration was missing.** The existing nightly logic only covered Morningstar fair-value sync. There was no automated, ordered sequence that ran stock-universe refresh → bhavcopy → backfill → indicators → scores → **W/M sync** → scan/notif after market close.

4. **W/M data was stale on weekends/holidays.** Because W/M candles were only fetched by an independent afternoon worker (16:00–20:00 IST), after a long weekend the weekly and monthly bars could be several days behind before the next market-day afternoon.

5. **Main.py was becoming a coordinator.** The FastAPI entry point was accumulating too much knowledge about background task internals. The Orchestrator moves that responsibility into a dedicated module.

6. **Observability.** With a single pipeline job in the registry, the UI can now show "Startup pipeline running — Stage 3/7" instead of requiring the operator to infer state from five separate job rows.

---

## Architecture & How It Works

### The Orchestrator Singleton

The Orchestrator is a module-level singleton (`app/orchestrator.py`). It does **not** replace the individual worker implementations — those still live in `backgroundtasks.py` and still self-manage their periodic cron loops. The Orchestrator is a thin coordination layer that:

1. Calls the existing synchronous "work" functions directly.
2. Manages the threading pipeline lock so scan/notification workers pause during data mutations.
3. Sets the same `threading.Event` startup gates so the workers' own cron loops are unblocked.

This means the Orchestrator and the workers are fully compatible: whichever path completes a stage first sets the gate, and the other path simply sees the gate already open.

### Pipeline Stages

Both pipelines follow the same seven-stage structure. The nightly pipeline additionally downloads the NSE bhavcopy before backfill and syncs W/M candles + indicators after scores.

#### STARTUP Pipeline

```
Stage 1  ──►  stock_universe
              (fetch all NSE symbol metadata)

Stage 2  ──►  ticker_backfill
              (one-year OHLCV history for every symbol)

Stage 2c ──►  ticker_intraday_hourly_stale_check
              (reconcile missing/stale 1h candles for watchlist symbols)

Stage 3  ──►  ticker_indicators
              (RSI, MACD, Bollinger, ATR, HV per candle)

Stage 4  ──►  ticker_scores
              (multi-period returns, momentum percentiles, volume ratios)

Stage 5  ──►  (skipped at startup — W/M is nightly-only)

Stage 6  ──►  global_scan  +  watchlist_notif
               (concurrent immediate cycle)
```

> **Note:** The hourly intraday workers (`ticker_intraday_hourly_update` → `ticker_intraday_hourly_indicators`) still run independently during market hours. In addition, the Orchestrator runs `ticker_intraday_hourly_stale_check` at startup and nightly so missing 1h candles are reconciled before daily indicator/score stages. The W/M startup stage uses DB consensus (not a live NSE reference symbol) to avoid false staleness when the live API returns the current incomplete period.

#### NIGHTLY Pipeline (23:00 IST)

```
Stage 1  ──►  stock_universe
              (re-sync metadata — new listings, delistings, PE changes)

Stage 2a ──►  ticker_daily_update
              (download NSE bhavcopy, gap-fill last 5 trading days)

Stage 2b ──►  ticker_backfill
              (deep gap-fill / catch-up for any symbols still stale)

Stage 2c ──►  ticker_intraday_hourly_stale_check
              (reconcile missing/stale 1h watchlist candles and recompute 1h indicators)

Stage 3  ──►  ticker_indicators
              (recompute indicators on the new candles)

Stage 4  ──►  ticker_scores
              (recompute momentum scores on the new indicators)

Stage 5a ──►  ticker_weekly_monthly_update
              (startup: backfill only stale/missing universe symbols using DB consensus; nightly: refresh all universe symbols with a bounded W/M window)

Stage 5b ──►  ticker_weekly_monthly_indicators
              (recompute indicators on W/M candles)

Stage 6  ──►  global_scan  +  watchlist_notif
              (concurrent immediate cycle on fresh data)
```

### Pipeline Locking & Safety

Stages that mutate tables read by the scan and notification workers acquire an existing `threading.Lock` (`_pipeline_lock`) and clear an existing `threading.Event` (`_pipeline_idle`).

```
Orchestrator                    Scan / Notif Workers
     │                                    │
     │  acquire _pipeline_lock            │
     │  clear _pipeline_idle              │
     │────────────────────────────────────┼──► workers see "idle=False"
     │                                    │     and block on _wait_for_pipeline()
     │  run indicators / scores           │
     │                                    │
     │  set _pipeline_idle                │
     │  release lock                      │
     │────────────────────────────────────┼──► workers unblock
     │                                    │
     │  trigger immediate scan+notif      │
```

This is the **same** lock already used by the workers for their own cron cycles. No new synchronization primitive was introduced.

An asyncio-level `asyncio.Lock` inside the Orchestrator prevents two pipeline runs from overlapping (e.g. if a manual API trigger arrives while the nightly pipeline is still running).

### Worker Taxonomy

| Worker | Managed By | Scheduling |
|--------|-----------|------------|
| `stock_universe_worker` | Self (cron + first-run) | Daily midnight + startup first-run |
| `ticker_backfill_worker` | Self | Startup only, then idle |
| `ticker_indicators_worker` | Self | Weekdays 11:00 + startup first-run |
| `ticker_scores_worker` | Self | Daily midnight + startup first-run |
| `ticker_daily_update_worker` | Self | Every 30 min 15:30–20:00 IST |
| `ticker_intraday_hourly_update_worker` | Self | At :15 past each trading hour 09:15–15:15 IST weekdays |
| `ticker_intraday_hourly_indicators_worker` | Self | At :30 past each trading hour 09:30–15:30 IST weekdays; waits `_startup_ticker_hourly_done` |
| `ticker_intraday_hourly_stale_check` | Orchestrator stage | Startup + 23:00 IST nightly |
| `global_scan_worker` | Self | Every 30 min (waits on pipeline idle) |
| `watchlist_notification_worker` | Self | Every 5 min market hours / 30 min after hours |
| `news_worker` | Self | Every 5 min |
| `news_rss_worker` | Self | Every 5 min |
| `watchlist_news_worker` | Self | Every 5 min |
| `market_data_worker` | Self | Every 5 min (market hours only) |
| `results_calendar_worker` | Self | 08:00 & 14:00 IST weekdays |
| **Pipeline (startup / nightly)** | **Orchestrator** | **Startup once + 23:00 IST daily** |
| `watchlist_fair_value` | Orchestrator scheduler | Every 3 hours |
| `full_fair_value` | Orchestrator scheduler | 23:00 IST nightly |

**Pipelined stages** (stages 1–6) are executed by the Orchestrator but the underlying work is delegated to the same synchronous functions the workers use. **Independent workers** are spawned by `start_all_workers()` and continue to run their own loops unaffected.

> **Note:** `ticker_intraday_hourly_stale_check`, `ticker_weekly_monthly_update`, and `ticker_weekly_monthly_indicators` are **not** standalone workers. They are orchestrator pipeline stages that call the same underlying intraday sync/indicator functions with interval-aware logic.

### Manual Triggering

Two new jobs are registered in the `JobRegistry`:

- `job.pipeline.startup`
- `job.pipeline.nightly`

Because they are registered as `is_async=True` with the Orchestrator's `run_pipeline` as their callable, the existing `POST /api/jobs/{job_key}/trigger` endpoint can execute them on demand. This is useful for:

- Recovery after an outage ("run the full startup sequence now")
- Ad-hoc testing of the nightly flow during the day
- Forcing a refresh when the operator knows data is stale

---

## Diagram: Full System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Lifespan                         │
│                                                                  │
│   1. Run Alembic migrations                                      │
│   2. Ensure watchlist data                                       │
│   3. Fix legacy encodings                                        │
│   4. await orchestrator.start()        ◄── replaces everything  │
│   5. MCP session manager yields                                  │
│   6. await orchestrator.stop()                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    orchestrator.start()                          │
│                                                                  │
│   ├─► init_client()            [Morningstar]                    │
│   ├─► start_all_workers()      [14 daemon threads]               │
│   ├─► register pipeline jobs   [JobRegistry + DB]               │
│   ├─► Morningstar first-run sync  [if needed]                   │
│   ├─► spawn watchlist-fv-scheduler   [every 3h]                 │
│   ├─► spawn nightly-pipeline-scheduler [23:00 IST]              │
│   └─► spawn startup-pipeline task  [background]                 │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
   ┌──────────────────────┐      ┌─────────────────────────┐
   │   Startup Pipeline   │      │   Nightly Pipeline      │
   │   (runs once)        │      │   (23:00 IST daily)     │
   └──────────────────────┘      └─────────────────────────┘
              │                               │
               │                               │
               │        ┌──────────────────────┐ │
               │        │  Hourly Intraday     │ │
               │        │  (independent)       │ │
               │        │  hourly_update ──►   │ │
               │        │  hourly_indicators    │ │
               │        └──────────────────────┘ │
               ▼                               ▼
    Stage 1: stock_universe          Stage 1: stock_universe
               │                               │
               ▼                               ▼
    Stage 2: ticker_backfill         Stage 2a: ticker_daily_update
               │                               │
               │                               ▼
               │                      Stage 2b: ticker_backfill
               │                               │
               ▼                               ▼
    Stage 2c: 1h stale-check         Stage 2c: 1h stale-check
               │                               │
               ▼                               ▼
    Stage 3: ticker_indicators       Stage 3: ticker_indicators
               │                               │
               ▼                               ▼
    Stage 4: ticker_scores           Stage 4: ticker_scores
               │                               │
               ▼                               ▼
    Stage 5: —                        Stage 5a: W/M candle sync
               │                               │
               ▼                               ▼
    Stage 6: scan + notif             Stage 5b: W/M indicator sync
               │                               │
               ▼                               ▼
          gates opened                  Stage 6: scan + notif
                                              │
                                              ▼
                                         gates opened
```

---

## Integration Points

### With JobRegistry

The Orchestrator registers two synthetic jobs after `start_all_workers()` has already registered the 14 individual worker jobs. This ordering matters because `sync_all_jobs_to_db()` is called inside `start_all_workers()`, so the pipeline jobs are synced to the database separately via `sync_job_to_db()`.

### With Existing Startup Gates

The Orchestrator sets the four daily-pipeline `threading.Event` objects (`_startup_stock_universe_done`, `_startup_ticker_backfill_done`, `_startup_ticker_indicators_done`, `_startup_ticker_scores_done`) after completing each stage. A **fifth** event, `_startup_ticker_hourly_done`, is set by `ticker_intraday_hourly_update_worker` after its first-run candle backfill completes; `ticker_intraday_hourly_indicators_worker` polls this gate before computing 1h indicators. This means:

- If the Orchestrator finishes a stage before the worker's own cron loop reaches it, the worker sees the gate already open and proceeds immediately.
- If the worker finishes first (e.g. on a warm restart where backfill is a no-op), the Orchestrator sees the gate already open and proceeds immediately.
- There is no race condition because the events are idempotent `set()` operations.

### With the API

No new endpoints were added. The existing `POST /api/jobs/{job_key}/trigger` endpoint works for `job.pipeline.startup` and `job.pipeline.nightly` because they follow the same `JobDefinition` contract as all other jobs.

---

## Key Behaviors & Guarantees

1. **Exactly-once pipeline at startup.** The startup pipeline is queued as a single background asyncio task. If it fails, it does not restart automatically — the operator must trigger it manually via the API.

2. **No concurrent pipelines.** An `asyncio.Lock` inside the Orchestrator ensures only one pipeline runs at a time. If the nightly scheduler fires while a manual trigger is still running, the scheduler skips that cycle with a warning log.

3. **Shutdown respects the pipeline.** If `_shutdown_event` is set mid-pipeline, each stage checks the event and returns early. The pipeline status is updated to `failed` so the UI reflects the abort.

4. **Scan/notif are paused during mutation.** Stages 2a, 3, 4, 5a, and 5b acquire the existing pipeline lock, so `global_scan_worker` and `watchlist_notification_worker` block on `_wait_for_pipeline()`. Once stage 5b releases the lock, the Orchestrator explicitly triggers one immediate scan+notif cycle before those workers resume their own cron schedules.

5. **Independent workers are unaffected.** News, market data, results calendar, fair-value, and **hourly intraday** workers run on their own threads and asyncio tasks. They do not participate in the daily pipeline and are never blocked by it. The hourly intraday workers do have their own internal ordering: `ticker_intraday_hourly_indicators_worker` waits on `_startup_ticker_hourly_done` set by `ticker_intraday_hourly_update_worker`.

6. **1h gaps are reconciled before indicators.** Because Stage 2c runs at both startup and nightly, watchlist symbols with missing hourly candles are backfilled and their 1h indicators are recomputed before the broader daily indicator/score pipeline continues.

7. **W/M are always fresh before scan.** Because W/M candle sync and indicator recompute are Stage 5a/5b of the nightly pipeline, the nightly scan (Stage 6) always sees the most recent weekly and monthly bars — even after holidays or long weekends.

---

## File Inventory

| File | Action | Role |
|------|--------|------|
| `backend/app/orchestrator.py` | **Modified** | Added Stage 2c (1h stale-check) and Stage 5a/5b (W/M sync + indicators), updated docstring/imports/stage labels |
| `backend/main.py` | **Unchanged** | Lifespan already calls `orchestrator.start()` / `orchestrator.stop()` |
| `backend/app/backgroundtasks.py` | **Modified** | Refactored `_ticker_intraday_update_sync()` and `_ticker_intraday_indicators_sync()` to accept `intervals` param; replaced old intraday workers with `ticker_intraday_hourly_update_worker` and `ticker_intraday_hourly_indicators_worker`; renamed gate to `_startup_ticker_hourly_done`; updated `register_all_jobs()` and `start_all_workers()` |
| `backend/alembic/versions/d8e1ed7addfa_cleanup_old_intraday_jobs.py` | **Created** | Deletes orphaned `job.ticker_intraday_update` / `job.ticker_intraday_indicators` rows and their `first_run.*` SystemConfig flags |
| `backend/app/jobs/registry.py` | **Unchanged** | Already supports arbitrary job registration; no modifications needed |
| `backend/app/models/ticker.py` | **Unchanged** | `TickerIntraday` model unchanged — still stores 1h / W / M with 17 indicator columns |
| `backend/app/services/indicators.py` | **Unchanged** | `compute_intraday_indicators_for_all_rows()` and `compute_intraday_indicators_for_latest_candle()` still handle all intervals |
| `backend/app/services/screener.py` | **Unchanged** | Cross-timeframe indicator loading and interval-prefixed filter keys still work |
| `backend/app/routers/ticker.py` | **Unchanged** | `GET /ticker/screener` still accepts `filters_json` for cross-timeframe filtering |
| `src/components/widgets/ScreenerWidget.tsx` | **Unchanged** | Frontend widget with Daily / 1h / Weekly / Monthly tabs |
| `src/components/Panel.tsx` | **Unchanged** | `SCREENER` widget route still registered |
| `src/components/CommandBar.tsx` | **Unchanged** | `SCREENER` command still present |

---

## Future Extensions

The Orchestrator design makes the following straightforward to add without touching worker code:

- **Pipeline health UI** — because `job.pipeline.startup` and `job.pipeline.nightly` are real rows in the `Job` table, a frontend widget can display overall pipeline progress (e.g. "Stage 5/6 — W/M indicators").
- **Pipeline retry with backoff** — the `_run_startup_pipeline` wrapper can be extended to catch failures and retry with exponential backoff.
- **Staggered nightly** — the 23:00 trigger could be split into 23:00 for universe/daily_update and 01:00 for indicators/scores if NSE data availability shifts.
- **Intraday pipeline observability** — the hourly update and indicator workers could be surfaced in the pipeline UI as lightweight "running" stages during market hours.
- **Cross-timeframe screener UI** — the `ScreenerWidget` already supports Daily / 1h / Weekly / Monthly tabs; future work could add MACD histogram and Bollinger Band width columns per interval.
- **Dry-run mode** — a `dry_run` flag could be threaded through `run_pipeline()` to log what would happen without writing to the database.
- **Real-time 1h pipeline** — instead of cron, the hourly worker could be triggered by a market-hours heartbeat for tighter latency.

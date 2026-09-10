# Backend Background Tasks Redesign Plan (Desktop Conversion)

## 1. Overview
The BLM Terminal backend was originally designed for a 24/7 hosted server environment. In that model, a rigorous startup pipeline (managed by `app/orchestrator.py`) pre-computed indicators, backfilled historical data, and scanned the entire market on boot before unlocking live data feeds. 
With the transition to a Desktop Client (Electron + PyInstaller), this eagerly-loaded, blocking architecture becomes a severe liability. 

## 2. Shift in Constraints & Limitations

### Old Limitations (Hosted Model) to REMOVE:
*   **Global Pre-computation Guarantee:** We no longer need to pre-cache historical W/M candles, RSI/MACD indicators, and momentum scores for all 2,000+ NSE equities on startup just in case one user requests them.
*   **Strict Linear Startup Gate:** Gating the live `market_data_scheduler` behind the completion of global backfills is no longer necessary.

### New Limitations (Desktop Model) to ADD & ENFORCE:
*   **Instant UI Readiness:** The user expects the app to be instantly usable within 3 seconds of launching.
*   **Local Hardware & DB Restraints:** Running 100% CPU to compute indicators for 2,000 stocks will spin up laptop fans and drain battery. Concurrently slamming SQLite with aggressive historical backfills causes `database is locked` errors, freezing user UI interactions.
*   **Ephemeral Lifespans:** Users close desktop apps arbitrarily. Long-running linear pipelines that restart from 0% on every boot will constantly redo work and never finish. Checkpointing is mandatory.

## 3. Core Strategy
1.  **Sever the Startup Gating:** Unblock the `market_data_scheduler` so watchlists get live data instantly, bypassing Stages 1b-6.
2.  **Transition to "Lazy" Loading:** For 90% of the NSE universe, only backfill history and compute indicators *when the user opens that specific stock's chart or widget*.
3.  **Background Trickle for Watchlists:** Limit automated background synchronization specifically to the user's active watchlists and portfolios, trickling the updates slowly to yield the SQLite WAL lock.

## 4. Action Plan: Code Modifications

### 4.1 Orchestrator Gating (`backend/app/orchestrator.py`)
*   **Remove market data block:** 
    *   Lines ~591-597: Remove the `while not _startup_market_data_done.is_set():` loop inside `_run_market_data_scheduler`. Live market fetching must begin immediately.
*   **Prune Startup Pipeline (`_execute_pipeline`):** 
    *   Lines ~354-367: Stage 1b (W/M candle backfill) - Add `requires_mode={PipelineMode.NIGHTLY}` or remove entirely. 
    *   Lines ~369-380: Stage 1c (W/M indicators) - Add `requires_mode={PipelineMode.NIGHTLY}` or remove entirely.
    *   Lines ~391-398: Stage 2b (backfill) - Add `requires_mode={PipelineMode.NIGHTLY}` or remove entirely.
    *   Lines ~400-410: Stage 2c (hourly stale check) - Add `requires_mode={PipelineMode.NIGHTLY}`.
    *   Lines ~412-419: Stage 3 (indicators) - Add `requires_mode={PipelineMode.NIGHTLY}`.
    *   Lines ~421-428: Stage 4 (scores) - Add `requires_mode={PipelineMode.NIGHTLY}`.
    *   Lines ~484-490: Stage 7 (market_data) - This gate is no longer needed since the scheduler doesn't wait for it.

### 4.2 Decouple Worker Daemons from Pipeline
*   Files: `backend/app/workers/ticker_compute.py`, `backend/app/workers/data.py`
*   Currently, daemons like `ticker_indicators_worker` block on `_wait_for_startup_event(_startup_pipeline_done)`. Once we remove the heavy stages from the startup pipeline, we must ensure these cron-based workers don't immediately slam the DB either.
*   **`backend/app/workers/ticker_compute.py`**:
    *   Line ~32: Remove or adjust `_wait_for_startup_event(_startup_pipeline_done)` in `ticker_scores_worker`.
    *   Line ~71: Remove or adjust `_wait_for_startup_event(_startup_pipeline_done)` in `ticker_indicators_worker`.
*   **`backend/app/workers/data.py`**:
    *   Line ~76: Remove or adjust `_wait_for_startup_event(_startup_pipeline_done)` in `ticker_daily_update_worker`.

### 4.3 Implement Lazy Sync for Widgets
*   When the frontend queries `/api/ticker/...` for historical data or indicators (Chart Widget, Screener Widget), the backend route must check if data is stale. If stale, run a synchronous backfill *just for that symbol* before returning the response.
*   Files to update: `backend/app/routers/ticker.py` and potentially `backend/app/services/data_sync/backfill.py` to support single-symbol on-demand fetches without hitting the queue.

### 4.4 Migrate to "Trickle" Writes (SQLite Lock Yielding)
*   Files: `backend/app/services/parallel_sync.py`
*   Any background task that still runs (e.g., Nightly pipeline) must include explicit `time.sleep()` or `asyncio.sleep()` yields between small batches (5-10 symbols) so the UI can safely acquire the SQLite write lock for user actions.
*   In `parallel_indicator_sync` (lines ~10-40), ensure that the `writer_batch_size` is small and that a yield occurs after `flush_fn` is called.

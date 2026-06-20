# Backend Memory Fix — Implementation Plan & Progress Log

## Phases

### Phase 0 — Quick Wins (Risk: Low)
- [x] **QW1:** Wire `screener_client.py` to use existing `screener_html_cache` from `cache.py`
- [x] **QW2:** `del` raw NSE responses in `global_scan_cycle.py`
- [x] **QW3:** Add `gc.collect()` after scores pipeline stages in `scores.py`
- [x] **QW4:** Remove dead `_html_cache` from `morningstar_client.py`

### Phase 1 — Stream + Chunk `_ticker_scores_sync` (Risk: Medium)
- [ ] Extract per-batch helper to `_scores_batch.py`
- [ ] Refactor `_ticker_scores_sync` in `scores.py` to process in chunks of 500
- [ ] Update tests and regenerate golden files

### Phase 2 — `QueuePool` on the sync engine (Risk: Low)
- [ ] Change sync engine in `database.py` to use `QueuePool` instead of `NullPool`
- [ ] Keep async engine on `NullPool`

### Phase 3 — NSE sync facade uses `_run_async` (Risk: High)
- [ ] Add `_run_async_from_sync` helper in `nse_client_async.py`
- [ ] Update 13 sync facade methods to use the helper
- [ ] Update `_get_client` to reuse httpx clients per thread loop

### Phase 4 — P2 Fixes (Risk: Low)
- [ ] **P2-1:** SQL window function in `get_latest_indicator_rows`
- [ ] **P2-3:** `news_fetcher` stream to DB instead of `asyncio.gather`

---

## Progress Log

**[Sat Jun 20 2026] Initialization**
- Created this tracking document.
- Commencing Phase 0 execution.

**[Sat Jun 20 2026] Phase 0 Completed**
- Successfully implemented QW1, QW2, QW3, and QW4.
- Added test coverage. `TTLCache`'s timer property was read-only, so removed the redundant test case mocking `time.monotonic` as cachetools tests TTLCache adequately. All tests passing!

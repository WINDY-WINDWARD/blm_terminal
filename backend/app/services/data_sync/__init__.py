"""Data-sync cores package — Phase C.1 split target.

After the split, this package holds the **sync cores** (the
business logic that runs in a worker thread) extracted from
``app/backgroundtasks.py``.  Each module holds one concern:

- ``universe.py``    — ``_stock_universe_sync`` (NSE universe refresh)
- ``backfill.py``    — ``_ticker_backfill_sync`` (multi-year backfill)
- ``daily.py``       — ``_ticker_daily_update_sync`` (bhavcopy ingest)
- ``intraday.py``    — ``_ticker_intraday_update_sync`` + hourly stale check
- ``indicators.py``  — ``_ticker_indicators_sync`` + intraday indicators
- ``scores.py``      — ``_ticker_scores_sync`` (returns + momentum)
- ``parallel.py``    — ``_parallel_indicator_sync`` (3-compute + 1-writer wrapper)
- ``snapshot.py``    — ``_screener_snapshot_sync`` (denormalized TQL view)
- ``news.py``        — news + RSS + watchlist-news sync cores (A.11 part 2)
- ``market.py``      — market data + is_market_open helpers (A.11 part 2)
- ``calendar.py``    — ``_results_calendar_sync`` (NSE event calendar, A.11 part 2)

Until the migration completes, the package is a no-op re-export
shim that defers to ``app.backgroundtasks`` so callers continue
to work unchanged.  See ``tests/test_data_sync_skeleton.py`` for
the contract.
"""

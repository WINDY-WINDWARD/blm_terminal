"""Data-sync cores package — Phase C.1 split target.

After the split, this package will hold the **sync cores** (the
business logic that runs in a worker thread) extracted from
``app/backgroundtasks.py``.  Each module holds one concern:

- ``universe.py``    — ``_stock_universe_sync`` (NSE universe refresh)
- ``backfill.py``    — ``_ticker_backfill_sync`` (multi-year backfill)
- ``daily.py``       — ``_ticker_daily_update_sync`` (bhavcopy ingest)
- ``intraday.py``    — ``_ticker_intraday_update_sync`` + hourly stale check
- ``indicators.py``  — ``_ticker_indicators_sync`` + intraday indicators
- ``scores.py``      — ``_ticker_scores_sync`` (returns + momentum)

Until the migration completes, the package is a no-op re-export
shim that defers to ``app.backgroundtasks`` so callers continue
to work unchanged.  See ``tests/test_data_sync_skeleton.py`` for
the contract.
"""

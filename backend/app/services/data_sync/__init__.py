"""Data-sync cores package — Phase C.1 split target.

After the split, this package holds the **sync cores** (the
business logic that runs in a worker thread) extracted from
``app/backgroundtasks.py``.  Each module holds one concern:

- ``universe.py``           — ``_stock_universe_sync`` (NSE universe refresh)
- ``backfill.py``           — ``_ticker_backfill_sync`` (multi-year backfill)
- ``daily.py``              — ``_ticker_daily_update_sync`` (bhavcopy ingest)
- ``intraday.py``           — ``_ticker_intraday_update_sync`` + hourly stale check
- ``indicators.py``         — ``_ticker_indicators_sync`` + intraday indicators
- ``scores.py``             — ``_ticker_scores_sync`` (returns + momentum)
- ``parallel.py``           — ``_parallel_indicator_sync`` (3-compute + 1-writer wrapper)
- ``snapshot.py``           — ``_screener_snapshot_sync`` (denormalized TQL view)
- ``news.py``               — news + RSS + watchlist-news sync cores (A.11 part 2)
- ``market.py``             — market data + is_market_open helpers (A.11 part 2)
- ``calendar.py``           — ``_results_calendar_sync`` (NSE event calendar, A.11 part 2)
- ``nse_parsing.py``        — ``_parse_*`` + ``_safe_fetch_*`` NSE helpers (A.12 part 1)
- ``cleanup.py``            — daily DB cleanup suite (A.12 part 1)
- ``deal_significance.py``  — ``DealRecord`` + deal-significance helpers (A.12 part 1)
- ``insider_trades.py``     — screener.in insider-trades fetcher (A.12 part 1)
- ``notifications.py``      — watchlist + global notification helpers (A.12 part 1)

Every module except ``parallel.py`` uses the lazy-import pattern
(``from app.backgroundtasks import _impl as _bg_impl; _bg_impl.<name>``)
inside the function body to avoid a circular import through
``_impl``'s re-export shim.  See ``tests/test_data_sync_<module>.py``
for the per-module contract.

Until the migration completes, the package is a no-op re-export
shim that defers to ``app.backgroundtasks`` so callers continue
to work unchanged.  See ``tests/test_data_sync_skeleton.py`` for
the contract.
"""

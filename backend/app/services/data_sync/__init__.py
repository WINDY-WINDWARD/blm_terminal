"""Data-sync cores package — Phase C.1 split target.

Each module holds the **sync core** for one concern, extracted from
``app/backgroundtasks.py``:

- ``universe.py``           — ``_stock_universe_sync`` (NSE universe refresh)
- ``backfill.py``           — ``_ticker_backfill_sync`` (multi-year backfill)
- ``daily.py``              — ``_ticker_daily_update_sync`` (bhavcopy ingest)
- ``intraday.py``           — ``_ticker_intraday_update_sync`` + hourly stale check
- ``indicators.py``         — ``_ticker_indicators_sync`` + intraday indicators
- ``scores.py``             — ``_ticker_scores_sync`` (returns + momentum)
- ``parallel.py``           — ``_parallel_indicator_sync`` (3-compute + 1-writer wrapper)
- ``snapshot.py``           — ``_screener_snapshot_sync`` (denormalized TQL view)
- ``news.py``               — news + RSS + watchlist-news sync cores
- ``market.py``             — market data + ``is_market_open`` helpers
- ``calendar.py``           — ``_results_calendar_sync`` (NSE event calendar)
- ``nse_parsing.py``        — ``_parse_*`` + ``_safe_fetch_*`` NSE helpers
- ``cleanup.py``            — daily DB cleanup suite
- ``deal_significance.py``  — ``DealRecord`` + deal-significance helpers
- ``insider_trades.py``     — screener.in insider-trades fetcher
- ``notifications.py``      — watchlist + global notification helpers

Several modules use a **lazy import** of
``app.backgroundtasks._runtime`` inside function bodies
to avoid circular dependencies through the ``__init__.py`` shim.
See ``tests/test_data_sync_<module>.py`` for the per-module contract.
"""

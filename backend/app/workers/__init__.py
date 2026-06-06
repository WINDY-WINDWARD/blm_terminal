"""Worker package — Phase C.1 split target for ``app.backgroundtasks``.

After the split, this package will hold the daemon-thread worker
targets that were previously defined at the top level of the
4994-LOC ``app/backgroundtasks.py``.  Each module here wraps a
specific concern:

- ``data.py``        — Ticker backfill / daily / intraday workers
- ``news.py``        — News RSS / aggregator / watchlist-news workers
- ``notifications.py`` — Watchlist + global scan notification cycles
- ``fair_value.py``   — Morningstar fair-value batch resolvers
- ``maintenance.py`` — Vacuum + retention workers
- ``__init__.py``     — ``start_all_workers`` / ``stop_all_workers``

Until the migration completes, the package re-exports every public
worker symbol from ``app.backgroundtasks`` so callers continue to
work unchanged.  See ``tests/test_workers_skeleton.py`` for the
contract.
"""
from app.backgroundtasks import (  # noqa: F401
    # Worker lifecycle (public)
    start_all_workers,
    stop_all_workers,
    start_cache_cleanup,
    # Data workers (re-exported here as a temporary bridge — they
    # will move into ``data.py`` in a later commit of C.1).
    stock_universe_worker,
    ticker_backfill_worker,
    ticker_daily_update_worker,
    ticker_intraday_hourly_update_worker,
    ticker_indicators_worker,
    ticker_intraday_hourly_indicators_worker,
    ticker_scores_worker,
    # News workers
    news_worker,
    news_rss_worker,
    watchlist_news_worker,
    market_data_worker,
    # Notification workers
    watchlist_notification_worker,
    global_scan_worker,
    # Results calendar + maintenance
    results_calendar_worker,
    vacuum_worker,
)

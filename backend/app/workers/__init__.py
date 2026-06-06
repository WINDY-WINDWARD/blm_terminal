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

NOTE: We re-export ``start_all_workers``/``stop_all_workers``/etc
from ``app.backgroundtasks`` (the legacy package), and the
moved-per-domain workers (currently just ``vacuum_worker``) from
their new homes under ``app.workers.<domain>``.  This avoids a
circular import where ``app.workers.__init__`` triggers
``app.backgroundtasks`` which triggers ``app.backgroundtasks._impl``
which tries to import a worker back through ``app.workers``.
"""
from app.backgroundtasks import (  # noqa: F401
    # Worker lifecycle (public)
    start_all_workers,
    stop_all_workers,
    start_cache_cleanup,
)
# Maintenance workers (moved to app.workers.maintenance in A.9).
# Re-exported here from the new module to keep callers stable.
from app.workers.maintenance import (  # noqa: E402,F401
    vacuum_worker,
)
# Data workers (moved to app.workers.{universe,data,ticker_compute} in A.9 step 2).
# Re-exported here from the new modules to keep callers stable.
from app.workers.universe import (  # noqa: E402,F401
    stock_universe_worker,
)
from app.workers.data import (  # noqa: E402,F401
    ticker_backfill_worker,
    ticker_daily_update_worker,
    ticker_intraday_hourly_update_worker,
)
from app.workers.ticker_compute import (  # noqa: E402,F401
    ticker_indicators_worker,
    ticker_intraday_hourly_indicators_worker,
    ticker_scores_worker,
)
# Notification workers (moved to app.workers.notifications in A.9 step 3).
# Re-exported here from the new module to keep callers stable.
from app.workers.notifications import (  # noqa: E402,F401
    watchlist_notification_worker,
    global_scan_worker,
)
# News + market workers (moved in A.9 step 4).
from app.workers.news import (  # noqa: E402,F401
    news_worker,
    news_rss_worker,
    watchlist_news_worker,
)
from app.workers.market_calendar import (  # noqa: E402,F401
    market_data_worker,
    results_calendar_worker,
)

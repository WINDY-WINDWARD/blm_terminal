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
- ``lifecycle.py``   — ``start_all_workers`` / ``stop_all_workers``
                       / ``start_cache_cleanup`` (A.12 part 3)

Until the migration completes, the package re-exports every public
worker symbol from their new homes under ``app.workers.<domain>`` so
callers continue to work unchanged.  See
``tests/test_workers_skeleton.py`` for the contract.

NOTE: lifecycle functions are imported from ``app.workers.lifecycle``
directly (NOT from ``app.backgroundtasks``) to avoid a circular
import where ``app.workers.__init__`` triggers
``app.backgroundtasks`` which triggers
``app.backgroundtasks._impl`` which re-imports lifecycle back through
``app.workers``.
"""
# Worker lifecycle (moved to app.workers.lifecycle in A.12 part 3).
from app.workers.lifecycle import (  # noqa: F401
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
    results_calendar_worker,
)

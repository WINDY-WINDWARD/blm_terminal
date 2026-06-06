"""Results calendar sync core (audit C.1, A.11 part 2).

Extracted from ``app/backgroundtasks/_impl.py``.  Holds the
NSE results calendar sync core called by the
``results_calendar_worker`` daemon in
``app.workers.market_calendar``.

Public function:
- ``_results_calendar_sync()`` — Fetch the NSE event calendar
  and create 'results_upcoming' notifications for any board
  meeting that mentions "Financial Results" in its purpose and
  whose symbol is in any watchlist.

Public constant:
- ``_RESULTS_CALENDAR_CRON`` — "0 8,14 * * 1-5" (8am + 2pm IST
  on trading days)

Each notification row is upserted with:
  - trigger_type   = 'results_upcoming'
  - triggered_date = the board meeting date  (dedup key)
  - triggered_at   = now (time the alert was generated)

The existing ``uq_notification_daily`` constraint (watchlist_id,
symbol, trigger_type, triggered_date) ensures each alert fires
only once per meeting date per watchlist — re-running the job
produces no duplicates.

NOTE: We import ``logger``, ``_get_watchlist_symbols``,
``_bulk_upsert_notifications``, and ``update_job_status_sync``
lazily inside the function body to avoid a circular import:
``app.backgroundtasks._impl`` re-exports us at the bottom of
its own module, so a top-level import from ``_impl`` here would
deadlock the import machinery.
"""
from __future__ import annotations

from datetime import datetime


_RESULTS_CALENDAR_CRON = "0 8,14 * * 1-5"  # 8am + 2pm IST on trading days


def _results_calendar_sync() -> None:
    """Fetch NSE event calendar and create 'results_upcoming' notifications.

    For each board meeting event that mentions "Financial Results" in its
    purpose and whose symbol is in any watchlist, upserts a Notification row
    with:
      - trigger_type = 'results_upcoming'
      - triggered_date = the board meeting date  (dedup key)
      - triggered_at   = now (time the alert was generated)

    The existing uq_notification_daily constraint (watchlist_id, symbol,
    trigger_type, triggered_date) ensures each alert fires only once per
    meeting date per watchlist — re-running the job produces no duplicates.
    """
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    update_job_status_sync = _bg_impl.update_job_status_sync
    _get_watchlist_symbols = _bg_impl._get_watchlist_symbols
    _bulk_upsert_notifications = _bg_impl._bulk_upsert_notifications

    try:
        logger.info("results_calendar_sync: starting")
        update_job_status_sync(
            "job.results_calendar", "running", progress=10,
            message="Fetching event calendar from NSE...",
        )

        # Import here to avoid circular imports at module level
        from app.routers.announcements import get_event_calendar_cached

        try:
            events = get_event_calendar_cached()
        except Exception:
            logger.exception("results_calendar_sync: failed to fetch event calendar")
            update_job_status_sync(
                "job.results_calendar", "failed",
                message="Failed to fetch event calendar from NSE",
            )
            return

        # Filter to only entries that include "Financial Results" in purpose
        results_events = [
            e for e in events
            if "financial results" in e.purpose.lower()
        ]

        if not results_events:
            logger.info("results_calendar_sync: no upcoming financial results events found")
            update_job_status_sync(
                "job.results_calendar", "waiting", progress=100,
                message="No upcoming results events",
            )
            return

        logger.info(
            "results_calendar_sync: %d results events found, cross-referencing watchlists",
            len(results_events),
        )
        update_job_status_sync(
            "job.results_calendar", "running", progress=40,
            message=f"Cross-referencing {len(results_events)} events against watchlists...",
        )

        # Load all watchlist symbols grouped by watchlist_id
        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.info("results_calendar_sync: watchlist is empty, skipping")
            update_job_status_sync(
                "job.results_calendar", "waiting", progress=100,
                message="Watchlist empty",
            )
            return

        # Build reverse map: symbol → list of watchlist_ids
        watchlists_by_symbol: dict[str, list[int]] = {}
        for wl_id, symbols in symbols_by_watchlist.items():
            for sym in symbols:
                watchlists_by_symbol.setdefault(sym.upper(), []).append(wl_id)

        now = datetime.now()
        pending: list[dict] = []

        for event in results_events:
            sym = event.symbol.upper()
            if sym not in watchlists_by_symbol:
                continue

            # Parse the board meeting date string, e.g. "20-Apr-2026"
            try:
                meeting_date = datetime.strptime(event.date, "%d-%b-%Y").date()
            except ValueError:
                logger.warning(
                    "results_calendar_sync: unparseable date '%s' for %s, skipping",
                    event.date, sym,
                )
                continue

            # Truncate description to 200 chars for the notification message
            desc = event.description or event.purpose
            msg = f"Results on {event.date}: {desc[:180]}"
            if len(desc) > 180:
                msg += "…"

            for wl_id in watchlists_by_symbol[sym]:
                pending.append(
                    {
                        "watchlist_id": wl_id,
                        "symbol": sym,
                        "exchange": "NSE",
                        "trigger_type": "results_upcoming",
                        "message": msg[:256],
                        "triggered_at": now,
                        "triggered_date": meeting_date,
                        "is_read": False,
                    }
                )

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info(
                "results_calendar_sync: upserted %d notification rows (%d unique events)",
                len(pending),
                len({(r["symbol"], r["triggered_date"]) for r in pending}),
            )
        else:
            logger.info("results_calendar_sync: no watchlist symbols matched upcoming results events")

        update_job_status_sync(
            "job.results_calendar", "waiting", progress=100,
            message=f"Done — {len(pending)} notifications upserted",
        )

    except Exception:
        logger.exception("results_calendar_sync: unhandled exception; will retry next cycle")
        update_job_status_sync("job.results_calendar", "failed", message="Unhandled exception")

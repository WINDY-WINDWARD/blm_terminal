"""A.12 part 3 — thin backward-compat shim for ``_impl``.

After A.12 part 3, ``_impl`` no longer contains implementation code.
All actual logic now lives in their final homes:

  - ``app.backgroundtasks._runtime`` — cross-cutting runtime helpers
    (state + scheduling primitives) that worker modules use.
  - ``app.workers.lifecycle`` — ``start_all_workers`` /
    ``stop_all_workers`` / ``start_cache_cleanup``.
  - ``app.workers.<domain>`` — domain-specific worker daemons.
  - ``app.services.data_sync.<domain>`` — sync cores.
  - ``app.services.fair_value`` — Morningstar fair-value sync.

This file re-exports ONLY the **frequently-imported primitives** that
worker modules and data_sync cores reach through ``_bg_impl`` for
historical reasons:

  - ``logger`` — module-level logger (``logging.getLogger(__name__)``)
  - ``AsyncSessionLocal`` / ``_SyncSessionLocal`` — DB session factories
  - ``settings`` — pydantic settings
  - ``update_job_status`` / ``update_job_status_sync`` /
    ``sync_all_jobs_to_db`` — job-runner helpers

Moved symbols (sync cores, workers, cycles, lifecycle, news helpers)
are NOT re-exported here.  A.13 migrates the lazy ``_bg_impl`` callers
in data_sync / workers / orchestrator to import from canonical homes
directly.  After A.13, this file is deleted.

Symbols that *are* re-exported (logger, session factories, settings,
job-runner helpers) are ``is``-identical to their canonical homes
(``app.database``, ``app.config``, ``app.jobs.runner``) so tests can
pin the move.
"""
# ─── Runtime helpers + state ─────────────────────────────────────────────
from app.backgroundtasks._runtime import (  # noqa: F401
    _shutdown_event,
    _worker_threads,
    _pipeline_lock,
    _pipeline_idle,
    _is_job_enabled,
    _is_first_run,
    _set_first_run_complete,
    _wait_for_startup_event,
    _wait_for_pipeline,
    _run_async,
    _report_job_waiting,
    _startup_stock_universe_done,
    _startup_ticker_backfill_done,
    _startup_ticker_indicators_done,
    _startup_ticker_scores_done,
    _startup_ticker_hourly_done,
    reset_async_shutdown_event,
    set_async_shutdown_event,
    _sleep_interruptible,
    _seconds_until_next_cron,
    get_async_shutdown_event,
)

# ─── Session factories + config ──────────────────────────────────────────
from app.database import (  # noqa: F401
    AsyncSessionLocal,
    _SyncSessionLocal,
)
from app.config import settings  # noqa: F401

# ─── Logger ──────────────────────────────────────────────────────────────
# Worker modules lazy-import ``_bg_impl.logger`` — keep the historical
# module-level logger re-exported.
import logging as _logging
logger = _logging.getLogger(__name__)

# ─── Job runner helpers ──────────────────────────────────────────────────
from app.jobs.runner import (  # noqa: F401
    sync_all_jobs_to_db,
    update_job_status,
    update_job_status_sync,
)

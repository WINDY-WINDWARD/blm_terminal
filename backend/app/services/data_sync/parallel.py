"""Parallel indicator sync core (audit C.1, A.11).

Extracted from ``app/backgroundtasks/_impl.py``.

Public function:
- ``_parallel_indicator_sync()`` — thin wrapper around
  ``app.services.parallel_sync.parallel_indicator_sync`` that wires
  in the orchestrator's ``_shutdown_event``, ``update_job_status``
  callbacks, and default logging.

The full implementation lives in ``app.services.parallel_sync`` so
it can be unit-tested without importing the heavy transitive
dependencies of ``app.backgroundtasks`` (NSE client, news
aggregator, etc.).

NOTE: We import ``logger``, ``_shutdown_event`` and
``update_job_status_sync`` lazily inside the function body to avoid
a circular import: ``app.backgroundtasks._impl`` re-exports us at
the bottom of its own module, so a top-level import from ``_impl``
here would deadlock the import machinery.
"""
from __future__ import annotations

from typing import Callable, Optional


def _parallel_indicator_sync(
    items: list[tuple],
    prepare_fn: Callable,
    flush_fn: Callable,
    *,
    job_key: str,
    pipeline_job_key: Optional[str] = None,
    pipeline_progress_start: Optional[int] = None,
    pipeline_progress_end: Optional[int] = None,
    num_compute_workers: int = 3,
    queue_maxsize: int = 100,
    writer_batch_size: int = 50,
    heartbeat_every_s: float = 10.0,
    progress_every: int = 10,
    slow_threshold_s: float = 5.0,
) -> dict:
    """Thin wrapper around `app.services.parallel_sync.parallel_indicator_sync`
    that wires in the orchestrator's `_shutdown_event`, `_ticker_*_status_sync`
    callbacks, and default logging.

    The full implementation lives in `app.services.parallel_sync` so it can
    be unit-tested without importing the heavy transitive dependencies of
    `app.backgroundtasks` (NSE client, news aggregator, etc.).
    """
    from app.backgroundtasks import _impl as _bg_impl
    from app.services.parallel_sync import parallel_indicator_sync

    logger = _bg_impl.logger
    _shutdown_event = _bg_impl._shutdown_event
    update_job_status_sync = _bg_impl.update_job_status_sync

    def _on_progress(enqueued: int, total: int, elapsed_s: float, rate: float) -> None:
        logger.info(
            "indicator_sync: enqueued %d/%d (%.1fs, %.1f items/s)",
            enqueued, total, elapsed_s, rate,
        )

    def _on_heartbeat(enqueued: int, total: int, elapsed_s: float) -> None:
        logger.info(
            "indicator_sync: heartbeat — %d/%d enqueued (%.1fs elapsed)",
            enqueued, total, elapsed_s,
        )

    def _update_job(job_key_: str, status: str, progress: int, message: str) -> None:
        update_job_status_sync(job_key_, status, progress=progress, message=message)

    return parallel_indicator_sync(
        items=items,
        prepare_fn=prepare_fn,
        flush_fn=flush_fn,
        shutdown_event=_shutdown_event,
        update_job_status_fn=_update_job,
        job_key=job_key,
        pipeline_job_key=pipeline_job_key,
        pipeline_progress_start=pipeline_progress_start,
        pipeline_progress_end=pipeline_progress_end,
        num_compute_workers=num_compute_workers,
        queue_maxsize=queue_maxsize,
        writer_batch_size=writer_batch_size,
        heartbeat_every_s=heartbeat_every_s,
        progress_every=progress_every,
        slow_threshold_s=slow_threshold_s,
        heartbeat_fn=_on_heartbeat,
        progress_fn=_on_progress,
    )

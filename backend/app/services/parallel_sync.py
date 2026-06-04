"""Multithreaded indicator sync helper.

3 compute workers + 1 dedicated writer thread, communicating through two
bounded `queue.Queue`s.  Extracted from `app.backgroundtasks` so it can be
imported in tests without pulling in the NSE / news / etc. transitive
imports that the rest of `backgroundtasks` requires.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def parallel_indicator_sync(
    items: list[tuple],
    prepare_fn: Callable[..., list[dict]],
    flush_fn: Callable[[list[dict]], int],
    *,
    shutdown_event: threading.Event,
    update_job_status_fn: Optional[Callable[..., None]] = None,
    job_key: Optional[str] = None,
    pipeline_job_key: Optional[str] = None,
    pipeline_progress_start: Optional[int] = None,
    pipeline_progress_end: Optional[int] = None,
    num_compute_workers: int = 3,
    queue_maxsize: int = 100,
    writer_batch_size: int = 50,
    heartbeat_every_s: float = 10.0,
    progress_every: int = 10,
    slow_threshold_s: float = 5.0,
    heartbeat_fn: Optional[Callable[[int, int, float], None]] = None,
    progress_fn: Optional[Callable[[int, int, float, float], None]] = None,
) -> dict:
    """Process a list of (symbol[, interval]) items with 3 compute workers + 1
    dedicated writer thread.

    Topology:
        producer (this thread) ──► compute_q (maxsize=100) ──► [3 compute workers]
                                                                       │
                                                                       ▼
                                                                 writer_q (maxsize=100)
                                                                       │
                                                                       ▼
                                                                 writer (1 thread)

    The producer enqueues all items, then waits for compute_q to drain
    (`compute_q.join()`) so no compute worker is still mid-flight. It then
    pushes N=`num_compute_workers` `None` sentinels; each compute worker
    receives one, forwards a `None` to writer_q, and exits. The writer flushes
    its pending batch after receiving all N sentinels, then exits.

    Args:
        items: list of tuples.  For daily: `[("SYM",), ...]`.  For intraday:
            `[("SYM", "1h"), ...]`.  Each tuple is passed as `*args` to
            `prepare_fn` and to the per-item log line.
        prepare_fn: pure function `(*args) -> list[dict]`.  Loads candles and
            builds update dicts.  Must NOT touch the DB for writes (the
            dedicated writer is the only writer).
        flush_fn: function `(list[dict]) -> int`.  Bulk-updates the prepared
            rows.  The writer calls this with the buffered updates.
        shutdown_event: `threading.Event` checked by the producer to abort
            mid-flight.  Shutdown stops the producer from enqueueing more
            items; the existing queue is drained and the writer exits cleanly
            on its sentinels.
        update_job_status_fn: optional callback `(job_key, status, progress,
            message)` used to update the JobRegistry.
        job_key: the JobRegistry key for the per-job status.
        pipeline_job_key: if set, also nudge the user-visible pipeline bar
            (e.g. "job.pipeline.startup") with a percentage in the
            [pipeline_progress_start, pipeline_progress_end] range.
        num_compute_workers: parallel compute threads (default 3).
        queue_maxsize: bound on each of the two queues (default 100).
        writer_batch_size: writer flushes when pending >= this (default 50).
        heartbeat_every_s: producer-side heartbeat interval (default 10s).
        progress_every: log per-N items (default 10).
        slow_threshold_s: compute workers log a warning when a single
            prepare_fn call exceeds this (default 5s).
        heartbeat_fn: optional `(enqueued, total, elapsed_s) -> None` callback
            invoked from the producer at the heartbeat cadence.
        progress_fn: optional `(enqueued, total, elapsed_s, rate) -> None`
            callback invoked from the producer at the progress cadence.

    Returns:
        dict with keys: success, failed, rows_written, elapsed_s.
    """
    total = len(items)
    if total == 0:
        return {"success": 0, "failed": 0, "rows_written": 0, "elapsed_s": 0.0}

    compute_q: queue.Queue = queue.Queue(maxsize=queue_maxsize)
    writer_q:  queue.Queue = queue.Queue(maxsize=queue_maxsize)

    state = {
        "rows_written": 0,
        "writer_failed": False,
        "writer_error": None,
        "writer_lock": threading.Lock(),
    }

    def _writer_loop() -> None:
        nones_expected = num_compute_workers
        nones_seen = 0
        pending: list[list[dict]] = []
        try:
            while True:
                try:
                    item = writer_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    nones_seen += 1
                    writer_q.task_done()
                    if nones_seen >= nones_expected:
                        if pending:
                            try:
                                n = flush_fn([u for batch in pending for u in batch])
                                with state["writer_lock"]:
                                    state["rows_written"] += n
                            except Exception as e:
                                logger.error(
                                    "parallel_indicator_sync writer: final flush failed: %s", e,
                                )
                                with state["writer_lock"]:
                                    state["writer_failed"] = True
                                    state["writer_error"] = e
                        return
                    continue
                if item:
                    pending.append(item)
                if len(pending) >= writer_batch_size:
                    try:
                        n = flush_fn([u for batch in pending for u in batch])
                        with state["writer_lock"]:
                            state["rows_written"] += n
                    except Exception as e:
                        logger.error(
                            "parallel_indicator_sync writer: batch flush failed: %s", e,
                        )
                        with state["writer_lock"]:
                            state["writer_failed"] = True
                            state["writer_error"] = e
                    pending.clear()
                writer_q.task_done()
        except Exception as e:
            logger.exception("parallel_indicator_sync writer: unhandled exception")
            with state["writer_lock"]:
                state["writer_failed"] = True
                state["writer_error"] = e

    def _compute_worker(worker_id: int) -> None:
        while True:
            try:
                item = compute_q.get(timeout=0.5)
            except queue.Empty:
                if shutdown_event.is_set():
                    writer_q.put(None, timeout=2.0)
                    compute_q.task_done()
                    return
                continue
            if item is None:
                writer_q.put(None, timeout=2.0)
                compute_q.task_done()
                return
            t0 = time.monotonic()
            try:
                updates = prepare_fn(*item)
            except Exception as e:
                logger.warning(
                    "parallel_indicator_sync compute worker %d: failed for %s: %s",
                    worker_id, item, e,
                )
                compute_q.task_done()
                continue
            dt = time.monotonic() - t0
            if dt > slow_threshold_s:
                logger.warning(
                    "parallel_indicator_sync compute worker %d: slow %s took %.1fs (%d updates)",
                    worker_id, item, dt, len(updates) if updates else 0,
                )
            try:
                writer_q.put(updates, timeout=2.0)
            except queue.Full:
                logger.error(
                    "parallel_indicator_sync compute worker %d: writer_q full, dropping %s",
                    worker_id, item,
                )
            compute_q.task_done()

    writer_thread = threading.Thread(
        target=_writer_loop, name="indicator_writer", daemon=True,
    )
    writer_thread.start()

    compute_threads = [
        threading.Thread(
            target=_compute_worker, name=f"indicator_compute_{i}", daemon=True,
            args=(i,),
        )
        for i in range(num_compute_workers)
    ]
    for t in compute_threads:
        t.start()

    pipeline_start_time = time.monotonic()
    last_heartbeat = pipeline_start_time
    enqueued = 0

    def _emit_progress() -> None:
        elapsed = time.monotonic() - pipeline_start_time
        rate = enqueued / elapsed if elapsed > 0 else 0
        if progress_fn is not None:
            progress_fn(enqueued, total, elapsed, rate)
        if pipeline_job_key and pipeline_progress_start is not None and pipeline_progress_end is not None:
            span = max(1, pipeline_progress_end - pipeline_progress_start)
            pct = pipeline_progress_start + int((enqueued / total) * span)
            if len(item) == 1:  # noqa: F821
                sym_label = str(item[0])  # noqa: F821
            else:
                sym_label = "/".join(str(x) for x in item)  # noqa: F821
            msg = f"Stage 3/7: Computing indicators... {enqueued}/{total} ({sym_label})"
            if len(msg) > 80:
                msg = msg[:77] + "..."
            if update_job_status_fn is not None:
                update_job_status_fn(pipeline_job_key, "running", progress=pct, message=msg)

    for i, item in enumerate(items, start=1):
        if shutdown_event.is_set():
            logger.info(
                "parallel_indicator_sync producer: shutdown requested, stopping enqueue at %d/%d",
                i - 1, total,
            )
            break
        try:
            compute_q.put(item, timeout=0.5)
        except queue.Full:
            while not shutdown_event.is_set():
                try:
                    compute_q.put(item, timeout=0.5)
                    break
                except queue.Full:
                    time.sleep(0.1)
            if shutdown_event.is_set():
                break
        enqueued = i

        if enqueued % progress_every == 0 or enqueued == total:
            _emit_progress()

        now = time.monotonic()
        if now - last_heartbeat > heartbeat_every_s:
            elapsed = now - pipeline_start_time
            if heartbeat_fn is not None:
                heartbeat_fn(enqueued, total, elapsed)
            last_heartbeat = now

    compute_q.join()
    for _ in range(num_compute_workers):
        compute_q.put(None, timeout=2.0)
    for t in compute_threads:
        t.join(timeout=10.0)
    writer_q.join()
    writer_thread.join(timeout=10.0)

    elapsed_total = time.monotonic() - pipeline_start_time

    if state["writer_failed"]:
        if job_key and update_job_status_fn is not None:
            update_job_status_fn(
                job_key, "failed", progress=0,
                message=f"Indicator sync failed: {state['writer_error']}",
            )
        raise RuntimeError(
            f"parallel_indicator_sync writer failed: {state['writer_error']}"
        ) from state["writer_error"]

    return {
        "success": enqueued,
        "failed": total - enqueued,
        "rows_written": state["rows_written"],
        "elapsed_s": elapsed_total,
    }

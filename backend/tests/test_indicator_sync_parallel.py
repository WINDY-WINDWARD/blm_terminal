"""Tests for `parallel_indicator_sync` — the 3-compute + 1-writer topology.

These tests use in-memory queues and stub prepare/flush callables so they
exercise the threading topology without needing a real database.  The real
DB-touching paths (`prepare_daily_indicator_updates`, `flush_daily_indicator_updates`,
etc.) are covered by the parity test and runtime smoke tests.

The function under test lives in `app.services.parallel_sync` (a small
module with no transitive dependencies) so this test imports in <1s.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.parallel_sync import parallel_indicator_sync  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prepare_fn(items_to_sleep: set | None = None, sleep_s: float = 0.0,
                     raise_for: set | None = None):
    """Return a stub `prepare_fn` that records its inputs and outputs.

    - `items_to_sleep` (set of `*args` tuples): simulate slow compute for these.
    - `sleep_s`: sleep duration for slow items.
    - `raise_for` (set of `*args` tuples): raise RuntimeError for these.
    """
    items_to_sleep = items_to_sleep or set()
    raise_for = raise_for or set()
    seen: list[tuple] = []
    seen_lock = threading.Lock()

    def _fn(*args):
        with seen_lock:
            seen.append(args)
        if args in raise_for:
            raise RuntimeError(f"simulated failure for {args}")
        if args in items_to_sleep:
            time.sleep(sleep_s)
        # Each item produces a list with one "update dict" (key=id)
        return [{"id": hash(args), "x": 1}]

    _fn.seen = seen
    return _fn


def _make_flush_fn(fail_after: int | None = None, fail_with: Exception | None = None):
    """Return a stub `flush_fn` that records the number of rows it was asked to write."""
    written: list[int] = []
    written_lock = threading.Lock()
    call_count = [0]
    count_lock = threading.Lock()

    def _fn(updates):
        with count_lock:
            call_count[0] += 1
            n_calls = call_count[0]
        if fail_after is not None and n_calls > fail_after:
            if fail_with is not None:
                raise fail_with
            raise RuntimeError("simulated flush failure")
        with written_lock:
            written.append(len(updates))
        return len(updates)

    _fn.written = written
    _fn.call_count = lambda: call_count[0]
    return _fn


@pytest.fixture
def shutdown_event():
    e = threading.Event()
    yield e
    e.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_items_returns_empty_summary(shutdown_event):
    """No items: should short-circuit and return a zero summary without spawning threads."""
    summary = parallel_indicator_sync(
        items=[],
        prepare_fn=_make_prepare_fn(),
        flush_fn=_make_flush_fn(),
        shutdown_event=shutdown_event,
        job_key="job.test",
    )
    assert summary == {"success": 0, "failed": 0, "rows_written": 0, "elapsed_s": 0.0}


def test_typical_run_processes_all_items(shutdown_event):
    """100 items, 3 compute workers, 1 writer.  All items should be processed."""
    items = [(f"SYM{i:03d}",) for i in range(100)]
    prepare_fn = _make_prepare_fn()
    flush_fn = _make_flush_fn()

    summary = parallel_indicator_sync(
        items=items,
        prepare_fn=prepare_fn,
        flush_fn=flush_fn,
        shutdown_event=shutdown_event,
        job_key="job.test",
    )

    assert summary["success"] == 100
    assert summary["failed"] == 0
    assert summary["rows_written"] == 100
    assert len(prepare_fn.seen) == 100
    assert set(prepare_fn.seen) == set(items)
    assert flush_fn.call_count() >= 2
    assert sum(flush_fn.written) == 100


def test_intraday_items_with_interval_arg(shutdown_event):
    """Items with two args (symbol, interval) — should be passed through correctly."""
    items = [(f"SYM{i}", "1h") for i in range(20)]
    prepare_fn = _make_prepare_fn()
    flush_fn = _make_flush_fn()

    summary = parallel_indicator_sync(
        items=items,
        prepare_fn=prepare_fn,
        flush_fn=flush_fn,
        shutdown_event=shutdown_event,
        job_key="job.test",
    )

    assert summary["success"] == 20
    assert summary["rows_written"] == 20
    for arg in prepare_fn.seen:
        assert len(arg) == 2
        assert arg[1] == "1h"


def test_compute_worker_failure_does_not_poison_run(shutdown_event):
    """If 10 of 50 items raise in the prepare_fn, the other 40 should still complete."""
    items = [(f"SYM{i:02d}",) for i in range(50)]
    failing = {items[i] for i in range(0, 50, 5)}  # 10 items fail
    prepare_fn = _make_prepare_fn(raise_for=failing)
    flush_fn = _make_flush_fn()

    summary = parallel_indicator_sync(
        items=items,
        prepare_fn=prepare_fn,
        flush_fn=flush_fn,
        shutdown_event=shutdown_event,
        job_key="job.test",
    )

    assert summary["success"] == 50
    assert summary["failed"] == 0
    assert summary["rows_written"] == 40
    assert len(prepare_fn.seen) == 50


def test_writer_failure_marks_run_failed(shutdown_event):
    """A flush_fn failure should raise and the run should be reported as failed."""
    items = [(f"SYM{i}",) for i in range(30)]
    prepare_fn = _make_prepare_fn()
    # fail_after=0 means the very first flush call raises.
    flush_fn = _make_flush_fn(fail_after=0, fail_with=RuntimeError("disk full"))

    with pytest.raises(RuntimeError, match="disk full"):
        parallel_indicator_sync(
            items=items,
            prepare_fn=prepare_fn,
            flush_fn=flush_fn,
            shutdown_event=shutdown_event,
            job_key="job.test",
        )


def test_shutdown_event_drains_queues(shutdown_event):
    """If `shutdown_event` is set mid-flight, the producer stops and queues drain cleanly.

    We force the producer to block on backpressure by using a tiny `queue_maxsize`
    (5) and a slow prepare_fn (50ms per item, 3 workers).  With 3 workers each
    holding 1 in-flight item, the producer fills the queue (5 items) in <50ms
    and then blocks on `compute_q.put`.  We trip shutdown while the producer
    is blocked, so it must stop enqueueing.
    """
    items = [(f"SYM{i:03d}",) for i in range(200)]
    slow = set(items)
    prepare_fn = _make_prepare_fn(items_to_sleep=slow, sleep_s=0.05)
    flush_fn = _make_flush_fn()

    def _trip_shutdown():
        time.sleep(0.15)
        shutdown_event.set()

    threading.Thread(target=_trip_shutdown, daemon=True).start()

    summary = parallel_indicator_sync(
        items=items,
        prepare_fn=prepare_fn,
        flush_fn=flush_fn,
        shutdown_event=shutdown_event,
        job_key="job.test",
        queue_maxsize=5,  # force backpressure
        heartbeat_every_s=60.0,
        progress_every=1_000_000,
    )

    # With queue_maxsize=5 and 3 in-flight workers, at most ~8 items can be
    # in flight at any moment.  Shutdown at 150ms should stop the producer
    # long before all 200 items are enqueued.
    assert summary["success"] < 200, f"producer didn't honor shutdown: {summary}"
    assert summary["failed"] > 0
    assert summary["rows_written"] <= summary["success"]


def test_thread_count_is_hardcoded(shutdown_event):
    """The helper should start exactly 3 compute threads + 1 writer thread.

    We assert by snapshotting the active thread names mid-run via a slow
    prepare_fn that records `threading.enumerate()` while it runs.
    """
    items = [(f"SYM{i:03d}",) for i in range(120)]
    seen_thread_names: set[str] = set()
    seen_lock = threading.Lock()

    def _slow_prepare(*args):
        with seen_lock:
            for t in threading.enumerate():
                seen_thread_names.add(t.name)
        time.sleep(0.01)
        return [{"id": 1}]

    flush_fn = _make_flush_fn()

    parallel_indicator_sync(
        items=items,
        prepare_fn=_slow_prepare,
        flush_fn=flush_fn,
        shutdown_event=shutdown_event,
        job_key="job.test",
        heartbeat_every_s=60.0,
        progress_every=1_000_000,
    )

    compute_names = sorted(n for n in seen_thread_names if n.startswith("indicator_compute_"))
    assert len(compute_names) == 3, \
        f"expected exactly 3 indicator_compute_* threads, saw: {compute_names}"
    assert "indicator_writer" in seen_thread_names, \
        f"no indicator_writer thread seen; active: {sorted(seen_thread_names)}"

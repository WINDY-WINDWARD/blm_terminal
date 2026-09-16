"""Priority write queue for SQLite — serialises all non-critical writes
through a single raw sqlite3 connection to eliminate the EXCLUSIVE-lock
contention that causes ``database is locked`` during startup.

Only used for:
- ``api_cache`` rows (persistent_cache bulk writes)
- ``jobs`` table progress updates (throttled — see runner.py Phase 2)

NOT used for:
- ORM-managed tables with FK relationships (stock_universe, watchlists, etc.)
- Reads — the existing async NullPool + sync QueuePool read paths are unchanged.

Usage::

    from app.services.write_queue import enqueue_api_cache, enqueue_write

    # Fire-and-forget API cache write (coalesced, batched)
    enqueue_api_cache(key, json_payload, created_at, expires_at)

    # Generic write (for jobs or other single-row updates)
    enqueue_write(prio=0, fn=my_update_fn, arg1, arg2, kw=val)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import os
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority constants (lower = higher priority)
# ---------------------------------------------------------------------------
PRIO_UI_ACTION = -1    # UI mutations (watchlist add/remove, layouts, notifications, trades)
PRIO_JOBS = 0          # progress bar updates — near-real-time for UI poll
PRIO_API_CACHE = 1     # screener / iinvest / morningstar cache writes
PRIO_NOTIFICATIONS = 2 # notification + global_scan rows
PRIO_BULK_DATA = 3     # ticker_daily, intraday, stock_universe bulk inserts, news crawl

_MAX_QUEUE = 5000
_BATCH_SIZE = 50
_FLUSH_INTERVAL = 0.2  # seconds
_LOCK_RETRY_SLEEP = 0.05  # seconds on SQLITE_BUSY during BEGIN IMMEDIATE
_AGING_THRESHOLD = 2.0  # seconds before prio 3 bumps to 1

# ---------------------------------------------------------------------------
# DB-stats alert thresholds (silent — surfaced only in Jobs → DB Stats)
# ---------------------------------------------------------------------------
_ALERT_OCCUPANCY_WARN_PCT = 70.0   # queue_size / _MAX_QUEUE * 100
_ALERT_OCCUPANCY_CRIT_PCT = 90.0
_ALERT_EXEC_MS_WARN = 2000.0       # single batch execution time
_ALERT_QUEUE_WAIT_MS_WARN = 5000.0  # enqueue → execution wait
_ALERT_COOLDOWN_S = 60.0           # per alert-type suppression window
_ALERT_HISTORY_MAX = 200           # in-memory ring (plus persisted table)
_BATCH_RING_MAX = 300              # per-batch samples for latency/throughput
_THROUGHPUT_WINDOW_S = 60.0        # sliding window for records/min
_HISTORY_BUCKET_S = 10.0           # history bucket width for sparklines
_HISTORY_BUCKETS = 30              # 30 × 10s = 5 minutes

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def _write_queue_enabled() -> bool:
    """Return True unless the feature flag is explicitly disabled."""
    return os.getenv("BLM_WRITE_QUEUE_DISABLED", "").strip() not in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_seq_lock = threading.Lock()
_seq_counter = 0

_pq: queue.PriorityQueue[tuple[int, int, tuple[Callable, tuple, dict]]] = queue.PriorityQueue(maxsize=_MAX_QUEUE)
_shutdown_event = threading.Event()
_writer_thread: threading.Thread | None = None
_writer_lock = threading.Lock()

# API cache coalescing — only the latest payload per key is flushed
_api_cache_lock = threading.Lock()
_pending_api_cache: dict[str, tuple[str, float, float]] = {}  # key -> (payload, created, expires)
_api_flush_pending = False
_pending_jobs: dict[str, tuple[Callable, tuple, dict]] = {}  # job_key -> (fn, args, kwargs)
_jobs_lock = threading.Lock()
_jobs_flush_pending = False

# ---------------------------------------------------------------------------
# DB-stats telemetry (all in-memory; hot path performs zero SQL so stats
# collection can never block or contend with real DB operations)
# ---------------------------------------------------------------------------
_metrics_lock = threading.Lock()
_metrics_counters: dict[str, int] = {
    "enqueued": 0,
    "executed": 0,
    "dropped": 0,
}
_metrics_per_prio: dict[int, dict[str, int]] = {}  # prio -> {"enqueued": n, "executed": n}
# Per-batch samples: (completed_ts_monotonic, exec_ms, items, avg_wait_ms)
_batch_ring: Any = None  # collections.deque(maxlen=_BATCH_RING_MAX), lazy
# Completion events for records/min: (completed_ts_monotonic, items)
_completion_ring: Any = None  # collections.deque(maxlen=2048), lazy
# Alert rings + cooldowns
_alert_ring: Any = None  # collections.deque(maxlen=_ALERT_HISTORY_MAX), lazy
_alert_cooldowns: dict[str, float] = {}  # alert_type -> last monotonic fire ts
_writer_started_ts: float | None = None


def _batch_deque():
    global _batch_ring  # noqa: PLW0603
    if _batch_ring is None:
        import collections
        _batch_ring = collections.deque(maxlen=_BATCH_RING_MAX)
    return _batch_ring


def _completion_deque():
    global _completion_ring  # noqa: PLW0603
    if _completion_ring is None:
        import collections
        _completion_ring = collections.deque(maxlen=2048)
    return _completion_ring


def _alert_deque():
    global _alert_ring  # noqa: PLW0603
    if _alert_ring is None:
        import collections
        _alert_ring = collections.deque(maxlen=_ALERT_HISTORY_MAX)
    return _alert_ring


def _record_enqueue(prio: int) -> None:
    with _metrics_lock:
        _metrics_counters["enqueued"] += 1
        bucket = _metrics_per_prio.setdefault(prio, {"enqueued": 0, "executed": 0})
        bucket["enqueued"] += 1


def _record_drop() -> None:
    with _metrics_lock:
        _metrics_counters["dropped"] += 1


def _record_batch_completed(exec_ms: float, items: int, avg_wait_ms: float) -> None:
    now = time.monotonic()
    with _metrics_lock:
        _batch_deque().append((now, exec_ms, items, avg_wait_ms))
        _completion_deque().append((now, items))


def _next_seq() -> int:
    global _seq_counter  # noqa: PLW0603
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


# ---------------------------------------------------------------------------
# Public API — enqueue
# ---------------------------------------------------------------------------

def enqueue_write(prio: int, fn: Callable, *args: Any, **kwargs: Any) -> bool:
    """Enqueue a generic write.  ``fn`` will be called with (*args, **kwargs)
    inside the single writer thread.

    ``prio`` should be one of ``PRIO_*`` constants.
    Returns True if enqueued, False if dropped (caller should not record _last_emit).
    """
    if not _write_queue_enabled():
        # Bypass: execute synchronously in the calling thread.
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.debug("write_queue bypass: fn %s failed", getattr(fn, "__name__", fn), exc_info=True)
        return True

    # PRIO_JOBS is coalesced — keep only latest per job_key
    if prio == PRIO_JOBS:
        job_key = args[0] if args else kwargs.get("job_key", "")
        with _jobs_lock:
            _pending_jobs[job_key] = (fn, args, kwargs)
        # Dedup sentinel: only enqueue if none pending
        global _jobs_flush_pending
        with _jobs_lock:
            if _jobs_flush_pending:
                return True
            _jobs_flush_pending = True
        seq = _next_seq()
        enqueue_ts = time.monotonic()
        try:
            _pq.put((PRIO_JOBS, seq, (_flush_pending_jobs, (), {}, enqueue_ts)), timeout=1.0)
            _record_enqueue(PRIO_JOBS)
            return True
        except queue.Full:
            with _jobs_lock:
                _jobs_flush_pending = False
            # Jobs must not be lost — keep in pending dict, will flush on next successful put or idle timeout
            logger.warning("write_queue full, coalesced jobs pending (%d keys) will flush on next cycle", len(_pending_jobs))
            return True  # still considered enqueued (coalesced)

    seq = _next_seq()
    enqueue_ts = time.monotonic()
    try:
        _pq.put_nowait((prio, seq, (fn, args, kwargs, enqueue_ts)))
        _record_enqueue(prio)
        return True
    except queue.Full:
        logger.warning("write_queue full, dropping write for %s", getattr(fn, "__name__", fn))
        _record_drop()
        _maybe_fire_alert(
            "queue_drop_critical",
            "critical",
            f"Write queue full ({_MAX_QUEUE}) — dropped write for {getattr(fn, '__name__', fn)}",
        )
        return False


async def enqueue_write_async(prio: int, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Enqueue a write function to run serially in the writer thread, and await its completion.
    Returns the return value of ``fn``. If ``fn`` raises an exception, it is re-raised here.
    Supports both sync callables and functions taking a session/raw args.
    """
    if not _write_queue_enabled():
        return fn(*args, **kwargs)

    loop = asyncio.get_running_loop()
    future: concurrent.futures.Future = concurrent.futures.Future()

    def _wrapper(*w_args, **w_kwargs):
        try:
            res = fn(*w_args, **w_kwargs)
            future.set_result(res)
        except Exception as exc:
            future.set_exception(exc)

    seq = _next_seq()
    enqueue_ts = time.monotonic()
    # High priority items wait up to 10 seconds to enter queue
    put_timeout = 10.0 if prio <= PRIO_UI_ACTION else 2.0
    try:
        _pq.put((prio, seq, (_wrapper, args, kwargs, enqueue_ts)), timeout=put_timeout)
        _record_enqueue(prio)
    except queue.Full:
        _record_drop()
        _maybe_fire_alert(
            "queue_drop_critical",
            "critical",
            f"Write queue full ({_MAX_QUEUE}) — rejected async write for {getattr(fn, '__name__', fn)}",
        )
        raise RuntimeError(f"write_queue full, rejected async write for {getattr(fn, '__name__', fn)}")

    return await asyncio.wrap_future(future)


def enqueue_write_sync(prio: int, fn: Callable, *args: Any, timeout: float = 30.0, **kwargs: Any) -> Any:
    """Synchronously enqueue and block until ``fn`` completes in the writer thread.
    Returns result or re-raises exception.
    """
    if not _write_queue_enabled():
        return fn(*args, **kwargs)

    future: concurrent.futures.Future = concurrent.futures.Future()

    def _wrapper(*w_args, **w_kwargs):
        try:
            res = fn(*w_args, **w_kwargs)
            future.set_result(res)
        except Exception as exc:
            future.set_exception(exc)

    seq = _next_seq()
    enqueue_ts = time.monotonic()
    put_timeout = 10.0 if prio <= PRIO_UI_ACTION else 2.0
    try:
        _pq.put((prio, seq, (_wrapper, args, kwargs, enqueue_ts)), timeout=put_timeout)
        _record_enqueue(prio)
    except queue.Full:
        _record_drop()
        _maybe_fire_alert(
            "queue_drop_critical",
            "critical",
            f"Write queue full ({_MAX_QUEUE}) — rejected sync write for {getattr(fn, '__name__', fn)}",
        )
        raise
    return future.result(timeout=timeout)


def enqueue_api_cache(key: str, payload: str, created: float, expires: float) -> None:
    """Coalesced API cache write — keeps only the latest payload per key."""
    if not _write_queue_enabled():
        # Bypass: direct SQLite write (legacy path).
        _flush_single_api_cache(key, payload, created, expires)
        return

    with _api_cache_lock:
        _pending_api_cache[key] = (payload, created, expires)

    # Dedup sentinel: only enqueue if none pending
    global _api_flush_pending
    with _api_cache_lock:
        if _api_flush_pending:
            return
        _api_flush_pending = True
    seq = _next_seq()
    enqueue_ts = time.monotonic()
    try:
        _pq.put_nowait((PRIO_API_CACHE, seq, (_flush_pending_api_cache, (), {}, enqueue_ts)))
        _record_enqueue(PRIO_API_CACHE)
    except queue.Full:
        with _api_cache_lock:
            _api_flush_pending = False
        logger.debug("write_queue: api_cache queue full, pending keys will flush on next put")


def flush_write_queue(timeout: float = 5.0) -> None:
    """Block until the queue and pending coalesces are drained."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _api_cache_lock:
            api_pending = len(_pending_api_cache)
        with _jobs_lock:
            jobs_pending = len(_pending_jobs)
        if _pq.empty() and api_pending == 0 and jobs_pending == 0:
            # Give writer one flush cycle to finish batch commit
            time.sleep(0.2)
            with _api_cache_lock:
                api_pending = len(_pending_api_cache)
            with _jobs_lock:
                jobs_pending = len(_pending_jobs)
            if _pq.empty() and api_pending == 0 and jobs_pending == 0:
                break
        time.sleep(0.05)


def get_stats() -> dict[str, Any]:
    """Return queue health stats for the /api/py/write-queue/stats endpoint."""
    with _api_cache_lock:
        pending = len(_pending_api_cache)
    with _jobs_lock:
        jobs_pending = len(_pending_jobs)
    return {
        "queue_size": _pq.qsize(),
        "pending_api_cache_keys": pending,
        "pending_jobs_keys": jobs_pending,
        "writer_alive": _writer_thread.is_alive() if _writer_thread else False,
        "shutdown_requested": _shutdown_event.is_set(),
    }


# ---------------------------------------------------------------------------
# DB-stats telemetry: snapshots, alerts, aggregation (all lock-light, zero SQL
# on the hot path — alert persistence runs on the writer thread itself)
# ---------------------------------------------------------------------------

def _peek_queue_snapshot() -> dict[str, Any]:
    """Capture queue occupancy + per-priority breakdown without blocking.

    Peeks the heap under a non-blocking trylock. If the writer thread holds
    the mutex, returns ``contended: True`` with just the atomic size rather
    than waiting — stats must never stall real DB work.
    """
    size = _pq.qsize()
    snapshot: dict[str, Any] = {
        "queue_size": size,
        "queue_max": _MAX_QUEUE,
        "occupancy_pct": round(size / _MAX_QUEUE * 100, 2) if _MAX_QUEUE else 0.0,
        "contended": False,
    }
    mutex = getattr(_pq, "mutex", None)
    heap = getattr(_pq, "queue", None)
    if mutex is None or heap is None or not mutex.acquire(blocking=False):
        snapshot["contended"] = True
        return snapshot
    try:
        per_prio: dict[str, int] = {}
        oldest_wait_ms: float | None = None
        now = time.monotonic()
        for entry in heap:
            try:
                prio, _seq, item = entry
                _fn, _args, _kwargs, enqueue_ts = item
            except (ValueError, TypeError):
                continue
            key = str(prio)
            per_prio[key] = per_prio.get(key, 0) + 1
            waited_ms = (now - enqueue_ts) * 1000
            if oldest_wait_ms is None or waited_ms > oldest_wait_ms:
                oldest_wait_ms = waited_ms
        snapshot["per_prio"] = per_prio
        snapshot["oldest_wait_ms"] = round(oldest_wait_ms, 1) if oldest_wait_ms is not None else 0.0
    finally:
        try:
            mutex.release()
        except Exception:
            pass
    return snapshot


def _get_db_file_sizes() -> dict[str, int]:
    """DB + WAL + SHM sizes via stat() — no SQLite lock is ever taken."""
    sizes = {"db_bytes": 0, "wal_bytes": 0, "shm_bytes": 0}
    try:
        db_path = _get_db_path()
    except Exception:
        return sizes
    for key, suffix in (("db_bytes", ""), ("wal_bytes", "-wal"), ("shm_bytes", "-shm")):
        try:
            sizes[key] = os.path.getsize(db_path + suffix)
        except OSError:
            pass
    sizes["total_bytes"] = sizes["db_bytes"] + sizes["wal_bytes"] + sizes["shm_bytes"]
    return sizes


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _aggregate_metrics() -> dict[str, Any]:
    """Fold the batch/completion rings into throughput + latency figures."""
    now = time.monotonic()
    with _metrics_lock:
        batches = list(_batch_deque())
        completions = list(_completion_deque())
        counters = dict(_metrics_counters)
        per_prio = {str(k): dict(v) for k, v in _metrics_per_prio.items()}
    window_start = now - _THROUGHPUT_WINDOW_S
    recent_items = sum(c for ts, c in completions if ts >= window_start)
    records_per_min = round(recent_items / (_THROUGHPUT_WINDOW_S / 60.0), 1)
    recent_batches = [b for b in batches if b[0] >= window_start]
    batches_per_min = round(len(recent_batches) / (_THROUGHPUT_WINDOW_S / 60.0), 1)
    exec_mss = sorted(b[1] for b in batches)
    waits = [b[3] for b in batches if b[3] is not None]
    return {
        "counters": counters,
        "per_prio": per_prio,
        "records_per_min": records_per_min,
        "batches_per_min": batches_per_min,
        "avg_latency_ms": round(sum(exec_mss) / len(exec_mss), 2) if exec_mss else 0.0,
        "p95_latency_ms": round(_percentile(exec_mss, 95), 2),
        "avg_queue_wait_ms": round(sum(waits) / len(waits), 1) if waits else 0.0,
        "batches_sampled": len(batches),
    }


def _build_history() -> list[dict[str, Any]]:
    """Downsample the batch ring into 10s buckets covering the last 5 min."""
    now = time.monotonic()
    with _metrics_lock:
        batches = list(_batch_deque())
    buckets: dict[int, dict[str, Any]] = {}
    for ts, exec_ms, items, wait_ms in batches:
        age = now - ts
        if age < 0 or age > _HISTORY_BUCKETS * _HISTORY_BUCKET_S:
            continue
        idx = int(age // _HISTORY_BUCKET_S)
        b = buckets.setdefault(idx, {"exec": [], "items": 0, "waits": []})
        b["exec"].append(exec_ms)
        b["items"] += items
        if wait_ms is not None:
            b["waits"].append(wait_ms)
    out = []
    for idx in range(_HISTORY_BUCKETS - 1, -1, -1):
        b = buckets.get(idx)
        bucket_ts = now - idx * _HISTORY_BUCKET_S
        if not b:
            out.append({"ts": round(bucket_ts, 1), "occupancy_pct": None,
                        "records_per_min": 0.0, "avg_latency_ms": 0.0})
            continue
        out.append({
            "ts": round(bucket_ts, 1),
            "occupancy_pct": None,  # occupancy is point-in-time; see live.occupancy
            "records_per_min": round(b["items"] / (_HISTORY_BUCKET_S / 60.0), 1),
            "avg_latency_ms": round(sum(b["exec"]) / len(b["exec"]), 2),
        })
    return out


def get_db_stats() -> dict[str, Any]:
    """Full live snapshot for the Jobs → DB Stats tab (cheap, non-blocking)."""
    snap = _peek_queue_snapshot()
    metrics = _aggregate_metrics()
    files = _get_db_file_sizes()
    uptime_s: float | None = None
    if _writer_started_ts is not None:
        uptime_s = round(time.monotonic() - _writer_started_ts, 1)
    with _metrics_lock:
        recent_alerts = [
            {"ts": a["ts"], "type": a["type"], "severity": a["severity"]}
            for a in list(_alert_deque())[-10:]
        ]
    return {
        "occupancy": {
            "size": snap["queue_size"],
            "max": snap["queue_max"],
            "pct": snap["occupancy_pct"],
        },
        "queue_detail": snap,
        "throughput": metrics,
        "db": files,
        "writer": {
            "alive": _writer_thread.is_alive() if _writer_thread else False,
            "uptime_s": uptime_s,
        },
        "recent_alerts": recent_alerts,
        "history": _build_history(),
    }


def get_recent_alerts(limit: int = 100) -> list[dict[str, Any]]:
    """In-memory alert ring (newest last); the persisted table is authoritative."""
    with _metrics_lock:
        items = list(_alert_deque())
    return items[-limit:]


def _persist_alert(alert: dict[str, Any]) -> None:
    """Persist one alert row + 7-day retention prune.

    MUST only be called from the single writer thread (or a context that owns
    the DB write lock) so it never contends with real writes.
    """
    try:
        import json as _json

        from app.models.db_alert import DbAlert

        db_path = _get_db_path()
        conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                """INSERT INTO db_alerts (ts, type, severity, message, snapshot_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (alert["ts"], alert["type"], alert["severity"],
                 alert["message"], _json.dumps(alert["snapshot"])),
            )
            # Retention: keep 7 days.
            cursor.execute(
                "DELETE FROM db_alerts WHERE ts < ?",
                (alert["ts"] - 7 * 24 * 3600,),
            )
            cursor.execute("COMMIT")
        except Exception:
            logger.debug("write_queue: db_alert persist failed", exc_info=True)
            try:
                cursor.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            conn.close()
    except Exception:
        logger.debug("write_queue: db_alert persist setup failed", exc_info=True)


def _maybe_fire_alert(alert_type: str, severity: str, message: str) -> None:
    """Record a silent alert event with a frozen queue snapshot.

    Safe to call from ANY thread (enqueue paths included): snapshotting is
    trylock-guarded and persistence is deferred — if called off the writer
    thread, the alert is queued for the writer to persist on its next batch
    so alert writes never contend with real DB operations.
    """
    now_wall = time.time()
    now_mono = time.monotonic()
    with _metrics_lock:
        last = _alert_cooldowns.get(alert_type, 0.0)
        if now_mono - last < _ALERT_COOLDOWN_S:
            return
        _alert_cooldowns[alert_type] = now_mono
    snapshot = _peek_queue_snapshot()
    metrics = _aggregate_metrics()
    files = _get_db_file_sizes()
    snapshot["records_per_min"] = metrics["records_per_min"]
    snapshot["p95_latency_ms"] = metrics["p95_latency_ms"]
    snapshot["db_total_bytes"] = files["total_bytes"]
    alert = {
        "id": f"{int(now_wall * 1000)}-{alert_type}",
        "ts": now_wall,
        "type": alert_type,
        "severity": severity,
        "message": message,
        "snapshot": snapshot,
    }
    with _metrics_lock:
        _alert_deque().append(alert)
    if threading.current_thread() is _writer_thread:
        _persist_alert(alert)
    else:
        # Defer persistence to the writer thread via a no-op-prio sentinel
        # item carrying the alert payload (executes inline in next batch).
        try:
            _pq.put_nowait((PRIO_JOBS, _next_seq(), (_persist_deferred_alert, (alert,), {}, now_mono)))
        except queue.Full:
            logger.debug("write_queue: alert persist deferred item dropped (queue full)")


def _persist_deferred_alert(alert: dict[str, Any]) -> None:
    """Writer-thread trampoline for off-thread alert persistence."""
    _persist_alert(alert)


def _evaluate_threshold_alerts(exec_ms: float, avg_wait_ms: float) -> None:
    """Fire occupancy/latency alerts after each writer batch (writer thread)."""
    snap = _peek_queue_snapshot()
    pct = snap["occupancy_pct"]
    if pct >= _ALERT_OCCUPANCY_CRIT_PCT:
        _maybe_fire_alert(
            "queue_occupancy_critical", "critical",
            f"Write queue {snap['queue_size']}/{snap['queue_max']} ({pct:.1f}%)",
        )
    elif pct >= _ALERT_OCCUPANCY_WARN_PCT:
        _maybe_fire_alert(
            "queue_occupancy_warn", "warning",
            f"Write queue {snap['queue_size']}/{snap['queue_max']} ({pct:.1f}%)",
        )
    if exec_ms >= _ALERT_EXEC_MS_WARN:
        _maybe_fire_alert(
            "batch_latency_spike", "warning",
            f"Write batch took {exec_ms:.0f}ms (threshold {_ALERT_EXEC_MS_WARN:.0f}ms)",
        )
    if avg_wait_ms >= _ALERT_QUEUE_WAIT_MS_WARN:
        _maybe_fire_alert(
            "queue_wait_spike", "warning",
            f"Avg enqueue→execute wait {avg_wait_ms:.0f}ms (threshold {_ALERT_QUEUE_WAIT_MS_WARN:.0f}ms)",
        )


# ---------------------------------------------------------------------------
# Internal — SQLite writer
# ---------------------------------------------------------------------------

def _apply_sqlite_pragmas(cursor: sqlite3.Cursor) -> None:
    """Apply the same pragmas as database.py to the raw connection."""
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA wal_autocheckpoint=1000")
    cursor.execute("PRAGMA journal_size_limit=67108864")
    cursor.execute("PRAGMA cache_size=-65536")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=268435456")
    cursor.execute("PRAGMA foreign_keys=ON")


def _get_db_path() -> str:
    """Resolve the SQLite database path — mirrors ``settings.db_path``."""
    from app.config import settings
    return settings.db_path


def _flush_pending_api_cache() -> None:
    """Flush all coalesced api_cache writes in one batch."""
    global _api_flush_pending
    with _api_cache_lock:
        items = dict(_pending_api_cache)
        _pending_api_cache.clear()
        _api_flush_pending = False

    if not items:
        return

    t0 = time.monotonic()
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    try:
        cursor = conn.cursor()
        _apply_sqlite_pragmas(cursor)

        # BEGIN IMMEDIATE — acquires RESERVED lock immediately so we fail
        # fast if another writer holds EXCLUSIVE.
        for attempt in range(5):
            try:
                cursor.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError:
                if attempt < 4:
                    time.sleep(_LOCK_RETRY_SLEEP * (attempt + 1))
                else:
                    logger.warning("write_queue: BEGIN IMMEDIATE failed after 5 attempts, dropping %d api_cache items", len(items))
                    return

        rows = []
        for key, (payload, created, expires) in items.items():
            # Convert float epochs to ISO strings if needed (SQLAlchemy DateTime expects string/datetime)
            if isinstance(created, float):
                from datetime import datetime, timezone
                created = datetime.fromtimestamp(created, tz=timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
            if isinstance(expires, float):
                from datetime import datetime, timezone
                expires = datetime.fromtimestamp(expires, tz=timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
            rows.append((key, payload, created, expires))

        cursor.executemany(
            """INSERT INTO api_cache (key, payload, created_at, expires_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 payload = excluded.payload,
                 created_at = excluded.created_at,
                 expires_at = excluded.expires_at""",
            rows,
        )
        cursor.execute("COMMIT")
        logger.debug("write_queue: flushed %d api_cache rows", len(rows))
        exec_ms = (time.monotonic() - t0) * 1000
        with _metrics_lock:
            bucket = _metrics_per_prio.setdefault(PRIO_API_CACHE, {"enqueued": 0, "executed": 0})
            bucket["executed"] += len(rows)
            _metrics_counters["executed"] += len(rows)
        _record_batch_completed(exec_ms, len(rows), 0.0)
        _evaluate_threshold_alerts(exec_ms, 0.0)
    except Exception:
        logger.exception("write_queue: api_cache flush failed")
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
    finally:
        conn.close()


def _flush_pending_jobs() -> None:
    """Flush all coalesced jobs updates — one latest per job_key."""
    global _jobs_flush_pending
    with _jobs_lock:
        items = dict(_pending_jobs)
        _pending_jobs.clear()
        _jobs_flush_pending = False
    if not items:
        return
    for job_key, (fn, args, kwargs) in items.items():
        try:
            fn(*args, **kwargs)
        except Exception:
            logger.debug("write_queue: jobs flush item %s failed", job_key, exc_info=True)
    logger.debug("write_queue: flushed %d jobs", len(items))


def _flush_single_api_cache(key: str, payload: str, created: float, expires: float) -> None:
    """Direct single-key write (bypass mode)."""
    # Normalize float epochs to SQLite-compatible datetime strings
    if isinstance(created, float):
        from datetime import datetime, timezone
        created = datetime.fromtimestamp(created, tz=timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
    if isinstance(expires, float):
        from datetime import datetime, timezone
        expires = datetime.fromtimestamp(expires, tz=timezone.utc).replace(tzinfo=None).isoformat(sep=' ')
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    try:
        cursor = conn.cursor()
        _apply_sqlite_pragmas(cursor)
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """INSERT INTO api_cache (key, payload, created_at, expires_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 payload = excluded.payload,
                 created_at = excluded.created_at,
                 expires_at = excluded.expires_at""",
            (key, payload, created, expires),
        )
        cursor.execute("COMMIT")
    except Exception:
        logger.debug("write_queue: single api_cache write failed for %s", key, exc_info=True)
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
    finally:
        conn.close()


def _writer_loop() -> None:
    """Main writer loop — runs in a single daemon thread."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    try:
        cursor = conn.cursor()
        _apply_sqlite_pragmas(cursor)

        last_flush = time.monotonic()
        batch: list[tuple[Callable, tuple, dict]] = []
        batch_waits_ms: list[float] = []

        def _take(prio: int, item: tuple, now: float) -> None:
            fn, args, kwargs, enqueue_ts = item
            effective_prio = prio
            if prio == PRIO_BULK_DATA:
                waited = now - enqueue_ts
                if waited > _AGING_THRESHOLD:
                    effective_prio = PRIO_API_CACHE
            batch.append((fn, args, kwargs, effective_prio))
            batch_waits_ms.append(max(0.0, (now - enqueue_ts) * 1000))

        def _flush_batch() -> None:
            nonlocal last_flush
            if not batch:
                return
            # Sort batch by effective priority so higher-priority items execute first.
            # Keep waits aligned with their items through the sort.
            order = sorted(range(len(batch)), key=lambda i: batch[i][3])
            ordered = [batch[i] for i in order]
            ordered_waits = [batch_waits_ms[i] for i in order]
            _execute_batch(cursor, conn, ordered, ordered_waits)
            batch.clear()
            batch_waits_ms.clear()
            last_flush = time.monotonic()

        while not _shutdown_event.is_set():
            try:
                prio, seq, item = _pq.get(timeout=0.2)
            except queue.Empty:
                # No items — flush any pending coalesces
                _flush_pending_api_cache()
                _flush_pending_jobs()
                continue

            now = time.monotonic()
            _take(prio, item, now)

            # Drain additional items up to batch size (non-blocking)
            while len(batch) < _BATCH_SIZE:
                try:
                    ex_prio, _, extra = _pq.get_nowait()
                    _take(ex_prio, extra, time.monotonic())
                except queue.Empty:
                    break

            now = time.monotonic()
            should_flush = (
                len(batch) >= _BATCH_SIZE
                or (now - last_flush) >= _FLUSH_INTERVAL
            )

            if should_flush:
                _flush_batch()

        # Shutdown: drain remaining items
        while not _pq.empty():
            try:
                ex_prio, _, extra = _pq.get_nowait()
                fn, args, kwargs, _ts = extra
                batch.append((fn, args, kwargs, ex_prio))
                batch_waits_ms.append(0.0)
            except queue.Empty:
                break

        _flush_batch()

        # Final coalesced flushes
        _flush_pending_api_cache()
        _flush_pending_jobs()

    except Exception:
        logger.exception("write_queue: writer thread crashed")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _execute_batch(
    cursor: sqlite3.Cursor,
    conn: sqlite3.Connection,
    batch: list[tuple[Callable, tuple, dict, int]],
    waits_ms: list[float] | None = None,
) -> None:
    """Execute a batch of write callables.
    For standard callables, each callable can either execute raw SQL or manage its own
    connection/session safely. If the callable accepts a 'cursor' or 'conn' parameter,
    we pass it directly. Otherwise it runs cleanly inside the single serialized writer thread.

    ``waits_ms`` carries per-item enqueue→execute waits measured by the caller.
    Records batch telemetry for the DB-stats dashboard and evaluates alert
    thresholds afterwards.
    """
    t0 = time.monotonic()
    for fn, args, kwargs, _prio in batch:
        try:
            # Check if fn accepts cursor or conn
            sig = inspect.signature(fn)
            params = sig.parameters
            call_kwargs = dict(kwargs)
            if "cursor" in params and "cursor" not in call_kwargs:
                call_kwargs["cursor"] = cursor
            if "conn" in params and "conn" not in call_kwargs:
                call_kwargs["conn"] = conn
            fn(*args, **call_kwargs)
        except Exception:
            logger.debug("write_queue: item %s failed", getattr(fn, "__name__", fn), exc_info=True)
    exec_ms = (time.monotonic() - t0) * 1000
    with _metrics_lock:
        for _, _, _, eff_prio in batch:
            bucket = _metrics_per_prio.setdefault(eff_prio, {"enqueued": 0, "executed": 0})
            bucket["executed"] += 1
        _metrics_counters["executed"] += len(batch)
    avg_wait = sum(waits_ms) / len(waits_ms) if waits_ms else 0.0
    _record_batch_completed(exec_ms, len(batch), avg_wait)
    _evaluate_threshold_alerts(exec_ms, avg_wait)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def start_writer() -> None:
    """Start the single writer daemon thread.  Safe to call multiple times."""
    global _writer_thread, _writer_started_ts  # noqa: PLW0603
    with _writer_lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return
        _shutdown_event.clear()
        _writer_started_ts = time.monotonic()
        _writer_thread = threading.Thread(target=_writer_loop, daemon=True, name="write-queue-writer")
        _writer_thread.start()
        logger.info("write_queue: writer thread started")


def stop_writer(timeout: float = 10.0) -> None:
    """Signal the writer to stop and wait for it to drain."""
    global _writer_thread  # noqa: PLW0603
    _shutdown_event.set()
    flush_write_queue(timeout=timeout)
    with _writer_lock:
        if _writer_thread is not None:
            _writer_thread.join(timeout=timeout)
            if _writer_thread.is_alive():
                logger.warning("write_queue: writer thread did not exit within %.1fs", timeout)
            else:
                logger.info("write_queue: writer thread stopped cleanly")
            _writer_thread = None

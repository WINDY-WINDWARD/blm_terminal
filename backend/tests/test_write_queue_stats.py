"""Tests for write-queue DB-stats telemetry (no DB, no writer thread).

Covers: counter math, throughput/latency aggregation, alert threshold edges
(70/90%), cooldown dedup, snapshot structure, and the zero-SQL hot-path
guarantee (all metric recording paths perform no SQLAlchemy/SQLite calls).
"""

import time
from unittest.mock import patch

import pytest

import app.services.write_queue as wq


@pytest.fixture(autouse=True)
def _reset_telemetry():
    """Isolate metric state between tests."""
    with wq._metrics_lock:
        wq._metrics_counters.update({"enqueued": 0, "executed": 0, "dropped": 0})
        wq._metrics_per_prio.clear()
        wq._batch_deque().clear()
        wq._completion_deque().clear()
        wq._alert_deque().clear()
        wq._alert_cooldowns.clear()
    yield
    with wq._metrics_lock:
        wq._metrics_counters.update({"enqueued": 0, "executed": 0, "dropped": 0})
        wq._metrics_per_prio.clear()
        wq._batch_deque().clear()
        wq._completion_deque().clear()
        wq._alert_deque().clear()
        wq._alert_cooldowns.clear()


def _seed_batches(n=10, exec_ms=5.0, items=20, wait_ms=10.0):
    now = time.monotonic()
    with wq._metrics_lock:
        for i in range(n):
            ts = now - i
            wq._batch_deque().append((ts, exec_ms, items, wait_ms))
            wq._completion_deque().append((ts, items))


def test_counters_and_per_prio():
    wq._record_enqueue(3)
    wq._record_enqueue(3)
    wq._record_enqueue(-1)
    wq._record_drop()
    agg = wq._aggregate_metrics()
    assert agg["counters"] == {"enqueued": 3, "executed": 0, "dropped": 1}
    assert agg["per_prio"]["3"] == {"enqueued": 2, "executed": 0}
    assert agg["per_prio"]["-1"] == {"enqueued": 1, "executed": 0}


def test_throughput_records_per_min():
    # 10 batches × 20 items within the last 60s window → 200/min
    _seed_batches(n=10, items=20)
    agg = wq._aggregate_metrics()
    assert agg["records_per_min"] == 200.0
    assert agg["batches_per_min"] == 10.0
    assert agg["avg_latency_ms"] == 5.0
    assert agg["p95_latency_ms"] == 5.0
    assert agg["avg_queue_wait_ms"] == 10.0


def test_p95_spread():
    _seed_batches(n=9, exec_ms=10.0)
    now = time.monotonic()
    with wq._metrics_lock:
        wq._batch_deque().append((now, 100.0, 1, 0.0))
    agg = wq._aggregate_metrics()
    assert agg["p95_latency_ms"] > 10.0
    assert agg["p95_latency_ms"] <= 100.0


def test_occupancy_threshold_edges():
    """70.0 → warn, 90.0 → critical, just-below → silent."""
    fired = []

    def _capture(alert_type, severity, message):
        fired.append((alert_type, severity))

    with patch.object(wq, "_maybe_fire_alert", side_effect=_capture):
        with patch.object(wq, "_peek_queue_snapshot") as peek:
            # 69.9% → no occupancy alert (latency args below thresholds)
            peek.return_value = {"queue_size": 3495, "queue_max": 5000, "occupancy_pct": 69.9}
            wq._evaluate_threshold_alerts(10.0, 10.0)
            assert fired == []
            # 70.0% → warn
            peek.return_value = {"queue_size": 3500, "queue_max": 5000, "occupancy_pct": 70.0}
            wq._evaluate_threshold_alerts(10.0, 10.0)
            assert ("queue_occupancy_warn", "warning") in fired
            # 90.0% → critical (and not warn)
            fired.clear()
            peek.return_value = {"queue_size": 4500, "queue_max": 5000, "occupancy_pct": 90.0}
            wq._evaluate_threshold_alerts(10.0, 10.0)
            assert ("queue_occupancy_critical", "critical") in fired
            assert not any(t == "queue_occupancy_warn" for t, _ in fired)


def test_latency_and_wait_thresholds():
    fired = []
    with patch.object(wq, "_maybe_fire_alert", side_effect=lambda t, s, m: fired.append(t)):
        with patch.object(
            wq, "_peek_queue_snapshot",
            return_value={"queue_size": 10, "queue_max": 5000, "occupancy_pct": 0.2},
        ):
            wq._evaluate_threshold_alerts(2500.0, 100.0)
            assert "batch_latency_spike" in fired
            fired.clear()
            wq._evaluate_threshold_alerts(100.0, 6000.0)
            assert "queue_wait_spike" in fired


def test_alert_cooldown_dedupes():
    """Same alert type within 60s fires once; snapshot frozen per event."""
    import queue as _queue_mod

    with patch.object(wq, "_peek_queue_snapshot") as peek, \
         patch.object(wq, "_persist_alert") as persist:
        peek.return_value = {
            "queue_size": 4600, "queue_max": 5000, "occupancy_pct": 92.0,
            "contended": False,
        }
        wq._maybe_fire_alert("queue_occupancy_critical", "critical", "m1")
        wq._maybe_fire_alert("queue_occupancy_critical", "critical", "m2")
        alerts = wq.get_recent_alerts()
        assert len(alerts) == 1
        assert alerts[0]["message"] == "m1"
        assert alerts[0]["snapshot"]["queue_size"] == 4600
        # Off-writer-thread: persistence is deferred as a queue item for the
        # writer to execute (never inline, never blocking the caller).
        assert persist.call_count == 0
        deferred = []
        try:
            while True:
                _prio, _seq, item = wq._pq.get_nowait()
                deferred.append(item[0])
        except _queue_mod.Empty:
            pass
        assert wq._persist_deferred_alert in deferred
        # Simulate the writer executing it.
        wq._persist_deferred_alert(alerts[0])
        assert persist.call_count == 1


def test_snapshot_structure():
    with patch.object(wq, "_peek_queue_snapshot") as peek, \
         patch.object(wq, "_persist_alert"):
        peek.return_value = {
            "queue_size": 350, "queue_max": 5000, "occupancy_pct": 7.0,
            "contended": False, "per_prio": {"3": 350}, "oldest_wait_ms": 12.5,
        }
        wq._maybe_fire_alert("queue_occupancy_warn", "warning", "m")
        snap = wq.get_recent_alerts()[-1]["snapshot"]
        for key in ("queue_size", "queue_max", "occupancy_pct",
                    "records_per_min", "p95_latency_ms", "db_total_bytes"):
            assert key in snap, f"snapshot missing {key}"


def test_hot_path_performs_no_sql():
    """enqueue/record/snapshot paths must never touch SQL (would contend)."""
    import sqlite3

    with patch.object(sqlite3, "connect", side_effect=AssertionError("SQL touched!")):
        wq._record_enqueue(3)
        wq._record_drop()
        wq._record_batch_completed(5.0, 10, 2.0)
        wq._aggregate_metrics()
        wq._build_history()
        wq.get_db_stats()
        wq.get_recent_alerts()


def test_execute_batch_records_telemetry_and_alerts():
    """_execute_batch records exec/items/waits and evaluates thresholds."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    calls = []

    def _fn(cursor=None):
        calls.append(1)

    wq._execute_batch(cursor, conn, [(_fn, (), {}, 3)], waits_ms=[250.0])
    agg = wq._aggregate_metrics()
    assert agg["counters"]["executed"] == 1
    assert agg["per_prio"]["3"]["executed"] == 1
    assert agg["avg_queue_wait_ms"] == 250.0
    assert calls == [1]
    conn.close()


def test_history_buckets_cover_five_minutes():
    # 10 samples land in the most-recent 10s bucket: 100 items / 10s → 600/min
    _seed_batches(n=10, exec_ms=4.0, items=10)
    hist = wq._build_history()
    assert len(hist) == 30  # 30 × 10s buckets
    assert all(set(h) == {"ts", "occupancy_pct", "records_per_min", "avg_latency_ms"} for h in hist)
    assert hist[-1]["records_per_min"] == 600.0
    assert hist[-1]["avg_latency_ms"] == 4.0
    # Buckets are ordered oldest → newest
    assert hist[0]["ts"] < hist[-1]["ts"]

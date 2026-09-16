"""Tests for screener fundamentals helpers (market cap + net-profit YoY).

Pure-function tests — no network, no DB.
"""

from app.services.data_sync.fundamentals import compute_np_yoy, parse_mcap_cr
from app.services.nse_client_async import mcap_cr_from_trade_info


def _quarters(np_by_period: dict[str, float]) -> dict:
    """Build a _parse_all_quarters-shaped dict from {(year, month): np}."""
    out: dict = {}
    for (year, month), np_val in np_by_period.items():
        out.setdefault(str(year), {})[month] = {"Net Profit": str(np_val)}
    return out


def test_parse_mcap_cr_indian_format():
    assert parse_mcap_cr("8,13,988 Cr.") == 813988.0
    assert parse_mcap_cr("56.7 Cr") == 56.7
    assert parse_mcap_cr("1,234 Cr.") == 1234.0
    assert parse_mcap_cr(None) is None
    assert parse_mcap_cr("") is None
    assert parse_mcap_cr("—") is None


def test_compute_np_yoy_latest_vs_year_ago():
    all_q = _quarters({
        (2024, "Jun"): 100.0,
        (2024, "Sep"): 110.0,
        (2024, "Dec"): 120.0,
        (2025, "Mar"): 130.0,
        (2025, "Jun"): 150.0,  # +50% vs Jun 2024
    })
    latest, yoy = compute_np_yoy(all_q)
    assert latest == 150.0
    assert yoy is not None and abs(yoy - 50.0) < 1e-6


def test_compute_np_yoy_needs_five_quarters():
    all_q = _quarters({
        (2025, "Mar"): 130.0,
        (2025, "Jun"): 150.0,
    })
    latest, yoy = compute_np_yoy(all_q)
    assert latest == 150.0
    assert yoy is None


def test_compute_np_yoy_ignores_ttm_and_empty():
    assert compute_np_yoy({}) == (None, None)
    # TTM-only columns are skipped entirely
    all_q = {"2025": {"Mar TTM": {"Net Profit": "500"}}}
    assert compute_np_yoy(all_q) == (None, None)


def test_mcap_cr_from_trade_info():
    # RELIANCE live shape: rupees → Rs Cr
    assert mcap_cr_from_trade_info({"totalMarketCap": 16904847371522.4}) == 16904847371522.4 / 1e7
    # Small-cap matches screener's ~706 Cr readout
    assert abs(mcap_cr_from_trade_info({"totalMarketCap": 7030482658.48}) - 703.048) < 0.01
    assert mcap_cr_from_trade_info({}) is None
    assert mcap_cr_from_trade_info(None) is None
    assert mcap_cr_from_trade_info({"totalMarketCap": 0}) is None
    assert mcap_cr_from_trade_info({"totalMarketCap": "N/A"}) is None


def _fake_row(sym):
    return {"symbol": sym, "market_cap": 100.0, "net_profit": 10.0, "net_profit_yoy": 5.0}


def test_store_chunks_isolates_timeout_and_advances_cursor():
    """A TimeoutError on one 50-row chunk must not abort the other chunks,
    and the cursor must advance past the last *written* chunk."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    import app.services.data_sync.fundamentals as fund_mod

    enriched = [_fake_row(f"S{i:04d}") for i in range(120)]  # 3 chunks
    calls = []

    def _enqueue(prio, fn, rows, **kwargs):
        calls.append([r["symbol"] for r in rows])
        if len(calls) == 2:
            raise TimeoutError("writer saturated")
        return None

    persisted = {}

    async def _fake_write_cursor(session, symbol):
        persisted["cursor"] = symbol

    class _FakeCtx:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    def _fake_session_factory():
        return _FakeCtx()

    with (
        patch.object(fund_mod, "_write_cursor_async", side_effect=_fake_write_cursor),
        patch("app.services.write_queue.enqueue_write_sync", side_effect=_enqueue),
    ):
        last = asyncio.run(fund_mod._store_enriched_chunks(enriched, "CURSOR0", _fake_session_factory))

    # All 3 chunks attempted despite chunk 2 timing out.
    assert [len(c) for c in calls] == [50, 50, 20]
    # Cursor advanced past the last *successful* chunk (chunk 3).
    assert last == "S0119"
    assert persisted["cursor"] == "S0119"


def test_store_chunks_all_fail_keeps_start_cursor():
    """If every chunk fails, the start cursor is preserved (safe retry)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    import app.services.data_sync.fundamentals as fund_mod

    enriched = [_fake_row("S0001")]

    class _FakeCtx:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    def _fake_session_factory():
        return _FakeCtx()

    with (
        patch.object(fund_mod, "_write_cursor_async", AsyncMock()) as write_cursor,
        patch(
            "app.services.write_queue.enqueue_write_sync",
            side_effect=TimeoutError("writer saturated"),
        ),
    ):
        last = asyncio.run(fund_mod._store_enriched_chunks(enriched, "CURSOR0", _fake_session_factory))

    assert last == "CURSOR0"
    write_cursor.assert_awaited_once()
    assert write_cursor.await_args.args[1] == "CURSOR0"


def test_compute_np_yoy_zero_base():
    all_q = _quarters({
        (2024, "Jun"): 0.0,
        (2024, "Sep"): 110.0,
        (2024, "Dec"): 120.0,
        (2025, "Mar"): 130.0,
        (2025, "Jun"): 150.0,
    })
    latest, yoy = compute_np_yoy(all_q)
    assert latest == 150.0
    assert yoy is None  # division by zero guarded


# ---------------------------------------------------------------------------
# Load-gate tests (mocked telemetry — no DB, no threads)
# ---------------------------------------------------------------------------

def _patch_gate(monkeypatch, *, alive=True, occupancy=10.0, p95=100.0, wait=50.0):
    import app.services.data_sync.fundamentals as fund_mod
    import app.services.write_queue as wq_mod

    class _Writer:
        def is_alive(self):
            return alive

    monkeypatch.setattr(wq_mod, "_writer_thread", _Writer())
    monkeypatch.setattr(
        wq_mod, "_peek_queue_snapshot",
        lambda: {"occupancy_pct": occupancy, "contended": False},
    )
    monkeypatch.setattr(
        wq_mod, "_aggregate_metrics",
        lambda: {"p95_latency_ms": p95, "avg_queue_wait_ms": wait},
    )
    return fund_mod


def test_gate_quiet_allows(monkeypatch):
    fund_mod = _patch_gate(monkeypatch)
    assert fund_mod._system_is_quiet() is True


def test_gate_busy_queue_blocks(monkeypatch):
    fund_mod = _patch_gate(monkeypatch, occupancy=55.0)
    assert fund_mod._system_is_quiet() is False


def test_gate_slow_p95_blocks(monkeypatch):
    fund_mod = _patch_gate(monkeypatch, p95=2500.0)
    assert fund_mod._system_is_quiet() is False


def test_gate_slow_queue_wait_blocks(monkeypatch):
    fund_mod = _patch_gate(monkeypatch, wait=5000.0)
    assert fund_mod._system_is_quiet() is False


def test_gate_dead_writer_blocks(monkeypatch):
    fund_mod = _patch_gate(monkeypatch, alive=False)
    assert fund_mod._system_is_quiet() is False


def test_gate_telemetry_error_fail_open(monkeypatch):
    import app.services.data_sync.fundamentals as fund_mod
    import app.services.write_queue as wq_mod

    class _Writer:
        def is_alive(self):
            return True

    monkeypatch.setattr(wq_mod, "_writer_thread", _Writer())

    def _boom():
        raise RuntimeError("telemetry exploded")

    monkeypatch.setattr(wq_mod, "_peek_queue_snapshot", _boom)
    assert fund_mod._system_is_quiet() is True


# ---------------------------------------------------------------------------
# Loop-driver tests (mocked batch fn + fake clock — no screener, no DB)
# ---------------------------------------------------------------------------

def _patch_driver(monkeypatch, *, count, batches, gate_calls=None):
    """Patch the loop driver's collaborators.

    ``batches``: list of dicts returned by successive _run_fundamentals_batch
    calls (each merged with zero-stats defaults). Returns dict of spies.
    """
    import asyncio
    import threading
    from unittest.mock import AsyncMock, MagicMock

    import app.services.data_sync.fundamentals as fund_mod
    import app.backgroundtasks._runtime as runtime_mod
    import app.database as db_mod
    import app.jobs.runner as runner_mod
    from app.services.screener_client import screener_client

    calls = {"batch_after": [], "sleeps": 0, "cursor_reset": []}

    async def _fake_batch(batch_limit, after):
        calls["batch_after"].append(after)
        res = {"processed": 0, "enriched": 0, "skipped": 0, "failed": 0,
               "last_symbol": after, "exhausted": False, "aborted": False}
        res.update(batches[min(len(calls["batch_after"]) - 1, len(batches) - 1)])
        return res

    async def _fake_sleep(seconds):
        calls["sleeps"] += 1

    async def _fake_write_cursor(session, symbol):
        calls["cursor_reset"].append(symbol)

    class _FakeCtx:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *exc):
            return False

    shutdown = threading.Event()

    monkeypatch.setattr(fund_mod, "_count_candidates", AsyncMock(return_value=count))
    monkeypatch.setattr(fund_mod, "_run_fundamentals_batch", _fake_batch)
    monkeypatch.setattr(fund_mod, "_async_sleep_interruptible", _fake_sleep)
    monkeypatch.setattr(fund_mod, "_write_cursor_async", _fake_write_cursor)
    monkeypatch.setattr(fund_mod, "_read_cursor", AsyncMock(return_value="CURSOR0"))
    monkeypatch.setattr(screener_client, "init", AsyncMock())
    monkeypatch.setattr(db_mod, "AsyncSessionLocal", lambda: _FakeCtx())
    monkeypatch.setattr(runtime_mod, "_shutdown_event", shutdown)
    monkeypatch.setattr(runner_mod, "update_job_status_sync", MagicMock())
    if gate_calls is not None:
        it = iter(gate_calls)
        monkeypatch.setattr(fund_mod, "_system_is_quiet", lambda: next(it, True))
    else:
        monkeypatch.setattr(fund_mod, "_system_is_quiet", lambda: True)
    return fund_mod, calls, shutdown


def test_loop_chains_batches_until_exhausted(monkeypatch):
    import asyncio

    fund_mod, calls, _ = _patch_driver(
        monkeypatch,
        count=250,  # batch_limit=120 → 3 batches
        batches=[
            {"processed": 120, "enriched": 90, "last_symbol": "AAA"},
            {"processed": 120, "enriched": 80, "last_symbol": "BBB"},
            {"processed": 10, "enriched": 5, "last_symbol": "CCC", "exhausted": True},
        ],
    )
    total = asyncio.run(fund_mod._fundamentals_sync_async(batch_limit=120))

    assert len(calls["batch_after"]) == 3
    # Cursor chains across batches.
    assert calls["batch_after"] == ["CURSOR0", "AAA", "BBB"]
    assert total["processed"] == 250
    assert total["enriched"] == 175
    # Exhaustion resets the cursor for wrap-around.
    assert calls["cursor_reset"] == [None]
    assert calls["sleeps"] == 0  # quiet the whole way — no backoff


def test_loop_busy_sleeps_then_resumes(monkeypatch):
    import asyncio

    fund_mod, calls, _ = _patch_driver(
        monkeypatch,
        count=240,
        batches=[
            {"processed": 120, "enriched": 90, "last_symbol": "AAA"},
            {"processed": 120, "enriched": 90, "last_symbol": "BBB", "exhausted": True},
        ],
        gate_calls=[False, True],  # busy once, then quiet
    )
    total = asyncio.run(fund_mod._fundamentals_sync_async(batch_limit=120))

    assert len(calls["batch_after"]) == 2
    assert calls["sleeps"] == 1  # one 5-min backoff, then resumed
    assert total["processed"] == 240


def test_loop_shutdown_exits_cleanly(monkeypatch):
    import asyncio

    fund_mod, calls, shutdown = _patch_driver(
        monkeypatch,
        count=1000,
        batches=[{"processed": 120, "enriched": 90, "last_symbol": "AAA"}],
    )

    orig_batch = fund_mod._run_fundamentals_batch

    async def _batch_then_stop(batch_limit, after):
        res = await orig_batch(batch_limit, after)
        shutdown.set()  # app closes mid-run
        return res

    monkeypatch.setattr(fund_mod, "_run_fundamentals_batch", _batch_then_stop)
    total = asyncio.run(fund_mod._fundamentals_sync_async(batch_limit=120))

    assert len(calls["batch_after"]) == 1
    assert total["processed"] == 120


def test_loop_max_batches_cap(monkeypatch):
    import asyncio

    fund_mod, calls, _ = _patch_driver(
        monkeypatch,
        count=1000,
        batches=[{"processed": 120, "enriched": 90, "last_symbol": "AAA"}],
    )
    total = asyncio.run(
        fund_mod._fundamentals_sync_async(batch_limit=120, max_batches=2)
    )

    assert len(calls["batch_after"]) == 2
    assert total["processed"] == 240
    assert calls["cursor_reset"] == []  # no exhaustion → no reset


def test_loop_abort_stops_run(monkeypatch):
    import asyncio

    fund_mod, calls, _ = _patch_driver(
        monkeypatch,
        count=1000,
        batches=[{"processed": 5, "failed": 5, "aborted": True}],
    )
    total = asyncio.run(fund_mod._fundamentals_sync_async(batch_limit=120))

    assert len(calls["batch_after"]) == 1
    assert total["failed"] == 5


def test_loop_no_candidates_no_batches(monkeypatch):
    import asyncio

    fund_mod, calls, _ = _patch_driver(monkeypatch, count=0, batches=[])
    total = asyncio.run(fund_mod._fundamentals_sync_async(batch_limit=120))

    assert calls["batch_after"] == []
    assert total == {"processed": 0, "enriched": 0, "skipped": 0, "failed": 0}

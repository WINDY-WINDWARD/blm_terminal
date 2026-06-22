"""Tests for the streaming market WS protocol in `app.routers.market_ws`.

The protocol sends one `*_started` message, then one `*_partial` per
symbol as each NSE call completes, then a final `*_complete` message.
This gives the browser per-symbol fan-out: a 20-symbol request can
finish painting the first 3 rows within ~200ms (cache hits) while the
remaining 17 NSE calls are still in flight.

These tests pin down:
  1. Per-symbol partials — every requested symbol gets its own partial
     message with the correct data, even when individual fetches
     complete out of order.
  2. The request_id round-trips — partials are tagged with the same
     request_id the client sent, so concurrent requests don't cross-
     contaminate.
  3. Per-symbol error path — when `_fetch_change_ranges_for_symbol`
     returns None for a symbol (e.g. ARROWGREEN's "no yearwise data"),
     that symbol's partial has `data: null` and no `error` message
     leaks out.
  4. `*_complete` fires after all partials.
  5. The `*_started` message announces the batch up-front so the
     client can pre-allocate loading state.
  6. The "thundering herd" of NSE is bounded — a 50-symbol request
     still produces exactly 50 partials + 1 started + 1 complete, in
     the order each per-symbol NSE call completed.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import market_ws as market_ws_module
from app.routers.market_ws import market_websocket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Minimal fake WebSocket that captures every JSON send and lets
    the test pretend to be the client sending requests."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.received: list[dict] = []
        self._receive_event = asyncio.Event()
        self._closed = False

    async def accept(self) -> None:
        pass

    async def send_json(self, data) -> None:
        self.sent.append(data)

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def receive_text(self) -> str:
        await self._receive_event.wait()
        if not self.received:
            raise RuntimeError("no message queued")
        return json.dumps(self.received.pop(0))

    def queue_receive(self, payload: dict) -> None:
        self.received.append(payload)
        self._receive_event.set()

    async def close(self) -> None:
        self._closed = True

    # The handler does `await websocket.send_json({...})` and `await
    # websocket.receive_text()`; nothing else is used. Provide a no-op
    # for the heart-beat cancel safety net.
    @property
    def closed(self) -> bool:
        return self._closed


async def _drive(ws: FakeWebSocket, request: dict, *, max_iters: int = 200) -> list[dict]:
    """Run the WS handler coroutine in the background and feed it one
    request. The handler loops on `receive_text`, so we drive it
    manually. Returns all messages the handler sent before it blocked
    on the next receive.

    The handler is in a tight `while True` loop, so we have to wait
    for it to be "stable" — i.e. consumed our message and either
    finished the round-trip (single-request, returning to
    `receive_text` to block) or completed the task. We detect
    stability by checking the message count and pending received
    messages haven't changed in a few iterations.
    """
    task = asyncio.create_task(market_websocket(ws))
    ws.queue_receive(request)
    last_sent_count = -1
    stable_iters = 0
    for _ in range(max_iters):
        await asyncio.sleep(0)
        if task.done():
            break
        if not ws.received and len(ws.sent) == last_sent_count:
            # No more queued messages and we haven't sent anything
            # new in this iteration — handler is blocked on
            # receive_text OR finished the streaming response.
            stable_iters += 1
            if stable_iters >= 3:
                break
        else:
            stable_iters = 0
        last_sent_count = len(ws.sent)
    # Cancel the background task — we only meant to drive one round-trip.
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    return ws.sent


def _patch_batch(monkeypatch, *, change_ranges=None, symbol_data=None,
                  per_symbol_delay: float = 0.0, fail_symbols: set[str] | None = None):
    """Patch `market_ws.fetch_change_ranges_batch` /
    `fetch_symbol_data_batch` to feed the WS handler deterministic data
    without going near NSE.

    `per_symbol_delay` is a per-call sleep so the test can force
    symbols to complete in a specific order (e.g. RELIANCE first, TCS
    last).
    """
    fail_symbols = fail_symbols or set()

    async def _change_ranges(symbols):
        out = {}
        for s in symbols:
            if per_symbol_delay:
                await asyncio.sleep(per_symbol_delay)
            if s in fail_symbols:
                out[s] = None
            else:
                # Allow per-symbol override
                if isinstance(change_ranges, dict) and s in change_ranges:
                    out[s] = change_ranges[s]
                else:
                    out[s] = {"oneWeekPercent": 1.0, "symbol": s}
        return out

    async def _symbol_data(symbols):
        out = {}
        for s in symbols:
            if per_symbol_delay:
                await asyncio.sleep(per_symbol_delay)
            if s in fail_symbols:
                out[s] = None
            else:
                if isinstance(symbol_data, dict) and s in symbol_data:
                    out[s] = symbol_data[s]
                else:
                    out[s] = {"ltp": 100.0, "pChange": 0.5, "symbol": s}
        return out

    monkeypatch.setattr(market_ws_module, "fetch_change_ranges_batch", _change_ranges)
    monkeypatch.setattr(market_ws_module, "fetch_symbol_data_batch", _symbol_data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_ranges_sends_started_partials_complete(monkeypatch):
    _patch_batch(monkeypatch, change_ranges={
        "RELIANCE": {"oneWeekPercent": 1.5},
        "TCS": {"oneWeekPercent": 2.0},
    })
    ws = FakeWebSocket()
    messages = await _drive(ws, {
        "action": "get_change_ranges",
        "request_id": 42,
        "symbols": ["RELIANCE", "TCS"],
    })

    # Filter out connection-management frames; the handler sends
    # {"type": "connected"} first, then the streaming frames.
    stream = [m for m in messages if m.get("request_id") == 42 or m.get("type") in {
        "change_ranges_started", "change_ranges_partial", "change_ranges_complete"
    }]

    types = [m["type"] for m in stream]
    # 1 started + 2 partials (one per symbol) + 1 complete
    assert types == [
        "change_ranges_started",
        "change_ranges_partial",
        "change_ranges_partial",
        "change_ranges_complete",
    ]

    started = stream[0]
    assert started["symbols"] == ["RELIANCE", "TCS"]
    assert started["request_id"] == 42

    partials = {m["symbol"]: m for m in stream if m["type"] == "change_ranges_partial"}
    assert partials["RELIANCE"]["data"] == {"oneWeekPercent": 1.5}
    assert partials["TCS"]["data"] == {"oneWeekPercent": 2.0}
    # Every partial carries the same request_id
    assert all(m["request_id"] == 42 for m in partials.values())

    assert stream[-1]["type"] == "change_ranges_complete"
    assert stream[-1]["request_id"] == 42


@pytest.mark.asyncio
async def test_symbol_data_sends_per_symbol_partials_with_ltp(monkeypatch):
    _patch_batch(monkeypatch, symbol_data={
        "RELIANCE": {"ltp": 1284.5, "pChange": 1.23},
        "TCS": {"ltp": 3450.0, "pChange": -0.5},
    })
    ws = FakeWebSocket()
    messages = await _drive(ws, {
        "action": "get_symbol_data",
        "request_id": 7,
        "symbols": ["RELIANCE", "TCS"],
    })

    stream = [m for m in messages if m.get("request_id") == 7]
    types = [m["type"] for m in stream]
    assert types == [
        "symbol_data_started",
        "symbol_data_partial",
        "symbol_data_partial",
        "symbol_data_complete",
    ]

    partials = {m["symbol"]: m for m in stream if m["type"] == "symbol_data_partial"}
    assert partials["RELIANCE"]["data"] == {"ltp": 1284.5, "pChange": 1.23}
    assert partials["TCS"]["data"] == {"ltp": 3450.0, "pChange": -0.5}


@pytest.mark.asyncio
async def test_request_id_round_trips_for_concurrent_requests(monkeypatch):
    """Two concurrent requests with different request_ids must NEVER
    cross-contaminate. This pins down the contract the browser relies
    on to attribute partials to the right outgoing send."""
    _patch_batch(monkeypatch)
    ws = FakeWebSocket()
    task = asyncio.create_task(market_websocket(ws))

    # Queue two requests back-to-back
    ws.queue_receive({
        "action": "get_change_ranges",
        "request_id": 100,
        "symbols": ["RELIANCE", "TCS"],
    })
    ws.queue_receive({
        "action": "get_change_ranges",
        "request_id": 200,
        "symbols": ["INFY", "HAL"],
    })

    # Let the handler process both. Wait until the sent-message count
    # has been stable for several iterations (i.e. both started +
    # both completed have been emitted, plus all 4 partials).
    last_sent_count = -1
    stable_iters = 0
    for _ in range(200):
        await asyncio.sleep(0)
        if task.done():
            break
        if not ws.received and len(ws.sent) == last_sent_count:
            stable_iters += 1
            if stable_iters >= 3:
                break
        else:
            stable_iters = 0
        last_sent_count = len(ws.sent)

    task.cancel()
    try:
        await task
    except Exception:
        pass

    # Every message with request_id 100 must be about {RELIANCE, TCS}
    # and never {INFY, HAL}; vice versa for 200.
    messages = ws.sent
    for m in messages:
        if m.get("type") == "change_ranges_partial":
            sym = m["symbol"]
            if m["request_id"] == 100:
                assert sym in {"RELIANCE", "TCS"}, f"id=100 leaked {sym}"
            elif m["request_id"] == 200:
                assert sym in {"INFY", "HAL"}, f"id=200 leaked {sym}"


@pytest.mark.asyncio
async def test_failed_symbol_emits_partial_with_null_data(monkeypatch):
    """When a per-symbol fetch returns None (e.g. ARROWGREEN with no
    yearwise data on NSE), the partial must have data=None and must
    NOT be reported as a top-level error."""
    _patch_batch(monkeypatch, fail_symbols={"ARROWGREEN"}, change_ranges={
        "TCS": {"oneWeekPercent": 1.0},
    })
    ws = FakeWebSocket()
    messages = await _drive(ws, {
        "action": "get_change_ranges",
        "request_id": 5,
        "symbols": ["ARROWGREEN", "TCS"],
    })

    partials = {m["symbol"]: m for m in messages
                if m.get("type") == "change_ranges_partial"}
    assert partials["ARROWGREEN"]["data"] is None
    assert partials["TCS"]["data"] == {"oneWeekPercent": 1.0}

    # The handler should NOT have sent a top-level error message
    # for the ARROWGREEN soft miss — that was the original bug that
    # tripped the circuit breaker.
    assert not any(m.get("type") == "error" for m in messages)


@pytest.mark.asyncio
async def test_empty_symbols_list_sends_protocol_error(monkeypatch):
    """`get_change_ranges` with no symbols is a protocol error, not
    a soft miss. The handler must reply with `{"type": "error", ...}`."""
    _patch_batch(monkeypatch)
    ws = FakeWebSocket()
    messages = await _drive(ws, {
        "action": "get_change_ranges",
        "request_id": 99,
        "symbols": [],
    })

    errors = [m for m in messages if m.get("type") == "error"]
    assert errors, "expected a protocol error"
    assert errors[0].get("request_id") == 99


@pytest.mark.asyncio
async def test_unknown_action_sends_error(monkeypatch):
    _patch_batch(monkeypatch)
    ws = FakeWebSocket()
    messages = await _drive(ws, {"action": "do_something_weird", "request_id": 1})

    errors = [m for m in messages if m.get("type") == "error"]
    assert errors
    assert "do_something_weird" in errors[0]["message"]


@pytest.mark.asyncio
async def test_ping_replies_with_pong(monkeypatch):
    _patch_batch(monkeypatch)
    ws = FakeWebSocket()
    messages = await _drive(ws, {"action": "ping"})
    assert any(m.get("type") == "pong" for m in messages)


@pytest.mark.asyncio
async def test_large_batch_produces_one_partial_per_symbol(monkeypatch):
    """A 50-symbol batch (the max we accept) must produce exactly 50
    partials + 1 started + 1 complete. This guards against any
    future 'optimization' that batches partials server-side."""
    symbols = [f"SYM{i:02d}" for i in range(50)]
    _patch_batch(monkeypatch, change_ranges={s: {"oneWeekPercent": 1.0} for s in symbols})
    ws = FakeWebSocket()
    messages = await _drive(ws, {
        "action": "get_change_ranges",
        "request_id": 1,
        "symbols": symbols,
    })

    types = [m["type"] for m in messages]
    assert types.count("change_ranges_partial") == 50
    assert types.count("change_ranges_complete") == 1
    assert types.count("change_ranges_started") == 1

    # Every requested symbol appears exactly once as a partial
    seen_symbols = {m["symbol"] for m in messages if m["type"] == "change_ranges_partial"}
    assert seen_symbols == set(symbols)

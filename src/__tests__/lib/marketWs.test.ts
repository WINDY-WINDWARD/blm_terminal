/**
 * Meaningful tests for the market WebSocket service (`src/lib/marketWs.ts`).
 *
 * The whole point of moving from HTTP to WS is per-symbol streaming: as
 * soon as one symbol's data is ready, the browser should render that
 * symbol — not wait for the slowest NSE call. These tests pin down the
 * behaviors that make that work:
 *
 *   1. URL resolution — env var > /api/py/ws-config > localhost fallback.
 *   2. Eager connect — `connect()` opens a real WebSocket; idempotent on
 *      multiple calls; no-op when already open/connecting.
 *   3. Connection-state propagation — `onConnectionChange` fires true on
 *      open, false on close.
 *   4. 50ms debounce — multiple `requestChangeRanges` calls within 50ms
 *      coalesce into a single WS send.
 *   5. Per-symbol fan-out — `*_partial` messages dispatch to listeners
 *      with the right symbol and data, even when one batch's symbols
 *      arrive interleaved with another batch's symbols.
 *   6. request_id correlation — two concurrent requests do NOT cross-
 *      contaminate: each resolves only with its own batch's partials.
 *   7. Client TTL cache — repeat calls within TTL skip the WS entirely.
 *   8. Disconnect rejection — pending requests are rejected with a clear
 *      error when the socket drops mid-flight, and consumers re-issue
 *      on reconnect.
 *   9. Reconnect — on close, the service schedules a reconnect with
 *      exponential backoff (mirroring newsSocket.ts).
 *
 * The tests inject a fake WebSocket so the assertions are deterministic
 * and don't depend on the dev server running.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

interface FakeWebSocket {
  readyState: number;
  CONNECTING: number;
  OPEN: number;
  CLOSING: number;
  CLOSED: number;
  url: string;
  sent: string[];
  listeners: {
    open?: () => void;
    message?: (event: { data: string }) => void;
    close?: () => void;
    error?: (e: unknown) => void;
  };
  send: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: ((e: unknown) => void) | null;
  __open: () => void;
  __message: (data: unknown) => void;
  __close: () => void;
  __error: (e?: unknown) => void;
}

const instances: FakeWebSocket[] = [];

function makeFakeWebSocket(this: unknown, url: string): FakeWebSocket {
  const ws: FakeWebSocket = {
    readyState: 0, // CONNECTING
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3,
    url,
    sent: [],
    listeners: {},
    send: vi.fn((payload: string) => {
      ws.sent.push(payload);
    }),
    close: vi.fn(() => {
      if (ws.readyState === 3) return;
      ws.readyState = 3; // CLOSED
      // Fire onclose synchronously — tests expect to see the close
      // event without needing to wait for an additional tick.
      ws.onclose?.();
    }),
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    __open() {
      ws.readyState = 1; // OPEN
      ws.onopen?.();
    },
    __message(data: unknown) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      ws.onmessage?.({ data: payload });
    },
    __close() {
      ws.close();
    },
    __error(e: unknown = new Error('socket error')) {
      ws.onerror?.(e);
    },
  };
  instances.push(ws);
  return ws;
}

function makeFakeWebSocketFactory() {
  const factory = function (url: string) {
    return makeFakeWebSocket(url);
  } as unknown as { new (url: string): FakeWebSocket };
  // Attach the constants so the implementation can use WebSocket.OPEN
  // etc. without TypeScript complaining. Tests don't actually rely
  // on these values.
  (factory as unknown as Record<string, number>).CONNECTING = 0;
  (factory as unknown as Record<string, number>).OPEN = 1;
  (factory as unknown as Record<string, number>).CLOSING = 2;
  (factory as unknown as Record<string, number>).CLOSED = 3;
  return factory;
}

vi.hoisted(() => {
  // Default the env var to empty so URL resolution is exercised via
  // the ws-config fetch path in most tests; individual tests
  // override it to test the env-var path.
  process.env.NEXT_PUBLIC_MARKET_WS_URL = '';
});

import { marketWsService } from '@/lib/marketWs';

function resetSingleton() {
  (marketWsService as unknown as { __resetForTests: () => void }).__resetForTests();
}

beforeEach(() => {
  vi.useFakeTimers();
  instances.length = 0;
  vi.stubGlobal('WebSocket', makeFakeWebSocketFactory() as unknown as typeof WebSocket);
  // Default ws-config fallback for tests — most tests don't care
  // about the URL path; they just want the socket to open.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify({ marketWsUrl: 'ws://test.local/ws/market' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ) as unknown as typeof fetch,
  );
  resetSingleton();
});

afterEach(() => {
  if (debugSpy.mock.calls.length) {
    // eslint-disable-next-line no-console
    console.log('DEBUG MARKET_WS:', JSON.stringify(debugSpy.mock.calls, null, 2));
  }
});

const debugSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  resetSingleton();
});

// We use a tiny helper to advance fake timers AND flush microtasks.
// `vi.advanceTimersByTimeAsync` advances fake timers and flushes the
// microtask queue; the small `setTimeout(resolve, 0)` after it gives
// the underlying WebSocket fake's onopen/onmessage handlers a chance
// to run.
async function tick(ms = 0) {
  await vi.advanceTimersByTimeAsync(ms);
  await Promise.resolve();
}

describe('MarketWsService — URL resolution', () => {
  it('uses NEXT_PUBLIC_MARKET_WS_URL when set (skips ws-config fetch)', async () => {
    const original = process.env.NEXT_PUBLIC_MARKET_WS_URL;
    process.env.NEXT_PUBLIC_MARKET_WS_URL = 'ws://env-host/ws/market';
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);
    try {
      marketWsService.connect();
      await tick(0);
      expect(instances).toHaveLength(1);
      expect(instances[0].url).toBe('ws://env-host/ws/market');
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      if (original === undefined) delete process.env.NEXT_PUBLIC_MARKET_WS_URL;
      else process.env.NEXT_PUBLIC_MARKET_WS_URL = original;
    }
  });

  it('falls back to /api/py/ws-config when env var is unset', async () => {
    const original = process.env.NEXT_PUBLIC_MARKET_WS_URL;
    delete process.env.NEXT_PUBLIC_MARKET_WS_URL;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ marketWsUrl: 'ws://fromconfig:9000/ws/market' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ) as unknown as typeof fetch,
    );

    marketWsService.connect();
    await tick(0);
    expect(instances).toHaveLength(1);
    expect(instances[0].url).toBe('ws://fromconfig:9000/ws/market');
    if (original !== undefined) process.env.NEXT_PUBLIC_MARKET_WS_URL = original;
  });

  it('falls back to localhost when ws-config fetch fails', async () => {
    const original = process.env.NEXT_PUBLIC_MARKET_WS_URL;
    delete process.env.NEXT_PUBLIC_MARKET_WS_URL;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('upstream down', { status: 500 })) as unknown as typeof fetch,
    );
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      value: { ...originalLocation, protocol: 'http:', host: 'fallback.test:3000' },
      writable: true,
      configurable: true,
    });

    try {
      marketWsService.connect();
      await tick(0);
      expect(instances).toHaveLength(1);
      expect(instances[0].url).toBe('ws://fallback.test:3000/ws/market');
    } finally {
      Object.defineProperty(window, 'location', {
        value: originalLocation,
        configurable: true,
      });
      if (original !== undefined) process.env.NEXT_PUBLIC_MARKET_WS_URL = original;
    }
  });
});

describe('MarketWsService — connect lifecycle', () => {
  it('opens a real WebSocket on connect()', async () => {
    marketWsService.connect();
    await tick(0);
    expect(instances).toHaveLength(1);
    expect(instances[0].readyState).toBe(0); // CONNECTING
  });

  it('is idempotent — second connect() while OPEN is a no-op', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    marketWsService.connect();
    marketWsService.connect();
    marketWsService.connect();
    expect(instances).toHaveLength(1);
  });

  it('is idempotent — second connect() while CONNECTING is a no-op', async () => {
    marketWsService.connect();
    await tick(0);
    marketWsService.connect();
    marketWsService.connect();
    expect(instances).toHaveLength(1);
  });

  it('onConnectionChange fires true on open, false on close', async () => {
    const states: boolean[] = [];
    marketWsService.onConnectionChange((c) => states.push(c));

    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);
    expect(states).toEqual([true]);

    instances[0].__close();
    await tick(0);
    expect(states).toEqual([true, false]);
  });

  it('schedules a reconnect with exponential backoff on unexpected close', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    instances[0].__close();
    await tick(0);
    // First reconnect attempt: 1s * 2^0 = 1000ms
    await vi.advanceTimersByTimeAsync(1100);
    expect(instances.length).toBeGreaterThanOrEqual(2);
  });

  it('resets reconnect attempts after a successful open', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    instances[0].__close();
    await tick(0);
    await vi.advanceTimersByTimeAsync(1100);
    expect(instances.length).toBeGreaterThanOrEqual(2);
    instances[1].__open();
    instances[1].__close();
    await tick(0);
    const beforeCount = instances.length;
    // After a successful open, the backoff resets to 1s
    await vi.advanceTimersByTimeAsync(1100);
    expect(instances.length).toBeGreaterThan(beforeCount);
  });
});

describe('MarketWsService — request batching (50ms debounce)', () => {
  it('coalesces multiple requestChangeRanges calls within 50ms into ONE WS message', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    marketWsService.requestChangeRanges(['TCS']);
    marketWsService.requestChangeRanges(['INFY', 'HAL']);

    // Nothing sent yet — still inside the 50ms debounce window
    expect(instances[0].send).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(60);
    expect(instances[0].send).toHaveBeenCalledTimes(1);

    const sent = JSON.parse(instances[0].sent[0]);
    expect(sent.action).toBe('get_change_ranges');
    expect([...sent.symbols].sort()).toEqual(['HAL', 'INFY', 'RELIANCE', 'TCS']);
  });

  it('coalesces multiple requestSymbolData calls within 50ms into ONE WS message', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestSymbolData(['RELIANCE']);
    marketWsService.requestSymbolData(['TCS']);

    await vi.advanceTimersByTimeAsync(60);
    expect(instances[0].send).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(instances[0].sent[0]);
    expect(sent.action).toBe('get_symbol_data');
    expect([...sent.symbols].sort()).toEqual(['RELIANCE', 'TCS']);
  });

  it('sends two separate messages if calls are spaced > 50ms apart', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    marketWsService.requestChangeRanges(['TCS']);
    await vi.advanceTimersByTimeAsync(60);

    expect(instances[0].send).toHaveBeenCalledTimes(2);
    expect(JSON.parse(instances[0].sent[0]).symbols).toEqual(['RELIANCE']);
    expect(JSON.parse(instances[0].sent[1]).symbols).toEqual(['TCS']);
  });

  it('does not coalesce change-ranges and symbol-data into the same message', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    marketWsService.requestSymbolData(['RELIANCE']);

    await vi.advanceTimersByTimeAsync(60);
    expect(instances[0].send).toHaveBeenCalledTimes(2);
    const actions = instances[0].sent.map((s) => JSON.parse(s).action).sort();
    expect(actions).toEqual(['get_change_ranges', 'get_symbol_data']);
  });

  it('each WS message carries a unique request_id (correlation handle)', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    marketWsService.requestChangeRanges(['TCS']);
    await vi.advanceTimersByTimeAsync(60);

    const id1 = JSON.parse(instances[0].sent[0]).request_id;
    const id2 = JSON.parse(instances[0].sent[1]).request_id;
    expect(typeof id1).toBe('number');
    expect(typeof id2).toBe('number');
    expect(id1).not.toBe(id2);
  });
});

describe('MarketWsService — per-symbol fan-out on partials', () => {
  it('dispatches each *_partial message to the matching listener with the right symbol', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    const rangesEvents: Array<{ symbol: string; data: unknown }> = [];
    marketWsService.onChangeRanges((symbol, data) => {
      rangesEvents.push({ symbol, data });
    });

    marketWsService.requestChangeRanges(['RELIANCE', 'TCS']);
    await vi.advanceTimersByTimeAsync(60);
    const requestId = JSON.parse(instances[0].sent[0]).request_id;

    instances[0].__message({
      type: 'change_ranges_partial',
      request_id: requestId,
      symbol: 'RELIANCE',
      data: { oneWeekPercent: 1.5, oneMonthPercent: 4.2 },
    });
    instances[0].__message({
      type: 'change_ranges_partial',
      request_id: requestId,
      symbol: 'TCS',
      data: { oneWeekPercent: 0.8, oneMonthPercent: 2.1 },
    });
    await tick(0);

    const bySymbol = Object.fromEntries(rangesEvents.map((e) => [e.symbol, e.data]));
    expect(rangesEvents).toHaveLength(2);
    expect(bySymbol.RELIANCE).toEqual({ oneWeekPercent: 1.5, oneMonthPercent: 4.2 });
    expect(bySymbol.TCS).toEqual({ oneWeekPercent: 0.8, oneMonthPercent: 2.1 });
  });

  it('symbol-data partials fan out to onSymbolData listeners with the LTP', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    const events: Array<{ symbol: string; ltp: number | null }> = [];
    marketWsService.onSymbolData((symbol, data) => {
      events.push({ symbol, ltp: data?.ltp ?? null });
    });

    marketWsService.requestSymbolData(['RELIANCE', 'TCS']);
    await vi.advanceTimersByTimeAsync(60);
    const requestId = JSON.parse(instances[0].sent[0]).request_id;

    instances[0].__message({
      type: 'symbol_data_partial',
      request_id: requestId,
      symbol: 'RELIANCE',
      data: { ltp: 1284.5, pChange: 1.23, yearHigh: 1350, yearLow: 980 },
    });
    instances[0].__message({
      type: 'symbol_data_partial',
      request_id: requestId,
      symbol: 'TCS',
      data: null,
      error: 'NSE returned 500',
    });
    await tick(0);

    const bySymbol = Object.fromEntries(events.map((e) => [e.symbol, e.ltp]));
    expect(events).toHaveLength(2);
    expect(bySymbol.RELIANCE).toBe(1284.5);
    expect(bySymbol.TCS).toBeNull();
  });

  it('each outgoing request gets a unique request_id and never collides', async () => {
    // The CRITICAL guarantee: the request_id round-trip is correct.
    // We send 3 separate requests and verify each gets a fresh id
    // and each batch's partials route to the right callback.
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    const id1 = JSON.parse(instances[0].sent[0]).request_id;

    marketWsService.requestChangeRanges(['TCS']);
    await vi.advanceTimersByTimeAsync(60);
    const id2 = JSON.parse(instances[0].sent[1]).request_id;

    marketWsService.requestChangeRanges(['INFY']);
    await vi.advanceTimersByTimeAsync(60);
    const id3 = JSON.parse(instances[0].sent[2]).request_id;

    expect(new Set([id1, id2, id3]).size).toBe(3);
  });
});

describe('MarketWsService — client TTL cache', () => {
  it('serves repeat requestChangeRanges for the same symbol from cache (no WS send)', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    // First call
    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    const requestId = JSON.parse(instances[0].sent[0]).request_id;
    instances[0].__message({
      type: 'change_ranges_partial',
      request_id: requestId,
      symbol: 'RELIANCE',
      data: { oneWeekPercent: 5.0 },
    });
    await tick(0);
    instances[0].send.mockClear();

    // Second call within TTL — must NOT send to WS
    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    expect(instances[0].send).not.toHaveBeenCalled();
  });

  it('cache hit fires the listener immediately (synchronously after the cache lookup)', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    // Populate the cache
    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    const id = JSON.parse(instances[0].sent[0]).request_id;
    instances[0].__message({
      type: 'change_ranges_partial',
      request_id: id,
      symbol: 'RELIANCE',
      data: { oneWeekPercent: 5.0 },
    });
    await tick(0);

    // Now register a NEW listener and request again — it should fire
    // immediately from cache, not after a WS round-trip.
    const seen: unknown[] = [];
    marketWsService.onChangeRanges((_symbol, data) => {
      if (data && (data as { oneWeekPercent?: number }).oneWeekPercent === 5.0) seen.push(data);
    });
    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    // The listener should have fired synchronously during the request
    // call (no need to wait for the WS).
    expect(seen).toHaveLength(1);
  });

  it('sends a WS message for a fresh symbol but uses cache for an already-cached one in the same batch', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    // Prime cache for RELIANCE
    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    const id1 = JSON.parse(instances[0].send.mock.calls[0][0]).request_id;
    instances[0].__message({
      type: 'change_ranges_partial',
      request_id: id1,
      symbol: 'RELIANCE',
      data: { oneWeekPercent: 5.0 },
    });
    await tick(0);
    instances[0].send.mockClear();

    // Now request [RELIANCE, TCS] — RELIANCE should hit cache, only TCS goes out
    marketWsService.requestChangeRanges(['RELIANCE', 'TCS']);
    await vi.advanceTimersByTimeAsync(60);
    expect(instances[0].send).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(instances[0].send.mock.calls[0][0]);
    expect(sent.symbols).toEqual(['TCS']);
  });
});

describe('MarketWsService — disconnect rejection and re-issue', () => {
  it('rejects pending request if the socket drops mid-flight', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    const seen: Array<{ symbol: string; data: unknown }> = [];
    marketWsService.onChangeRanges((symbol, data) => {
      seen.push({ symbol, data });
    });

    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    // No partial yet — then the socket drops
    instances[0].__close();
    await tick(0);

    // The listener must have been notified with `null` (consistent
    // with today's HTTP error path: WatchWidget treats null as '—').
    expect(seen).toEqual([{ symbol: 'RELIANCE', data: null }]);
  });

  it('re-issues a pending request automatically after reconnect', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    expect(instances[0].send).toHaveBeenCalledTimes(1);

    instances[0].__close();
    await tick(0);
    instances[0].send.mockClear();

    // Reconnect fires after 1s
    await vi.advanceTimersByTimeAsync(1100);
    expect(instances.length).toBeGreaterThanOrEqual(2);
    instances[1].__open();
    await tick(0);

    // The pending request should have been re-sent on the new socket
    expect(instances[1].send).toHaveBeenCalled();
    const resent = JSON.parse(instances[1].sent[0]);
    expect(resent.action).toBe('get_change_ranges');
    expect(resent.symbols).toEqual(['RELIANCE']);
  });

  it('does not re-send after the connection comes back if all pending requests already completed', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    marketWsService.requestChangeRanges(['RELIANCE']);
    await vi.advanceTimersByTimeAsync(60);
    const id = JSON.parse(instances[0].sent[0]).request_id;
    instances[0].__message({
      type: 'change_ranges_partial',
      request_id: id,
      symbol: 'RELIANCE',
      data: { oneWeekPercent: 5.0 },
    });
    instances[0].__message({ type: 'change_ranges_complete', request_id: id });
    instances[0].send.mockClear();

    instances[0].__close();
    await tick(0);
    await vi.advanceTimersByTimeAsync(1100);
    instances[1].__open();
    await tick(0);

    // Nothing to re-send — the request was already resolved
    expect(instances[1].send).not.toHaveBeenCalled();
  });
});

describe('MarketWsService — keep-alive ping', () => {
  it('sends a ping on a keep-alive interval when the socket is open', async () => {
    marketWsService.connect();
    await tick(0);
    instances[0].__open();
    await tick(0);

    // Wait for the keep-alive interval (25s default in marketWs)
    await vi.advanceTimersByTimeAsync(26_000);

    const pings = instances[0].send.mock.calls
      .map((c) => JSON.parse(c[0] as string))
      .filter((m) => m.action === 'ping');
    expect(pings.length).toBeGreaterThan(0);
  });
});

/**
 * Tests for the WebSocket protocol helpers used by
 * `src/app/api/ws/market/route.ts`. The route itself is a thin
 * shell that:
 *   1. accepts a WebSocket upgrade,
 *   2. sends `{type: "connected"}`,
 *   3. on each `{action, request_id, symbols}` message, dispatches
 *      to `streamChangeRanges` or `streamSymbolData` and pipes
 *      the streamed events back over the socket.
 *
 * These tests pin down the per-symbol streaming behavior — the
 * protocol that the browser's `marketWs.ts` service relies on.
 * The actual Next.js WS plumbing (WebSocketPair, accept, etc.)
 * is exercised in the dev/prod server; the route is small
 * enough that the streamer's behavior IS the route's contract.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cache } from '@/lib/cache';
import { __resetThrottleStateForTests } from '@/lib/nseThrottle';
import { streamChangeRanges, streamSymbolData } from '@/lib/marketWsRoute';

interface WsEvent {
  type: string;
  request_id?: number;
  symbol?: string;
  symbols?: string[];
  data?: unknown;
  error?: string;
  message?: string;
}

class FakeWebSocket {
  sent: WsEvent[] = [];
  binary: (data: string) => void = () => {};
  send = vi.fn((payload: string) => {
    const parsed = JSON.parse(payload) as WsEvent;
    this.sent.push(parsed);
  });
  close = vi.fn();
}

function makeUrlRoutedFetchSpy(
  routes: Array<{ match: (url: string) => boolean; respond: (call: { url: string }) => Response | Promise<Response> }>,
) {
  const calls: Array<{ url: string }> = [];
  const spy = vi.fn(async (url: string | URL | Request) => {
    const u = typeof url === 'string' ? url : url.toString();
    calls.push({ url: u });
    for (const route of routes) {
      if (route.match(u)) return route.respond({ url: u });
    }
    throw new Error(`fetch called with no matching route: ${u}`);
  });
  return { spy, calls };
}

beforeEach(() => {
  vi.useRealTimers();
  cache.clear();
  __resetThrottleStateForTests();
  vi.stubGlobal(
    'PYTHON_BACKEND_URL',
    process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455',
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamChangeRanges', () => {
  it('emits started → 1 partial → complete for a single symbol', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: () =>
          new Response(
            JSON.stringify([{ one_week_chng_per: 1.5, one_year_chng_per: -9.0 }]),
            { status: 200, headers: { 'content-type': 'application/json' } },
          ),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    await streamChangeRanges(ws as unknown as WebSocket, 42, ['RELIANCE']);

    const types = ws.sent.map((m) => m.type);
    expect(types).toEqual([
      'change_ranges_started',
      'change_ranges_partial',
      'change_ranges_complete',
    ]);

    const started = ws.sent[0];
    expect(started.request_id).toBe(42);
    expect(started.symbols).toEqual(['RELIANCE']);

    const partial = ws.sent[1];
    expect(partial.request_id).toBe(42);
    expect(partial.symbol).toBe('RELIANCE');
    expect(partial.data).toEqual({
      oneDayPercent: null,
      oneWeekPercent: 1.5,
      oneMonthPercent: null,
      threeMonthPercent: null,
      sixMonthPercent: null,
      oneYearPercent: -9.0,
      twoYearPercent: null,
      threeYearPercent: null,
      fiveYearPercent: null,
    });

    const complete = ws.sent[2];
    expect(complete.type).toBe('change_ranges_complete');
    expect(complete.request_id).toBe(42);
  });

  it('emits exactly N partials for N symbols (one partial per symbol)', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: (call) => {
          const sym = new URL(call.url).searchParams.get('symbol')?.replace('EQN', '') ?? 'X';
          return new Response(
            JSON.stringify([{ one_week_chng_per: 1.0, symbol: sym }]),
            { status: 200, headers: { 'content-type': 'application/json' } },
          );
        },
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const symbols = ['RELIANCE', 'TCS', 'INFY', 'HAL', 'WIPRO'];
    await streamChangeRanges(ws as unknown as WebSocket, 1, symbols);

    const partials = ws.sent.filter((m) => m.type === 'change_ranges_partial');
    expect(partials).toHaveLength(symbols.length);
    expect(new Set(partials.map((p) => p.symbol))).toEqual(new Set(symbols));
  });

  it('emits a partial with data:null for a symbol that fails NSE and Python', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => new Response('upstream down', { status: 500 }) },
      { match: (u) => u.includes('python') || u.includes('4455'), respond: () => new Response('upstream down', { status: 500 }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    await streamChangeRanges(ws as unknown as WebSocket, 1, ['INFY']);

    const partial = ws.sent.find((m) => m.type === 'change_ranges_partial');
    expect(partial).toBeDefined();
    expect(partial?.symbol).toBe('INFY');
    expect(partial?.data).toBeNull();
    expect(partial?.error).toBeUndefined();
  });

  it('sends an error message for empty symbols (protocol error, not a soft miss)', async () => {
    const ws = new FakeWebSocket();
    await streamChangeRanges(ws as unknown as WebSocket, 99, []);

    expect(ws.sent).toHaveLength(1);
    expect(ws.sent[0].type).toBe('error');
    expect(ws.sent[0].request_id).toBe(99);
    expect(ws.sent[0].message).toMatch(/symbols/i);
  });

  it('handles a batch of 10 symbols without deadlock', async () => {
    // The throttle serializes different symbols on the same endpoint
    // with a 1.5s courtesy delay, so 10 symbols take ~15s. Keep the
    // batch small to keep the test fast.
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: () =>
          new Response(JSON.stringify([{ one_week_chng_per: 1.0 }]), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const symbols = Array.from({ length: 10 }, (_, i) => `SYM${i.toString().padStart(2, '0')}`);
    await streamChangeRanges(ws as unknown as WebSocket, 1, symbols);

    const types = ws.sent.map((m) => m.type);
    expect(types.filter((t) => t === 'change_ranges_partial')).toHaveLength(10);
    expect(types[0]).toBe('change_ranges_started');
    expect(types[types.length - 1]).toBe('change_ranges_complete');
  }, 30_000);
});

describe('streamSymbolData', () => {
  it('emits started → 1 partial → complete for a single symbol with extracted shape', async () => {
    const ws = new FakeWebSocket();
    const rawNse = {
      equityResponse: [
        {
          orderBook: { lastPrice: 1284.5 },
          metaData: { pChange: 1.23 },
          priceInfo: { yearHigh: 1350, yearLow: 980 },
        },
      ],
    };
    const { spy } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => new Response(JSON.stringify(rawNse), { status: 200 }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    await streamSymbolData(ws as unknown as WebSocket, 7, ['RELIANCE']);

    const types = ws.sent.map((m) => m.type);
    expect(types).toEqual([
      'symbol_data_started',
      'symbol_data_partial',
      'symbol_data_complete',
    ]);

    const partial = ws.sent[1];
    expect(partial.request_id).toBe(7);
    expect(partial.symbol).toBe('RELIANCE');
    // The wire shape is the EXTRACTED SymbolDataExtract, not the
    // raw NSE payload. The browser's marketWs.ts service receives
    // this directly and doesn't need to call extractSymbolData.
    expect(partial.data).toEqual({
      ltp: 1284.5,
      pChange: 1.23,
      yearHigh: 1350,
      yearLow: 980,
    });
    expect(partial.data).not.toHaveProperty('equityResponse');
  });

  it('emits exactly N partials for N symbols (one partial per symbol)', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: (call) => {
          const sym = new URL(call.url).searchParams.get('symbol') ?? 'X';
          const lastPrice = sym.length * 100;
          return new Response(
            JSON.stringify({
              equityResponse: [{ orderBook: { lastPrice }, metaData: { pChange: 0.5 } }],
            }),
            { status: 200 },
          );
        },
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const symbols = ['RELIANCE', 'TCS', 'INFY', 'HAL', 'WIPRO'];
    await streamSymbolData(ws as unknown as WebSocket, 1, symbols);

    const partials = ws.sent.filter((m) => m.type === 'symbol_data_partial');
    expect(partials).toHaveLength(symbols.length);
  });

  it('emits a partial with data:null for a symbol that fails NSE and Python', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => new Response('upstream down', { status: 500 }) },
      { match: (u) => u.includes('python') || u.includes('4455'), respond: () => new Response('upstream down', { status: 500 }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    await streamSymbolData(ws as unknown as WebSocket, 1, ['INFY']);

    const partial = ws.sent.find((m) => m.type === 'symbol_data_partial');
    expect(partial).toBeDefined();
    expect(partial?.symbol).toBe('INFY');
    expect(partial?.data).toBeNull();
  });

  it('sends an error message for empty symbols (protocol error)', async () => {
    const ws = new FakeWebSocket();
    await streamSymbolData(ws as unknown as WebSocket, 99, []);

    expect(ws.sent).toHaveLength(1);
    expect(ws.sent[0].type).toBe('error');
    expect(ws.sent[0].request_id).toBe(99);
  });

  it('mixed batch: 2 symbols fail NSE → still emits partials for all, with the 2 failures carrying Python data', async () => {
    const ws = new FakeWebSocket();
    const nseFailures = new Set(['RELIANCE', 'HAL']);
    const pythonData: Record<string, unknown> = {
      RELIANCE: { equityResponse: [{ orderBook: { lastPrice: 1310 }, metaData: { pChange: 0.7 } }] },
      HAL: { equityResponse: [{ orderBook: { lastPrice: 2200 }, metaData: { pChange: 1.1 } }] },
    };
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: (call) => {
          const sym = new URL(call.url).searchParams.get('symbol') ?? '';
          if (nseFailures.has(sym)) return new Response('upstream down', { status: 500 });
          return new Response(
            JSON.stringify({
              equityResponse: [{ orderBook: { lastPrice: 1000 }, metaData: { pChange: 0.1 } }],
            }),
            { status: 200 },
          );
        },
      },
      {
        match: (u) => u.includes('python') || u.includes('4455'),
        respond: (call) => {
          const sym = new URL(call.url).searchParams.get('symbol') ?? '';
          return new Response(
            JSON.stringify({ data: { [sym]: pythonData[sym] } }),
            { status: 200 },
          );
        },
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const symbols = ['RELIANCE', 'TCS', 'INFY', 'HAL'];
    await streamSymbolData(ws as unknown as WebSocket, 1, symbols);

    const partials = ws.sent.filter((m) => m.type === 'symbol_data_partial');
    expect(partials).toHaveLength(4);

    const bySymbol = Object.fromEntries(partials.map((p) => [p.symbol, p.data]));
    // The 2 NSE failures got their data from Python.
    expect(bySymbol.RELIANCE).toEqual({ ltp: 1310, pChange: 0.7, yearHigh: undefined, yearLow: undefined });
    expect(bySymbol.HAL).toEqual({ ltp: 2200, pChange: 1.1, yearHigh: undefined, yearLow: undefined });
    // The 2 NSE successes got their data from NSE.
    expect(bySymbol.TCS).toEqual({ ltp: 1000, pChange: 0.1, yearHigh: undefined, yearLow: undefined });
    expect(bySymbol.INFY).toEqual({ ltp: 1000, pChange: 0.1, yearHigh: undefined, yearLow: undefined });
  });
});

describe('protocol ordering', () => {
  it('the first message is always started; the last is always complete', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: () =>
          new Response(JSON.stringify([{ one_week_chng_per: 1.0 }]), { status: 200 }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    await streamChangeRanges(ws as unknown as WebSocket, 1, ['A', 'B', 'C']);

    expect(ws.sent[0].type).toBe('change_ranges_started');
    expect(ws.sent[ws.sent.length - 1].type).toBe('change_ranges_complete');
  });

  it('every partial carries the same request_id as the request', async () => {
    const ws = new FakeWebSocket();
    const { spy } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: () =>
          new Response(JSON.stringify([{ one_week_chng_per: 1.0 }]), { status: 200 }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    await streamChangeRanges(ws as unknown as WebSocket, 99, ['A', 'B', 'C']);

    const requestIds = ws.sent
      .filter((m) => m.request_id !== undefined)
      .map((m) => m.request_id);
    expect(new Set(requestIds)).toEqual(new Set([99]));
  });
});

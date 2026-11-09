/**
 * Tests for the per-symbol fetch + fallback helpers in
 * `src/lib/marketWsStreamer.ts`.
 *
 * The contract under test:
 *
 *   1. `fetchSymbolDataWithFallback(symbol)`:
 *      - Try the Python backend first.
 *      - On a Python failure or soft miss, fall back to NSE direct
 *        (3 total attempts with exponential backoff).
 *      - On both failing, return null.
 *
 *   2. `fetchChangeRangesWithFallback(symbol)` mirrors the same
 *      Python-first shape.
 *
 *   3. The in-process cache is consulted before any HTTP call and is
 *      written on success.
 *
 * Tests use vitest's fake timers and a stubbed global `fetch` —
 * no real NSE or Python calls.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cache } from '@/lib/cache';
import { __resetThrottleStateForTests } from '@/lib/nseThrottle';
import {
  fetchChangeRangesWithFallback,
  fetchSymbolDataWithFallback,
} from '@/lib/marketWsStreamer';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function errorResponse(status: number, text = 'upstream down'): Response {
  return new Response(text, { status });
}

interface FetchCall {
  url: string;
  init?: RequestInit;
}

/**
 * URL-aware fetch spy. The responder is chosen by predicate
 * (URL substring match), so a test can route Python calls to one
 * responder and NSE calls to another.
 */
function makeUrlRoutedFetchSpy(
  routes: Array<{ match: (url: string) => boolean; respond: (call: FetchCall) => Response | Promise<Response> }>,
) {
  const calls: FetchCall[] = [];
  const spy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = typeof url === 'string' ? url : url.toString();
    calls.push({ url: u, init });
    const call: FetchCall = { url: u, init };
    for (const route of routes) {
      if (route.match(u)) {
        return route.respond(call);
      }
    }
    throw new Error(`fetch called with no matching route: ${u}`);
  });
  return { spy, calls };
}

const isPythonSymbolData = (url: string): boolean => url.includes('/api/markets/symbol-data');
const isPythonChangeRanges = (url: string): boolean => url.includes('/api/markets/change-ranges');
const isNse = (url: string): boolean => url.includes('nseindia.com');

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

describe('fetchSymbolDataWithFallback', () => {
  it('returns the extracted shape when Python returns the raw NSE payload', async () => {
    const raw = {
      equityResponse: [
        {
          orderBook: { lastPrice: 1284.5 },
          metaData: { pChange: 1.23 },
          priceInfo: { yearHigh: 1350, yearLow: 980 },
        },
      ],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: isPythonSymbolData,
        respond: () => jsonResponse({ data: { RELIANCE: raw } }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('RELIANCE');
    expect(out).toEqual({ ltp: 1284.5, pChange: 1.23, yearHigh: 1350, yearLow: 980 });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=RELIANCE`,
    );
  });

  it('falls back to NSE when Python fails', async () => {
    const raw = {
      equityResponse: [
        { orderBook: { lastPrice: 1300 }, metaData: { pChange: 0.5 } },
      ],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonSymbolData, respond: () => errorResponse(500, 'python down') },
      { match: isNse, respond: () => jsonResponse(raw) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('RELIANCE');
    expect(out).toEqual({ ltp: 1300, pChange: 0.5, yearHigh: undefined, yearLow: undefined });
    // One Python attempt, then one successful NSE attempt.
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toBe(
      `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=RELIANCE`,
    );
    expect(calls[1].url).toContain('nseindia.com');
  });

  it('falls back to NSE when Python returns no value', async () => {
    const raw = {
      equityResponse: [
        { orderBook: { lastPrice: 3450 }, metaData: { pChange: -0.5 } },
      ],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonSymbolData, respond: () => jsonResponse({ data: {} }) },
      { match: isNse, respond: () => jsonResponse(raw) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('TCS');
    expect(out).toEqual({ ltp: 3450, pChange: -0.5, yearHigh: undefined, yearLow: undefined });
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain('nseindia.com');
  });

  it('returns null when both Python and NSE miss', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonSymbolData, respond: () => jsonResponse({ data: {} }) },
      { match: isNse, respond: () => jsonResponse({ metadata: {} }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('ARROWGREEN');
    expect(out).toBeNull();
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain('nseindia.com');
  });

  it('returns null after 3 NSE failures when Python also fails', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonSymbolData, respond: () => errorResponse(500, 'python down') },
      { match: isNse, respond: () => errorResponse(500) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('INFY');
    expect(out).toBeNull();
    // One Python attempt + three NSE attempts.
    expect(calls).toHaveLength(4);
    expect(calls[0].url).toBe(
      `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=INFY`,
    );
    expect(calls[1].url).toContain('nseindia.com');
    expect(calls[2].url).toContain('nseindia.com');
    expect(calls[3].url).toContain('nseindia.com');
  });

  it('uses the Python result when the NSE circuit breaker is open', async () => {
    // Trip the NSE breaker by recording five consecutive NSE failures.
    // Python also fails during warm-up, so each call reaches NSE.
    const { spy: tripper } = makeUrlRoutedFetchSpy([
      { match: isPythonSymbolData, respond: () => errorResponse(500) },
      { match: isNse, respond: () => errorResponse(500) },
    ]);
    vi.stubGlobal('fetch', tripper as unknown as typeof fetch);

    for (let i = 0; i < 5; i++) {
      await expect(fetchSymbolDataWithFallback('AAA')).resolves.toBeNull();
    }

    // The breaker is open. Python now succeeds, so no NSE call happens.
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: isPythonSymbolData,
        respond: () =>
          jsonResponse({
            data: {
              AAA: {
                equityResponse: [
                  { orderBook: { lastPrice: 2200 }, metaData: { pChange: 1.1 } },
                ],
              },
            },
          }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('AAA');
    expect(out).toEqual({ ltp: 2200, pChange: 1.1, yearHigh: undefined, yearLow: undefined });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=AAA`,
    );
  }, 20_000);
});

describe('fetchChangeRangesWithFallback', () => {
  it('returns the Python shape when Python returns camelCase data', async () => {
    const row = {
      oneDayPercent: 0.1,
      oneWeekPercent: 1.5,
      oneMonthPercent: 4.2,
      threeMonthPercent: null,
      sixMonthPercent: null,
      oneYearPercent: -9.1,
      twoYearPercent: null,
      threeYearPercent: null,
      fiveYearPercent: 19.7,
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: isPythonChangeRanges,
        respond: () => jsonResponse({ data: { RELIANCE: row } }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('RELIANCE');
    expect(out).toEqual(row);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(
      `${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=RELIANCE`,
    );
  });

  it('falls back to NSE bare arrays when Python returns no value', async () => {
    const row = {
      one_week_chng_per: 1.5,
      one_month_chng_per: 4.2,
      one_year_chng_per: -9.1,
      five_year_chng_per: 19.7,
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonChangeRanges, respond: () => jsonResponse({ data: {} }) },
      { match: isNse, respond: () => jsonResponse([row]) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('RELIANCE');
    expect(out).toEqual({
      oneDayPercent: null,
      oneWeekPercent: 1.5,
      oneMonthPercent: 4.2,
      threeMonthPercent: null,
      sixMonthPercent: null,
      oneYearPercent: -9.1,
      twoYearPercent: null,
      threeYearPercent: null,
      fiveYearPercent: 19.7,
    });
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain('getYearwiseData');
    expect(calls[1].url).toContain('symbol=RELIANCEEQN');
  });

  it('falls back to NSE {data: [...]} envelopes when Python fails', async () => {
    const row = { one_week_chng_per: 2.0 };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonChangeRanges, respond: () => errorResponse(500) },
      { match: isNse, respond: () => jsonResponse({ data: [row] }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('TCS');
    expect(out?.oneWeekPercent).toBe(2.0);
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toContain('nseindia.com');
  });

  it('returns null when both Python and NSE miss', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonChangeRanges, respond: () => jsonResponse({ data: {} }) },
      { match: isNse, respond: () => jsonResponse({ metadata: {} }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('ARROWGREEN');
    expect(out).toBeNull();
    expect(calls).toHaveLength(2);
  });

  it('returns null after 3 NSE failures when Python also fails', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: isPythonChangeRanges, respond: () => errorResponse(500) },
      { match: isNse, respond: () => errorResponse(500) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('INFY');
    expect(out).toBeNull();
    // One Python attempt + three NSE attempts.
    expect(calls).toHaveLength(4);
    expect(calls[0].url).toBe(
      `${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=INFY`,
    );
  });
});

describe('caching', () => {
  it('a second call within the TTL skips both Python and NSE', async () => {
    const raw = {
      equityResponse: [{ orderBook: { lastPrice: 1284.5 }, metaData: { pChange: 1.23 } }],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: isPythonSymbolData,
        respond: () => jsonResponse({ data: { RELIANCE: raw } }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const first = await fetchSymbolDataWithFallback('RELIANCE');
    expect(first?.ltp).toBe(1284.5);
    expect(calls).toHaveLength(1);

    const second = await fetchSymbolDataWithFallback('RELIANCE');
    expect(second).toEqual(first);
    expect(calls).toHaveLength(1);
  });
});

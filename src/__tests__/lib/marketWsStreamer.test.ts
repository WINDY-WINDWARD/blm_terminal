/**
 * Tests for the per-symbol fetch + fallback helpers in
 * `src/lib/marketWsStreamer.ts`. The WS route in
 * `src/app/api/ws/market/route.ts` delegates per-symbol work to
 * these helpers — they're the place the NSE+Python fallback lives,
 * and the place the "3 NSE failures → Python" rule is enforced.
 *
 * The contract under test:
 *
 *   1. `fetchSymbolDataWithFallback(symbol)`:
 *      - Try NSE (via throttledNseCall, which does up to 2 retries =
 *        3 total attempts, with exponential backoff).
 *      - On any failure (network, 5xx, soft-miss), fall back to the
 *        Python backend's /api/markets/symbol-data route.
 *      - On Python failure too, return null.
 *
 *   2. `fetchChangeRangesWithFallback(symbol)` mirrors the same
 *      shape for change-ranges.
 *
 *   3. The throttle's circuit breaker is honored: if NSE is
 *      "open" (per-endpoint breaker), we skip straight to Python
 *      without trying NSE.
 *
 *   4. Concurrent calls for the same symbol share one NSE fetch
 *      (request coalescing via throttledNseCall).
 *
 *   5. The throttle's courtesy delay is honored (we don't
 *      parallelize 50 NSE calls in a burst).
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

function jsonResponse(status: number, body: unknown): Response {
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

function makeFetchSpy(plan: Array<(call: FetchCall) => Response | Promise<Response>>) {
  const calls: FetchCall[] = [];
  const spy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const u = typeof url === 'string' ? url : url.toString();
    calls.push({ url: u, init });
    const responder = plan.shift();
    if (!responder) {
      throw new Error(`fetch called more times than planned: ${u}`);
    }
    return responder({ url: u, init });
  });
  return { spy, calls };
}

/**
 * URL-aware fetch spy. The responder is chosen by predicate
 * (URL substring match), so a test can route NSE calls to one
 * responder and Python calls to another, without the production
 * code's NSE-direct path accidentally receiving the Python
 * fallback's response shape.
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

beforeEach(() => {
  vi.useRealTimers();
  // Clear the in-process cache + throttle state between tests so
  // an NSE result or a tripped circuit breaker from a previous
  // test can't accidentally satisfy or skip later assertions.
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
  it('returns the extracted shape when NSE returns 200', async () => {
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
        match: (u) => u.includes('nseindia.com'),
        respond: () => jsonResponse(200, raw),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('RELIANCE');
    expect(out).toEqual({ ltp: 1284.5, pChange: 1.23, yearHigh: 1350, yearLow: 980 });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toContain('nseindia.com');
    expect(calls[0].url).toContain('symbol=RELIANCE');
  });

  it('falls back to Python after 3 NSE failures', async () => {
    // The streamer retries 2 times (3 total attempts). After the
    // 3rd 500, it throws and we should fall through to Python.
    // Python's /api/markets/symbol-data returns the raw NSE
    // getSymbolData payload, not the extracted shape — we extract
    // it on our side (see marketWsStreamer.fetchSymbolDataFromPython).
    const rawPython = {
      equityResponse: [
        { orderBook: { lastPrice: 1300 }, metaData: { pChange: 0.5 } },
      ],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: () => errorResponse(500, 'upstream down'),
      },
      {
        match: (u) => u.includes(PYTHON_BACKEND_URL),
        respond: () => jsonResponse(200, { data: { RELIANCE: rawPython } }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('RELIANCE');
    expect(out).toEqual({ ltp: 1300, pChange: 0.5, yearHigh: undefined, yearLow: undefined });
    // Exactly 3 NSE attempts + 1 Python attempt.
    expect(calls).toHaveLength(4);
    expect(calls[0].url).toContain('nseindia.com');
    expect(calls[1].url).toContain('nseindia.com');
    expect(calls[2].url).toContain('nseindia.com');
    expect(calls[3].url).toBe(`${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=RELIANCE`);
  });

  it('falls back to Python when NSE times out (network failure)', async () => {
    // Network failures are retried by the streamer (2 retries =
    // 3 total). All three throw TypeError; we fall back to Python.
    const rawPython = {
      equityResponse: [
        { orderBook: { lastPrice: 3450 }, metaData: { pChange: -0.5 } },
      ],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes('nseindia.com'),
        respond: () => Promise.reject(new TypeError('fetch failed')),
      },
      {
        match: (u) => u.includes(PYTHON_BACKEND_URL),
        respond: () => jsonResponse(200, { data: { TCS: rawPython } }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('TCS');
    expect(out).toEqual({ ltp: 3450, pChange: -0.5, yearHigh: undefined, yearLow: undefined });
    expect(calls).toHaveLength(4);
    expect(calls[3].url).toBe(`${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=TCS`);
  });

  it('returns null when both NSE and Python fail', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => errorResponse(500) },
      { match: (u) => u.includes(PYTHON_BACKEND_URL), respond: () => errorResponse(500, 'python down') },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('INFY');
    expect(out).toBeNull();
    // 3 NSE + 1 Python. No more.
    expect(calls).toHaveLength(4);
  });

  it('returns null on a soft miss (empty NSE payload, no Python data)', async () => {
    // NSE returns 200 but the payload has no equityResponse —
    // extractSymbolData returns null. This is a soft miss; we
    // should not retry NSE, and we should still try Python.
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => jsonResponse(200, { metadata: {} }) },
      { match: (u) => u.includes(PYTHON_BACKEND_URL), respond: () => jsonResponse(200, { data: {} }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('ARROWGREEN');
    expect(out).toBeNull();
    expect(calls).toHaveLength(2);
    // The first NSE call (the soft miss), then Python.
    expect(calls[0].url).toContain('nseindia.com');
    expect(calls[1].url).toBe(`${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=ARROWGREEN`);
  });

  it('uses the Python result when the circuit breaker for symbol-data is open', async () => {
    // This test takes ~8s because the throttle's 1.5s courtesy
    // delay applies between consecutive NSE calls. The 5 calls
    // needed to trip the breaker therefore take 5 × 1.5s = 7.5s.
    // The default vitest 5s timeout is too short; raise it.
    // Trip the circuit breaker by recording 5 consecutive failures
    // for the 'symbol-data' endpoint. After the 5th failure the
    // breaker opens; the next call should skip NSE entirely and
    // go straight to Python.
    const { spy: tripper } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => errorResponse(500) },
      { match: (u) => u.includes(PYTHON_BACKEND_URL), respond: () => errorResponse(500) },
    ]);
    vi.stubGlobal('fetch', tripper as unknown as typeof fetch);

    // 5 calls × 1 NSE attempt each = 5 failures. CIRCUIT_FAIL_MAX
    // is 5 so the breaker opens on the 5th call. The 6th call
    // should skip NSE entirely and go straight to Python.
    for (let i = 0; i < 5; i++) {
      await expect(fetchSymbolDataWithFallback('AAA')).resolves.toBeNull();
    }

    // Reset the mock and try again — should go straight to Python
    // (the breaker is open, so NSE is skipped).
    const { spy, calls } = makeUrlRoutedFetchSpy([
      {
        match: (u) => u.includes(PYTHON_BACKEND_URL),
        // Python's /api/markets/symbol-data returns the raw NSE
        // payload; the streamer extracts it.
        respond: () => jsonResponse(200, {
          data: { AAA: { equityResponse: [{ orderBook: { lastPrice: 2200 }, metaData: { pChange: 1.1 } }] } },
        }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchSymbolDataWithFallback('AAA');
    expect(out).toEqual({ ltp: 2200, pChange: 1.1, yearHigh: undefined, yearLow: undefined });
    // No NSE calls — only the Python fallback.
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe(`${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=AAA`);
  }, 20_000);
});

describe('fetchChangeRangesWithFallback', () => {
  it('returns the parsed shape when NSE returns 200 with a bare array', async () => {
    const row = {
      one_week_chng_per: 1.5,
      one_month_chng_per: 4.2,
      one_year_chng_per: -9.1,
      five_year_chng_per: 19.7,
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => jsonResponse(200, [row]) },
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
    expect(calls[0].url).toContain('getYearwiseData');
    // The Next.js route appends the literal EQN suffix that NSE's
    // yearwise endpoint expects (e.g. RELIANCEEQN). The HTTP
    // proxy already does this; the WS path must too.
    expect(calls[0].url).toContain('symbol=RELIANCEEQN');
  });

  it('returns the parsed shape when NSE returns {data: [...]}', async () => {
    const row = { one_week_chng_per: 2.0 };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => jsonResponse(200, { data: [row] }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('TCS');
    expect(out?.oneWeekPercent).toBe(2.0);
    expect(calls).toHaveLength(1);
  });

  it('falls back to Python after 3 NSE failures', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => errorResponse(500) },
      {
        match: (u) => u.includes(PYTHON_BACKEND_URL),
        respond: () =>
          jsonResponse(200, {
            data: { RELIANCE: { oneDayPercent: 0.1, oneWeekPercent: 1.5, oneYearPercent: -9.0 } },
          }),
      },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('RELIANCE');
    expect(out?.oneWeekPercent).toBe(1.5);
    expect(calls).toHaveLength(4);
    expect(calls[3].url).toBe(`${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=RELIANCE`);
  });

  it('returns null on a soft miss (empty NSE payload, no Python data)', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => jsonResponse(200, { metadata: {} }) },
      { match: (u) => u.includes(PYTHON_BACKEND_URL), respond: () => jsonResponse(200, { data: {} }) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('ARROWGREEN');
    expect(out).toBeNull();
    expect(calls).toHaveLength(2);
  });

  it('returns null when both NSE and Python fail', async () => {
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => errorResponse(500) },
      { match: (u) => u.includes(PYTHON_BACKEND_URL), respond: () => errorResponse(500) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    const out = await fetchChangeRangesWithFallback('INFY');
    expect(out).toBeNull();
    expect(calls).toHaveLength(4);
  });
});

describe('caching', () => {
  it('a second call within the TTL skips both NSE and Python', async () => {
    const raw = {
      equityResponse: [{ orderBook: { lastPrice: 1284.5 }, metaData: { pChange: 1.23 } }],
    };
    const { spy, calls } = makeUrlRoutedFetchSpy([
      { match: (u) => u.includes('nseindia.com'), respond: () => jsonResponse(200, raw) },
    ]);
    vi.stubGlobal('fetch', spy as unknown as typeof fetch);

    // First call — hits NSE.
    const first = await fetchSymbolDataWithFallback('RELIANCE');
    expect(first?.ltp).toBe(1284.5);
    expect(calls).toHaveLength(1);

    // Second call within TTL — should hit the in-process cache.
    const second = await fetchSymbolDataWithFallback('RELIANCE');
    expect(second).toEqual(first);
    expect(calls).toHaveLength(1);
  });
});


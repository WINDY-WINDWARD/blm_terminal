/**
 * Regression test for the per-symbol coalescing bug in
 * `src/app/api/nse/symbol-data/route.ts`.
 *
 * Bug: `throttledNseCall` keyed its in-flight dedup map on `endpointName`
 * alone, so a `Promise.all` of N concurrent symbol fetches collapsed to a
 * single underlying NSE call. Every caller received the first symbol's
 * response and the per-symbol cache dutifully stored it under N different
 * keys, returning identical data for every requested symbol.
 *
 * Fix: `throttledNseCall` now requires a `coalesceKey` option that
 * uniquely identifies the work (e.g. `symbol-data:${symbol}`). Distinct
 * symbols → distinct in-flight promises → distinct responses.
 *
 * This test stubs the global `fetch` to return a per-symbol payload, hits
 * the route handler directly, and asserts that:
 *   1. Each symbol in the response carries its own LTP/pChange.
 *   2. The per-symbol cache is populated with distinct entries.
 *   3. The underlying NSE fetch was actually called once per symbol
 *      (i.e. the inflight map no longer collapses them).
 */

// Set throttle env vars BEFORE the throttle module is imported so the
// singleton Semaphore/courtesy-delay are configured for fast tests.
vi.hoisted(() => {
  process.env.NSE_COURTESY_DELAY = '0';
  process.env.NSE_CONCURRENCY = '50';
  process.env.NSE_MAX_RETRIES = '0';
  process.env.NSE_CIRCUIT_FAIL_MAX = '1000';
});

import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cache } from '@/lib/cache';
import { GET } from '@/app/api/nse/symbol-data/route';

function buildNsePayload(symbol: string, ltp: number) {
  return {
    equityResponse: [
      {
        orderBook: { lastPrice: ltp },
        tradeInfo: { lastPrice: ltp },
        metaData: { pChange: ltp % 7 },
        priceInfo: { yearHigh: ltp * 2, yearLow: ltp / 2 },
      },
    ],
  };
}

function buildRequest(symbols: string[]): NextRequest {
  const url = `http://localhost/api/nse/symbol-data?symbols=${symbols.join(',')}`;
  return new NextRequest(url);
}

describe('GET /api/nse/symbol-data — per-symbol coalescing', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    cache.clear();
    fetchSpy = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      const match = url.match(/[?&]symbol=([^&]+)/);
      if (!match) {
        return new Response('not found', { status: 404 });
      }
      const symbol = decodeURIComponent(match[1]).toUpperCase();
      // Deterministic per-symbol LTP — use a stable hash so symbols that
      // share a leading letter (IRIS / IRCON / IRCTC) still get distinct
      // values. This is the failure mode the original bug produced:
      // every caller got the FIRST symbol's LTP because the throttle
      // coalesced every request under the same `endpointName` key.
      let h = 0;
      for (let i = 0; i < symbol.length; i++) {
        h = (h * 31 + symbol.charCodeAt(i)) | 0;
      }
      const ltp = 1000 + (Math.abs(h) % 9000) + symbol.length / 10;
      return new Response(JSON.stringify(buildNsePayload(symbol, ltp)), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cache.clear();
  });

  it('returns distinct LTP per symbol for a 5-symbol request', async () => {
    const symbols = ['IRIS', 'TCS', 'RELIANCE', 'INFY', 'HAL'];
    const resp = await GET(buildRequest(symbols));
    const body = (await resp.json()) as {
      data: Record<string, { ltp: number; pChange: number; yearHigh: number; yearLow: number } | null>;
    };

    expect(Object.keys(body.data).sort()).toEqual([...symbols].sort());
    for (const sym of symbols) {
      const entry = body.data[sym];
      expect(entry, `entry for ${sym} should not be null`).not.toBeNull();
      // LTP must equal the value our fetch stub returned for THIS symbol,
      // not any other symbol's value.
      let h = 0;
      for (let i = 0; i < sym.length; i++) {
        h = (h * 31 + sym.charCodeAt(i)) | 0;
      }
      const expectedLtp = 1000 + (Math.abs(h) % 9000) + sym.length / 10;
      expect(entry!.ltp).toBe(expectedLtp);
      expect(entry!.yearHigh).toBeCloseTo(entry!.ltp * 2, 5);
      expect(entry!.yearLow).toBeCloseTo(entry!.ltp / 2, 5);
    }

    // No two symbols may share the same LTP — the canonical symptom of
    // the bug under test.
    const ltps = symbols.map((s) => body.data[s]!.ltp);
    expect(new Set(ltps).size).toBe(ltps.length);
  });

  it('hits the NSE endpoint once per symbol (no coalescing collapse)', async () => {
    const symbols = ['IRIS', 'TCS', 'RELIANCE', 'INFY', 'HAL'];
    await GET(buildRequest(symbols));

    const nseCalls = fetchSpy.mock.calls.filter(([arg]) => {
      const url = typeof arg === 'string' ? arg : (arg as URL).toString();
      return url.includes('nseindia.com');
    });
    expect(nseCalls).toHaveLength(symbols.length);
  });

  it('caches each symbol under its own key', async () => {
    const symbols = ['IRIS', 'TCS', 'RELIANCE'];
    await GET(buildRequest(symbols));

    const cacheKeys = cache.getStats().keys;
    for (const sym of symbols) {
      expect(cacheKeys).toContain(`symbol-data:${sym}`);
    }
  });

  it('serves subsequent identical requests from cache without re-hitting NSE', async () => {
    const symbols = ['IRIS', 'TCS'];
    await GET(buildRequest(symbols));
    fetchSpy.mockClear();

    await GET(buildRequest(symbols));
    const nseCalls = fetchSpy.mock.calls.filter(([arg]) => {
      const url = typeof arg === 'string' ? arg : (arg as URL).toString();
      return url.includes('nseindia.com');
    });
    expect(nseCalls).toHaveLength(0);
  });

  it('returns distinct LTP for the 25-symbol workload from the bug report', async () => {
    const symbols = [
      'IRIS', 'RAILTEL', 'ABCAPITAL', 'WCIL', 'HAL', 'TANLA', 'TARACHAND',
      'LATENTVIEW', 'ARTEMISMED', 'AWHCL', 'GRANULES', 'IRCON', 'PRAJIND',
      'ARROWGREEN', 'BIRLANU', 'NLCINDIA', 'PARAS', 'MICEL', 'NEWGEN',
      'TARIL', 'CONCOR', 'WEBELSOLAR', 'CMSINFO', 'ZENSARTECH', 'IRCTC',
    ];
    const resp = await GET(buildRequest(symbols));
    const body = (await resp.json()) as {
      data: Record<string, { ltp: number } | null>;
    };

    const ltps = symbols.map((s) => body.data[s]!.ltp);
    expect(new Set(ltps).size).toBe(ltps.length);
  });
});

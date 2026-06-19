/**
 * Regression tests for the NSE response-shape handling in
 * `src/app/api/nse/change-ranges/route.ts`.
 *
 * NSE's `getYearwiseData` endpoint returns:
 *   - `[ { ...row... } ]` for symbols with yearwise data
 *   - `{ data: [ { ...row... } ] }` for some symbols
 *   - an object/empty payload for unknown / too-new symbols (e.g. ARROWGREEN)
 *
 * The pre-fix handler treated anything that wasn't a non-empty array as
 * a hard error, which:
 *   1. Tripped the NSE circuit breaker as if NSE itself were down.
 *   2. Surfaced an `unhandledRejection` to the Node process.
 *
 * The fix is to return `null` (a soft miss) for the third case.
 */

import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.hoisted(() => {
  process.env.NSE_COURTESY_DELAY = '0';
  process.env.NSE_CONCURRENCY = '50';
  process.env.NSE_MAX_RETRIES = '0';
  process.env.NSE_CIRCUIT_FAIL_MAX = '1000';
});

import { cache } from '@/lib/cache';
import { GET } from '@/app/api/nse/change-ranges/route';

function buildRequest(symbols: string[]): NextRequest {
  const url = `http://localhost/api/nse/change-ranges?symbols=${symbols.join(',')}`;
  return new NextRequest(url);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('GET /api/nse/change-ranges — response shape tolerance', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    cache.clear();
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cache.clear();
  });

  it('parses bare array payloads', async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse([
        {
          one_week_chng_per: '2.5',
          one_month_chng_per: '5.0',
        },
      ]),
    );

    const resp = await GET(buildRequest(['RELIANCE']));
    const body = (await resp.json()) as { data: Record<string, unknown> };

    expect(body.data.RELIANCE).toEqual({
      oneDayPercent: null,
      oneWeekPercent: 2.5,
      oneMonthPercent: 5.0,
      threeMonthPercent: null,
      sixMonthPercent: null,
      oneYearPercent: null,
      twoYearPercent: null,
      threeYearPercent: null,
      fiveYearPercent: null,
    });
  });

  it('parses { data: [...] } envelopes', async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        data: [{ one_week_chng_per: '1.1' }],
      }),
    );

    const resp = await GET(buildRequest(['TCS']));
    const body = (await resp.json()) as { data: Record<string, { oneWeekPercent: number | null }> };

    expect(body.data.TCS.oneWeekPercent).toBe(1.1);
  });

  it('returns null for unknown symbols (regression for ARROWGREEN)', async () => {
    // NSE returns an object body for symbols it doesn't have yearwise
    // data for. The route must treat that as a soft miss, not a hard
    // error that trips the circuit breaker.
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ message: 'No data', errorCode: 'NO_DATA' }),
    );

    const resp = await GET(buildRequest(['ARROWGREEN']));
    const body = (await resp.json()) as { data: Record<string, unknown> };

    expect(resp.status).toBe(200);
    expect(body.data.ARROWGREEN).toBeNull();
  });

  it('returns null for empty arrays', async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse([]));

    const resp = await GET(buildRequest(['NEWSTOCK']));
    const body = (await resp.json()) as { data: Record<string, unknown> };

    expect(body.data.NEWSTOCK).toBeNull();
  });

  it('does not trigger unhandledRejection when one symbol fails shape check', async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ message: 'No data' }), // ARROWGREEN: bad shape
    );
    fetchSpy.mockResolvedValueOnce(
      jsonResponse([{ one_week_chng_per: '3.0' }]), // TCS: valid
    );

    const resp = await GET(buildRequest(['ARROWGREEN', 'TCS']));
    await resp.json();
    await new Promise<void>((r) => setImmediate(r));
    process.off('unhandledRejection', onUnhandled);

    expect(unhandled).toEqual([]);
  });
});

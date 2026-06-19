/**
 * Unit tests for `throttledNseCall` coalescing behavior.
 *
 * The original implementation keyed the in-flight dedup map on
 * `endpointName` alone, which caused distinct requests against the same
 * endpoint (e.g. fetching different symbols) to share a single
 * underlying call. This test pins down the new `coalesceKey` contract.
 *
 * The route-level integration test
 * (`src/__tests__/api/symbol-data/route.test.ts`) is the canonical
 * end-to-end regression test. These unit tests are the focused,
 * fast-feedback complement: they exercise the real throttle singleton
 * directly so a regression in coalescing logic is caught even if the
 * route is refactored.
 *
 * Env vars are set in `vi.hoisted` (runs before any import) so the
 * throttle's module-level constants disable the production 1.5s
 * courtesy delay that would otherwise make these tests too slow.
 */

vi.hoisted(() => {
  process.env.NSE_COURTESY_DELAY = '0';
  process.env.NSE_CONCURRENCY = '50';
  process.env.NSE_MAX_RETRIES = '0';
  process.env.NSE_CIRCUIT_FAIL_MAX = '1000';
});

import { describe, expect, it, vi } from 'vitest';

import { throttledNseCall } from '@/lib/nseThrottle';

describe('throttledNseCall — coalesceKey contract', () => {
  it('passes through results from the underlying thunk', async () => {
    const fn = vi.fn(async () => 42);
    const out = await throttledNseCall('symbol-data', fn, {
      coalesceKey: 'symbol-data:RELIANCE',
    });
    expect(out).toBe(42);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('coalesces concurrent calls that share a coalesceKey', async () => {
    const fn = vi.fn(async () => 7);

    const [a, b, c] = await Promise.all([
      throttledNseCall('symbol-data', fn, { coalesceKey: 'symbol-data:RELIANCE' }),
      throttledNseCall('symbol-data', fn, { coalesceKey: 'symbol-data:RELIANCE' }),
      throttledNseCall('symbol-data', fn, { coalesceKey: 'symbol-data:RELIANCE' }),
    ]);

    expect([a, b, c]).toEqual([7, 7, 7]);
    // The original bug would have allowed this even with distinct keys;
    // with shared keys, exactly one underlying call should fire.
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('does NOT coalesce concurrent calls with different coalesceKeys (regression)', async () => {
    const fnA = vi.fn(async () => 100);
    const fnB = vi.fn(async () => 200);

    const [a, b] = await Promise.all([
      throttledNseCall('symbol-data', fnA, { coalesceKey: 'symbol-data:RELIANCE' }),
      throttledNseCall('symbol-data', fnB, { coalesceKey: 'symbol-data:TCS' }),
    ]);

    // The original bug would have collapsed these into a single call,
    // making both promises resolve to fnA's value (100). The fix uses
    // coalesceKey as the dedup key, so each gets its own result.
    expect(a).toBe(100);
    expect(b).toBe(200);
    expect(fnA).toHaveBeenCalledTimes(1);
    expect(fnB).toHaveBeenCalledTimes(1);
  });

  it('propagates rejected thunks to the caller (and does not log unhandledRejection)', async () => {
    // The pre-fix implementation used `promise.finally(cleanup)` to
    // remove the inflight entry. `.finally()` returns a NEW promise that
    // inherits the rejection state; since nobody awaited that new
    // promise, Node logged an `unhandledRejection` for every failed
    // NSE call (e.g. ARROWGREEN's "Unexpected getYearwiseData response
    // shape"). The fix replaces `.finally()` with `.then(cleanup, cleanup)`
    // so the rejection is observed exactly once — by the caller.
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on('unhandledRejection', onUnhandled);

    const boom = new Error('NSE returned 500');
    const fn = vi.fn(async () => {
      throw boom;
    });

    await expect(
      throttledNseCall('change-ranges', fn, {
        coalesceKey: 'change-ranges:ARROWGREEN',
      }),
    ).rejects.toBe(boom);

    // Allow a microtask to flush any spurious unhandledRejection events.
    await new Promise<void>((r) => setImmediate(r));
    process.off('unhandledRejection', onUnhandled);

    expect(unhandled).toEqual([]);
  });
});

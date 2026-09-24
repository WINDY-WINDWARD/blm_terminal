import { describe, expect, it } from 'vitest';
import {
  brewDaily,
  brewIntraday,
  brewScriptBars,
  intradayBucketStart,
  isBrewableInterval,
  istDateBarTime,
  istParts,
  LIVE_STALE_MS,
  shouldBrew,
  type BrewInput,
} from './liveBar';

// Fixed clock: 2026-09-24 10:30:00 IST (Thursday) = 05:00:00 UTC.
const NOW = Date.UTC(2026, 8, 24, 5, 0, 0);
const TODAY = Date.UTC(2026, 8, 24, 0, 0, 0) / 1000;
const YDAY = Date.UTC(2026, 8, 23, 0, 0, 0) / 1000;

const bar = (time: number, c = 100, v = 1000): BrewInput => ({
  time,
  o: 99,
  h: 101,
  l: 98,
  c,
  v,
});

describe('shouldBrew', () => {
  it('brews on a fresh tick in market hours', () => {
    expect(shouldBrew({ ltp: 100, updatedAt: NOW - 30_000 }, NOW, true)).toBe(true);
  });
  it('refuses ticks older than 2 minutes (L4)', () => {
    expect(LIVE_STALE_MS).toBe(120_000);
    expect(shouldBrew({ ltp: 100, updatedAt: NOW - 121_000 }, NOW, true)).toBe(false);
    expect(shouldBrew({ ltp: 100, updatedAt: NOW - 119_000 }, NOW, true)).toBe(true);
  });
  it('refuses null tick, closed market, bad prices, future stamps', () => {
    expect(shouldBrew(null, NOW, true)).toBe(false);
    expect(shouldBrew({ ltp: 100, updatedAt: NOW }, NOW, false)).toBe(false);
    expect(shouldBrew({ ltp: 0, updatedAt: NOW }, NOW, true)).toBe(false);
    expect(shouldBrew({ ltp: NaN, updatedAt: NOW }, NOW, true)).toBe(false);
    expect(shouldBrew({ ltp: 100, updatedAt: NOW + 60_000 }, NOW, true)).toBe(false);
  });
});

describe('ist helpers', () => {
  it('splits 10:30 IST correctly (Thursday)', () => {
    expect(istParts(NOW)).toEqual({ y: 2026, m: 9, d: 24, mins: 630, day: 4 });
  });
  it('matches the server daily bar time convention', () => {
    expect(istDateBarTime(2026, 9, 24)).toBe(TODAY);
  });
});

describe('intradayBucketStart', () => {
  it('anchors 1h buckets at the 09:15 open (10:30 -> 10:15)', () => {
    const open = Math.floor(Date.UTC(2026, 8, 24, 3, 45, 0) / 1000); // 09:15 IST
    expect(intradayBucketStart(NOW, '1h')).toBe(open + 3600);
  });
  it('aligns 5m buckets to the clock (10:30 -> 10:30)', () => {
    expect(intradayBucketStart(NOW, '5m')).toBe(Math.floor(NOW / 1000));
  });
  it('clamps pre-market to the first bucket', () => {
    const pre = Date.UTC(2026, 8, 24, 2, 30, 0); // 08:00 IST
    const open = Math.floor(Date.UTC(2026, 8, 24, 3, 45, 0) / 1000);
    expect(intradayBucketStart(pre, '5m')).toBe(open);
  });
  it('returns null for W/M/unknown', () => {
    expect(intradayBucketStart(NOW, 'W')).toBeNull();
    expect(intradayBucketStart(NOW, 'M')).toBeNull();
    expect(intradayBucketStart(NOW, 'D')).toBeNull();
  });
  it('isBrewableInterval covers 1m-1h only', () => {
    for (const i of ['1m', '5m', '15m', '30m', '1h']) expect(isBrewableInterval(i)).toBe(true);
    for (const i of ['D', 'W', 'M', 'tick']) expect(isBrewableInterval(i)).toBe(false);
  });
});

describe('brewDaily', () => {
  it('appends a forming bar when history ends yesterday', () => {
    const out = brewDaily([bar(YDAY, 100, 5000)], 105, NOW);
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ time: YDAY, c: 100, v: 5000 });
    expect(out[0].live).toBeUndefined();
    expect(out[1]).toMatchObject({
      time: TODAY,
      o: 105,
      h: 105,
      l: 105,
      c: 105,
      v: 0,
      live: true,
    });
  });
  it('updates today in place, keeping open and volume', () => {
    const out = brewDaily([bar(YDAY, 100, 5000), bar(TODAY, 102, 7000)], 90, NOW);
    expect(out).toHaveLength(2);
    expect(out[1]).toMatchObject({ time: TODAY, o: 99, h: 101, l: 90, c: 90, v: 7000, live: true });
  });
  it('brews a single bar from empty history', () => {
    const out = brewDaily([], 50, NOW);
    expect(out).toEqual([{ time: TODAY, o: 50, h: 50, l: 50, c: 50, v: 0, live: true }]);
  });
  it('never appends into the future on clock skew', () => {
    const future = TODAY + 86_400;
    const out = brewDaily([bar(future, 100, 5000)], 105, NOW);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ time: future, c: 105, live: true });
  });
  it('does not mutate the input', () => {
    const input = [bar(YDAY, 100, 5000)];
    brewDaily(input, 105, NOW);
    expect(input).toHaveLength(1);
    expect(input[0].live).toBeUndefined();
  });
});

describe('brewIntraday', () => {
  const bucket5 = Math.floor(NOW / 1000); // 10:30 IST, 5m-aligned
  it('updates the forming bucket in place', () => {
    const out = brewIntraday([bar(bucket5 - 300, 100, 2000), bar(bucket5, 101, 3000)], 95, NOW, '5m');
    expect(out).toHaveLength(2);
    expect(out[1]).toMatchObject({ time: bucket5, o: 99, h: 101, l: 95, c: 95, v: 3000, live: true });
  });
  it('rolls over to a new bucket with flat volume', () => {
    const out = brewIntraday([bar(bucket5 - 600, 100, 2000)], 107, NOW, '5m');
    expect(out).toHaveLength(2);
    expect(out[1]).toMatchObject({
      time: bucket5,
      o: 107,
      h: 107,
      l: 107,
      c: 107,
      v: 0,
      live: true,
    });
  });
  it('updates a misaligned newer server bar in place', () => {
    const out = brewIntraday([bar(bucket5 + 60, 100, 2000)], 107, NOW, '5m');
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ time: bucket5 + 60, c: 107, live: true });
  });
  it('returns W/M bars untouched', () => {
    const input = [bar(bucket5 - 300, 100, 2000)];
    expect(brewIntraday(input, 107, NOW, 'W')).toHaveLength(1);
    const out = brewIntraday(input, 107, NOW, 'W');
    expect(out[0].live).toBeUndefined();
    expect(out[0].c).toBe(100);
  });
  it('brews a single bucket from empty history', () => {
    const out = brewIntraday([], 50, NOW, '1m');
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ o: 50, c: 50, v: 0, live: true });
  });
});

describe('brewScriptBars', () => {
  it('flags the live bar and keeps v defined (NaN guard)', () => {
    const out = brewScriptBars(
      [
        { time: YDAY, o: 99, h: 101, l: 98, c: 100, v: 5000 },
      ],
      105,
      NOW,
      null,
    );
    expect(out).toHaveLength(2);
    expect(out[1].live).toBe(true);
    for (const b of out) expect(typeof b.v).toBe('number');
  });
});

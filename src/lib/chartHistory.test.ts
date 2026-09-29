/**
 * Tests for in-memory chart history backfill (merge, cache TTL, windows).
 * Extended history is never persisted — cache entries expire after 2h.
 */
import { describe, expect, it } from 'vitest';
import {
  BACKFILL_TRIGGER_BARS,
  EMPTY_STOP_STREAK,
  HISTORY_CACHE_TTL_MS,
  HistoryCache,
  backfillCacheAction,
  backfillChunkSpanMs,
  dailyBackfillRange,
  historyCacheKey,
  intradayBackfillRange,
  mapDailyCandles,
  mapIntradayCandles,
  mergeHistoryBars,
  shouldBackfill,
  type DailyCandleLike,
  type IntradayCandleLike,
} from './chartHistory';
import type { BrewInput } from './scripts/liveBar';

const bar = (time: number, c = time): BrewInput => ({ time, o: c, h: c, l: c, c, v: 1 });

describe('mergeHistoryBars', () => {
  it('prepends older bars and sorts ascending', () => {
    const out = mergeHistoryBars([bar(3), bar(4)], [bar(1), bar(2)]);
    expect(out.map((b) => b.time)).toEqual([1, 2, 3, 4]);
  });

  it('dedupes overlap with base winning', () => {
    const out = mergeHistoryBars([bar(2, 99), bar(3)], [bar(1), bar(2, 5)]);
    expect(out.map((b) => b.time)).toEqual([1, 2, 3]);
    expect(out[1].c).toBe(99);
  });

  it('handles empty sides', () => {
    expect(mergeHistoryBars([], [bar(2), bar(1)]).map((b) => b.time)).toEqual([1, 2]);
    expect(mergeHistoryBars([bar(1)], []).map((b) => b.time)).toEqual([1]);
  });
});

describe('mappers match chart conventions', () => {
  it('daily uses midnight-UTC keys', () => {
    const rows: DailyCandleLike[] = [
      { Date: '2026-09-28', open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
    ];
    const [b] = mapDailyCandles(rows);
    expect(b.time).toBe(new Date('2026-09-28T00:00:00Z').getTime() / 1000);
    expect(b).toMatchObject({ o: 1, h: 2, l: 0.5, c: 1.5, v: 10 });
  });

  it('intraday floors NSE ms to seconds', () => {
    const rows: IntradayCandleLike[] = [
      { timestamp: 1_758_000_000_123, open: 1, high: 1, low: 1, close: 1, volume: 5 },
    ];
    expect(mapIntradayCandles(rows)[0].time).toBe(1_758_000_000);
  });
});

describe('HistoryCache', () => {
  it('returns entries within TTL and expires after 2h', () => {
    const cache = new HistoryCache();
    cache.set('k', [bar(1)], 1_000);
    expect(cache.get('k', 1_000 + HISTORY_CACHE_TTL_MS - 1)).toHaveLength(1);
    expect(cache.get('k', 1_000 + HISTORY_CACHE_TTL_MS + 1)).toBeNull();
  });

  it('sweeps stale entries on set', () => {
    const cache = new HistoryCache();
    cache.set('old', [bar(1)], 0);
    cache.set('new', [bar(2)], HISTORY_CACHE_TTL_MS + 10);
    expect(cache.size).toBe(1);
    expect(cache.get('new', HISTORY_CACHE_TTL_MS + 10)).toHaveLength(1);
  });

  it('clearPrefix drops one symbol|interval only', () => {
    const cache = new HistoryCache();
    cache.set('RELIANCE|D|a', [bar(1)]);
    cache.set('TCS|D|a', [bar(2)]);
    cache.clearPrefix('RELIANCE|D');
    expect(cache.get('RELIANCE|D|a')).toBeNull();
    expect(cache.get('TCS|D|a')).toHaveLength(1);
  });

  it('keys include symbol, interval, window start', () => {
    expect(historyCacheKey('RELIANCE', 'D', '01-01-2024')).toBe('RELIANCE|D|01-01-2024');
  });
});

describe('windows and trigger', () => {
  it('daily chunk is a 2-year window ending the day before oldest', () => {
    const oldest = new Date('2026-09-28T00:00:00Z').getTime() / 1000;
    const { fromDate, toDate } = dailyBackfillRange(oldest);
    expect(toDate).toBe('27-09-2026');
    expect(fromDate).toBe('27-09-2024');
  });

  it('intraday chunk spans stay NSE-safe; W backfills, M null', () => {
    const oldest = 1_758_000_000;
    const r = intradayBackfillRange(oldest, '1m');
    expect(r).not.toBeNull();
    expect(r!.toTsMs).toBe(oldest * 1000 - 1000);
    expect(r!.toTsMs - r!.fromTsMs).toBe(10 * 86_400_000);
    // Oversize windows used to come back newest-capped (dupes only): capped now.
    expect(backfillChunkSpanMs('15m')).toBe(30 * 86_400_000);
    expect(backfillChunkSpanMs('30m')).toBe(30 * 86_400_000);
    expect(backfillChunkSpanMs('1h')).toBe(90 * 86_400_000);
    expect(backfillChunkSpanMs('W')).toBe(365 * 86_400_000);
    expect(intradayBackfillRange(oldest, 'W')).not.toBeNull();
    expect(intradayBackfillRange(oldest, 'M')).toBeNull();
    expect(backfillChunkSpanMs('nope')).toBeNull();
  });

  it('backfillCacheAction: empties never cached, only network empties count', () => {
    expect(backfillCacheAction({ fromCache: false, count: 12 })).toBe('store');
    expect(backfillCacheAction({ fromCache: true, count: 12 })).toBe('store');
    // A transient NSE failure must not poison the next 2h or kill backfill.
    expect(backfillCacheAction({ fromCache: false, count: 0 })).toBe('count-empty');
    expect(backfillCacheAction({ fromCache: true, count: 0 })).toBe('ignore');
  });

  it('triggers only near logical bar 0', () => {
    expect(shouldBackfill(10)).toBe(true);
    expect(shouldBackfill(BACKFILL_TRIGGER_BARS - 1)).toBe(true);
    expect(shouldBackfill(BACKFILL_TRIGGER_BARS)).toBe(false);
    expect(shouldBackfill(500)).toBe(false);
    expect(shouldBackfill(null)).toBe(false);
    expect(shouldBackfill(undefined)).toBe(false);
    expect(shouldBackfill(NaN)).toBe(false);
  });

  it('stop streak constant is 2 (single empty = holiday)', () => {
    expect(EMPTY_STOP_STREAK).toBe(2);
  });
});

/**
 * Chart history backfill — in-memory extended history.
 *
 * Extended (scrolled-back) bars are NEVER persisted: no react-query cache,
 * no localStorage, no IndexedDB, and the backend serves them without DB
 * writes. They live in `historyCache` (2h TTL) plus a per-chart ref, and
 * vanish on symbol/interval switch or unmount.
 */
import type { BrewInput } from './scripts/liveBar';

/** Extended-history entries expire 2h after fetch (lazy sweep on access). */
export const HISTORY_CACHE_TTL_MS = 2 * 60 * 60_000;
/** Fetch older history when the visible left edge is within N bars of bar 0. */
export const BACKFILL_TRIGGER_BARS = 50;
/** Never backfill older than ~2 years. */
export const HISTORY_MAX_AGE_S = 2 * 365 * 86_400;
/** Stop asking after this many consecutive empty windows (1 empty = holiday). */
export const EMPTY_STOP_STREAK = 2;
/** Daily backfill chunk: 2 years per fetch. */
export const DAILY_CHUNK_DAYS = 2 * 365;

/** Intraday backfill chunk per fetch, in ms. Null = no backfill (M loads full history).
 * Spans stay within what NSE returns in one call — oversize windows come back
 * newest-capped (mostly dupes), so the chart never visibly grows. */
export function backfillChunkSpanMs(interval: string): number | null {
  const day = 86_400_000;
  switch (interval) {
    case '1m':
      return 10 * day;
    case '5m':
      return 30 * day;
    case '15m':
    case '30m':
      return 30 * day;
    case '1h':
      return 90 * day;
    case 'W':
      return 365 * day;
    default:
      return null;
  }
}

export interface DailyCandleLike {
  Date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IntradayCandleLike {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Same mapping as the chart render (midnight-UTC keys for daily). */
export function mapDailyCandles(candles: DailyCandleLike[]): BrewInput[] {
  return candles.map((candle) => ({
    time: new Date(candle.Date + 'T00:00:00Z').getTime() / 1000,
    o: candle.open,
    h: candle.high,
    l: candle.low,
    c: candle.close,
    v: candle.volume,
  }));
}

/** Same mapping as the chart render (NSE ms → seconds). */
export function mapIntradayCandles(candles: IntradayCandleLike[]): BrewInput[] {
  return candles.map((candle) => ({
    time: Math.floor(candle.timestamp / 1000),
    o: candle.open,
    h: candle.high,
    l: candle.low,
    c: candle.close,
    v: candle.volume,
  }));
}

/**
 * Merge an older (backfilled) window under the base array. Base wins ties
 * (same source, identical values), output is strictly ascending and deduped —
 * lightweight-charts setData throws or crashes on unsorted/duplicate times.
 */
export function mergeHistoryBars(base: BrewInput[], older: BrewInput[]): BrewInput[] {
  if (older.length === 0 && base.length === 0) return [];
  const map = new Map<number, BrewInput>();
  // Older first so base overwrites older on timestamp collision
  for (const b of older) {
    if (typeof b?.time === 'number' && Number.isFinite(b.time)) {
      map.set(b.time, b);
    }
  }
  for (const b of base) {
    if (typeof b?.time === 'number' && Number.isFinite(b.time)) {
      map.set(b.time, b);
    }
  }
  return Array.from(map.values()).sort((a, b) => a.time - b.time);
}

interface CacheEntry {
  bars: BrewInput[];
  fetchedAt: number;
}

/** Keyed by symbol|interval|window-start; TTL-evicted, never persisted. */
export class HistoryCache {
  private entries = new Map<string, CacheEntry>();

  get(key: string, now: number = Date.now()): BrewInput[] | null {
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (now - entry.fetchedAt > HISTORY_CACHE_TTL_MS) {
      this.entries.delete(key);
      return null;
    }
    return entry.bars;
  }

  set(key: string, bars: BrewInput[], now: number = Date.now()): void {
    this.sweep(now);
    this.entries.set(key, { bars, fetchedAt: now });
  }

  clearPrefix(prefix: string): void {
    for (const key of [...this.entries.keys()]) {
      if (key.startsWith(prefix)) this.entries.delete(key);
    }
  }

  clear(): void {
    this.entries.clear();
  }

  sweep(now: number = Date.now()): void {
    for (const [key, entry] of this.entries) {
      if (now - entry.fetchedAt > HISTORY_CACHE_TTL_MS) this.entries.delete(key);
    }
  }

  get size(): number {
    return this.entries.size;
  }
}

export const historyCache = new HistoryCache();

export function historyCacheKey(symbol: string, interval: string, windowStart: string): string {
  return `${symbol}|${interval}|${windowStart}`;
}

function toBackendDate(d: Date): string {
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  return `${day}-${month}-${d.getFullYear()}`;
}

/** Daily backfill window (DAILY_CHUNK_DAYS) ending the day before the oldest loaded bar. */
export function dailyBackfillRange(oldestSec: number): { fromDate: string; toDate: string } {
  const to = new Date((oldestSec - 86_400) * 1000);
  const from = new Date(to.getTime() - DAILY_CHUNK_DAYS * 86_400_000);
  return { fromDate: toBackendDate(from), toDate: toBackendDate(to) };
}

/** Intraday window: 2×-style chunk (see backfillChunkSpanMs) ending 1s before oldest. */
export function intradayBackfillRange(
  oldestSec: number,
  interval: string,
): { fromTsMs: number; toTsMs: number } | null {
  const span = backfillChunkSpanMs(interval);
  if (span === null) return null;
  const toTsMs = oldestSec * 1000 - 1000;
  return { fromTsMs: toTsMs - span, toTsMs };
}

/** Trigger when the visible left edge approaches logical bar 0 (oldest). */
export function shouldBackfill(visibleFrom: number | null | undefined): boolean {
  return typeof visibleFrom === 'number' && Number.isFinite(visibleFrom) && visibleFrom < BACKFILL_TRIGGER_BARS;
}

export interface BackfillOutcome {
  /** True when the window came from historyCache instead of the network. */
  fromCache: boolean;
  count: number;
}

/**
 * Cache/streak decision for a backfill window. Empty windows are NEVER
 * cached (a transient NSE failure must not poison the next 2h), and only a
 * genuine network empty counts toward the stop streak — a cache hit for a
 * window still in flight elsewhere must not kill backfill.
 */
export function backfillCacheAction(out: BackfillOutcome): 'store' | 'count-empty' | 'ignore' {
  if (out.count > 0) return 'store';
  return out.fromCache ? 'ignore' : 'count-empty';
}

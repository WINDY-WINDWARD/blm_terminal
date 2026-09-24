/**
 * Live brewing-bar logic — Script Lab Phase 5 (Addendum L).
 *
 * Pure functions that merge the latest WS tick into server bars in memory.
 * Ticks carry LTP only (no volume), so:
 *  - in-place updates keep the server volume,
 *  - freshly appended forming bars get v: 0,
 *  - every touched bar is flagged live: true (scripts can tell forming
 *    bars apart from settled history).
 *
 * Server data always wins: callers repaint from the server on every poll
 * and re-apply (or drop, when stale) the brewing bar afterwards.
 */
import type { ScriptBar } from './types';

/** Ticks older than this never brew (L4: STALE => no refresh > 2min). */
export const LIVE_STALE_MS = 2 * 60_000;

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const DAY_MS = 86_400_000;
/** NSE morning session opens 09:15 IST — intraday buckets anchor here. */
const OPEN_MINUTES_IST = 9 * 60 + 15;

export interface BrewTick {
  ltp: number;
  updatedAt: number;
}

/** Minimal bar shape for brewing. ScriptBar satisfies this structurally. */
export interface BrewInput {
  time: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  live?: boolean;
}

export function shouldBrew(
  tick: BrewTick | null | undefined,
  nowMs: number,
  marketOpen: boolean,
): boolean {
  if (tick == null || !marketOpen) return false;
  if (!Number.isFinite(tick.ltp) || tick.ltp <= 0) return false;
  if (!Number.isFinite(tick.updatedAt)) return false;
  const age = nowMs - tick.updatedAt;
  return age >= 0 && age <= LIVE_STALE_MS;
}

/** IST calendar parts for an epoch-ms timestamp (month is 1-12). */
export function istParts(ms: number): {
  y: number;
  m: number;
  d: number;
  mins: number;
  day: number;
} {
  const d = new Date(ms + IST_OFFSET_MS);
  return {
    y: d.getUTCFullYear(),
    m: d.getUTCMonth() + 1,
    d: d.getUTCDate(),
    mins: d.getUTCHours() * 60 + d.getUTCMinutes(),
    day: d.getUTCDay(),
  };
}

/**
 * Midnight-UTC epoch seconds for an IST calendar date.
 * Matches the server daily bar time convention (Date + 'T00:00:00Z').
 */
export function istDateBarTime(y: number, m: number, day: number): number {
  return Date.UTC(y, m - 1, day, 0, 0, 0) / 1000;
}

function touch(bar: BrewInput, ltp: number): BrewInput {
  return {
    ...bar,
    c: ltp,
    h: Math.max(bar.h, ltp),
    l: Math.min(bar.l, ltp),
    live: true,
  };
}

/**
 * Daily forming candle (L1): update today's bar in place, or append a new
 * forming bar when the server history ends on an earlier session.
 * Empty history brews a single-bar series from the tick alone.
 */
export function brewDaily(
  bars: readonly BrewInput[],
  ltp: number,
  nowMs: number,
): BrewInput[] {
  const p = istParts(nowMs);
  const todayTime = istDateBarTime(p.y, p.m, p.d);
  if (bars.length === 0) {
    return [{ time: todayTime, o: ltp, h: ltp, l: ltp, c: ltp, v: 0, live: true }];
  }
  const out = bars.slice();
  const last = out[out.length - 1];
  if (last.time <= todayTime) {
    if (last.time === todayTime) {
      out[out.length - 1] = touch(last, ltp);
    } else {
      out.push({ time: todayTime, o: ltp, h: ltp, l: ltp, c: ltp, v: 0, live: true });
    }
  } else {
    // Server ahead of the local clock — update in place, never append
    // a bar into the future.
    out[out.length - 1] = touch(last, ltp);
  }
  return out;
}

const BUCKET_SEC: Record<string, number> = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
};

/** Intervals that brew in Phase 5. W/M return server bars untouched. */
export function isBrewableInterval(interval: string): boolean {
  return interval in BUCKET_SEC;
}

/**
 * Current bucket start (epoch seconds), anchored at the 09:15 IST open.
 * Pre-market clamps to the first bucket of the day.
 */
export function intradayBucketStart(nowMs: number, interval: string): number | null {
  const bucket = BUCKET_SEC[interval];
  if (!bucket) return null;
  const nowSec = Math.floor(nowMs / 1000);
  const istDay = Math.floor((nowMs + IST_OFFSET_MS) / DAY_MS);
  const openSec = istDay * 86_400 - IST_OFFSET_MS / 1000 + OPEN_MINUTES_IST * 60;
  if (nowSec < openSec) return openSec;
  const idx = Math.floor((nowSec - openSec) / bucket);
  return openSec + idx * bucket;
}

/**
 * Intraday bucket rollover (L1): update the forming bucket in place, or
 * append a new bucket when the server history ends on an earlier one.
 * A server bar newer than the current bucket (misaligned feed / clock
 * skew) is updated in place — never append into the future.
 */
export function brewIntraday(
  bars: readonly BrewInput[],
  ltp: number,
  nowMs: number,
  interval: string,
): BrewInput[] {
  const start = intradayBucketStart(nowMs, interval);
  if (start === null) return bars.slice();
  if (bars.length === 0) {
    return [{ time: start, o: ltp, h: ltp, l: ltp, c: ltp, v: 0, live: true }];
  }
  const out = bars.slice();
  const last = out[out.length - 1];
  if (last.time === start || last.time > start) {
    out[out.length - 1] = touch(last, ltp);
  } else {
    out.push({ time: start, o: ltp, h: ltp, l: ltp, c: ltp, v: 0, live: true });
  }
  return out;
}

/** Type-narrowing helper: ScriptBar arrays brew without conversion. */
export function brewScriptBars(
  bars: ScriptBar[],
  ltp: number,
  nowMs: number,
  interval: string | null,
): ScriptBar[] {
  const brewed =
    interval === null
      ? brewDaily(bars, ltp, nowMs)
      : brewIntraday(bars, ltp, nowMs, interval);
  // v is always present: server volume survives in-place updates and fresh
  // forming bars are stamped v: 0 above — never undefined (NaN guard).
  return brewed as ScriptBar[];
}

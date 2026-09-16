/**
 * Pure indicator math — no DOM, no chart library, no network.
 * All functions return arrays aligned with the input candles; warmup
 * positions are `null` so the render layer can filter them out.
 * Param conventions mirror the backend constants (RSI-14 Wilder,
 * MACD 12/26/9, Stoch 14/3/3, ATR-14, BB 20/2) for cross-widget consistency.
 */
import type { IndicatorCandle } from './types';

const isFiniteNum = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v);

/** Simple moving average over a plain value array. Seed = first full window. */
export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!isFiniteNum(v)) {
      sum = 0;
      // Invalidate the trailing window — values after a gap restart cleanly.
      for (let k = Math.max(0, i - period + 1); k <= i; k++) out[k] = null;
      continue;
    }
    sum += v;
    if (i >= period) sum -= values[i - period] as number;
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/** Exponential moving average — seeded with the first window's SMA (TV convention). */
export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) {
    if (!isFiniteNum(values[i])) return out; // gap inside seed window — no EMA
    seed += values[i] as number;
  }
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    const v = values[i];
    if (!isFiniteNum(v)) {
      out[i] = null;
      continue; // keep prev — resume on next finite value
    }
    prev = v * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export interface BollingerBands {
  basis: (number | null)[];
  upper: (number | null)[];
  lower: (number | null)[];
}

/** Bollinger Bands — basis SMA(period), bands ±mult * population stdev. */
export function bollinger(
  values: number[],
  period = 20,
  mult = 2,
): BollingerBands {
  const basis = sma(values, period);
  const upper: (number | null)[] = new Array(values.length).fill(null);
  const lower: (number | null)[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    if (basis[i] == null) continue;
    const window = values.slice(i - period + 1, i + 1);
    if (!window.every(isFiniteNum)) continue;
    const mean = basis[i] as number;
    const variance =
      window.reduce((acc, v) => acc + (v - mean) * (v - mean), 0) / period;
    const sd = Math.sqrt(Math.max(0, variance));
    upper[i] = mean + mult * sd;
    lower[i] = mean - mult * sd;
  }
  return { basis, upper, lower };
}

/**
 * Session VWAP — cumulative (typical * volume) / cumulative volume, reset at
 * each calendar-day boundary. On daily+ timeframes a "session" is the bar
 * itself, so VWAP degrades to the bar's typical price (correct by definition).
 */
export function sessionVWAP(candles: IndicatorCandle[]): (number | null)[] {
  const out: (number | null)[] = new Array(candles.length).fill(null);
  let pv = 0;
  let vol = 0;
  let curDay = '';
  for (let i = 0; i < candles.length; i++) {
    const c = candles[i];
    const day = new Date(c.time * 1000).toISOString().slice(0, 10);
    if (day !== curDay) {
      curDay = day;
      pv = 0;
      vol = 0;
    }
    const typical = (c.high + c.low + c.close) / 3;
    if (isFiniteNum(typical) && isFiniteNum(c.volume) && c.volume > 0) {
      pv += typical * c.volume;
      vol += c.volume;
    }
    out[i] = vol > 0 ? pv / vol : isFiniteNum(typical) ? typical : null;
  }
  return out;
}

/** RSI (Wilder smoothing). All-up window → 100, all-down → 0. */
export function rsi(closes: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (!isFiniteNum(d) || !isFiniteNum(closes[i])) return out;
    if (d > 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    if (!isFiniteNum(d)) {
      out[i] = null;
      continue;
    }
    avgGain = (avgGain * (period - 1) + Math.max(0, d)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(0, -d)) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

export interface MACDResult {
  macdLine: (number | null)[];
  signalLine: (number | null)[];
  hist: (number | null)[];
}

/** MACD 12/26/9 — signal is EMA(9) of the macd line (seeded on first value). */
export function macd(
  closes: number[],
  fast = 12,
  slow = 26,
  signal = 9,
): MACDResult {
  const n = closes.length;
  const macdLine: (number | null)[] = new Array(n).fill(null);
  const signalLine: (number | null)[] = new Array(n).fill(null);
  const hist: (number | null)[] = new Array(n).fill(null);
  const fastE = ema(closes, fast);
  const slowE = ema(closes, slow);
  const start = slow - 1;
  for (let i = start; i < n; i++) {
    if (fastE[i] == null || slowE[i] == null) continue;
    macdLine[i] = (fastE[i] as number) - (slowE[i] as number);
  }
  // Seed signal with SMA of first `signal` macd values, then EMA.
  const k = 2 / (signal + 1);
  const seedEnd = start + signal - 1;
  let seeded = false;
  let prev = 0;
  for (let i = start; i < n; i++) {
    if (macdLine[i] == null) continue;
    if (!seeded) {
      const window: number[] = [];
      for (let j = start; j <= Math.min(seedEnd, n - 1); j++) {
        if (macdLine[j] == null) break;
        window.push(macdLine[j] as number);
      }
      if (window.length < signal || i < seedEnd) continue;
      prev = window.reduce((a, b) => a + b, 0) / signal;
      signalLine[i] = prev;
      hist[i] = (macdLine[i] as number) - prev;
      seeded = true;
      continue;
    }
    prev = (macdLine[i] as number) * k + prev * (1 - k);
    signalLine[i] = prev;
    hist[i] = (macdLine[i] as number) - prev;
  }
  return { macdLine, signalLine, hist };
}

export interface StochResult {
  k: (number | null)[];
  d: (number | null)[];
}

/** Stochastic %K (SMA-smoothed over slowing) + %D signal. Flat range → 50. */
export function stochastic(
  highs: number[],
  lows: number[],
  closes: number[],
  kPeriod = 14,
  slowing = 3,
  dPeriod = 3,
): StochResult {
  const n = closes.length;
  const rawK: (number | null)[] = new Array(n).fill(null);
  for (let i = kPeriod - 1; i < n; i++) {
    const hiSlice = highs.slice(i - kPeriod + 1, i + 1);
    const loSlice = lows.slice(i - kPeriod + 1, i + 1);
    if (!hiSlice.every(isFiniteNum) || !loSlice.every(isFiniteNum)) continue;
    const hh = Math.max(...hiSlice);
    const ll = Math.min(...loSlice);
    if (!isFiniteNum(closes[i])) continue;
    rawK[i] = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;
  }
  // %K = SMA(slowing) of rawK — operate only on the non-null tail.
  const k: (number | null)[] = new Array(n).fill(null);
  for (let i = 2 * kPeriod - 2; i < n; i++) {
    const window = rawK.slice(i - slowing + 1, i + 1);
    if (!window.every((v): v is number => v != null)) continue;
    k[i] = window.reduce((a, b) => a + (b as number), 0) / slowing;
  }
  const d: (number | null)[] = new Array(n).fill(null);
  const kStart = 2 * kPeriod - 2;
  for (let i = kStart + dPeriod - 1; i < n; i++) {
    const window = k.slice(i - dPeriod + 1, i + 1);
    if (!window.every((v): v is number => v != null)) continue;
    d[i] = window.reduce((a, b) => a + (b as number), 0) / dPeriod;
  }
  return { k, d };
}

/** ATR (Wilder smoothing of true range). */
export function atr(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14,
): (number | null)[] {
  const n = closes.length;
  const out: (number | null)[] = new Array(n).fill(null);
  if (n <= period) return out;
  const tr: number[] = new Array(n).fill(NaN);
  for (let i = 1; i < n; i++) {
    if (![highs[i], lows[i], closes[i - 1]].every(isFiniteNum)) continue;
    tr[i] = Math.max(
      highs[i] - lows[i],
      Math.abs(highs[i] - closes[i - 1]),
      Math.abs(lows[i] - closes[i - 1]),
    );
  }
  const seed = tr.slice(1, period + 1);
  if (!seed.every(isFiniteNum)) return out;
  let prev = seed.reduce((a, b) => a + b, 0) / period;
  out[period] = prev;
  for (let i = period + 1; i < n; i++) {
    if (!isFiniteNum(tr[i])) {
      out[i] = null;
      continue;
    }
    prev = (prev * (period - 1) + (tr[i] as number)) / period;
    out[i] = prev;
  }
  return out;
}

/** On-Balance Volume — signed volume accumulation, no warmup. */
export function obv(closes: number[], volumes: number[]): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length === 0 || !isFiniteNum(closes[0])) return out;
  let acc = 0;
  out[0] = 0;
  for (let i = 1; i < closes.length; i++) {
    if (!isFiniteNum(closes[i]) || !isFiniteNum(volumes[i])) {
      out[i] = null;
      continue;
    }
    if (closes[i] > closes[i - 1]) acc += volumes[i];
    else if (closes[i] < closes[i - 1]) acc -= volumes[i];
    out[i] = acc;
  }
  return out;
}

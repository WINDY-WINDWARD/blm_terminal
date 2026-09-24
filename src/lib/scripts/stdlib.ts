/**
 * BLM Script Lab v1 — stdlib.
 *
 * Self-contained port of src/lib/indicators/calculations.ts (no imports) so
 * the exact same function sources can be injected into the script Worker.
 * Semantics MUST stay identical to the engine — parity tests enforce this.
 */
import type { ScriptBar } from './types';

type Num = number | null;

const isFiniteNum = (v: unknown): v is number =>
  typeof v === 'number' && Number.isFinite(v);

export function sma(values: number[], period: number): Num[] {
  const out: Num[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!isFiniteNum(v)) {
      sum = 0;
      for (let k = Math.max(0, i - period + 1); k <= i; k++) out[k] = null;
      continue;
    }
    sum += v;
    if (i >= period) sum -= values[i - period] as number;
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values: number[], period: number): Num[] {
  const out: Num[] = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) {
    if (!isFiniteNum(values[i])) return out;
    seed += values[i] as number;
  }
  let prev = seed / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    const v = values[i];
    if (!isFiniteNum(v)) {
      out[i] = null;
      continue;
    }
    prev = v * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

export interface BBResult {
  basis: Num[];
  upper: Num[];
  lower: Num[];
}

export function bb(values: number[], period = 20, mult = 2): BBResult {
  const basis = sma(values, period);
  const upper: Num[] = new Array(values.length).fill(null);
  const lower: Num[] = new Array(values.length).fill(null);
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

export function rsi(closes: number[], period = 14): Num[] {
  const out: Num[] = new Array(closes.length).fill(null);
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
  macdLine: Num[];
  signalLine: Num[];
  hist: Num[];
}

export function macd(closes: number[], fast = 12, slow = 26, signal = 9): MACDResult {
  const n = closes.length;
  const macdLine: Num[] = new Array(n).fill(null);
  const signalLine: Num[] = new Array(n).fill(null);
  const hist: Num[] = new Array(n).fill(null);
  const fastE = ema(closes, fast);
  const slowE = ema(closes, slow);
  const start = slow - 1;
  for (let i = start; i < n; i++) {
    if (fastE[i] == null || slowE[i] == null) continue;
    macdLine[i] = (fastE[i] as number) - (slowE[i] as number);
  }
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
  k: Num[];
  d: Num[];
}

export function stoch(
  highs: number[],
  lows: number[],
  closes: number[],
  kPeriod = 14,
  slowing = 3,
  dPeriod = 3,
): StochResult {
  const n = closes.length;
  const rawK: Num[] = new Array(n).fill(null);
  for (let i = kPeriod - 1; i < n; i++) {
    const hiSlice = highs.slice(i - kPeriod + 1, i + 1);
    const loSlice = lows.slice(i - kPeriod + 1, i + 1);
    if (!hiSlice.every(isFiniteNum) || !loSlice.every(isFiniteNum)) continue;
    const hh = Math.max(...hiSlice);
    const ll = Math.min(...loSlice);
    if (!isFiniteNum(closes[i])) continue;
    rawK[i] = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;
  }
  const k: Num[] = new Array(n).fill(null);
  for (let i = 2 * kPeriod - 2; i < n; i++) {
    const window = rawK.slice(i - slowing + 1, i + 1);
    if (!window.every((v): v is number => v != null)) continue;
    k[i] = window.reduce((a, b) => a + (b as number), 0) / slowing;
  }
  const d: Num[] = new Array(n).fill(null);
  const kStart = 2 * kPeriod - 2;
  for (let i = kStart + dPeriod - 1; i < n; i++) {
    const window = k.slice(i - dPeriod + 1, i + 1);
    if (!window.every((v): v is number => v != null)) continue;
    d[i] = window.reduce((a, b) => a + (b as number), 0) / dPeriod;
  }
  return { k, d };
}

export function atr(highs: number[], lows: number[], closes: number[], period = 14): Num[] {
  const n = closes.length;
  const out: Num[] = new Array(n).fill(null);
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

export function obv(closes: number[], volumes: number[]): Num[] {
  const out: Num[] = new Array(closes.length).fill(null);
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

/**
 * Session VWAP over ScriptBars — same day-boundary reset semantics as
 * sessionVWAP, adapted to o/h/l/c/v field names.
 */
export function vwap(bars: ScriptBar[]): Num[] {
  const out: Num[] = new Array(bars.length).fill(null);
  let pv = 0;
  let vol = 0;
  let curDay = '';
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const day = new Date(b.time * 1000).toISOString().slice(0, 10);
    if (day !== curDay) {
      curDay = day;
      pv = 0;
      vol = 0;
    }
    const typical = (b.h + b.l + b.c) / 3;
    if (isFiniteNum(typical) && isFiniteNum(b.v) && b.v > 0) {
      pv += typical * b.v;
      vol += b.v;
    }
    out[i] = vol > 0 ? pv / vol : isFiniteNum(typical) ? typical : null;
  }
  return out;
}

export function highest(values: number[], period: number): Num[] {
  const out: Num[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  for (let i = period - 1; i < values.length; i++) {
    const window = values.slice(i - period + 1, i + 1);
    if (!window.every(isFiniteNum)) continue;
    out[i] = Math.max(...(window as number[]));
  }
  return out;
}

export function lowest(values: number[], period: number): Num[] {
  const out: Num[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  for (let i = period - 1; i < values.length; i++) {
    const window = values.slice(i - period + 1, i + 1);
    if (!window.every(isFiniteNum)) continue;
    out[i] = Math.min(...(window as number[]));
  }
  return out;
}

export function change(values: number[]): Num[] {
  const out: Num[] = new Array(values.length).fill(null);
  for (let i = 1; i < values.length; i++) {
    if (!isFiniteNum(values[i]) || !isFiniteNum(values[i - 1])) continue;
    out[i] = (values[i] as number) - (values[i - 1] as number);
  }
  return out;
}

export function nz(value: number | null | undefined, fallback = 0): number {
  return isFiniteNum(value) ? (value as number) : fallback;
}

/** Names exposed on the frozen BLM global inside the Worker. */
export const BLM_EXPORT_NAMES = [
  'sma', 'ema', 'rsi', 'macd', 'bb', 'atr', 'stoch', 'obv', 'vwap',
  'highest', 'lowest', 'change', 'nz',
] as const;

const BLM_FNS: Record<string, unknown> = {
  sma, ema, rsi, macd, bb, atr, stoch, obv, vwap, highest, lowest, change, nz,
};

/**
 * Build the worker-injected source for the frozen BLM global.
 * Serializes the actual engine functions above, so worker semantics are
 * identical to main-thread semantics by construction. Each function is bound
 * as a scope-level const (parenthesized: works for declarations and arrows)
 * because the bodies reference each other + isFiniteNum by bare name.
 */
export function buildBlmSource(): string {
  const defs = ['isFiniteNum', ...BLM_EXPORT_NAMES].map((name) => {
    const fn = (name === 'isFiniteNum' ? isFiniteNum : BLM_FNS[name]) as (...args: never[]) => unknown;
    return `const ${name} = (${fn.toString()});`;
  });
  return `${defs.join('\n')}\nconst BLM = Object.freeze({ ${BLM_EXPORT_NAMES.join(', ')} });`;
}

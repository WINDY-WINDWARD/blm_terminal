/**
 * BLM Script Lab v1 — deterministic 120-bar fixture for dry-runs and tests.
 * Random walk with fixed seed: no Date.now, no Math.random at runtime.
 */
import type { ScriptBar } from './types';

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function sampleBars(count = 120, endSec = 1_700_000_000): ScriptBar[] {
  const rand = mulberry32(42);
  const bars: ScriptBar[] = [];
  let price = 1000;
  for (let i = 0; i < count; i++) {
    const drift = (rand() - 0.48) * 14;
    const o = price;
    const c = Math.max(1, o + drift);
    const h = Math.max(o, c) + rand() * 4;
    const l = Math.min(o, c) - rand() * 4;
    const v = Math.floor(50000 + rand() * 200000);
    bars.push({ time: endSec - (count - 1 - i) * 86400, o, h, l, c, v });
    price = c;
  }
  return bars;
}

import { describe, it, expect } from 'vitest';
import {
  sma, ema, bollinger, sessionVWAP, rsi, macd, stochastic, atr, obv,
} from './calculations';

const approx = (v: number | null, expected: number, eps = 1e-9) => {
  expect(v).not.toBeNull();
  expect(Math.abs((v as number) - expected)).toBeLessThan(eps);
};

describe('sma', () => {
  it('null warmup then window means', () => {
    const out = sma([1, 2, 3, 4, 5], 3);
    expect(out.slice(0, 2)).toEqual([null, null]);
    approx(out[2], 2);
    approx(out[3], 3);
    approx(out[4], 4);
  });

  it('flat series stays flat', () => {
    expect(sma([7, 7, 7, 7], 2)).toEqual([null, 7, 7, 7]);
  });
});

describe('ema', () => {
  it('seeds with first-window SMA then decays', () => {
    const out = ema([1, 2, 3, 4, 5], 3);
    expect(out.slice(0, 2)).toEqual([null, null]);
    approx(out[2], 2); // seed
    approx(out[3], 3); // 4*0.5 + 2*0.5
    approx(out[4], 4); // 5*0.5 + 3*0.5
  });

  it('flat series stays flat', () => {
    const out = ema([5, 5, 5, 5, 5], 3);
    approx(out[4], 5);
  });
});

describe('bollinger', () => {
  it('basis equals SMA and bands are symmetric', () => {
    const { basis, upper, lower } = bollinger([10, 11, 12, 13, 14], 5, 2);
    approx(basis[4], 12);
    approx(upper[4], 12 + 2 * Math.sqrt(2));
    approx(lower[4], 12 - 2 * Math.sqrt(2));
  });

  it('flat series collapses bands to price', () => {
    const { upper, lower } = bollinger([9, 9, 9, 9, 9], 5, 2);
    approx(upper[4], 9);
    approx(lower[4], 9);
  });
});

describe('sessionVWAP', () => {
  const day = (h: number, m: number) =>
    Date.UTC(2026, 8, 15, h, m, 0) / 1000;

  it('cumulative within a session, resets next day', () => {
    const candles = [
      { time: day(3, 45), open: 100, high: 102, low: 99, close: 101, volume: 1000 },
      { time: day(3, 50), open: 101, high: 103, low: 100, close: 102, volume: 1000 },
      // next day — must reset, not carry pv/vol forward
      { time: day(3, 45) + 86400, open: 200, high: 200, low: 200, close: 200, volume: 10 },
    ];
    const out = sessionVWAP(candles);
    const t1 = (102 + 99 + 101) / 3;
    const t2 = (103 + 100 + 102) / 3;
    approx(out[0], t1);
    approx(out[1], (t1 * 1000 + t2 * 1000) / 2000);
    approx(out[2], 200);
  });

  it('zero-volume bar falls back to typical price', () => {
    const out = sessionVWAP([
      { time: day(3, 45), open: 50, high: 52, low: 48, close: 51, volume: 0 },
    ]);
    approx(out[0], (52 + 48 + 51) / 3);
  });
});

describe('rsi', () => {
  it('all-up window pins to 100, all-down to 0', () => {
    const up = Array.from({ length: 20 }, (_, i) => 100 + i);
    const down = Array.from({ length: 20 }, (_, i) => 100 - i);
    approx(rsi(up, 14)[14], 100);
    approx(rsi(down, 14)[14], 0);
  });

  it('flat market sits at 100 (no losses)', () => {
    approx(rsi(Array(20).fill(50), 14)[19], 100);
  });
});

describe('macd', () => {
  it('flat series yields zero lines', () => {
    const closes = Array(60).fill(100);
    const { macdLine, signalLine, hist } = macd(closes);
    approx(macdLine[59], 0);
    approx(signalLine[59], 0);
    approx(hist[59], 0);
  });

  it('warming-up positions stay null', () => {
    const closes = Array.from({ length: 60 }, (_, i) => 100 + i * 0.1);
    const { signalLine } = macd(closes);
    expect(signalLine[25]).toBeNull();
    expect(signalLine[59]).not.toBeNull();
  });
});

describe('stochastic', () => {
  it('price at range top pins %K near 100', () => {
    const n = 30;
    const highs = Array(n).fill(110);
    const lows = Array(n).fill(90);
    const closes = Array(n).fill(109);
    const { k, d } = stochastic(highs, lows, closes);
    approx(k[n - 1], 95);
    approx(d[n - 1], 95);
  });

  it('flat range yields 50', () => {
    const n = 30;
    const flat = Array(n).fill(100);
    const { k } = stochastic(flat, flat, flat);
    approx(k[n - 1], 50);
  });
});

describe('atr', () => {
  it('constant range equals that range', () => {
    const n = 30;
    const highs = Array(n).fill(105);
    const lows = Array(n).fill(95);
    const closes = Array(n).fill(100);
    approx(atr(highs, lows, closes, 14)[29], 10);
  });
});

describe('obv', () => {
  it('accumulates signed volume', () => {
    const out = obv([10, 11, 10, 10, 12], [100, 200, 300, 400, 500]);
    expect(out).toEqual([0, 200, -100, -100, 400]);
  });
});

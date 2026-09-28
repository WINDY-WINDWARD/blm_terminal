/**
 * Script Lab v1 runtime tests: stdlib parity, validator matrix,
 * worker mapping, param migration, fundamentals normalization.
 */
import { describe, it, expect } from 'vitest';
import {
  sma, ema, bollinger as engBb, sessionVWAP, rsi as engRsi,
  macd as engMacd, stochastic as engStoch, atr as engAtr, obv as engObv,
} from '@/lib/indicators/calculations';
import type { IndicatorCandle } from '@/lib/indicators/types';
import {
  sma as sSma, ema as sEma, bb, rsi as sRsi, macd as sMacd,
  stoch as sStoch, atr as sAtr, obv as sObv, vwap,
  highest, lowest, change, nz, buildBlmSource, BLM_EXPORT_NAMES,
} from './stdlib';
import { sampleBars } from './sampleBars';
import { validateManifest, validateScript } from './validate';
import { checkOutputShape, runScript } from './worker';
import { migrateParamValues, paramsWithDefaults } from './params';
import { normalizeQuarterly, normalizeRatios } from './fundamentalsCtx';

const bars = sampleBars(120);
const closes = bars.map((b) => b.c);
const highs = bars.map((b) => b.h);
const lows = bars.map((b) => b.l);
const vols = bars.map((b) => b.v);
const engineCandles: IndicatorCandle[] = bars.map((b) => ({
  time: b.time, open: b.o, high: b.h, low: b.l, close: b.c, volume: b.v,
}));

describe('stdlib parity with the indicator engine', () => {
  it('sma/ema match exactly', () => {
    expect(sSma(closes, 20)).toEqual(sma(closes, 20));
    expect(sEma(closes, 12)).toEqual(ema(closes, 12));
  });

  it('bb/rsi/macd/stoch/atr/obv match exactly', () => {
    expect(bb(closes, 20, 2)).toEqual(engBb(closes, 20, 2));
    expect(sRsi(closes, 14)).toEqual(engRsi(closes, 14));
    expect(sMacd(closes)).toEqual(engMacd(closes));
    expect(sStoch(highs, lows, closes)).toEqual(engStoch(highs, lows, closes));
    expect(sAtr(highs, lows, closes)).toEqual(engAtr(highs, lows, closes));
    expect(sObv(closes, vols)).toEqual(engObv(closes, vols));
  });

  it('vwap matches sessionVWAP on mapped candles', () => {
    expect(vwap(bars)).toEqual(sessionVWAP(engineCandles));
  });

  it('highest/lowest/change/nz behave', () => {
    expect(highest([1, 3, 2, 5, 4], 3)).toEqual([null, null, 3, 5, 5]);
    expect(lowest([1, 3, 2, 5, 4], 3)).toEqual([null, null, 1, 2, 2]);
    expect(change([1, 3, 2])).toEqual([null, 2, -1]);
    expect(nz(null)).toBe(0);
    expect(nz(7)).toBe(7);
  });

  it('buildBlmSource exposes every export and evaluates', () => {
    const src = buildBlmSource();
    for (const name of BLM_EXPORT_NAMES) {
      expect(src).toContain(`const ${name} = (`);
    }
    const factory = new Function(`${src}\nreturn { sma, rsi, BLM };`);
    const { sma: wSma, BLM } = factory() as {
      sma: typeof sSma; BLM: Record<string, unknown>;
    };
    expect(wSma([1, 2, 3, 4], 2)).toEqual(sSma([1, 2, 3, 4], 2));
    expect(Object.keys(BLM).sort()).toEqual([...BLM_EXPORT_NAMES].sort());
    // Frozen: assignment throws in strict mode.
    expect(() => {
      'use strict';
      (BLM as Record<string, unknown>).sma = 1;
    }).toThrow();
  });
});

const GOOD = `// @blm-script {"name":"T","version":1,"params":[{"key":"len","type":"int","default":5,"min":2,"max":50}],"outputs":[{"id":"a","kind":"line"}]}
function calculate(ctx) { return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) }; }`;

describe('validateManifest matrix', () => {
  it('accepts a good script', () => {
    const { manifest, errors } = validateManifest(GOOD);
    expect(errors).toEqual([]);
    expect(manifest?.name).toBe('T');
  });

  it('rejects missing header / bad json / version 2 / v2 kinds', () => {
    expect(validateManifest('function calculate(ctx){return{};}').errors[0]).toMatch(/^E_MANIFEST_JSON/);
    expect(validateManifest('// @blm-script {oops}\nfunction calculate(ctx){return{};}').errors[0]).toMatch(/^E_MANIFEST_JSON/);
    expect(validateManifest(GOOD.replace('"version":1', '"version":2').replace('ctx.params.len', 'ctx.params.len')).errors[0]).toMatch(/requires spec v2/);
    const withAlert = GOOD.replace('"outputs"', '"alerts":[{"id":"x"}],"outputs"');
    expect(validateManifest(withAlert).errors[0]).toMatch(/^E_V2_KIND/);
  });

  it('rejects bad params and outputs', () => {
    const dup = GOOD.replace('"key":"len"', '"key":"len","label":"x"').replace(
      '"params":[',
      '"params":[{"key":"len","type":"int","default":1},',
    );
    expect(validateManifest(dup).errors.some((e) => e.includes('duplicate param'))).toBe(true);
    const badBand = GOOD.replace(
      '"outputs":[{"id":"a","kind":"line"}]',
      '"outputs":[{"id":"b","kind":"band","upper":"x","lower":"y"}]',
    );
    expect(validateManifest(badBand).errors.some((e) => e.includes('band'))).toBe(true);
    const unref = GOOD.replace('ctx.params.len', '99');
    expect(validateManifest(unref).errors.some((e) => e.startsWith('E_PARAM'))).toBe(true);
  });

  it('rejects async and missing calculate', () => {
    expect(validateManifest(GOOD.replace('function calculate', 'async function calculate').replace('ctx.params.len', 'ctx.params.len')).errors.some((e) => e.startsWith('E_STATIC'))).toBe(true);
    expect(validateManifest(GOOD.replace('function calculate(ctx)', 'function nope(ctx)')).errors.some((e) => e.includes('calculate'))).toBe(true);
  });
});

describe('validateScript dry-run', () => {
  it('runs the good script on fixtures', async () => {
    const v = await validateScript(GOOD);
    expect(v.valid).toBe(true);
    expect(v.stats?.outputs).toEqual(['a']);
    expect(v.stats?.bars).toBe(120);
  });

  it('maps runtime throws to E_RUNTIME', async () => {
    const bad = GOOD.replace(
      'BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len)',
      'BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len).map(function(){ throw new Error("boom"); })',
    );
    const v = await validateScript(bad);
    expect(v.valid).toBe(false);
    expect(v.errors[0]).toMatch(/^E_RUNTIME.*boom/);
  });

  it('maps length mismatch to E_LENGTH', async () => {
    const short = GOOD.replace(
      'return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) };',
      'return { a: [ctx.params.len, 2] };',
    );
    const v = await validateScript(short);
    expect(v.valid).toBe(false);
    expect(v.errors[0]).toMatch(/^E_LENGTH/);
  });

  it('accepts a two-color line through the full dry-run', async () => {
    const twoColor = GOOD.replace(
      'return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) };',
      'return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len).map(function (x, i) { return x == null ? null : { value: x, color: i % 2 ? "#26a69a" : "#ef5350" }; }) };',
    );
    const v = await validateScript(twoColor);
    expect(v.valid).toBe(true);
  });

  it('runScript computes over the full loaded history (no 2000-bar truncation)', async () => {
    const manifest = validateManifest(GOOD).manifest!;
    const many = sampleBars(2500);
    const r = await runScript({
      code: GOOD,
      manifest,
      ctx: {
        bars: many,
        params: { len: 20 },
        symbol: 'X',
        exchange: 'NSE',
        interval: '1d',
      },
    });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.stats.bars).toBe(2500);
      const series = r.values.a as unknown[];
      expect(series.length).toBe(2500);
    }
  });
});

describe('checkOutputShape', () => {
  const manifest = validateManifest(GOOD).manifest!;
  it('accepts aligned series, rejects extras and short arrays', () => {
    expect(checkOutputShape(manifest, { a: new Array(10).fill(1) }, 10)).toBeNull();
    expect(checkOutputShape(manifest, { a: [1] }, 10)).toMatch(/^E_LENGTH/);
    expect(checkOutputShape(manifest, { a: [], zzz: [] }, 0)).toMatch(/unexpected output/);
  });

  it('accepts {value, color} line points, rejects bad colors with E_COLOR', () => {
    const colored = new Array(10).fill(0).map((_, i) => ({
      value: i,
      color: i % 2 ? '#26a69a' : '#ef5350',
    }));
    expect(checkOutputShape(manifest, { a: colored }, 10)).toBeNull();
    const badColor = new Array(10).fill({ value: 1, color: 'red' });
    expect(checkOutputShape(manifest, { a: badColor }, 10)).toMatch(/^E_COLOR/);
    const badValue = new Array(10).fill({ value: NaN });
    expect(checkOutputShape(manifest, { a: badValue }, 10)).toMatch(/^E_COLOR/);
    const junk = new Array(10).fill([1, 2]);
    expect(checkOutputShape(manifest, { a: junk }, 10)).toMatch(/^E_COLOR/);
  });
});

describe('runScript timeout', () => {
  it.runIf(typeof Worker !== 'undefined')('terminates an infinite loop', async () => {
    const loop = GOOD.replace(
      'return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) };',
      'while (true) {} return { a: [] };',
    );
    const r = await runScript({
      code: loop,
      manifest: validateManifest(GOOD).manifest!,
      ctx: { bars, params: { len: 5 }, symbol: 'X', exchange: 'NSE', interval: 'D' },
    });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('E_TIMEOUT');
  }, 10000);
});

describe('sandbox', () => {
  it('bans eval and Function constructor statically', () => {
    const withEval = GOOD.replace('function calculate(ctx) {', 'function calculate(ctx) { eval("1");');
    expect(validateManifest(withEval).errors.some((e) => e.startsWith('E_STATIC'))).toBe(true);
    const withFunc = GOOD.replace('function calculate(ctx) {', 'function calculate(ctx) { const F = Function("return 1");');
    expect(validateManifest(withFunc).errors.some((e) => e.startsWith('E_STATIC'))).toBe(true);
  });

  it('shadows network globals at runtime', async () => {
    const exfil = GOOD.replace(
      'return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) };',
      'fetch("http://127.0.0.1:1/x"); return { a: BLM.sma(ctx.bars.map(function (b) { return b.c; }), ctx.params.len) };',
    );
    const v = await validateScript(exfil);
    expect(v.valid).toBe(false);
    expect(v.errors[0]).toMatch(/^E_RUNTIME/);
  });

  it('drops unsafe keys from stored JSON', () => {
    const stored = JSON.parse('{"a":1,"__proto__":{"polluted":true}}') as Record<string, number | boolean | string>;
    const oldM = { params: [{ key: 'a' }] } as never;
    const newM = { params: [{ key: 'a' }] } as never;
    expect(migrateParamValues(oldM, newM, stored)).toEqual({ a: 1 });
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });
});

describe('param migration', () => {
  it('keeps survivors, drops removed', () => {
    const oldM = { params: [{ key: 'a' }, { key: 'b' }] } as never;
    const newM = { params: [{ key: 'a' }, { key: 'c' }] } as never;
    expect(migrateParamValues(oldM, newM, { a: 1, b: 2 })).toEqual({ a: 1 });
  });

  it('fills defaults for missing keys', () => {
    const m = { params: [{ key: 'a', default: 5 }] } as never;
    expect(paramsWithDefaults(m, {})).toEqual({ a: 5 });
  });
});

describe('fundamentals normalization', () => {
  it('parses quarterly year/month cells, skips TTM', () => {
    const rows = normalizeQuarterly({
      quarterly_results: {
        '2024': {
          Sep: { Sales: '1,234', 'Net Profit': '56', 'EPS in Rs': '7.8' },
          'Mar TTM': { Sales: '9' },
        },
        '2023': { Dec: { Sales: '100' } },
      },
    });
    expect(rows.map((r) => r.period)).toEqual(['2023Q4', '2024Q3']);
    expect(rows[1].sales).toBe(1234);
    expect(rows[1].eps).toBe(7.8);
  });

  it('parses ratios defensively', () => {
    expect(normalizeRatios({ ratios: { pe: '21.5', roe: null, market_cap: '1,00,000' } })).toEqual({
      pe: 21.5, roe: null, roce: null, marketCapCr: 100000,
    });
  });
});

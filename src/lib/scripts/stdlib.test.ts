import { describe, expect, it } from 'vitest';
import {
  assembleBlmSource,
  BLM_EXPORT_NAMES,
  buildBlmSource,
} from './stdlib';

describe('assembleBlmSource', () => {
  it('maps exports through minified runtime names', () => {
    // Synthetic prod shape: the guard's runtime name `r` differs from any
    // export name, and the caller references bare `r`. Binding by export
    // name (the old scheme) would leave `r` dangling.
    const src = assembleBlmSource(
      [
        { exportName: null, runtimeName: 'r', body: 'function r(v) { return typeof v === "number"; }' },
        { exportName: 'sma', runtimeName: 's', body: 'function s(v) { return r(v) ? 1 : 0; }' },
      ],
      ['sma'],
    );
    const BLM = new Function(`${src}; return BLM;`)() as { sma: (v: unknown) => number };
    expect(BLM.sma(1)).toBe(1);
    expect(BLM.sma('x')).toBe(0);
  });

  it('buildBlmSource evaluates with a working BLM namespace', () => {
    const BLM = new Function(`${buildBlmSource()}; return BLM;`)() as Record<
      string,
      (...args: unknown[]) => unknown
    >;
    for (const name of BLM_EXPORT_NAMES) {
      expect(typeof BLM[name], `BLM.${name}`).toBe('function');
    }
    // Cross-reference check: sma (which calls the internal guard in the
    // engine source) must run, not throw ReferenceError.
    expect(BLM.sma([1, 2, 3, 4], 2)).toEqual([null, 1.5, 2.5, 3.5]);
  });
});

import { describe, it, expect, beforeEach } from 'vitest';
import { createStore } from 'jotai';
import { chartSymbolOverridesAtom } from '@/store/terminalStore';

describe('chartSymbolOverridesAtom', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('degrades corrupt storage to {} instead of throwing', () => {
    localStorage.setItem('terminal.chartOverrides', '"x"');
    const store = createStore();
    expect(store.get(chartSymbolOverridesAtom)).toEqual({});
  });

  it('degrades null/array storage to {}', () => {
    localStorage.setItem('terminal.chartOverrides', '[1,2]');
    const store = createStore();
    expect(store.get(chartSymbolOverridesAtom)).toEqual({});
  });

  it('round-trips valid overrides', () => {
    const store = createStore();
    store.set(chartSymbolOverridesAtom, { 'panel-1': { symbol: 'SBIN', exchange: 'NSE' } });
    expect(store.get(chartSymbolOverridesAtom)).toEqual({
      'panel-1': { symbol: 'SBIN', exchange: 'NSE' },
    });
  });

  it('supports functional updates', () => {
    const store = createStore();
    store.set(chartSymbolOverridesAtom, (prev) => ({
      ...prev,
      p2: { symbol: 'TCS', exchange: 'NSE' },
    }));
    expect(store.get(chartSymbolOverridesAtom).p2.symbol).toBe('TCS');
  });
});

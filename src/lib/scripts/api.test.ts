/**
 * Contract test: frontend scripts API client must call the exact backend
 * routes (backend/tests/test_main_wiring.py asserts the server half).
 * A /chart-state-under-/scripts mismatch once shipped and 422'd every
 * chart slot load — this test pins the wire paths + methods from this side.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fetchChartState,
  fetchScriptDetail,
  fetchScripts,
  setChartSlot,
} from './api';

const calls: Array<{ url: string; method: string }> = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? 'GET' });
      return {
        ok: true,
        json: async () => (Array.isArray(url) ? [] : {}),
      } as Response;
    }),
  );
});

describe('scripts api contract', () => {
  it('catalog + detail hit /api/py/scripts', async () => {
    await fetchScripts();
    await fetchScriptDetail(7);
    expect(calls).toEqual([
      { url: '/api/py/scripts', method: 'GET' },
      { url: '/api/py/scripts/7', method: 'GET' },
    ]);
  });

  it('chart-state hits TOP-LEVEL /api/py/chart-state, never nested', async () => {
    await fetchChartState('panel-1');
    await setChartSlot('panel-1', { script_id: 3, enabled: true, param_values: {} });
    expect(calls).toEqual([
      { url: '/api/py/chart-state?panel_id=panel-1', method: 'GET' },
      { url: '/api/py/chart-state?panel_id=panel-1', method: 'POST' },
    ]);
    for (const c of calls) {
      expect(c.url).not.toContain('/scripts/chart-state');
    }
  });
});

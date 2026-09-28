/**
 * Contract test: frontend scripts API client must call the exact backend
 * routes (backend/tests/test_main_wiring.py asserts the server half).
 * A /chart-state-under-/scripts mismatch once shipped and 422'd every
 * chart slot load — this test pins the wire paths + methods from this side.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  deleteScript,
  fetchChartState,
  fetchScriptDetail,
  fetchScripts,
  setChartSlot,
} from './api';

const calls: Array<{ url: string; method: string; body?: string }> = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? init.body : undefined,
      });
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
    expect(calls.map((c) => ({ url: c.url, method: c.method }))).toEqual([
      { url: '/api/py/chart-state?panel_id=panel-1', method: 'GET' },
      { url: '/api/py/chart-state?panel_id=panel-1', method: 'POST' },
    ]);
    for (const c of calls) {
      expect(c.url).not.toContain('/scripts/chart-state');
    }
  });

  it('omitted param_values stays out of the POST body (backend keeps stored params)', async () => {
    await setChartSlot('panel-1', { script_id: 3, enabled: true });
    const sent = JSON.parse(calls[0].body ?? '{}') as Record<string, unknown>;
    expect(sent.script_id).toBe(3);
    expect('param_values' in sent).toBe(false);
  });

  it('explicit param_values are sent through', async () => {
    await setChartSlot('panel-1', { script_id: 3, enabled: true, param_values: { len: 5 } });
    const sent = JSON.parse(calls[0].body ?? '{}') as Record<string, unknown>;
    expect(sent.param_values).toEqual({ len: 5 });
  });

  it('delete hits POST /api/py/scripts/:id/delete', async () => {
    await deleteScript(9);
    expect(calls).toEqual([{ url: '/api/py/scripts/9/delete', method: 'POST' }]);
  });
});

describe('scripts api errors', () => {
  function stubFailure(status: number, body: unknown) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status, json: async () => body }) as Response),
    );
  }

  it('surfaces backend {error} verbatim', async () => {
    stubFailure(409, { error: 'duplicate script name' });
    await expect(fetchScripts()).rejects.toThrow('duplicate script name');
  });

  it('surfaces FastAPI {detail} string instead of a bare status', async () => {
    stubFailure(404, { detail: 'script not found' });
    await expect(fetchScriptDetail(9)).rejects.toThrow('script not found');
  });

  it('stringifies FastAPI {detail} arrays', async () => {
    stubFailure(422, { detail: [{ loc: ['x'], msg: 'bad', type: 'x' }] });
    await expect(fetchChartState('p')).rejects.toThrow('bad');
  });

  it('falls back to status when the body is empty', async () => {
    stubFailure(500, {});
    await expect(fetchScripts()).rejects.toThrow('scripts API 500');
  });
});

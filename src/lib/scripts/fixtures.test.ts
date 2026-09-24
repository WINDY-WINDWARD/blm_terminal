/**
 * Script Lab dev fixtures — permanent suite (dev-only page shares codes).
 * Fixture 6 (index 6) is the expected E_RUNTIME case.
 */
import { it, expect } from 'vitest';
import { sampleBars } from './sampleBars';
import { DEV_FIXTURES } from './fixtures';
import { validateManifest } from './validate';
import { runScript } from './worker';

it('all dev fixtures behave as the page expects', async () => {
  expect(DEV_FIXTURES).toHaveLength(7);
  const bars = sampleBars(120);
  for (let i = 0; i < DEV_FIXTURES.length; i++) {
    const f = DEV_FIXTURES[i];
    const { manifest, errors } = validateManifest(f.code);
    expect(errors, `fixture ${i} (${f.name}) static`).toEqual([]);
    expect(manifest, `fixture ${i} (${f.name}) manifest`).not.toBeNull();
    const params: Record<string, number | boolean | string> = {};
    for (const p of manifest!.params ?? []) params[p.key] = p.default;
    const r = await runScript({
      code: f.code,
      manifest: manifest!,
      ctx: { bars, params, symbol: 'FIX', exchange: 'NSE', interval: 'D' },
    });
    if (f.name === 'Runtime error') {
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.code).toBe('E_RUNTIME');
    } else {
      expect(r.ok, `fixture ${i} (${f.name}) run`).toBe(true);
    }
  }
});

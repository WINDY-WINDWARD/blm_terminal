'use client';

/**
 * BLM Script Lab v1 — dev fixtures runner view.
 * Executes each fixture (from @/lib/scripts/fixtures, shared with the test
 * suite) via validateManifest + runScript on the seeded 120-bar fixture
 * and reports validity, outputs, and sample values.
 */
import { useEffect, useState } from 'react';
import { sampleBars } from '@/lib/scripts/sampleBars';
import { DEV_FIXTURES } from '@/lib/scripts/fixtures';
import { validateManifest } from '@/lib/scripts/validate';
import { runScript } from '@/lib/scripts/worker';
import type { ScriptOutputValues } from '@/lib/scripts/types';
import { cn } from '@/lib/utils';

interface FixtureResult {
  valid: boolean;
  errors: string[];
  outputs: string[];
  ms: number;
  samples: Record<string, string>;
}

function summarizeValues(values: Record<string, ScriptOutputValues>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [id, v] of Object.entries(values)) {
    if (typeof v === 'number') {
      out[id] = `priceline ${v.toFixed(2)}`;
    } else if (Array.isArray(v) && v.length > 0 && Array.isArray(v[0])) {
      const hits = (v as unknown[][]).filter((a) => a.length > 0).length;
      out[id] = `${hits}/${v.length} bars with markers`;
    } else {
      const nums = (v as (number | null)[]).filter((x) => typeof x === 'number');
      out[id] = nums.length > 0
        ? `first values ${nums.slice(0, 3).map((x) => (x as number).toFixed(2)).join(', ')}`
        : 'all null';
    }
  }
  return out;
}

export default function FixturesView() {
  const [results, setResults] = useState<(FixtureResult | null)[]>(() => DEV_FIXTURES.map(() => null));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const bars = sampleBars(120);
      const next: (FixtureResult | null)[] = [];
      for (const f of DEV_FIXTURES) {
        const { manifest, errors } = validateManifest(f.code);
        if (!manifest) {
          next.push({ valid: false, errors, outputs: [], ms: 0, samples: {} });
          continue;
        }
        const params: Record<string, number | boolean | string> = {};
        for (const p of manifest.params ?? []) params[p.key] = p.default;
        const r = await runScript({
          code: f.code,
          manifest,
          ctx: { bars, params, symbol: 'FIX', exchange: 'NSE', interval: 'D' },
        });
        next.push(
          r.ok
            ? {
                valid: true,
                errors: [],
                outputs: Object.keys(r.values),
                ms: r.stats.ms,
                samples: summarizeValues(r.values),
              }
            : { valid: false, errors: [`${r.code}: ${r.message}`], outputs: [], ms: 0, samples: {} },
        );
      }
      if (!cancelled) setResults(next);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-black p-6 font-mono text-sm text-neutral-200">
      <h1 className="text-lg font-bold text-amber-400">Script Lab — dev fixtures ({DEV_FIXTURES.length})</h1>
      <p className="mt-1 text-xs text-neutral-500">
        Seeded 120-bar fixture · dev only · this page 404s in production builds
      </p>
      <div className="mt-4 space-y-3">
        {DEV_FIXTURES.map((f, i) => {
          const r = results[i];
          return (
            <div key={f.name} className="rounded border border-neutral-800 bg-neutral-950 p-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    'rounded px-1.5 py-0.5 text-xs font-bold',
                    !r ? 'bg-neutral-800 text-neutral-400' : r.valid ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300',
                  )}
                >
                  {!r ? '…' : r.valid ? 'VALID' : 'ERROR'}
                </span>
                <span className="font-bold text-neutral-100">{f.name}</span>
                {r && r.valid && <span className="text-xs text-neutral-500">{r.outputs.join(', ')} · {r.ms}ms</span>}
              </div>
              <p className="mt-1 text-xs text-neutral-400">{f.desc}</p>
              {r && !r.valid && (
                <pre className="mt-1 whitespace-pre-wrap text-xs text-red-400">{r.errors.join('\n')}</pre>
              )}
              {r && r.valid && (
                <pre className="mt-1 whitespace-pre-wrap text-xs text-neutral-500">
                  {Object.entries(r.samples).map(([k, s]) => `${k}: ${s}`).join('\n')}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * BLM Script Lab v1 — param migration helper (mirrors backend _migrate_params).
 * Surviving keys keep values; new keys take manifest defaults; removed dropped.
 */
import type { ScriptManifest } from './types';

export function migrateParamValues(
  oldManifest: Pick<ScriptManifest, 'params'> | null,
  newManifest: Pick<ScriptManifest, 'params'>,
  values: Record<string, number | boolean | string>,
): Record<string, number | boolean | string> {
  const oldKeys = new Set((oldManifest?.params ?? []).map((p) => p.key));
  const newKeys = new Set((newManifest.params ?? []).map((p) => p.key));
  const out: Record<string, number | boolean | string> = {};
  for (const [k, v] of Object.entries(values)) {
    if (oldKeys.has(k) && newKeys.has(k)) out[k] = v;
  }
  return out;
}

/** Fill manifest defaults for keys missing from values. */
export function paramsWithDefaults(
  manifest: Pick<ScriptManifest, 'params'>,
  values: Record<string, number | boolean | string>,
): Record<string, number | boolean | string> {
  const out: Record<string, number | boolean | string> = { ...values };
  for (const p of manifest.params ?? []) {
    if (!(p.key in out)) out[p.key] = p.default;
  }
  return out;
}

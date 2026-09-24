/**
 * BLM Script Lab v1 — param migration helper (mirrors backend _migrate_params).
 * Surviving keys keep values; new keys take manifest defaults; removed dropped.
 */
import type { ScriptManifest } from './types';

/** Keys that must never become live object properties from stored JSON. */
const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

export function migrateParamValues(
  oldManifest: Pick<ScriptManifest, 'params'> | null,
  newManifest: Pick<ScriptManifest, 'params'>,
  values: Record<string, number | boolean | string>,
): Record<string, number | boolean | string> {
  const oldKeys = new Set((oldManifest?.params ?? []).map((p) => p.key));
  const newKeys = new Set((newManifest.params ?? []).map((p) => p.key));
  const out: Record<string, number | boolean | string> = {};
  for (const [k, v] of Object.entries(values)) {
    if (UNSAFE_KEYS.has(k)) continue;
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
    if (UNSAFE_KEYS.has(p.key)) continue;
    if (!Object.hasOwn(out, p.key)) out[p.key] = p.default;
  }
  return out;
}

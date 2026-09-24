/**
 * BLM Script Lab v1 — frontend validation: manifest schema + worker dry-run.
 * Mirrors backend/app/schemas/script.py (which never executes JS).
 */
import { sampleBars } from './sampleBars';
import type {
  ScriptManifest,
  ScriptParam,
  ScriptValidation,
} from './types';
import { MAX_CODE_BYTES, MAX_OUTPUTS, MAX_PARAMS, SCRIPT_SPEC_VERSION } from './types';
import { runScript } from './worker';

const V2_MANIFEST_KEYS = ['drawings', 'alerts', 'strategy', 'timeframe', 'symbol'];
const V2_OUTPUT_KINDS = ['drawing', 'alert', 'strategy'];
const PARAM_TYPES = ['int', 'number', 'bool', 'select', 'color', 'source'];
const OUTPUT_KINDS = ['line', 'histogram', 'markers', 'priceline', 'band'];
const IDENT_RE = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const HEX_RE = /^#[0-9a-fA-F]{6}$/;
const HEADER_RE = /\/\/\s*@blm-script\s+(\{.*\})/;
const SOURCES = ['open', 'high', 'low', 'close', 'hlc3', 'hl2', 'ohlc4', 'volume'];

function checkParam(p: ScriptParam, errors: string[]): void {
  if (!p || typeof p !== 'object') {
    errors.push('E_MANIFEST_SCHEMA: param must be an object');
    return;
  }
  if (!IDENT_RE.test(p.key || '')) {
    errors.push(`E_MANIFEST_SCHEMA: param key ${JSON.stringify(p.key)} must be a valid JS identifier`);
    return;
  }
  if (!PARAM_TYPES.includes(p.type)) {
    errors.push(`E_PARAM: param ${p.key} has unknown type ${JSON.stringify(p.type)}`);
    return;
  }
  const d = p.default;
  const inRange = (v: number) =>
    (p.min == null || v >= p.min) && (p.max == null || v <= p.max);
  switch (p.type) {
    case 'int':
      if (typeof d !== 'number' || !Number.isInteger(d) || !inRange(d)) {
        errors.push(`E_PARAM: int param ${p.key} default must be an integer in range`);
      }
      break;
    case 'number':
      if (typeof d !== 'number' || !Number.isFinite(d) || !inRange(d)) {
        errors.push(`E_PARAM: number param ${p.key} default must be finite and in range`);
      }
      break;
    case 'bool':
      if (typeof d !== 'boolean') errors.push(`E_PARAM: bool param ${p.key} default must be true/false`);
      break;
    case 'select':
      if (!Array.isArray(p.options) || p.options.length < 2) {
        errors.push(`E_PARAM: select param ${p.key} needs ≥2 options`);
      } else if (!p.options.includes(d as string)) {
        errors.push(`E_PARAM: select param ${p.key} default must be one of options`);
      }
      break;
    case 'color':
      if (typeof d !== 'string' || !HEX_RE.test(d)) {
        errors.push(`E_PARAM: color param ${p.key} default must be #rrggbb`);
      }
      break;
    case 'source':
      if (!SOURCES.includes(d as string)) {
        errors.push(`E_PARAM: source param ${p.key} default must be one of ${SOURCES.join('|')}`);
      }
      break;
  }
}

/** Schema-only validation (no execution). Returns manifest or null + errors. */
export function validateManifest(code: string): { manifest: ScriptManifest | null; errors: string[] } {
  const errors: string[] = [];
  if (new TextEncoder().encode(code).length > MAX_CODE_BYTES) {
    return { manifest: null, errors: ['E_LIMIT: code exceeds 64KB'] };
  }
  const headerMatch = code.split('\n').map((l) => l.trim()).map((l) => l.match(HEADER_RE)).find(Boolean);
  if (!headerMatch) return { manifest: null, errors: ['E_MANIFEST_JSON: missing // @blm-script {...} header'] };
  let header: Record<string, unknown>;
  try {
    header = JSON.parse(headerMatch[1]);
  } catch (e) {
    return { manifest: null, errors: [`E_MANIFEST_JSON: header is not valid JSON (${e instanceof Error ? e.message : e})`] };
  }
  for (const k of V2_MANIFEST_KEYS) {
    if (k in header) return { manifest: null, errors: [`E_V2_KIND: ${JSON.stringify(k)} requires spec v2`] };
  }
  const outputs = header.outputs;
  if (Array.isArray(outputs)) {
    for (const o of outputs) {
      if (o && typeof o === 'object' && V2_OUTPUT_KINDS.includes((o as { kind: string }).kind)) {
        return { manifest: null, errors: [`E_V2_KIND: output kind ${JSON.stringify((o as { kind: string }).kind)} requires spec v2`] };
      }
    }
  }
  if (typeof header.name !== 'string' || header.name.length < 1 || header.name.length > 64) {
    errors.push('E_MANIFEST_SCHEMA: name must be 1–64 chars');
  }
  if (header.version !== SCRIPT_SPEC_VERSION) {
    return { manifest: null, errors: [`E_VERSION: spec version ${JSON.stringify(header.version)} unsupported — requires spec v2`] };
  }
  if (header.description != null && (typeof header.description !== 'string' || header.description.length > 280)) {
    errors.push('E_MANIFEST_SCHEMA: description must be ≤280 chars');
  }
  const params = Array.isArray(header.params) ? header.params : header.params == null ? [] : null;
  if (params === null) {
    errors.push('E_MANIFEST_SCHEMA: params must be an array');
  } else {
    if (params.length > MAX_PARAMS) errors.push('E_MANIFEST_SCHEMA: more than 24 params');
    const keys = new Set<string>();
    for (const p of params as ScriptParam[]) {
      checkParam(p, errors);
      if (p && typeof p.key === 'string') {
        if (keys.has(p.key)) errors.push('E_MANIFEST_SCHEMA: duplicate param keys');
        keys.add(p.key);
      }
    }
  }
  if (!Array.isArray(outputs) || outputs.length < 1 || outputs.length > MAX_OUTPUTS) {
    errors.push('E_MANIFEST_SCHEMA: outputs must have 1–8 entries');
  } else {
    const ids = new Set<string>();
    const lineIds = new Set<string>();
    for (const o of outputs as Array<Record<string, unknown>>) {
      if (!o || typeof o !== 'object' || !IDENT_RE.test(String(o.id || ''))) {
        errors.push('E_MANIFEST_SCHEMA: output id must be a valid JS identifier');
        continue;
      }
      const id = String(o.id);
      if (ids.has(id)) errors.push('E_MANIFEST_SCHEMA: duplicate output ids');
      ids.add(id);
      if (!OUTPUT_KINDS.includes(String(o.kind))) {
        errors.push(`E_OUTPUT: output ${id} has unknown kind ${JSON.stringify(o.kind)}`);
        continue;
      }
      if (o.kind === 'line') lineIds.add(id);
    }
    for (const o of outputs as Array<Record<string, unknown>>) {
      if (o && o.kind === 'band') {
        if (!lineIds.has(String(o.upper)) || !lineIds.has(String(o.lower))) {
          errors.push(`E_OUTPUT: band ${String(o.id)} must reference two line outputs of this script`);
        }
      }
    }
  }
  if (errors.length > 0) return { manifest: null, errors };
  const manifest = header as unknown as ScriptManifest;
  // Static code checks (mirrors backend).
  if (!/\bfunction\s+calculate\s*\(\s*ctx\s*\)/.test(code)) {
    errors.push('E_STATIC: top-level function calculate(ctx) not found');
  }
  for (const pat of [/\basync\b/, /\bawait\b/, /\bimport\b/, /\brequire\s*\(/, /\bclass\b/, /function\s*\*/]) {
    if (pat.test(code)) {
      errors.push('E_STATIC: forbidden construct (async/import/class/generator)');
      break;
    }
  }
  for (const p of manifest.params ?? []) {
    const ref = new RegExp(`\\bparams\\s*\\.\\s*${p.key}\\b|\\bparams\\s*\\[\\s*['"]${p.key}['"]\\s*\\]`);
    if (!ref.test(code)) errors.push(`E_PARAM: param ${p.key} never referenced in code`);
  }
  return { manifest: errors.length > 0 ? null : manifest, errors };
}

/** Full validation: schema + worker dry-run on the 120-bar fixture. */
export async function validateScript(code: string): Promise<ScriptValidation> {
  const { manifest, errors } = validateManifest(code);
  if (!manifest) return { valid: false, errors, manifest: null };
  const params: Record<string, number | boolean | string> = {};
  for (const p of manifest.params ?? []) params[p.key] = p.default;
  const result = await runScript({
    code,
    manifest,
    ctx: {
      bars: sampleBars(),
      params,
      symbol: 'VALIDATE',
      exchange: 'NSE',
      interval: 'D',
    },
  });
  if (!result.ok) {
    return {
      valid: false,
      manifest: null,
      errors: [`${result.code}: ${result.message}${result.line ? ` (line ${result.line})` : ''}`],
    };
  }
  return {
    valid: true,
    errors: [],
    manifest,
    stats: {
      bars: result.stats.bars,
      ms: result.stats.ms,
      outputs: Object.keys(result.values),
    },
  };
}

/**
 * BLM Script Lab v1 — sandboxed script execution in a Web Worker.
 * The worker evaluates user code with `new Function` exposing ONLY the frozen
 * BLM global + ctx + Math. Main-thread watchdog terminates on timeout.
 */
import { buildBlmSource, BLM_EXPORT_NAMES } from './stdlib';
import type { ScriptCtx, ScriptManifest, ScriptOutputValues, ScriptRunResult } from './types';
import { EXEC_TIMEOUT_MS, MAX_BARS_PER_RUN } from './types';

export interface RunRequest {
  code: string;
  manifest: ScriptManifest;
  ctx: ScriptCtx;
}

/**
 * Worker globals that user code must NOT see (network/exfiltration/loader
 * surface). They are shadowed with `undefined` parameters on the user factory,
 * so AI-generated scripts stay pure compute: Math/Date/JSON + frozen BLM only.
 * Static checks additionally ban eval/Function (which would re-open globals).
 */
const SANDBOXED_GLOBALS = [
  'self',
  'postMessage',
  'onmessage',
  'onerror',
  'fetch',
  'XMLHttpRequest',
  'WebSocket',
  'EventSource',
  'importScripts',
  'caches',
  'indexedDB',
  'navigator',
  'location',
  'close',
  'setTimeout',
  'setInterval',
  'clearTimeout',
  'clearInterval',
  'queueMicrotask',
] as const;

function buildWorkerSource(code: string): string {
  const shadow = SANDBOXED_GLOBALS.map((g) => `'${g}'`).join(',');
  return `
${buildBlmSource()}
const __userCode = ${JSON.stringify(code)};
let calculate;
try {
  const factory = new Function('BLM', 'Math', ${shadow}, __userCode + '\\nreturn calculate;');
  calculate = factory(BLM, Math);
} catch (e) {
  postMessage({ ok: false, code: 'E_STATIC', message: String((e && e.message) || e) });
}
if (typeof calculate !== 'function') {
  postMessage({ ok: false, code: 'E_STATIC', message: 'calculate is not a function' });
} else {
  onmessage = function (ev) {
    const t0 = Date.now();
    try {
      const out = calculate(ev.data.ctx);
      postMessage({ ok: true, values: out, stats: { bars: ev.data.ctx.bars.length, ms: Date.now() - t0 } });
    } catch (e) {
      const stack = String((e && e.stack) || '');
      const line = (stack.match(/<anonymous>:(\\d+)/) || [])[1];
      postMessage({ ok: false, code: 'E_RUNTIME', message: String((e && e.message) || e), line: line ? Number(line) : undefined });
    }
  };
}
`;
}

/** Validate returned values against the manifest (length + kind checks). */
export function checkOutputShape(
  manifest: ScriptManifest,
  values: Record<string, unknown>,
  barCount: number,
): string | null {
  const ids = new Set(manifest.outputs.map((o) => o.id));
  for (const key of Object.keys(values)) {
    if (!ids.has(key)) return `E_OUTPUT: unexpected output key ${key}`;
  }
  for (const o of manifest.outputs) {
    const v = (values as Record<string, unknown>)[o.id];
    if (o.kind === 'priceline') {
      if (typeof v !== 'number' || !Number.isFinite(v)) {
        return `E_LENGTH: priceline ${o.id} must be a finite number`;
      }
      continue;
    }
    if (!Array.isArray(v) || v.length !== barCount) {
      return `E_LENGTH: output ${o.id} length ${Array.isArray(v) ? v.length : '?'} !== bars ${barCount}`;
    }
    // Line points may be plain values or {value, color} objects (per-bar
    // segment color — the engine colors each segment from its start bar).
    if (o.kind === 'line') {
      for (let i = 0; i < v.length; i++) {
        const item = v[i] as unknown;
        if (item == null || typeof item === 'number') continue;
        if (typeof item !== 'object' || Array.isArray(item)) {
          return `E_COLOR: line ${o.id}[${i}] must be a number, null, or {value, color}`;
        }
        const pt = item as { value?: unknown; color?: unknown };
        if (
          pt.value != null &&
          (typeof pt.value !== 'number' || !Number.isFinite(pt.value))
        ) {
          return `E_COLOR: line ${o.id}[${i}].value must be a finite number or null`;
        }
        if (
          pt.color !== undefined &&
          (typeof pt.color !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(pt.color))
        ) {
          return `E_COLOR: line ${o.id}[${i}].color must be #rrggbb`;
        }
      }
    }
  }
  return null;
}

/**
 * In-thread fallback for runtimes without Web Workers (vitest node env, SSR).
 * Same compile+shape semantics as the worker path, but there is NO timeout
 * watchdog here — a hung script would block the thread. E_TIMEOUT is only
 * produced by the real Worker path above. Static checks remain the caller's job.
 */
function runInThread(code: string, manifest: ScriptManifest, ctx: ScriptCtx): ScriptRunResult {
  try {
    const nsFactory = new Function(`${buildBlmSource()}\nreturn BLM;`);
    const BLM = nsFactory() as Record<string, unknown>;
    const shadowArgs = [...SANDBOXED_GLOBALS, 'window', 'document', 'localStorage', 'process', 'require', 'globalThis'];
    const factory = new Function('BLM', 'Math', ...shadowArgs, code + '\nreturn calculate;');
    const calculate = (factory as (...a: unknown[]) => unknown)(BLM, Math) as
      | ((c: ScriptCtx) => Record<string, ScriptOutputValues>)
      | undefined;
    if (typeof calculate !== 'function') {
      return { ok: false, code: 'E_STATIC', message: 'calculate is not a function' };
    }
    let values: Record<string, ScriptOutputValues>;
    try {
      values = calculate(ctx);
    } catch (e) {
      return { ok: false, code: 'E_RUNTIME', message: e instanceof Error ? e.message : String(e) };
    }
    const shapeErr = checkOutputShape(manifest, values, ctx.bars.length);
    if (shapeErr) {
      return { ok: false, code: shapeErr.split(':')[0], message: shapeErr };
    }
    return { ok: true, values, stats: { bars: ctx.bars.length, ms: 0 } };
  } catch (e) {
    return { ok: false, code: 'E_STATIC', message: e instanceof Error ? e.message : String(e) };
  }
}

/** Execute a script off the main thread. Never rejects — errors are values. */
export function runScript(req: RunRequest): Promise<ScriptRunResult> {
  const bars = req.ctx.bars.slice(-MAX_BARS_PER_RUN);
  const ctx: ScriptCtx = { ...req.ctx, bars };
  if (typeof Worker === 'undefined') {
    return Promise.resolve(runInThread(req.code, req.manifest, ctx));
  }
  return new Promise((resolve) => {
    let worker: Worker | null = null;
    let settled = false;
    const finish = (r: ScriptRunResult) => {
      if (settled) return;
      settled = true;
      try {
        worker?.terminate();
      } catch {
        /* ignore */
      }
      resolve(r);
    };
    const timer = setTimeout(() => {
      finish({ ok: false, code: 'E_TIMEOUT', message: `exceeded ${EXEC_TIMEOUT_MS}ms` });
    }, EXEC_TIMEOUT_MS + 250);
    const clear = () => clearTimeout(timer);
    try {
      const blob = new Blob([buildWorkerSource(req.code)], { type: 'text/javascript' });
      const url = URL.createObjectURL(blob);
      worker = new Worker(url);
      URL.revokeObjectURL(url); // only needed at construction; frees the blob
    } catch (e) {
      clear();
      resolve({
        ok: false,
        code: 'E_STATIC',
        message: e instanceof Error ? e.message : 'Worker unavailable',
      });
      return;
    }
    worker.onmessage = (ev: MessageEvent) => {
      const data = ev.data as ScriptRunResult;
      if (!data.ok) {
        clear();
        finish(data);
        return;
      }
      const shapeErr = checkOutputShape(req.manifest, data.values, bars.length);
      clear();
      if (shapeErr) {
        finish({ ok: false, code: shapeErr.split(':')[0], message: shapeErr });
        return;
      }
      finish(data);
    };
    worker.onerror = (ev: ErrorEvent) => {
      clear();
      finish({ ok: false, code: 'E_STATIC', message: ev.message || 'worker error' });
    };
    worker.postMessage({ ctx });
  });
}

/** Exported for tests: the exact stdlib surface scripts can see. */
export const WORKER_GLOBALS = [...BLM_EXPORT_NAMES, 'Math'] as const;

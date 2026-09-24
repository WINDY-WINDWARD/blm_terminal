'use client';
/**
 * BLM Script Lab v1 — manifest-driven parameter form.
 * Sliders/toggles/selects/color/source pickers in terminal styling.
 * Changes debounced 300ms before onChange fires.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ScriptParam } from './types';
import { cn } from '@/lib/utils';

interface ParamFormProps {
  params: ScriptParam[];
  values: Record<string, number | boolean | string>;
  onChange: (values: Record<string, number | boolean | string>) => void;
}

const SOURCES = ['open', 'high', 'low', 'close', 'hlc3', 'hl2', 'ohlc4', 'volume'];

export function ScriptParamForm({ params, values, onChange }: ParamFormProps): React.JSX.Element | null {
  const [draft, setDraft] = useState(values);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setDraft(values), [values]);
  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const push = useMemo(
    () => (next: Record<string, number | boolean | string>) => {
      setDraft(next);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => onChange(next), 300);
    },
    [onChange],
  );

  if (params.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {params.map((p) => {
        const v = draft[p.key] ?? p.default;
        const label = p.label || p.key;
        return (
          <label key={p.key} className="flex flex-col gap-1 text-[11px]">
            <span className="flex justify-between text-zinc-400">
              <span>{label}</span>
              {(p.type === 'int' || p.type === 'number') && (
                <span className="text-amber-400 font-mono">{String(v)}</span>
              )}
            </span>
            {(p.type === 'int' || p.type === 'number') && (
              <input
                type="range"
                min={p.min ?? 0}
                max={p.max ?? 100}
                step={p.step ?? (p.type === 'int' ? 1 : 0.1)}
                value={Number(v)}
                onChange={(e) =>
                  push({ ...draft, [p.key]: p.type === 'int' ? parseInt(e.target.value, 10) : parseFloat(e.target.value) })
                }
                className="w-full accent-amber-500"
              />
            )}
            {p.type === 'bool' && (
              <button
                type="button"
                onClick={() => push({ ...draft, [p.key]: !v })}
                className={cn(
                  'w-9 h-5 rounded-full relative transition-colors',
                  v ? 'bg-amber-500' : 'bg-zinc-700',
                )}
                aria-pressed={Boolean(v)}
              >
                <span
                  className={cn(
                    'absolute top-0.5 h-4 w-4 rounded-full bg-black transition-all',
                    v ? 'left-[18px]' : 'left-0.5',
                  )}
                />
              </button>
            )}
            {p.type === 'select' && (
              <select
                value={String(v)}
                onChange={(e) => push({ ...draft, [p.key]: e.target.value })}
                className="bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-200"
              >
                {(p.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            )}
            {p.type === 'color' && (
              <input
                type="color"
                value={String(v)}
                onChange={(e) => push({ ...draft, [p.key]: e.target.value })}
                className="w-10 h-6 bg-transparent border border-zinc-700 rounded cursor-pointer"
              />
            )}
            {p.type === 'source' && (
              <select
                value={String(v)}
                onChange={(e) => push({ ...draft, [p.key]: e.target.value })}
                className="bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-200 font-mono"
              >
                {SOURCES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            )}
          </label>
        );
      })}
    </div>
  );
}

'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';
import type { ActiveIndicator, IndicatorType } from '@/lib/indicators/types';
import {
  INDICATOR_DEFS,
  MAX_INDICATORS,
  makeIndicator,
  paramLimits,
} from '@/lib/indicators/presets';

interface ChartIndicatorMenuProps {
  interval: string;
  active: ActiveIndicator[];
  onChange: (next: ActiveIndicator[]) => void;
}

const SWATCHES = ['#FFB900', '#2962FF', '#00E5A0', '#FF6D00', '#B388FF', '#F23645'];

export function ChartIndicatorMenu({ interval, active, onChange }: ChartIndicatorMenuProps) {
  const [open, setOpen] = useState(false);
  const [editingType, setEditingType] = useState<IndicatorType | null>(null);

  // One entry per type — checkbox reflects visibility, hidden entries persist
  // with their params so they can be loaded back later. The cap applies to
  // VISIBLE indicators only: unchecking frees a slot for a different one.
  const byType = new Map(active.map((a) => [a.type, a]));
  const visibleCount = active.filter((a) => a.visible).length;
  const full = visibleCount >= MAX_INDICATORS;

  const toggle = (type: IndicatorType) => {
    const existing = byType.get(type);
    if (existing) {
      if (!existing.visible && full) return; // showing would exceed the cap
      if (existing.visible) setEditingType(null); // hiding collapses settings
      onChange(active.map((a) => (a.type === type ? { ...a, visible: !a.visible } : a)));
      return;
    }
    if (full) return;
    onChange([...active, { ...makeIndicator(type, active.length), visible: true }]);
  };

  const update = (type: IndicatorType, patch: Partial<ActiveIndicator>) => {
    onChange(active.map((a) => (a.type === type ? { ...a, ...patch } : a)));
  };

  const remove = (type: IndicatorType) => {
    onChange(active.filter((a) => a.type !== type));
    if (editingType === type) setEditingType(null);
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'px-1.5 py-0.5 text-[10px] font-mono border transition-colors',
          open || visibleCount > 0
            ? 'border-terminal-amber text-terminal-amber bg-black'
            : 'border-terminal-gray text-white/70 hover:text-terminal-amber hover:border-terminal-amber bg-black',
        )}
        title={`Chart indicators (max ${MAX_INDICATORS}) — check to show, uncheck to hide`}
      >
        Fx{visibleCount > 0 ? ` ${visibleCount}` : ''}
      </button>

      {open && (
        <div className="absolute z-50 left-0 top-full mt-0.5 w-64 bg-black border border-terminal-gray shadow-lg text-xs font-mono">
          {INDICATOR_DEFS.map((def) => {
            const entry = byType.get(def.type);
            const checked = entry?.visible ?? false;
            const disabled = def.disabledOn?.(interval) ?? false;
            // Blocked only when checking it would exceed the visible cap.
            const blocked = !checked && full;
            const editing = editingType === def.type && entry != null;
            return (
              <div key={def.type} className="border-b border-terminal-gray/40 last:border-b-0">
                <div
                  className={cn(
                    'w-full text-left px-2 py-1 flex items-center gap-2',
                    disabled || blocked ? 'text-white/25' : 'text-white/80',
                  )}
                  title={disabled ? def.disabledReason : blocked ? `Max ${MAX_INDICATORS} indicators` : def.label}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={disabled || blocked}
                    onChange={() => toggle(def.type)}
                    className="accent-[#FFB900] w-3 h-3 flex-shrink-0 cursor-pointer disabled:cursor-not-allowed"
                    title={disabled ? def.disabledReason : `Show ${def.label}`}
                  />
                  <button
                    type="button"
                    disabled={disabled || blocked}
                    onClick={() => toggle(def.type)}
                    className={cn(
                      'flex-1 text-left',
                      disabled || blocked ? 'cursor-not-allowed' : 'cursor-pointer hover:text-terminal-amber',
                    )}
                  >
                    {def.label}
                  </button>
                  {disabled && <span className="text-[9px] text-white/25">D/W/M</span>}
                  {entry != null && (def.paramKeys.length > 0) && (
                    <button
                      type="button"
                      onClick={() => setEditingType(editing ? null : def.type)}
                      className="text-white/50 hover:text-terminal-amber px-0.5"
                      title="Settings"
                    >
                      ⚙
                    </button>
                  )}
                  {entry != null && (
                    <button
                      type="button"
                      onClick={() => remove(def.type)}
                      className="text-white/50 hover:text-terminal-red px-0.5"
                      title="Remove"
                    >
                      ✕
                    </button>
                  )}
                </div>
                {editing && entry && (
                  <div className="px-2 pb-1.5 pt-0.5 bg-zinc-950">
                    {def.paramKeys.map((key) => {
                      const limits = paramLimits(key);
                      return (
                        <label key={key} className="flex items-center justify-between gap-2 py-0.5 text-white/80">
                          <span className="uppercase">{key}</span>
                          <input
                            type="number"
                            value={entry.params[key] ?? ''}
                            min={limits.min}
                            max={limits.max}
                            step={limits.step}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              if (!Number.isFinite(v)) return;
                              update(def.type, {
                                params: {
                                  ...entry.params,
                                  [key]: Math.min(limits.max, Math.max(limits.min, v)),
                                },
                              });
                            }}
                            className="w-16 bg-zinc-900 border border-terminal-gray text-terminal-amber px-1 py-0.5 text-right"
                          />
                        </label>
                      );
                    })}
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {SWATCHES.map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => update(def.type, { color: c })}
                          className={cn(
                            'w-4 h-4 border',
                            entry.color === c ? 'border-white' : 'border-transparent',
                          )}
                          style={{ backgroundColor: c }}
                          title={c}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {full && (
            <div className="px-2 py-1 text-[10px] text-white/40 border-t border-terminal-gray">
              Max {MAX_INDICATORS} visible — uncheck one to show another.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

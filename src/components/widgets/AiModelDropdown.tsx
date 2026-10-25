'use client';

import React, { useEffect, useRef, useState } from 'react';
import type { ModelOption } from '@/types/aiWidgetTypes';

export interface AiModelDropdownProps {
  value: string;
  onChange: (id: string) => void;
  availableModels: ModelOption[];
  routeGroups?: { route_id: string; label: string; models: ModelOption[] }[];
  activeRouteLabel?: string;
  isLoading?: boolean;
  loadError?: boolean;
  onRetry?: () => void;
  disabled?: boolean;
}

export function AiModelDropdown({
  value,
  onChange,
  availableModels,
  routeGroups,
  activeRouteLabel,
  isLoading = false,
  loadError = false,
  onRetry,
  disabled = false,
}: AiModelDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedModel = availableModels.find((m) => m.id === value);
  const displayLabel = loadError && availableModels.length === 0
    ? 'Model list unavailable - retry'
    : selectedModel ? selectedModel.label : (value || "Select Model…");

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen]);

  const groups = (routeGroups ?? []).filter((g) => g.models.length > 0);
  const useGroups = groups.length > 0;

  function renderModelButton(m: ModelOption) {
    return (
      <button
        key={m.id}
        type="button"
        onClick={() => {
          onChange(m.id);
          setIsOpen(false);
        }}
        className={`w-full text-left px-2 py-1.5 rounded flex items-center justify-between border transition-all ${
          m.id === value
            ? 'bg-terminal-amber text-black font-bold border-terminal-amber shadow'
            : 'text-zinc-200 border-transparent hover:border-amber-400/60 hover:bg-zinc-800/90 hover:text-white'
        }`}
      >
        <span className="truncate">{m.label}</span>
        {m.id === value && <span>✓</span>}
      </button>
    );
  }

  return (
    <div ref={containerRef} className="relative inline-block">
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          if (loadError && availableModels.length === 0) {
            onRetry?.();
            return;
          }
          setIsOpen((prev) => !prev);
        }}
        data-testid="ai-model-select"
        className="flex items-center justify-between gap-2 bg-[#121216] hover:bg-[#18181f] border border-zinc-700 hover:border-amber-400 focus:border-amber-400 focus:ring-1 focus:ring-terminal-amber/50 rounded px-3 py-1.5 text-xs text-white font-mono cursor-pointer transition-all shadow-sm hover:shadow-[0_0_12px_rgba(245,158,11,0.3)] min-w-[210px] max-w-[280px] disabled:opacity-50 select-none"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" title={activeRouteLabel ?? "Provider Active"} />
        <span className="truncate">{displayLabel}</span>
        <span className="text-[10px] text-zinc-400 ml-1">▼</span>
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1.5 w-72 bg-[#09090b] border border-zinc-700 hover:border-amber-400/60 rounded-md shadow-2xl z-50 max-h-80 overflow-y-auto font-mono text-xs p-1.5 transition-colors">
          {availableModels.length === 0 ? (
            <div className="p-2 text-zinc-400 text-center">
              {isLoading ? 'Loading models…' : 'No models available - open provider manager'}
            </div>
          ) : useGroups ? (
            groups.map((g) => (
              <div key={g.route_id} className="mb-1">
                <div className="px-2 py-1 text-[10px] font-bold text-terminal-amber uppercase tracking-wider bg-terminal-amber/10 rounded">
                  {g.label}
                </div>
                {g.models.map((m) => renderModelButton(m))}
              </div>
            ))
          ) : (
            availableModels.map((m) => renderModelButton(m))
          )}
        </div>
      )}
    </div>
  );
}

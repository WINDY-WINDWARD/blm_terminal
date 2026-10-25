'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import type { ModelOption } from '@/types/aiWidgetTypes';
import type { RouteModelCatalogResponse } from '@/types/aiRoutes';
import { AiModelDropdown } from '@/components/widgets/AiModelDropdown';
import { modeKnobClass, modeTrackClass } from '@/types/aiWidgetTypes';

export interface AiToolbarProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  sessionCount: number;
  model: string;
  defaultModel: string;
  onModelChange: (model: string) => void;
  isStreaming: boolean;
  availableModels: ModelOption[];
  catalogData: RouteModelCatalogResponse | undefined;
  modelsLoading: boolean;
  modelsError: boolean;
  onRetryModels: () => void;
  symbol: string;
  exchange: string;
  streamRouteLabel: string | null;
  streamElapsed: number;
  sessionMode: 'research' | 'script';
  onToggleMode: () => void;
  onNewChat: () => void;
}

export function AiToolbar({
  sidebarOpen,
  onToggleSidebar,
  sessionCount,
  model,
  defaultModel,
  onModelChange,
  isStreaming,
  availableModels,
  catalogData,
  modelsLoading,
  modelsError,
  onRetryModels,
  symbol,
  exchange,
  streamRouteLabel,
  streamElapsed,
  sessionMode,
  onToggleMode,
  onNewChat,
}: AiToolbarProps) {
  return (
    <div className="bg-[#09090b] border-b border-[#27272a] p-2 flex flex-col items-stretch justify-between gap-2 shrink-0 @3xl:flex-row @3xl:items-center">
      <div className="flex w-full min-w-0 flex-wrap items-center gap-2 @3xl:w-auto">
        {/* History Drawer Button */}
        <button
          onClick={onToggleSidebar}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded border text-xs font-mono transition-colors',
            sidebarOpen
              ? 'bg-terminal-amber/15 border-terminal-amber/50 text-terminal-amber font-bold'
              : 'bg-[#121216] border-[#27272a] text-zinc-300 hover:border-amber-400/40 hover:text-white',
          )}
          title="Toggle Session Drawer"
        >
          <span className="text-terminal-amber">☰</span>
          <span className="text-[11px] font-medium">Sessions</span>
          {sessionCount > 0 && (
            <span className="text-[10px] bg-zinc-800 text-zinc-300 px-1 py-0.2 rounded font-mono">
              {sessionCount}
            </span>
          )}
        </button>

        {/* Model Selector Bento Dropdown */}
        <AiModelDropdown
          value={availableModels.some((m) => m.id === model) ? model : defaultModel}
          onChange={onModelChange}
          disabled={isStreaming}
          availableModels={availableModels}
          routeGroups={(catalogData?.routes ?? []).map((route) => ({
            route_id: route.route_id,
            label: route.label,
            models: route.models.map((m) => ({ id: m.id, label: m.label })),
          }))}
          isLoading={modelsLoading}
          loadError={modelsError}
          onRetry={onRetryModels}
        />

        {/* Active Context Stock Pill */}
        <div className="ml-auto flex items-center gap-1.5 bg-terminal-amber/10 border border-terminal-amber/30 px-2.5 py-1 rounded text-xs font-mono @3xl:ml-0">
          <span className="text-[10px] uppercase tracking-wider text-zinc-400 font-bold">CTX</span>
          <span className="text-terminal-amber font-bold">
            {symbol ? `${symbol}.${exchange}` : 'NIFTY.NSE'}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        {/* Thinking indicator */}
        {isStreaming && (
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-500/10 border border-blue-400/30 text-blue-300 text-[11px] font-mono animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            <span>thinking…{streamRouteLabel ? ` · ${streamRouteLabel}` : ""}{streamElapsed > 0 ? ` · ${streamElapsed}s` : ""}</span>
          </div>
        )}

        {/* Sliding Research | Script mode toggle */}
        <button
          role="switch"
          aria-checked={sessionMode === 'script'}
          data-testid="ai-mode-toggle"
          data-mode={sessionMode}
          onClick={onToggleMode}
          disabled={isStreaming}
          title="Research answers questions; Script writes versioned chart scripts (Script Lab)"
          className={cn(
            'relative w-[130px] h-[24px] rounded-full border transition-all shrink-0 disabled:opacity-50',
            modeTrackClass(sessionMode),
          )}
        >
          <span
            className={cn(
              'absolute inset-0 flex items-center justify-between px-2 text-[10px] font-mono font-bold pointer-events-none',
              sessionMode === 'script' ? 'text-emerald-300/85' : 'text-terminal-amber/85',
            )}
          >
            <span>Research</span>
            <span>Σ Script</span>
          </span>
          <span
            className={cn(
              'absolute top-[2px] bottom-[2px] w-[calc(50%-3px)] rounded-full text-[10px] font-mono flex items-center justify-center transition-all',
              modeKnobClass(sessionMode),
            )}
          >
            {sessionMode === 'script' ? 'Σ Script' : 'Research'}
          </span>
        </button>

        {/* New Chat Button */}
        <button
          onClick={onNewChat}
          className="px-2.5 py-1 rounded bg-[#121216] border border-[#27272a] hover:border-amber-400 hover:text-terminal-amber text-zinc-200 text-xs font-mono font-semibold transition-colors"
          title="Create new scratch session"
        >
          + New
        </button>
      </div>
    </div>
  );
}

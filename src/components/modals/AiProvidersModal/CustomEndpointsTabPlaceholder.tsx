'use client';

import React from 'react';
import { Globe, Key, Layers, Plus, Server, Sparkles } from 'lucide-react';
import type { RouteSummary } from '@/types/aiRoutes';

interface CustomEndpointsTabPlaceholderProps {
  routes: RouteSummary[];
  activeRouteId: string;
}

export function CustomEndpointsTabPlaceholder({ routes, activeRouteId }: CustomEndpointsTabPlaceholderProps) {
  const endpointRoutes = routes.filter((r) => r.kind === 'endpoint');

  return (
    <div data-testid="custom-endpoints-tab" className="flex flex-col gap-4 font-sans">
      {/* Intro Bento Banner */}
      <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
            <Globe className="w-5 h-5" />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-mono font-bold text-white uppercase tracking-wider">
                CUSTOM OPENAI-COMPATIBLE ENDPOINTS
              </h4>
              <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[10px]">
                Task 7 Seam
              </span>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed max-w-2xl">
              Connect private enterprise gateways, vLLM, Ollama, OpenRouter proxies, or LiteLLM endpoints with weighted
              keys, model catalogs, and live failover routing.
            </p>
          </div>
        </div>

        <button
          type="button"
          disabled
          className="shrink-0 px-3 py-1.5 rounded bg-zinc-800 text-zinc-500 font-mono text-xs border border-zinc-700 cursor-not-allowed flex items-center gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          + NEW ENDPOINT (TASK 7)
        </button>
      </div>

      {/* Existing Endpoint Routes or Empty State */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {endpointRoutes.length > 0 ? (
          endpointRoutes.map((route) => (
            <div
              key={route.id}
              className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-3.5 flex flex-col gap-2"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono font-bold text-xs text-white">{route.display_label}</span>
                <span className="text-[10px] font-mono text-zinc-400">{route.keys.length} keys</span>
              </div>
              <span className="text-[11px] font-mono text-zinc-500 truncate">{route.config.base_url || route.id}</span>
            </div>
          ))
        ) : (
          <div className="col-span-full p-8 rounded-lg border border-dashed border-zinc-800 bg-[#0c0c0f]/60 text-center flex flex-col items-center justify-center gap-2">
            <Server className="w-8 h-8 text-zinc-600 mb-1" />
            <span className="text-sm font-mono text-zinc-300">No Custom Endpoints Registered</span>
            <p className="text-xs text-zinc-500 max-w-md">
              Full CRUD management for custom endpoints, base URLs, secret headers, weighted keys, and model fetching will
              be unlocked in Task 7.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

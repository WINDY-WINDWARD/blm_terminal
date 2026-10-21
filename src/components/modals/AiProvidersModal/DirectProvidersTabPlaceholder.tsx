'use client';

import React from 'react';
import { CheckCircle2, Cpu, Key, ShieldCheck, Zap } from 'lucide-react';
import { useActivateRouteMutation } from '@/hooks/useAiRoutes';
import type { RouteSummary } from '@/types/aiRoutes';

interface DirectProvidersTabPlaceholderProps {
  routes: RouteSummary[];
  activeRouteId: string;
}

export function DirectProvidersTabPlaceholder({ routes, activeRouteId }: DirectProvidersTabPlaceholderProps) {
  const activateRoute = useActivateRouteMutation();
  const directRoutes = routes.filter((r) => r.kind === 'direct');

  return (
    <div data-testid="direct-providers-tab" className="flex flex-col gap-4 font-sans">
      {/* Intro Banner */}
      <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
            <Cpu className="w-5 h-5" />
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-mono font-bold text-white uppercase tracking-wider">
                DIRECT API-KEY PROVIDERS
              </h4>
              <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[10px]">
                Task 7 Seam
              </span>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed max-w-2xl">
              Direct providers communicate directly with provider APIs. They remain 100% operational even if the local
              proxy supervisor or encrypted vault is offline or degraded.
            </p>
          </div>
        </div>

        <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 rounded bg-emerald-950/40 border border-emerald-800/60 text-emerald-300 font-mono text-xs">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          Native Direct Paths Ready
        </div>
      </div>

      {/* Direct Providers Overview Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {directRoutes.map((route) => {
          const isActive = activeRouteId === route.id;
          const isConfigured = Boolean(route.config.is_configured);

          return (
            <div
              key={route.id}
              className={`p-3 bg-[#0c0c0f] border rounded-lg flex flex-col justify-between transition-colors ${
                isActive ? 'border-terminal-amber/60 bg-amber-950/5' : 'border-[#27272a]'
              }`}
            >
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-bold text-xs text-white">{route.display_label}</span>
                  {isActive ? (
                    <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 font-mono text-[10px] font-bold">
                      ACTIVE
                    </span>
                  ) : isConfigured ? (
                    <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px]">
                      Configured
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-500 font-mono text-[10px]">
                      Not Set
                    </span>
                  )}
                </div>
                <span className="text-[10px] font-mono text-zinc-500">{route.id}</span>
              </div>

              <div className="flex items-center justify-between pt-2 mt-2 border-t border-[#27272a]/60">
                <span className="text-[10px] font-mono text-zinc-500">Inference: Direct HTTP</span>
                {!isActive && (
                  <button
                    type="button"
                    onClick={() => activateRoute.mutate(route.id)}
                    disabled={activateRoute.isPending}
                    className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-terminal-amber font-mono text-[10px] font-bold border border-terminal-amber/30 transition-colors cursor-pointer"
                  >
                    Activate
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

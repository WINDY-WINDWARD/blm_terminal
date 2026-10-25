'use client';

import React, { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Layers,
  Lock,
  RefreshCw,
  Server,
  ShieldAlert,
  ShieldCheck,
  ToggleLeft,
  ToggleRight,
  Zap,
} from 'lucide-react';
import { useUpdateRouteSettingsMutation } from '@/hooks/useAiRoutes';
import { VaultResetModal } from './VaultResetModal';
import type { RoutesListResponse, RoutingStrategy } from '@/types/aiRoutes';

interface TopSummaryProps {
  data: RoutesListResponse;
}

export function TopSummary({ data }: TopSummaryProps) {
  const updateSettings = useUpdateRouteSettingsMutation();
  const [showResetModal, setShowResetModal] = useState(false);

  const activeRoute = data.routes.find((r) => r.id === data.active_route_id);
  const activeLabel = activeRoute?.display_label || data.active_route_id;

  const proxyState = (data.proxy_status?.state || 'stopped').toLowerCase();
  const vaultState = data.vault_state || 'available';
  const isVaultDegraded = vaultState !== 'available' || Boolean(data.recovery_state);

  // Totals
  const totalOAuthAccounts = data.routes
    .filter((r) => r.kind === 'oauth')
    .reduce((acc, r) => acc + (r.accounts?.length || 0), 0);

  const totalCustomKeys = data.routes
    .filter((r) => r.kind === 'endpoint')
    .reduce((acc, r) => acc + (r.keys?.length || 0), 0);

  const currentStrategy = (data.settings?.strategy || 'fill-first') as RoutingStrategy;
  const strategyDescriptions: Record<string, string> = {
    'fill-first': 'Use the first healthy account until it cools down.',
    'round-robin': 'Rotate among healthy accounts.',
    priority: 'Use strict priority tiers.',
  };
  const strategyDescription = strategyDescriptions[currentStrategy] ?? strategyDescriptions['fill-first'];
  const stickyEnabled = Boolean(data.settings?.session_affinity);

  const handleStrategyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    updateSettings.mutate({ strategy: e.target.value });
  };

  const handleToggleSticky = () => {
    updateSettings.mutate({ session_affinity: !stickyEnabled });
  };

  return (
    <div className="flex flex-col gap-2.5 font-mono">
      {/* Recovery / Degraded Banner */}
      {isVaultDegraded && (
        <div
          data-testid="vault-recovery-banner"
          className="p-2.5 rounded bg-amber-950/50 border border-amber-800 text-amber-200 text-xs flex items-center justify-between gap-3 flex-wrap"
        >
          <div className="flex items-center gap-2 min-w-0">
            <AlertTriangle className="w-4 h-4 text-terminal-amber shrink-0" />
            <span className="leading-snug truncate">
              {data.recovery_state ||
                `Provider vault is ${vaultState}. Direct providers remain fully functional.`}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setShowResetModal(true)}
            className="px-2.5 py-1 rounded bg-amber-900/60 hover:bg-amber-800 text-terminal-amber text-[10px] font-bold border border-amber-700 transition-colors shrink-0 cursor-pointer"
          >
            RESET VAULT
          </button>
        </div>
      )}

      {/* Primary Summary Bento Matrix Strip */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5">
        {/* 1. Active Route */}
        <div className="flex flex-col gap-1 p-2 rounded bg-[#09090b] border border-zinc-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase text-zinc-400 font-bold tracking-wider">ACTIVE ROUTE</span>
            <Zap className="w-3.5 h-3.5 text-terminal-amber" />
          </div>
          <div
            data-testid="active-route-display"
            className="text-xs font-bold text-white truncate"
            title={activeLabel}
          >
            {activeLabel}
          </div>
          <span className="text-[10px] text-terminal-amber truncate">{data.active_route_id}</span>
        </div>

        {/* 2. Proxy Health */}
        <div className="flex flex-col gap-1 p-2 rounded bg-[#09090b] border border-zinc-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase text-zinc-400 font-bold tracking-wider">PROXY HEALTH</span>
            <Server className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                proxyState === 'running'
                  ? 'bg-terminal-green shadow-sm shadow-emerald-500'
                  : proxyState === 'crashed'
                  ? 'bg-terminal-red shadow-sm shadow-rose-500'
                  : 'bg-zinc-500'
              }`}
            />
            <span
              data-testid="proxy-health-status"
              className={`text-xs font-bold uppercase ${
                proxyState === 'running'
                  ? 'text-emerald-400'
                  : proxyState === 'crashed'
                  ? 'text-rose-400'
                  : 'text-zinc-400'
              }`}
            >
              {proxyState}
            </span>
          </div>
          <span className="text-[10px] text-zinc-500">
            {data.proxy_status?.port ? `Port: ${data.proxy_status.port}` : 'Local sidecar'}
          </span>
        </div>

        {/* 3. Vault Recovery */}
        <div className="flex flex-col gap-1 p-2 rounded bg-[#09090b] border border-zinc-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase text-zinc-400 font-bold tracking-wider">VAULT</span>
            <Lock className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center justify-between gap-1">
            <span
              data-testid="vault-state-status"
              className={`text-xs font-bold uppercase truncate ${
                vaultState === 'available'
                  ? 'text-emerald-400'
                  : vaultState === 'keyring_unavailable'
                  ? 'text-amber-400'
                  : 'text-rose-400'
              }`}
            >
              {vaultState === 'available' ? 'READY' : vaultState}
            </span>
            <button
              type="button"
              onClick={() => setShowResetModal(true)}
              title="Reset encrypted provider vault"
              aria-label="Reset provider vault"
              className="text-[10px] px-1 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-white transition-colors cursor-pointer"
            >
              Reset
            </button>
          </div>
          <span className="text-[10px] text-zinc-500">AES-256 Keyring</span>
        </div>

        {/* 4. Routing Strategy */}
        <div className="flex flex-col gap-1 p-2 rounded bg-[#09090b] border border-zinc-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase text-zinc-400 font-bold tracking-wider">STRATEGY</span>
            <Layers className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <select
            data-testid="routing-strategy-select"
            value={currentStrategy}
            onChange={handleStrategyChange}
            disabled={updateSettings.isPending}
            aria-label="Routing Strategy"
            className="bg-[#121216] border border-zinc-700 rounded px-1.5 py-0.5 text-xs text-white focus:border-terminal-amber outline-none cursor-pointer"
          >
            <option value="fill-first">fill-first</option>
            <option value="round-robin">round-robin</option>
            <option value="priority">priority</option>
          </select>
          <span data-testid="routing-strategy-description" className="text-[10px] leading-relaxed text-zinc-500">
            {strategyDescription}
          </span>
        </div>

        {/* 5. Sticky Session Toggle */}
        <div className="flex flex-col gap-1 p-2 rounded bg-[#09090b] border border-zinc-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase text-zinc-400 font-bold tracking-wider">STICKY SESSIONS</span>
            <Activity className="w-3.5 h-3.5 text-zinc-400" />
          </div>
          <button
            type="button"
            data-testid="sticky-session-toggle"
            onClick={handleToggleSticky}
            disabled={updateSettings.isPending}
            aria-label={`Toggle sticky sessions: currently ${stickyEnabled ? 'ON' : 'OFF'}`}
            className={`flex items-center justify-between px-2 py-0.5 rounded text-xs font-bold border transition-colors cursor-pointer ${
              stickyEnabled
                ? 'bg-emerald-950/60 border-emerald-700 text-emerald-300'
                : 'bg-zinc-800 border-zinc-700 text-zinc-400'
            }`}
          >
            <span>{stickyEnabled ? 'ON' : 'OFF'}</span>
            {stickyEnabled ? (
              <ToggleRight className="w-4 h-4 text-emerald-400" />
            ) : (
              <ToggleLeft className="w-4 h-4 text-zinc-500" />
            )}
          </button>
          <span className="text-[10px] text-zinc-500">Session affinity</span>
        </div>

        {/* 6. Accounts / Keys Total Count */}
        <div className="flex flex-col gap-1 p-2 rounded bg-[#09090b] border border-zinc-800/80">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase text-zinc-400 font-bold tracking-wider">INVENTORY</span>
            <Cpu className="w-3.5 h-3.5 text-terminal-amber" />
          </div>
          <div data-testid="credentials-count" className="text-xs font-bold text-white truncate">
            {totalOAuthAccounts} Acct{totalOAuthAccounts !== 1 ? 's' : ''} · {totalCustomKeys} Key{totalCustomKeys !== 1 ? 's' : ''}
          </div>
          <span className="text-[10px] text-zinc-500">Registered pool</span>
        </div>
      </div>

      {/* Vault Reset Modal Dialog */}
      <VaultResetModal isOpen={showResetModal} onClose={() => setShowResetModal(false)} />
    </div>
  );
}

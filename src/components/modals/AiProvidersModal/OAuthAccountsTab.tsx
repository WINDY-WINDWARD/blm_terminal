'use client';

import React, { useState } from 'react';
import {
  Check,
  CheckCircle2,
  ExternalLink,
  Laptop,
  Layers,
  Loader2,
  Plus,
  Radio,
  Shield,
  Smartphone,
  Zap,
} from 'lucide-react';
import { useActivateRouteMutation } from '@/hooks/useAiRoutes';
import { OAuthAccountCard } from './OAuthAccountCard';
import { OAuthSessionDialog } from './OAuthSessionDialog';
import type { RouteSummary } from '@/types/aiRoutes';

export interface OAuthProviderDef {
  id: string;
  label: string;
  routeId: string;
  desc: string;
}

export const OAUTH_PROVIDER_DEFINITIONS: OAuthProviderDef[] = [
  { id: 'codex', label: 'Codex', routeId: 'oauth:codex', desc: 'OpenAI Codex models via ChatGPT Plus/Pro OAuth' },
  { id: 'antigravity', label: 'Antigravity', routeId: 'oauth:antigravity', desc: 'Google Gemini 3.8 Flash via Google Antigravity OAuth' },
  { id: 'claude', label: 'Claude', routeId: 'oauth:claude', desc: 'Anthropic Claude Code CLI OAuth' },
  { id: 'xai', label: 'xAI', routeId: 'oauth:xai', desc: 'xAI Grok models via OAuth subscription' },
  { id: 'kimi', label: 'Kimi', routeId: 'oauth:kimi', desc: 'Moonshot Kimi models via OAuth' },
  { id: 'kimi-ai', label: 'Kimi AI', routeId: 'oauth:kimi-ai', desc: 'Kimi AI platform OAuth' },
  { id: 'meta', label: 'Meta', routeId: 'oauth:meta', desc: 'Meta AI OAuth subscription' },
  { id: 'devin', label: 'Devin', routeId: 'oauth:devin', desc: 'Cognition Devin AI OAuth' },
];

interface OAuthAccountsTabProps {
  routes: RouteSummary[];
  activeRouteId: string;
}

interface DialogState {
  isOpen: boolean;
  provider: string;
  providerLabel: string;
  flow: 'browser' | 'device';
  replaceAccountId?: string | null;
  replaceAccountIdentity?: string | null;
}

export function OAuthAccountsTab({ routes, activeRouteId }: OAuthAccountsTabProps) {
  const activateRoute = useActivateRouteMutation();

  const [dialogState, setDialogState] = useState<DialogState>({
    isOpen: false,
    provider: 'codex',
    providerLabel: 'Codex',
    flow: 'browser',
  });

  const handleStartOAuth = (provider: string, providerLabel: string, flow: 'browser' | 'device') => {
    setDialogState({
      isOpen: true,
      provider,
      providerLabel,
      flow,
      replaceAccountId: null,
      replaceAccountIdentity: null,
    });
  };

  const handleReauth = (provider: string, providerLabel: string, accountId: string, identity: string) => {
    setDialogState({
      isOpen: true,
      provider,
      providerLabel,
      flow: 'browser',
      replaceAccountId: accountId,
      replaceAccountIdentity: identity,
    });
  };

  const handleCloseDialog = () => {
    setDialogState((prev) => ({ ...prev, isOpen: false }));
  };

  return (
    <div className="flex flex-col gap-4 font-sans">
      {/* Provider Groups Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {OAUTH_PROVIDER_DEFINITIONS.map((def) => {
          const matchedRoute = routes.find((r) => r.id === def.routeId || (r.kind === 'oauth' && r.provider === def.id));
          const accounts = matchedRoute?.accounts || [];
          const isActive = activeRouteId === def.routeId;
          const isConfigured = accounts.length > 0;
          const isActivating = activateRoute.isPending && activateRoute.variables === def.routeId;

          return (
            <div
              key={def.id}
              data-testid={`oauth-provider-group-${def.id}`}
              className={`bg-[#0c0c0f] border rounded-lg p-3.5 flex flex-col justify-between transition-colors ${
                isActive
                  ? 'border-terminal-amber/60 bg-amber-950/5 shadow-md shadow-terminal-amber/5'
                  : 'border-[#27272a] hover:border-zinc-700'
              }`}
            >
              {/* Card Header */}
              <div className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <div
                      className={`p-1.5 rounded font-mono font-bold text-xs ${
                        isActive
                          ? 'bg-terminal-amber/20 text-terminal-amber border border-terminal-amber/40'
                          : 'bg-zinc-800 text-zinc-300'
                      }`}
                    >
                      {def.label.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex flex-col min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-mono font-bold text-white tracking-wide">{def.label}</h4>
                        <span className="text-[10px] font-mono text-zinc-500">{def.routeId}</span>
                      </div>
                      <p className="text-[11px] text-zinc-400 line-clamp-1">{def.desc}</p>
                    </div>
                  </div>

                  {/* Active Route Pill or Activate Button */}
                  <div className="shrink-0 flex items-center">
                    {isActive ? (
                      <span
                        data-testid={`active-pill-${def.id}`}
                        className="px-2.5 py-0.5 rounded bg-emerald-950/70 border border-emerald-700 text-emerald-300 font-mono text-[10px] font-bold flex items-center gap-1"
                      >
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        ACTIVE ROUTE
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => activateRoute.mutate(def.routeId)}
                        disabled={isActivating || !isConfigured}
                        title={
                          isConfigured
                            ? `Set ${def.label} as the active BLM inference route`
                            : 'Add at least one account to activate this route'
                        }
                        className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-300 font-mono text-[10px] font-bold border border-zinc-700 transition-colors flex items-center gap-1 cursor-pointer"
                      >
                        {isActivating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3 text-terminal-amber" />}
                        ACTIVATE
                      </button>
                    )}
                  </div>
                </div>

                {/* Account Actions Bar */}
                <div className="flex items-center justify-between pt-2 pb-1 border-t border-[#27272a]/60 flex-wrap gap-2">
                  <span className="text-[11px] font-mono text-zinc-400">
                    Accounts: <span className="text-white font-bold">{accounts.length}</span>
                  </span>

                  <div className="flex items-center gap-1.5">
                    {/* Add (Browser) */}
                    <button
                      type="button"
                      onClick={() => handleStartOAuth(def.id, def.label, 'browser')}
                      className="px-2 py-0.5 rounded bg-terminal-amber/10 hover:bg-terminal-amber/20 text-terminal-amber font-mono text-[10px] font-bold border border-terminal-amber/30 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3 h-3" />
                      ADD (BROWSER)
                    </button>

                    {/* Add (Device) */}
                    <button
                      type="button"
                      onClick={() => handleStartOAuth(def.id, def.label, 'device')}
                      className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-[10px] font-bold border border-zinc-700 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Smartphone className="w-3 h-3 text-zinc-400" />
                      ADD (DEVICE)
                    </button>
                  </div>
                </div>
              </div>

              {/* Accounts List */}
              <div className="flex flex-col gap-2 mt-2 pt-1">
                {accounts.length === 0 ? (
                  <div className="p-3 rounded border border-dashed border-zinc-800 bg-zinc-950/40 text-center text-zinc-500 font-mono text-[11px]">
                    No accounts connected. Click <span className="text-terminal-amber">ADD</span> to link via OAuth.
                  </div>
                ) : (
                  accounts.map((acc) => (
                    <OAuthAccountCard
                      key={acc.id}
                      account={acc}
                      providerLabel={def.label}
                      onReauth={(accId, ident) => handleReauth(def.id, def.label, accId, ident)}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* OAuth Session Dialog */}
      <OAuthSessionDialog
        isOpen={dialogState.isOpen}
        provider={dialogState.provider}
        providerLabel={dialogState.providerLabel}
        flow={dialogState.flow}
        replaceAccountId={dialogState.replaceAccountId}
        replaceAccountIdentity={dialogState.replaceAccountIdentity}
        onClose={handleCloseDialog}
      />
    </div>
  );
}

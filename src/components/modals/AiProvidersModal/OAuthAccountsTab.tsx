'use client';

import React, { useState } from 'react';
import { OAuthAccountCard } from './OAuthAccountCard';
import { OAuthSessionDialog } from './OAuthSessionDialog';
import { RouteActiveToggle } from './RouteActiveToggle';
import { useActivateRouteMutation, useSetRouteEnabledMutation } from '@/hooks/useAiRoutes';
import { Plus } from 'lucide-react';
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
  replaceAccountId?: string | null;
  replaceAccountIdentity?: string | null;
}

export function OAuthAccountsTab({ routes, activeRouteId }: OAuthAccountsTabProps) {
  const activateRoute = useActivateRouteMutation();
  const setRouteEnabled = useSetRouteEnabledMutation();

  const [dialogState, setDialogState] = useState<DialogState>({
    isOpen: false,
    provider: 'codex',
    providerLabel: 'Codex',
  });

  const handleStartOAuth = (provider: string, providerLabel: string) => {
    setDialogState({
      isOpen: true,
      provider,
      providerLabel,
      replaceAccountId: null,
      replaceAccountIdentity: null,
    });
  };

  const handleReauth = (provider: string, providerLabel: string, accountId: string, identity: string) => {
    setDialogState({
      isOpen: true,
      provider,
      providerLabel,
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
          const isDefault = activeRouteId === def.routeId;
          const isConfigured = accounts.length > 0;
          const isEnabled = matchedRoute?.enabled ?? true;
          const isPending = setRouteEnabled.isPending && setRouteEnabled.variables?.routeId === def.routeId;

          return (
            <div
              key={def.id}
              data-testid={`oauth-provider-group-${def.id}`}
              className={`bg-[#0c0c0f] border rounded-lg p-3.5 flex flex-col justify-between transition-colors ${
                isDefault
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
                        isDefault
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

                  {/* Route Active / Inactive / Default Controls */}
                  <RouteActiveToggle
                    enabled={isEnabled}
                    isDefault={isDefault}
                    configured={isConfigured}
                    isPending={isPending}
                    testId={`route-active-toggle-${def.id}`}
                    onToggle={() =>
                      setRouteEnabled.mutate({
                        routeId: def.routeId,
                        enabled: !isEnabled,
                      })
                    }
                    onMakeDefault={() => activateRoute.mutate(def.routeId)}
                  />
                </div>

                {/* Account Actions Bar */}
                <div className="flex items-center justify-between pt-2 pb-1 border-t border-[#27272a]/60 flex-wrap gap-2">
                  <span className="text-[11px] font-mono text-zinc-400">
                    Accounts: <span className="text-white font-bold">{accounts.length}</span>
                  </span>

                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => handleStartOAuth(def.id, def.label)}
                      className="px-2 py-0.5 rounded bg-terminal-amber/10 hover:bg-terminal-amber/20 text-terminal-amber font-mono text-[10px] font-bold border border-terminal-amber/30 transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3 h-3" />
                      ADD ACCOUNT
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
        replaceAccountId={dialogState.replaceAccountId}
        replaceAccountIdentity={dialogState.replaceAccountIdentity}
        onClose={handleCloseDialog}
      />
    </div>
  );
}

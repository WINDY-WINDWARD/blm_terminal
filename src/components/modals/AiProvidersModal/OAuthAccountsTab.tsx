'use client';

import React, { useState } from 'react';
import { AlertTriangle, Plus } from 'lucide-react';
import { OAuthAccountCard } from './OAuthAccountCard';
import { OAuthSessionDialog } from './OAuthSessionDialog';
import { ProviderRiskModal } from './ProviderRiskModal';
import { RouteActiveToggle } from './RouteActiveToggle';
import {
  useAcknowledgeRouteRiskMutation,
  useActivateRouteMutation,
  usePatchAccountMutation,
  useSetRouteEnabledMutation,
} from '@/hooks/useAiRoutes';
import type { ProviderRiskInfo, RouteSummary } from '@/types/aiRoutes';

export interface OAuthProviderDef {
  id: string;
  label: string;
  routeId: string;
  desc: string;
}

export const OAUTH_PROVIDER_DEFINITIONS: OAuthProviderDef[] = [
  { id: 'codex', label: 'Codex', routeId: 'oauth:codex', desc: 'OpenAI Codex models via ChatGPT Plus/Pro OAuth' },
  { id: 'antigravity', label: 'Gemini (Antigravity)', routeId: 'oauth:antigravity', desc: 'Google Gemini via Google Antigravity OAuth' },
  { id: 'claude', label: 'Claude', routeId: 'oauth:claude', desc: 'Anthropic Claude Code CLI OAuth' },
  { id: 'xai', label: 'xAI', routeId: 'oauth:xai', desc: 'xAI Grok models via OAuth subscription' },
  { id: 'kimi', label: 'Kimi', routeId: 'oauth:kimi', desc: 'Moonshot Kimi models via OAuth' },
  { id: 'kimi-ai', label: 'Kimi AI', routeId: 'oauth:kimi-ai', desc: 'Kimi AI platform OAuth' },
  { id: 'meta', label: 'Meta', routeId: 'oauth:meta', desc: 'Meta AI OAuth subscription' },
  { id: 'devin', label: 'Devin', routeId: 'oauth:devin', desc: 'Cognition Devin AI OAuth' },
];

const RISKY_PROVIDER_IDS = new Set(['antigravity', 'claude']);
const SAFE_OAUTH_PROVIDERS = OAUTH_PROVIDER_DEFINITIONS.filter((d) => !RISKY_PROVIDER_IDS.has(d.id));
const RISKY_OAUTH_PROVIDERS = OAUTH_PROVIDER_DEFINITIONS.filter((d) => RISKY_PROVIDER_IDS.has(d.id));

const RISK_FALLBACK_MESSAGE =
  'These connections use your personal subscription through an unofficial client. ' +
  'The provider can detect this use and suspend or permanently ban the account. ' +
  'A ban can also block other services tied to that account. ' +
  'BLM Terminal cannot recover a banned account.';

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

interface RiskDialogState {
  provider: OAuthProviderDef;
  risk: ProviderRiskInfo;
  run: () => void;
}

export function OAuthAccountsTab({ routes, activeRouteId }: OAuthAccountsTabProps) {
  const activateRoute = useActivateRouteMutation();
  const setRouteEnabled = useSetRouteEnabledMutation();
  const patchAccount = usePatchAccountMutation();
  const acknowledgeRisk = useAcknowledgeRouteRiskMutation();

  const [dialogState, setDialogState] = useState<DialogState>({
    isOpen: false,
    provider: 'codex',
    providerLabel: 'Codex',
  });
  const [riskDialog, setRiskDialog] = useState<RiskDialogState | null>(null);
  const [riskError, setRiskError] = useState<string | null>(null);

  const findRoute = (def: OAuthProviderDef): RouteSummary | undefined =>
    routes.find((r) => r.id === def.routeId || (r.kind === 'oauth' && r.provider === def.id));

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

  const guardRisk = (def: OAuthProviderDef, risk: ProviderRiskInfo | null, run: () => void) => {
    if (!risk || risk.acknowledged) {
      run();
      return;
    }
    setRiskError(null);
    setRiskDialog({ provider: def, risk, run });
  };

  const handleAcceptRisk = async () => {
    if (!riskDialog) return;
    setRiskError(null);
    try {
      await acknowledgeRisk.mutateAsync(riskDialog.provider.routeId);
      const run = riskDialog.run;
      setRiskDialog(null);
      run();
    } catch (err: unknown) {
      setRiskError(err instanceof Error ? err.message : 'Could not record risk acceptance');
    }
  };

  const handleCloseRiskDialog = () => {
    if (acknowledgeRisk.isPending) return;
    setRiskDialog(null);
    setRiskError(null);
  };

  const renderProviderCard = (def: OAuthProviderDef, risky: boolean) => {
    const matchedRoute = findRoute(def);
    const accounts = matchedRoute?.accounts || [];
    const risk = matchedRoute?.risk ?? null;
    const isDefault = activeRouteId === def.routeId;
    const isConfigured = accounts.length > 0;
    const isEnabled = matchedRoute?.enabled ?? true;
    const isPending = setRouteEnabled.isPending && setRouteEnabled.variables?.routeId === def.routeId;
    const autoDisabled = risky && risk != null && !risk.acknowledged && !isEnabled;

    return (
      <div
        key={def.id}
        data-testid={`oauth-provider-group-${def.id}`}
        className={`bg-[#0c0c0f] border rounded-lg p-3.5 flex flex-col justify-between transition-colors ${
          isDefault
            ? 'border-terminal-amber/60 bg-amber-950/5 shadow-md shadow-terminal-amber/5'
            : risky
            ? 'border-rose-900/60 bg-rose-950/5'
            : 'border-[#27272a] hover:border-zinc-700'
        }`}
      >
        {/* Card Header */}
        <div className="flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <div
                className={`p-1.5 rounded font-mono font-bold text-xs ${
                  risky
                    ? 'bg-rose-950/60 text-rose-300 border border-rose-800'
                    : isDefault
                    ? 'bg-terminal-amber/20 text-terminal-amber border border-terminal-amber/40'
                    : 'bg-zinc-800 text-zinc-300'
                }`}
              >
                {def.label.slice(0, 2).toUpperCase()}
              </div>
              <div className="flex flex-col min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h4 className="text-sm font-mono font-bold text-white tracking-wide">{def.label}</h4>
                  <span className="text-[10px] font-mono text-zinc-500">{def.routeId}</span>
                  {risky && (
                    <span
                      data-testid={`risk-badge-${def.id}`}
                      className="px-1.5 py-0.5 rounded bg-rose-950/60 border border-rose-800 text-rose-300 font-mono text-[9px] font-bold tracking-wider flex items-center gap-1"
                    >
                      <AlertTriangle className="w-2.5 h-2.5" />
                      DO NOT USE
                    </span>
                  )}
                  {autoDisabled && (
                    <span
                      data-testid={`risk-auto-disabled-${def.id}`}
                      className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 font-mono text-[9px] font-bold tracking-wider"
                    >
                      AUTO-DISABLED
                    </span>
                  )}
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
              onToggle={() => {
                if (isEnabled) {
                  setRouteEnabled.mutate({ routeId: def.routeId, enabled: false });
                  return;
                }
                guardRisk(def, risk, () => setRouteEnabled.mutate({ routeId: def.routeId, enabled: true }));
              }}
              onMakeDefault={() => guardRisk(def, risk, () => activateRoute.mutate(def.routeId))}
            />
          </div>

          {/* Account Actions Bar */}
          <div className="flex items-center justify-between pt-2 pb-1 border-t border-[#27272a]/60 flex-wrap gap-2">
            <span className="text-[11px] font-mono text-zinc-400">
              Accounts: <span className="text-white font-bold">{accounts.length}</span>
            </span>

            <div className="flex items-center gap-1.5">
              {risky && risk && !risk.acknowledged && (
                <button
                  type="button"
                  onClick={() => {
                    setRiskError(null);
                    setRiskDialog({ provider: def, risk, run: () => {} });
                  }}
                  data-testid={`review-risk-${def.id}`}
                  className="px-2 py-0.5 rounded bg-rose-950/60 hover:bg-rose-900/60 text-rose-300 font-mono text-[10px] font-bold border border-rose-800 transition-colors flex items-center gap-1 cursor-pointer"
                >
                  <AlertTriangle className="w-3 h-3" />
                  REVIEW RISK
                </button>
              )}
              <button
                type="button"
                onClick={() => guardRisk(def, risk, () => handleStartOAuth(def.id, def.label))}
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
                onReauth={(accId, ident) =>
                  guardRisk(def, risk, () => handleReauth(def.id, def.label, accId, ident))
                }
                riskAcknowledged={!risk || risk.acknowledged}
                onBlockedEnable={
                  risk && !risk.acknowledged
                    ? () =>
                        guardRisk(def, risk, () =>
                          patchAccount.mutate({ accountId: acc.id, patch: { enabled: true } }),
                        )
                    : undefined
                }
              />
            ))
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4 font-sans">
      {/* Standard Providers */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
        {SAFE_OAUTH_PROVIDERS.map((def) => renderProviderCard(def, false))}
      </div>

      {/* High-Risk Providers */}
      <div className="flex flex-col gap-2.5">
        <div className="p-3 rounded-lg border border-rose-900/60 bg-rose-950/20">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <h3 className="font-mono text-xs font-bold text-rose-300 uppercase tracking-wider">
              DO NOT USE - HIGH RISK OF ACCOUNT BAN
            </h3>
          </div>
          <p className="text-[11px] text-rose-200/80 mt-1.5 leading-relaxed">{RISK_FALLBACK_MESSAGE}</p>
          <p className="text-[11px] text-rose-200/60 mt-1 leading-relaxed font-mono">
            These routes are disabled by default. Enable only after you accept the risk.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
          {RISKY_OAUTH_PROVIDERS.map((def) => renderProviderCard(def, true))}
        </div>
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

      {/* Risk Acknowledgement Dialog */}
      <ProviderRiskModal
        isOpen={riskDialog != null}
        providerLabel={riskDialog?.provider.label ?? ''}
        risk={riskDialog?.risk ?? null}
        isPending={acknowledgeRisk.isPending}
        error={riskError}
        onAccept={handleAcceptRisk}
        onClose={handleCloseRiskDialog}
      />
    </div>
  );
}

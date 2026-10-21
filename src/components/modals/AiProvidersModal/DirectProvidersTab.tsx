'use client';

import React, { useState } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Cpu,
  Edit2,
  Eye,
  EyeOff,
  Key,
  Layers,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Zap,
} from 'lucide-react';
import { useActivateRouteMutation, useInvalidateAiCaches } from '@/hooks/useAiRoutes';
import { AI_PROVIDERS, type AiProviderMeta } from '@/lib/aiProviders';
import { AiProviderInstructions } from '@/components/AiProviderInstructions';
import type { RouteSummary } from '@/types/aiRoutes';

interface DirectProvidersTabProps {
  routes: RouteSummary[];
  activeRouteId: string;
}

export function DirectProvidersTab({ routes, activeRouteId }: DirectProvidersTabProps) {
  const activateRouteMutation = useActivateRouteMutation();
  const invalidateAiCaches = useInvalidateAiCaches();

  // Filter to API-key based direct providers
  const directProviders = AI_PROVIDERS.filter((p) => p.kind === 'api-key');

  // Map route-configured status
  const routeMap = new Map<string, RouteSummary>();
  for (const r of routes) {
    if (r.kind === 'direct') {
      routeMap.set(r.provider, r);
      routeMap.set(r.id, r);
    }
  }

  // Selected provider for focused detail, default to first or currently active
  const initialSelectedId = () => {
    if (activeRouteId.startsWith('direct:')) {
      const prov = activeRouteId.split(':', 1)[1] || activeRouteId.replace('direct:', '');
      if (directProviders.some((p) => p.id === prov)) return prov;
    }
    return directProviders[0]?.id || 'aistudio';
  };

  const [selectedProviderId, setSelectedProviderId] = useState<string>(initialSelectedId);

  // Key replacement mode state: Record<providerId, boolean>
  const [replacingKey, setReplacingKey] = useState<Record<string, boolean>>({});

  // Key input values: Record<providerId, string>
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});

  // Show/hide key input visibility
  const [showKeySecret, setShowKeySecret] = useState<Record<string, boolean>>({});

  // Saving states
  const [savingKey, setSavingKey] = useState<Record<string, boolean>>({});
  const [saveSuccess, setSaveSuccess] = useState<Record<string, boolean>>({});
  const [saveError, setSaveError] = useState<Record<string, string | null>>({});

  // Model fetching states
  const [fetchingModels, setFetchingModels] = useState<Record<string, boolean>>({});
  const [fetchedModels, setFetchedModels] = useState<Record<string, Array<{ id: string; label: string }>>>({});
  const [fetchError, setFetchError] = useState<Record<string, string | null>>({});

  const selectedMeta = directProviders.find((p) => p.id === selectedProviderId) || directProviders[0];
  const selectedRoute = routeMap.get(selectedMeta?.id) || routeMap.get(`direct:${selectedMeta?.id}`);
  const isSelectedActive =
    activeRouteId === `direct:${selectedMeta?.id}` || activeRouteId === selectedMeta?.id;
  const isSelectedConfigured = Boolean(selectedRoute?.config?.is_configured);

  const handleSaveKey = async (provider: AiProviderMeta) => {
    const rawVal = keyInputs[provider.id]?.trim() || '';
    if (!rawVal) return;

    const dbKey = provider.credentialDbKey;
    if (!dbKey) return;

    setSavingKey((prev) => ({ ...prev, [provider.id]: true }));
    setSaveError((prev) => ({ ...prev, [provider.id]: null }));
    setSaveSuccess((prev) => ({ ...prev, [provider.id]: false }));

    try {
      const res = await fetch(`/api/py/system-config/${encodeURIComponent(dbKey)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ value: rawVal }),
      });

      if (!res.ok) {
        throw new Error(`Failed to save credential (HTTP ${res.status})`);
      }

      setSaveSuccess((prev) => ({ ...prev, [provider.id]: true }));
      setReplacingKey((prev) => ({ ...prev, [provider.id]: false }));
      setKeyInputs((prev) => ({ ...prev, [provider.id]: '' }));
      invalidateAiCaches();

      setTimeout(() => {
        setSaveSuccess((prev) => ({ ...prev, [provider.id]: false }));
      }, 3000);
    } catch (err) {
      setSaveError((prev) => ({
        ...prev,
        [provider.id]: err instanceof Error ? err.message : 'Save failed',
      }));
    } finally {
      setSavingKey((prev) => ({ ...prev, [provider.id]: false }));
    }
  };

  const handleFetchModels = async (provider: AiProviderMeta) => {
    const enteredKey = keyInputs[provider.id]?.trim() || '';
    setFetchingModels((prev) => ({ ...prev, [provider.id]: true }));
    setFetchError((prev) => ({ ...prev, [provider.id]: null }));

    try {
      const res = await fetch('/api/py/ai/provider-models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          provider: provider.id,
          api_key: enteredKey,
        }),
      });

      if (!res.ok) {
        throw new Error(`Failed to fetch models (HTTP ${res.status})`);
      }

      const data = await res.json();
      if (Array.isArray(data)) {
        setFetchedModels((prev) => ({
          ...prev,
          [provider.id]: data.map((m: { id: string; label?: string }) => ({
            id: m.id,
            label: m.label || m.id,
          })),
        }));
      }
    } catch (err) {
      setFetchError((prev) => ({
        ...prev,
        [provider.id]: err instanceof Error ? err.message : 'Failed to fetch models',
      }));
    } finally {
      setFetchingModels((prev) => ({ ...prev, [provider.id]: false }));
    }
  };

  const handleActivate = (providerId: string) => {
    activateRouteMutation.mutate(`direct:${providerId}`);
  };

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
              <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px]">
                {directProviders.length} Providers Supported
              </span>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed max-w-2xl font-sans">
              Direct providers communicate directly with provider APIs without proxy overhead. They remain 100%
              operational even if the local proxy supervisor or encrypted vault is offline.
            </p>
          </div>
        </div>

        <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 rounded bg-emerald-950/40 border border-emerald-800/60 text-emerald-300 font-mono text-xs">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          Native Direct Paths Ready
        </div>
      </div>

      {/* Main Two-Column Layout: Left Sidebar List, Right Detail Pane */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
        {/* Left Column: Provider List */}
        <div className="md:col-span-4 flex flex-col gap-1.5 max-h-[60vh] overflow-y-auto pr-1">
          {directProviders.map((p) => {
            const isSelected = p.id === selectedProviderId;
            const r = routeMap.get(p.id) || routeMap.get(`direct:${p.id}`);
            const isActive = activeRouteId === `direct:${p.id}` || activeRouteId === p.id;
            const isConfigured = Boolean(r?.config?.is_configured);

            return (
              <button
                key={p.id}
                type="button"
                onClick={() => setSelectedProviderId(p.id)}
                data-testid={`direct-provider-item-${p.id}`}
                className={`p-2.5 rounded-lg border text-left flex items-center justify-between transition-colors cursor-pointer ${
                  isSelected
                    ? 'bg-[#18181b] border-terminal-amber text-white shadow-sm'
                    : 'bg-[#0c0c0f] border-[#27272a] text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
                }`}
              >
                <div className="flex flex-col gap-0.5 truncate pr-2">
                  <span className="font-mono text-xs font-semibold text-white truncate">{p.label}</span>
                  <span className="text-[10px] font-mono text-zinc-500 truncate">{p.id}</span>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  {isActive ? (
                    <span
                      data-testid={`active-badge-${p.id}`}
                      className="px-1.5 py-0.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 font-mono text-[9px] font-bold"
                    >
                      ACTIVE
                    </span>
                  ) : isConfigured ? (
                    <span
                      data-testid={`configured-pill-${p.id}`}
                      className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[9px] flex items-center gap-0.5"
                    >
                      <Check className="w-2.5 h-2.5 text-emerald-400" />
                      Set
                    </span>
                  ) : null}
                </div>
              </button>
            );
          })}
        </div>

        {/* Right Column: Selected Provider Setup Panel */}
        <div className="md:col-span-8 bg-[#0c0c0f] border border-[#27272a] rounded-lg p-5 flex flex-col gap-4 text-xs font-sans">
          {selectedMeta && (
            <>
              {/* Header & Activation */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#27272a]">
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-mono font-bold text-sm text-white">{selectedMeta.label}</h3>
                    {isSelectedActive ? (
                      <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 font-mono text-[10px] font-bold flex items-center gap-1">
                        <Zap className="w-3 h-3" />
                        ACTIVE ROUTE
                      </span>
                    ) : isSelectedConfigured ? (
                      <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px] flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                        Configured
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded bg-zinc-900 text-zinc-500 font-mono text-[10px]">
                        Not Configured
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] font-mono text-zinc-400">
                    Route ID: <code className="text-zinc-300">direct:{selectedMeta.id}</code> · Slot:{' '}
                    <code className="text-zinc-300">{selectedMeta.credentialDbKey}</code>
                  </span>
                </div>

                {!isSelectedActive && (
                  <button
                    type="button"
                    onClick={() => handleActivate(selectedMeta.id)}
                    disabled={activateRouteMutation.isPending}
                    data-testid={`activate-direct-route-btn`}
                    className="px-3.5 py-1.5 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono text-xs font-bold transition-colors cursor-pointer shrink-0"
                  >
                    Set as Active Route
                  </button>
                )}
              </div>

              {/* Instructions Callout */}
              <AiProviderInstructions providerId={selectedMeta.id} />

              {/* Credential Setup / Configured Key Indicator / Replace Key Flow */}
              <div className="flex flex-col gap-2 pt-2 border-t border-[#27272a]">
                <span className="font-mono text-xs font-bold text-zinc-200 uppercase tracking-wider">
                  {selectedMeta.credentialLabel || 'API Credential'}
                </span>

                {/* State A: Key is already configured and user has not clicked Replace Key */}
                {isSelectedConfigured && !replacingKey[selectedMeta.id] ? (
                  <div
                    data-testid="configured-key-indicator"
                    className="p-3 rounded bg-[#09090b] border border-zinc-800 flex items-center justify-between gap-3"
                  >
                    <div className="flex items-center gap-2.5">
                      <Key className="w-4 h-4 text-emerald-400" />
                      <div className="flex flex-col">
                        <span className="font-mono text-xs text-white">●●●●●●●●●●●●●●●●</span>
                        <span className="text-[10px] text-zinc-400 font-mono">
                          API key configured and securely stored on the server.
                        </span>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => setReplacingKey((prev) => ({ ...prev, [selectedMeta.id]: true }))}
                      data-testid="replace-key-btn"
                      className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-mono text-xs border border-zinc-700 flex items-center gap-1.5 cursor-pointer"
                    >
                      <Edit2 className="w-3 h-3 text-terminal-amber" />
                      Replace Key
                    </button>
                  </div>
                ) : (
                  /* State B: Not configured or User clicked Replace Key */
                  <div className="flex flex-col gap-2 p-3 rounded bg-[#09090b] border border-zinc-800">
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1">
                        <input
                          type={showKeySecret[selectedMeta.id] ? 'text' : 'password'}
                          value={keyInputs[selectedMeta.id] || ''}
                          onChange={(e) =>
                            setKeyInputs((prev) => ({ ...prev, [selectedMeta.id]: e.target.value }))
                          }
                          placeholder={selectedMeta.placeholder || 'Enter API Key'}
                          autoComplete="off"
                          data-testid="direct-key-input"
                          className="w-full bg-[#121216] border border-zinc-700 px-3 py-1.5 pr-9 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            setShowKeySecret((prev) => ({
                              ...prev,
                              [selectedMeta.id]: !prev[selectedMeta.id],
                            }))
                          }
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white p-1 cursor-pointer"
                          title={showKeySecret[selectedMeta.id] ? 'Hide key' : 'Show key'}
                        >
                          {showKeySecret[selectedMeta.id] ? (
                            <EyeOff className="w-3.5 h-3.5" />
                          ) : (
                            <Eye className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleSaveKey(selectedMeta)}
                        disabled={!keyInputs[selectedMeta.id]?.trim() || savingKey[selectedMeta.id]}
                        data-testid="save-direct-key-btn"
                        className="px-3.5 py-1.5 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono text-xs font-bold disabled:opacity-40 transition-colors flex items-center gap-1.5 cursor-pointer shrink-0"
                      >
                        {savingKey[selectedMeta.id] ? (
                          <>
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Saving...
                          </>
                        ) : (
                          'Save Key'
                        )}
                      </button>

                      {isSelectedConfigured && (
                        <button
                          type="button"
                          onClick={() => {
                            setReplacingKey((prev) => ({ ...prev, [selectedMeta.id]: false }));
                            setKeyInputs((prev) => ({ ...prev, [selectedMeta.id]: '' }));
                          }}
                          className="px-2.5 py-1.5 rounded bg-zinc-800 text-zinc-400 hover:text-white font-mono text-xs cursor-pointer"
                        >
                          Cancel
                        </button>
                      )}
                    </div>

                    {saveError[selectedMeta.id] && (
                      <span className="text-rose-400 font-mono text-[11px] flex items-center gap-1">
                        <AlertCircle className="w-3.5 h-3.5" />
                        {saveError[selectedMeta.id]}
                      </span>
                    )}

                    {saveSuccess[selectedMeta.id] && (
                      <span className="text-emerald-400 font-mono text-[11px] flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        API Key saved successfully!
                      </span>
                    )}
                  </div>
                )}
              </div>

              {/* Model Fetch Controls */}
              <div className="flex flex-col gap-2 pt-2 border-t border-[#27272a]">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="font-mono text-xs font-bold text-zinc-200 uppercase tracking-wider block">
                      Provider Models
                    </span>
                    <span className="text-[10px] text-zinc-500 font-sans">
                      Test credentials by dynamically querying the upstream provider API for available models.
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleFetchModels(selectedMeta)}
                    disabled={fetchingModels[selectedMeta.id]}
                    data-testid="fetch-direct-models-btn"
                    className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-xs border border-zinc-700 flex items-center gap-1.5 cursor-pointer shrink-0 disabled:opacity-40"
                  >
                    {fetchingModels[selectedMeta.id] ? (
                      <>
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Querying...
                      </>
                    ) : (
                      <>
                        <RefreshCw className="w-3 h-3 text-terminal-amber" />
                        Fetch Models
                      </>
                    )}
                  </button>
                </div>

                {fetchError[selectedMeta.id] && (
                  <div className="p-2 rounded bg-rose-950/40 border border-rose-800 text-rose-300 font-mono text-xs">
                    {fetchError[selectedMeta.id]}
                  </div>
                )}

                {/* Display Fetched Models or Default Catalog */}
                {fetchedModels[selectedMeta.id] && fetchedModels[selectedMeta.id].length > 0 ? (
                  <div className="flex flex-col gap-1.5 p-2.5 rounded bg-[#09090b] border border-zinc-800">
                    <span className="font-mono text-[10px] text-zinc-400 uppercase">
                      Live Catalog ({fetchedModels[selectedMeta.id].length} models fetched):
                    </span>
                    <div className="flex flex-wrap gap-1 max-h-36 overflow-y-auto">
                      {fetchedModels[selectedMeta.id].map((m) => (
                        <span
                          key={m.id}
                          className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px] border border-zinc-700"
                        >
                          {m.label || m.id}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : selectedRoute?.models && selectedRoute.models.length > 0 ? (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-mono text-zinc-500">Default Catalog:</span>
                    {selectedRoute.models.map((m) => (
                      <span
                        key={m}
                        className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px] border border-zinc-700"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

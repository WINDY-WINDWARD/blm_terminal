'use client';

import React, { useState } from 'react';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Edit2,
  Globe,
  Key,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  Zap,
} from 'lucide-react';
import {
  useActivateRouteMutation,
  useAddEndpointKeyMutation,
  useDeleteEndpointKeyMutation,
  useDeleteEndpointMutation,
  usePatchEndpointKeyMutation,
  useRefreshEndpointModelsMutation,
  useTestAccountMutation,
  useTestEndpointMutation,
} from '@/hooks/useAiRoutes';
import { EndpointEditorModal } from './EndpointEditorModal';
import type { CredentialSummary, RouteSummary } from '@/types/aiRoutes';

interface CustomEndpointsTabProps {
  routes: RouteSummary[];
  activeRouteId: string;
}

export function CustomEndpointsTab({ routes, activeRouteId }: CustomEndpointsTabProps) {
  const endpointRoutes = routes.filter((r) => r.kind === 'endpoint');

  const activateMutation = useActivateRouteMutation();
  const deleteEndpointMutation = useDeleteEndpointMutation();
  const refreshModelsMutation = useRefreshEndpointModelsMutation();
  const testEndpointMutation = useTestEndpointMutation();
  const addKeyMutation = useAddEndpointKeyMutation();
  const patchKeyMutation = usePatchEndpointKeyMutation();
  const deleteKeyMutation = useDeleteEndpointKeyMutation();
  const testAccountMutation = useTestAccountMutation();

  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editingRoute, setEditingRoute] = useState<RouteSummary | null>(null);

  // Endpoint test results by routeId
  const [endpointTestResults, setEndpointTestResults] = useState<
    Record<string, { status: string; latency_ms?: number; status_code?: number; error?: string }>
  >({});

  // Key test results by keyId
  const [keyTestResults, setKeyTestResults] = useState<
    Record<string, { status: string; latency_ms?: number; proxy_status?: string; error?: string }>
  >({});

  // Inline add-key state per routeId
  const [addingKeyForRoute, setAddingKeyForRoute] = useState<string | null>(null);
  const [newKeyInput, setNewKeyInput] = useState('');
  const [newKeyPriority, setNewKeyPriority] = useState(1);
  const [newKeyWeight, setNewKeyWeight] = useState(1);

  // Deletion confirm state
  const [deletingRouteId, setDeletingRouteId] = useState<string | null>(null);
  const [tabError, setTabError] = useState<string | null>(null);

  const handleOpenCreate = () => {
    setEditingRoute(null);
    setIsEditorOpen(true);
  };

  const handleOpenEdit = (route: RouteSummary) => {
    setEditingRoute(route);
    setIsEditorOpen(true);
  };

  const handleDeleteRoute = async (routeId: string) => {
    setTabError(null);
    try {
      await deleteEndpointMutation.mutateAsync(routeId);
      setDeletingRouteId(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Delete endpoint failed';
      setTabError(msg);
      console.error('Delete endpoint failed', err);
    }
  };

  const handleTestEndpoint = async (routeId: string) => {
    try {
      const res = await testEndpointMutation.mutateAsync(routeId);
      setEndpointTestResults((prev) => ({
        ...prev,
        [routeId]: {
          status: res.status,
          latency_ms: res.latency_ms,
          status_code: res.status_code,
          error: res.error,
        },
      }));
    } catch (err) {
      setEndpointTestResults((prev) => ({
        ...prev,
        [routeId]: {
          status: 'error',
          error: err instanceof Error ? err.message : 'Endpoint test failed',
        },
      }));
    }
  };

  const handleTestKey = async (keyId: string) => {
    try {
      const res = await testAccountMutation.mutateAsync(keyId);
      setKeyTestResults((prev) => ({
        ...prev,
        [keyId]: {
          status: res.status,
          latency_ms: res.latency_ms,
          proxy_status: res.proxy_status,
          error: res.error,
        },
      }));
    } catch (err) {
      setKeyTestResults((prev) => ({
        ...prev,
        [keyId]: {
          status: 'error',
          error: err instanceof Error ? err.message : 'Key test failed',
        },
      }));
    }
  };

  const handleSaveNewKey = async (endpointId: string) => {
    if (!newKeyInput.trim()) return;
    setTabError(null);
    try {
      await addKeyMutation.mutateAsync({
        endpointId,
        key: {
          api_key: newKeyInput.trim(),
          priority: Number(newKeyPriority) || 1,
          weight: Number(newKeyWeight) || 1,
        },
      });
      setAddingKeyForRoute(null);
      setNewKeyInput('');
      setNewKeyPriority(1);
      setNewKeyWeight(1);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Add key failed';
      setTabError(msg);
      console.error('Add key failed', err);
    }
  };

  return (
    <div data-testid="custom-endpoints-tab" className="flex flex-col gap-4 font-sans">
      {tabError && (
        <div
          data-testid="custom-endpoints-error-banner"
          className="p-3 bg-rose-950/40 border border-rose-800 rounded-lg flex items-center justify-between text-rose-300 font-mono text-xs"
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
            <span>{tabError}</span>
          </div>
          <button
            type="button"
            onClick={() => setTabError(null)}
            className="text-zinc-400 hover:text-white p-1 cursor-pointer"
            title="Dismiss error"
          >
            ✕
          </button>
        </div>
      )}
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
              <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono text-[10px]">
                {endpointRoutes.length} Configured
              </span>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed max-w-2xl font-sans">
              Connect private enterprise gateways, vLLM, Ollama, OpenRouter proxies, or LiteLLM endpoints with weighted
              keys, model catalogs, and live failover routing.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={handleOpenCreate}
          data-testid="add-endpoint-btn"
          className="shrink-0 px-3.5 py-1.5 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono text-xs font-bold border border-terminal-amber transition-colors flex items-center gap-1.5 cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          + NEW ENDPOINT
        </button>
      </div>

      {/* Existing Endpoint Routes or Empty State */}
      <div className="grid grid-cols-1 gap-4">
        {endpointRoutes.length > 0 ? (
          endpointRoutes.map((route) => {
            const isActive = activeRouteId === route.id;
            const testResult = endpointTestResults[route.id];
            const isTesting = testEndpointMutation.isPending && testEndpointMutation.variables === route.id;
            const isRefreshing =
              refreshModelsMutation.isPending && refreshModelsMutation.variables === route.id;
            const warnings = (route.config.warning_flags as string[]) || [];
            const headerNames = (route.config.header_names as string[]) || [];

            return (
              <div
                key={route.id}
                data-testid={`endpoint-card-${route.id}`}
                className={`bg-[#0c0c0f] border rounded-lg p-4 flex flex-col gap-3 transition-colors ${
                  isActive ? 'border-terminal-amber/60 bg-amber-950/5' : 'border-[#27272a]'
                }`}
              >
                {/* Header Row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-[#27272a]">
                  <div className="flex items-center gap-2.5">
                    <div className="p-1.5 rounded bg-zinc-800 text-terminal-amber">
                      <Server className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-sm text-white">{route.display_label}</span>
                        {isActive ? (
                          <span
                            data-testid={`active-badge-${route.id}`}
                            className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-400 font-mono text-[10px] font-bold flex items-center gap-1"
                          >
                            <Zap className="w-3 h-3" />
                            ACTIVE
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[10px]">
                            {route.keys.length > 0 ? 'Configured' : 'No Keys'}
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] font-mono text-zinc-400 truncate block mt-0.5">
                        {route.config.base_url || route.id}
                      </span>
                    </div>
                  </div>

                  {/* Actions Bar */}
                  <div className="flex items-center gap-1.5 shrink-0 self-start sm:self-center">
                    {!isActive && (
                      <button
                        type="button"
                        onClick={() => activateMutation.mutate(route.id)}
                        disabled={activateMutation.isPending}
                        data-testid={`activate-endpoint-${route.id}`}
                        className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-terminal-amber font-mono text-xs font-bold border border-terminal-amber/30 transition-colors cursor-pointer"
                      >
                        Activate
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => handleTestEndpoint(route.id)}
                      disabled={isTesting}
                      data-testid={`test-endpoint-${route.id}`}
                      className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-mono text-xs border border-zinc-700 flex items-center gap-1 cursor-pointer"
                      title="Test endpoint HTTP connectivity"
                    >
                      {isTesting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
                      Test
                    </button>
                    <button
                      type="button"
                      onClick={() => handleOpenEdit(route)}
                      data-testid={`edit-endpoint-${route.id}`}
                      className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
                      title="Edit endpoint"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setDeletingRouteId(route.id)}
                      data-testid={`delete-endpoint-${route.id}`}
                      className="p-1 rounded text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 transition-colors cursor-pointer"
                      title="Delete endpoint"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Confirm Delete Banner */}
                {deletingRouteId === route.id && (
                  <div className="p-2.5 rounded bg-rose-950/40 border border-rose-800 text-rose-200 text-xs font-mono flex items-center justify-between gap-2">
                    <span>Delete custom endpoint "{route.display_label}" and remove its stored keys?</span>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setDeletingRouteId(null)}
                        className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700 cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteRoute(route.id)}
                        disabled={deleteEndpointMutation.isPending}
                        data-testid={`confirm-delete-btn-${route.id}`}
                        className="px-2.5 py-0.5 rounded bg-rose-700 text-white font-bold hover:bg-rose-600 cursor-pointer"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}

                {/* Test Result Feedback */}
                {testResult && (
                  <div
                    data-testid={`test-result-${route.id}`}
                    className={`p-2 rounded text-xs font-mono flex items-center gap-2 ${
                      testResult.status === 'ok'
                        ? 'bg-emerald-950/40 border border-emerald-800 text-emerald-300'
                        : 'bg-rose-950/40 border border-rose-800 text-rose-300'
                    }`}
                  >
                    {testResult.status === 'ok' ? (
                      <>
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        <span>Connected successfully ({testResult.latency_ms}ms)</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                        <span>{testResult.error || 'Connection failed'}</span>
                      </>
                    )}
                  </div>
                )}

                {/* Warnings / Metadata row */}
                {(warnings.length > 0 || headerNames.length > 0) && (
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-mono">
                    {warnings.map((w, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded bg-amber-950/30 border border-amber-800/50 text-amber-300 flex items-center gap-1"
                      >
                        <AlertTriangle className="w-3 h-3 text-amber-400" />
                        {w}
                      </span>
                    ))}
                    {headerNames.length > 0 && (
                      <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">
                        Secret Headers: {headerNames.join(', ')}
                      </span>
                    )}
                  </div>
                )}

                {/* Models Row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-2 rounded bg-[#09090b] border border-zinc-800/80">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[10px] font-mono font-bold uppercase text-zinc-400">Models:</span>
                    {route.models && route.models.length > 0 ? (
                      route.models.map((m) => (
                        <span
                          key={m}
                          className="px-2 py-0.5 rounded bg-zinc-800/80 text-zinc-200 font-mono text-[11px] border border-zinc-700"
                        >
                          {m}
                        </span>
                      ))
                    ) : (
                      <span className="text-zinc-500 font-mono text-xs">No models configured</span>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => refreshModelsMutation.mutate(route.id)}
                    disabled={isRefreshing}
                    data-testid={`refresh-models-${route.id}`}
                    className="self-start sm:self-center px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-[10px] border border-zinc-700 flex items-center gap-1 cursor-pointer shrink-0"
                    title="Refresh model catalog live from endpoint"
                  >
                    {isRefreshing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    Refresh Models
                  </button>
                </div>

                {/* Keys Section */}
                <div className="flex flex-col gap-2 pt-2 border-t border-[#27272a]/60">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Key className="w-3.5 h-3.5 text-terminal-amber" />
                      <span className="font-mono text-xs font-bold text-zinc-300 uppercase tracking-wider">
                        Weighted Keys ({route.keys.length})
                      </span>
                    </div>

                    <button
                      type="button"
                      onClick={() => setAddingKeyForRoute(addingKeyForRoute === route.id ? null : route.id)}
                      data-testid={`add-key-toggle-${route.id}`}
                      className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-[11px] border border-zinc-700 flex items-center gap-1 cursor-pointer"
                    >
                      <Plus className="w-3 h-3" />
                      {addingKeyForRoute === route.id ? 'Cancel' : 'Add Key'}
                    </button>
                  </div>

                  {/* Inline Add Key Form */}
                  {addingKeyForRoute === route.id && (
                    <div
                      data-testid={`add-key-form-${route.id}`}
                      className="p-3 rounded bg-[#09090b] border border-terminal-amber/30 flex flex-col gap-2.5 animate-in fade-in"
                    >
                      <span className="text-[11px] font-mono text-terminal-amber font-bold uppercase">
                        Add New API Key
                      </span>
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                        <input
                          type="password"
                          value={newKeyInput}
                          onChange={(e) => setNewKeyInput(e.target.value)}
                          placeholder="Enter API key"
                          autoComplete="off"
                          className="flex-1 bg-[#121216] border border-zinc-700 px-2.5 py-1 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
                        />
                        <div className="flex items-center gap-2">
                          <label className="flex items-center gap-1 font-mono text-[11px] text-zinc-400">
                            <span>Priority:</span>
                            <input
                              type="number"
                              step="1"
                              min="1"
                              max="100"
                              value={newKeyPriority}
                              aria-label="New endpoint key priority"
                              aria-describedby="new-endpoint-key-routing-help"
                              title="Lower numbers are tried first."
                              onChange={(e) => {
                                const value = e.currentTarget.valueAsNumber;
                                if (Number.isFinite(value)) setNewKeyPriority(Math.max(1, Math.min(100, Math.floor(value))));
                              }}
                              className="w-14 bg-[#121216] border border-zinc-700 px-1.5 py-1 rounded text-white"
                            />
                          </label>
                          <label className="flex items-center gap-1 font-mono text-[11px] text-zinc-400">
                            <span>Weight:</span>
                            <input
                              type="number"
                              step="1"
                              min="1"
                              max="100"
                              value={newKeyWeight}
                              aria-label="New endpoint key weight"
                              aria-describedby="new-endpoint-key-routing-help"
                              title="Share of requests among keys with equal priority."
                              onChange={(e) => {
                                const value = e.currentTarget.valueAsNumber;
                                if (Number.isFinite(value)) setNewKeyWeight(Math.max(1, Math.min(100, Math.floor(value))));
                              }}
                              className="w-14 bg-[#121216] border border-zinc-700 px-1.5 py-1 rounded text-white"
                            />
                          </label>
                        </div>
                      </div>
                      <p id="new-endpoint-key-routing-help" className="text-[10px] leading-relaxed text-zinc-500">
                        <span>Priority - lower numbers are tried first.</span>{' '}
                        <span>Weight - share of requests among keys with equal priority.</span>
                      </p>
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setAddingKeyForRoute(null)}
                          className="px-2.5 py-1 rounded bg-zinc-800 text-zinc-400 hover:text-white font-mono text-xs cursor-pointer"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={() => handleSaveNewKey(route.id)}
                          disabled={!newKeyInput.trim() || addKeyMutation.isPending}
                          data-testid="save-new-key-btn"
                          className="px-3 py-1 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono text-xs font-bold disabled:opacity-40 cursor-pointer"
                        >
                          Save Key
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Keys List */}
                  {route.keys.length > 0 ? (
                    <div className="flex flex-col gap-1.5">
                      {route.keys.map((k) => {
                        const keyTest = keyTestResults[k.id];
                        const isTestingKey =
                          testAccountMutation.isPending && testAccountMutation.variables === k.id;

                        return (
                          <div
                            key={k.id}
                            data-testid={`key-row-${k.id}`}
                            className="p-2 rounded bg-[#09090b] border border-zinc-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                          >
                            <div className="flex items-center gap-2.5">
                              <span className="font-mono text-xs text-white font-semibold">
                                {k.masked_identity || '****'}
                              </span>
                              <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[10px]">
                                P:{k.priority}
                              </span>
                              <span className="px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 font-mono text-[10px]">
                                W:{k.weight}
                              </span>
                              <span
                                className={`px-1.5 py-0.5 rounded font-mono text-[10px] uppercase ${
                                  k.enabled
                                    ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-800/50'
                                    : 'bg-zinc-900 text-zinc-500 border border-zinc-800'
                                }`}
                              >
                                {k.enabled ? 'Enabled' : 'Disabled'}
                              </span>
                            </div>

                            <div className="flex items-center gap-2">
                              {keyTest && (
                                <span
                                  data-testid={`key-test-result-${k.id}`}
                                  className={`text-[10px] font-mono ${
                                    keyTest.status === 'ok' ? 'text-emerald-400' : 'text-rose-400'
                                  }`}
                                >
                                  {keyTest.status === 'ok' ? `✓ ${keyTest.latency_ms}ms` : `✕ Error`}
                                </span>
                              )}

                              {/* Toggle Enable/Disable */}
                              <button
                                type="button"
                                onClick={() =>
                                  patchKeyMutation.mutate({
                                    endpointId: route.id,
                                    keyId: k.id,
                                    patch: { enabled: !k.enabled },
                                  })
                                }
                                disabled={patchKeyMutation.isPending}
                                data-testid={`toggle-key-${k.id}`}
                                className={`px-2 py-0.5 rounded font-mono text-[10px] border cursor-pointer ${
                                  k.enabled
                                    ? 'bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border-zinc-700'
                                    : 'bg-emerald-950/30 hover:bg-emerald-900/50 text-emerald-400 border-emerald-800/50'
                                }`}
                              >
                                {k.enabled ? 'Disable' : 'Enable'}
                              </button>

                              {/* Test Key */}
                              <button
                                type="button"
                                onClick={() => handleTestKey(k.id)}
                                disabled={isTestingKey}
                                data-testid={`test-key-${k.id}`}
                                className="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-[10px] border border-zinc-700 cursor-pointer flex items-center gap-1"
                              >
                                {isTestingKey ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : null}
                                Test
                              </button>

                              {/* Delete Key */}
                              <button
                                type="button"
                                onClick={() =>
                                  deleteKeyMutation.mutate({ endpointId: route.id, keyId: k.id })
                                }
                                disabled={deleteKeyMutation.isPending}
                                data-testid={`delete-key-${k.id}`}
                                className="p-1 rounded text-zinc-400 hover:text-rose-400 transition-colors cursor-pointer"
                                title="Remove key"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <span className="text-[11px] font-mono text-zinc-500 py-1">
                      No keys configured. Upstream calls will proceed with optional secret headers only.
                    </span>
                  )}
                </div>
              </div>
            );
          })
        ) : (
          <div className="p-8 rounded-lg border border-dashed border-zinc-800 bg-[#0c0c0f]/60 text-center flex flex-col items-center justify-center gap-3">
            <Server className="w-9 h-9 text-zinc-600 mb-1" />
            <span className="text-sm font-mono text-zinc-300 font-bold uppercase tracking-wider">
              No Custom Endpoints Registered
            </span>
            <p className="text-xs text-zinc-500 max-w-md font-sans leading-relaxed">
              Register private enterprise gateways, local LLM servers (Ollama, vLLM, LMStudio), or custom OpenAI-compatible proxies.
            </p>
            <button
              type="button"
              onClick={handleOpenCreate}
              data-testid="empty-add-endpoint-btn"
              className="mt-2 px-4 py-1.5 rounded bg-terminal-amber hover:bg-amber-400 text-black font-mono text-xs font-bold transition-colors cursor-pointer"
            >
              + Create First Endpoint
            </button>
          </div>
        )}
      </div>

      {/* Endpoint Editor Modal */}
      <EndpointEditorModal
        isOpen={isEditorOpen}
        onClose={() => setIsEditorOpen(false)}
        route={editingRoute}
      />
    </div>
  );
}

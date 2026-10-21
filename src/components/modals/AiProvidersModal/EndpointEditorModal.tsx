'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Globe,
  Key,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from 'lucide-react';
import {
  useCreateEndpointMutation,
  usePreviewEndpointModelsMutation,
  useUpdateEndpointMutation,
} from '@/hooks/useAiRoutes';
import { useModalFocusTrap } from '@/hooks/useModalFocusTrap';
import type { RouteSummary } from '@/types/aiRoutes';

interface EndpointEditorModalProps {
  isOpen: boolean;
  onClose: () => void;
  route?: RouteSummary | null;
}

interface HeaderRow {
  id: string;
  name: string;
  value: string;
}

interface KeyRow {
  id: string;
  apiKey: string;
  label: string;
  priority: number;
  weight: number;
}

function validateUrlLocal(url: string): { isValid: boolean; error?: string; warnings: string[] } {
  if (!url.trim()) return { isValid: false, warnings: [] };
  const clean = url.trim();
  if (clean.includes('\r') || clean.includes('\n') || clean.includes('\0')) {
    return { isValid: false, error: 'URL contains illegal control characters', warnings: [] };
  }
  let parsed: URL;
  try {
    parsed = new URL(clean);
  } catch {
    return {
      isValid: false,
      error: 'Invalid URL format (must be full URL, e.g. http://localhost:8000/v1)',
      warnings: [],
    };
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return {
      isValid: false,
      error: `Invalid scheme '${parsed.protocol}'. Only http: and https: are allowed.`,
      warnings: [],
    };
  }
  if (parsed.username || parsed.password) {
    return { isValid: false, error: 'Credentials in URL (user:pass@) are not permitted.', warnings: [] };
  }
  const warnings: string[] = [];
  if (parsed.protocol === 'http:') {
    warnings.push('Unencrypted HTTP connection');
  }
  const host = parsed.hostname.toLowerCase();
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1') {
    warnings.push('Local loopback target (localhost)');
  } else if (host.endsWith('.local') || host.endsWith('.lan') || host.endsWith('.internal')) {
    warnings.push('Private network target');
  }
  return { isValid: true, warnings };
}

export function EndpointEditorModal({ isOpen, onClose, route }: EndpointEditorModalProps) {
  const isEditing = Boolean(route);
  const createMutation = useCreateEndpointMutation();
  const updateMutation = useUpdateEndpointMutation();
  const previewMutation = usePreviewEndpointModelsMutation();

  const [displayLabel, setDisplayLabel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [headers, setHeaders] = useState<HeaderRow[]>([]);
  const [headersTouched, setHeadersTouched] = useState(false);
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [models, setModels] = useState<string[]>(['default']);
  const [manualModel, setManualModel] = useState('');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [previewNotice, setPreviewNotice] = useState<string | null>(null);
  const [discoveredModels, setDiscoveredModels] = useState<string[]>([]);

  const modalRef = useRef<HTMLDivElement>(null);
  const initialInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      if (route) {
        setDisplayLabel(route.display_label || '');
        setBaseUrl(route.config.base_url || '');
        setModels(route.models && route.models.length > 0 ? route.models : ['default']);
        setHeaders([]);
        setHeadersTouched(false);
        setKeys([]);
      } else {
        setDisplayLabel('');
        setBaseUrl('');
        setHeaders([]);
        setKeys([]);
        setModels(['default']);
      }
      setManualModel('');
      setErrorMsg(null);
      setPreviewNotice(null);
      setDiscoveredModels([]);
    }
  }, [isOpen, route]);

  const handleClose = useCallback(() => {
    if (createMutation.isPending || updateMutation.isPending) return;
    onClose();
  }, [createMutation.isPending, updateMutation.isPending, onClose]);

  useModalFocusTrap({
    id: 'endpoint-editor-modal',
    isOpen,
    onClose: handleClose,
    containerRef: modalRef,
    initialFocusRef: initialInputRef,
  });

  if (!isOpen) return null;

  const urlCheck = validateUrlLocal(baseUrl);

  // Headers helpers
  const addHeaderRow = () => {
    setHeadersTouched(true);
    setHeaders((prev) => [...prev, { id: Math.random().toString(36).substring(7), name: '', value: '' }]);
  };

  const removeHeaderRow = (id: string) => {
    setHeadersTouched(true);
    setHeaders((prev) => prev.filter((h) => h.id !== id));
  };

  const updateHeaderRow = (id: string, field: 'name' | 'value', val: string) => {
    setHeadersTouched(true);
    setHeaders((prev) => prev.map((h) => (h.id === id ? { ...h, [field]: val } : h)));
  };

  // Keys helpers (for create mode)
  const addKeyRow = () => {
    setKeys((prev) => [
      ...prev,
      { id: Math.random().toString(36).substring(7), apiKey: '', label: '', priority: 1, weight: 1 },
    ]);
  };

  const removeKeyRow = (id: string) => {
    setKeys((prev) => prev.filter((k) => k.id !== id));
  };

  const updateKeyRow = (id: string, field: keyof KeyRow, val: unknown) => {
    setKeys((prev) => prev.map((k) => (k.id === id ? { ...k, [field]: val } : k)));
  };

  // Models helpers
  const addModel = (name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (!models.includes(trimmed)) {
      setModels((prev) => [...prev.filter((m) => m !== 'default'), trimmed]);
    }
  };

  const removeModel = (name: string) => {
    setModels((prev) => {
      const next = prev.filter((m) => m !== name);
      return next.length > 0 ? next : ['default'];
    });
  };

  const handleManualAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualModel.trim()) return;
    addModel(manualModel.trim());
    setManualModel('');
  };

  const handleFetchModels = async () => {
    if (!urlCheck.isValid) {
      setErrorMsg('Please enter a valid base URL first.');
      return;
    }
    setErrorMsg(null);
    setPreviewNotice(null);

    const headersDict: Record<string, string> = {};
    for (const h of headers) {
      if (h.name.trim()) headersDict[h.name.trim()] = h.value;
    }
    const firstKey = keys.find((k) => k.apiKey.trim())?.apiKey;

    try {
      const res = await previewMutation.mutateAsync({
        base_url: baseUrl.trim(),
        headers: Object.keys(headersDict).length > 0 ? headersDict : undefined,
        api_key: firstKey || undefined,
      });

      if (res.notice) {
        setPreviewNotice(res.notice);
      }
      if (res.models && res.models.length > 0) {
        setDiscoveredModels(res.models);
        // Automatically add non-default models
        const validFetched = res.models.filter((m) => m !== 'default');
        if (validFetched.length > 0) {
          setModels((prev) => {
            const set = new Set([...prev.filter((m) => m !== 'default'), ...validFetched]);
            return Array.from(set);
          });
        }
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to preview models');
    }
  };

  const handleSave = async () => {
    if (!displayLabel.trim()) {
      setErrorMsg('Endpoint label is required.');
      return;
    }
    if (!urlCheck.isValid) {
      setErrorMsg(urlCheck.error || 'A valid Base URL is required.');
      return;
    }

    const headersDict: Record<string, string> = {};
    for (const h of headers) {
      if (h.name.trim()) headersDict[h.name.trim()] = h.value;
    }

    setErrorMsg(null);
    try {
      if (isEditing && route) {
        await updateMutation.mutateAsync({
          endpointId: route.id,
          patch: {
            display_label: displayLabel.trim(),
            base_url: baseUrl.trim(),
            // Only replace headers when the user actually edited them; otherwise
            // an unrelated edit would silently wipe stored secret headers.
            ...(headersTouched ? { headers: headersDict } : {}),
            models: models.length > 0 ? models : ['default'],
          },
        });
      } else {
        const initialKeys = keys
          .filter((k) => k.apiKey.trim())
          .map((k) => ({
            api_key: k.apiKey.trim(),
            label: k.label.trim() || undefined,
            priority: Number(k.priority) || 1,
            weight: Number(k.weight) || 1,
          }));

        await createMutation.mutateAsync({
          display_label: displayLabel.trim(),
          base_url: baseUrl.trim(),
          headers: Object.keys(headersDict).length > 0 ? headersDict : undefined,
          models: models.length > 0 ? models : ['default'],
          keys: initialKeys.length > 0 ? initialKeys : undefined,
        });
      }
      onClose();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Save failed');
    }
  };

  const isSaving = createMutation.isPending || updateMutation.isPending;

  return (
    <div
      ref={modalRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="endpoint-editor-title"
      className="fixed inset-0 z-60 flex items-center justify-center p-4 bg-black/85 backdrop-blur-sm animate-in fade-in duration-150 select-none outline-none font-sans"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSaving) handleClose();
      }}
    >
      <div className="relative w-full max-w-2xl bg-[#0c0c0f] border border-[#27272a] rounded-lg shadow-2xl flex flex-col max-h-[90vh] overflow-hidden text-zinc-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#27272a] bg-[#121216] shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
              <Globe className="w-4 h-4" />
            </div>
            <div>
              <h3 id="endpoint-editor-title" className="text-sm font-mono font-bold tracking-wider text-white uppercase">
                {isEditing ? 'EDIT CUSTOM ENDPOINT' : 'NEW CUSTOM ENDPOINT'}
              </h3>
              <p className="text-[11px] text-zinc-400 font-sans">
                Configure OpenAI-compatible upstream endpoint URL, secret headers, models, and weighted keys.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            disabled={isSaving}
            aria-label="Close endpoint editor"
            className="text-zinc-400 hover:text-white p-1 rounded hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4 text-xs font-sans">
          {errorMsg && (
            <div
              data-testid="endpoint-error-banner"
              className="p-3 rounded bg-rose-950/60 border border-rose-800 text-rose-200 font-mono text-xs flex items-start gap-2"
            >
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Display Label */}
          <div className="flex flex-col gap-1">
            <label htmlFor="endpoint-label-input" className="font-mono text-zinc-300 font-semibold uppercase tracking-wider text-[11px]">
              Display Label *
            </label>
            <input
              ref={initialInputRef}
              id="endpoint-label-input"
              data-testid="endpoint-label-input"
              type="text"
              value={displayLabel}
              onChange={(e) => setDisplayLabel(e.target.value)}
              placeholder="e.g. Local Ollama Gateway, vLLM Node, LiteLLM Enterprise"
              disabled={isSaving}
              className="bg-[#09090b] border border-zinc-700 px-3 py-1.5 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
            />
          </div>

          {/* Base URL */}
          <div className="flex flex-col gap-1">
            <label htmlFor="endpoint-url-input" className="font-mono text-zinc-300 font-semibold uppercase tracking-wider text-[11px]">
              Base URL *
            </label>
            <input
              id="endpoint-url-input"
              data-testid="endpoint-url-input"
              type="text"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://localhost:11434/v1 or https://ai-gateway.internal.net/v1"
              disabled={isSaving}
              className="bg-[#09090b] border border-zinc-700 px-3 py-1.5 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
            />
            {/* Live URL Warnings and Errors */}
            {baseUrl && !urlCheck.isValid && (
              <span data-testid="url-validation-error" className="text-rose-400 text-[11px] font-mono flex items-center gap-1 mt-0.5">
                <AlertCircle className="w-3.5 h-3.5" />
                {urlCheck.error}
              </span>
            )}
            {baseUrl && urlCheck.isValid && urlCheck.warnings.length > 0 && (
              <div data-testid="url-validation-warnings" className="flex flex-wrap gap-1.5 mt-1">
                {urlCheck.warnings.map((warn, i) => (
                  <span
                    key={i}
                    className="px-2 py-0.5 rounded bg-amber-950/40 border border-amber-800/60 text-amber-300 font-mono text-[10px] flex items-center gap-1"
                  >
                    <AlertTriangle className="w-3 h-3 text-amber-400" />
                    {warn}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Optional Secret Headers */}
          <div className="flex flex-col gap-2 pt-2 border-t border-[#27272a]">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-mono text-zinc-300 font-semibold uppercase tracking-wider text-[11px] block">
                  Optional Secret Headers
                </span>
                <span className="text-[10px] text-zinc-500 font-sans">
                  Stored securely in the OS keyring vault only; never rendered in HTML or logs.
                </span>
              </div>
              <button
                type="button"
                onClick={addHeaderRow}
                className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-[11px] border border-zinc-700 flex items-center gap-1 cursor-pointer"
              >
                <Plus className="w-3 h-3" />
                Add Header
              </button>
            </div>

            {headers.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {headers.map((h) => (
                  <div key={h.id} className="flex items-center gap-2">
                    <input
                      type="text"
                      value={h.name}
                      onChange={(e) => updateHeaderRow(h.id, 'name', e.target.value)}
                      placeholder="Header Name (e.g. X-Api-Key)"
                      className="flex-1 bg-[#09090b] border border-zinc-700 px-2.5 py-1 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
                    />
                    <input
                      type="password"
                      value={h.value}
                      onChange={(e) => updateHeaderRow(h.id, 'value', e.target.value)}
                      placeholder="Header Value"
                      autoComplete="off"
                      className="flex-1 bg-[#09090b] border border-zinc-700 px-2.5 py-1 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
                    />
                    <button
                      type="button"
                      onClick={() => removeHeaderRow(h.id)}
                      className="p-1 text-zinc-400 hover:text-rose-400 transition-colors cursor-pointer"
                      title="Remove header"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Initial Keys Section (in create mode) */}
          {!isEditing && (
            <div className="flex flex-col gap-2 pt-2 border-t border-[#27272a]">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-mono text-zinc-300 font-semibold uppercase tracking-wider text-[11px] block">
                    Endpoint API Keys
                  </span>
                  <span className="text-[10px] text-zinc-500 font-sans">
                    Weighted keys for load balancing & failover. Keys are stored in the keyring vault.
                  </span>
                </div>
                <button
                  type="button"
                  onClick={addKeyRow}
                  className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-[11px] border border-zinc-700 flex items-center gap-1 cursor-pointer"
                >
                  <Plus className="w-3 h-3" />
                  Add Key
                </button>
              </div>

              {keys.length > 0 && (
                <div className="flex flex-col gap-2">
                  {keys.map((k) => (
                    <div key={k.id} className="p-2.5 rounded bg-[#09090b] border border-zinc-800 flex flex-col gap-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="password"
                          value={k.apiKey}
                          onChange={(e) => updateKeyRow(k.id, 'apiKey', e.target.value)}
                          placeholder="API Key (e.g. sk-...)"
                          autoComplete="off"
                          className="flex-1 bg-[#121216] border border-zinc-700 px-2.5 py-1 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
                        />
                        <button
                          type="button"
                          onClick={() => removeKeyRow(k.id)}
                          className="p-1 text-zinc-400 hover:text-rose-400 transition-colors cursor-pointer"
                          title="Remove key"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                      <div className="flex items-center gap-4 text-[11px] font-mono text-zinc-400">
                        <label className="flex items-center gap-1.5">
                          <span>Priority:</span>
                          <input
                            type="number"
                            min="1"
                            max="100"
                            value={k.priority}
                            onChange={(e) => updateKeyRow(k.id, 'priority', parseInt(e.target.value) || 1)}
                            className="w-16 bg-[#121216] border border-zinc-700 px-2 py-0.5 rounded text-white"
                          />
                        </label>
                        <label className="flex items-center gap-1.5">
                          <span>Weight:</span>
                          <input
                            type="number"
                            min="1"
                            max="100"
                            value={k.weight}
                            onChange={(e) => updateKeyRow(k.id, 'weight', parseInt(e.target.value) || 1)}
                            className="w-16 bg-[#121216] border border-zinc-700 px-2 py-0.5 rounded text-white"
                          />
                        </label>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Models Catalog & Manual Fallback */}
          <div className="flex flex-col gap-2 pt-2 border-t border-[#27272a]">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-mono text-zinc-300 font-semibold uppercase tracking-wider text-[11px] block">
                  Model Catalog & Manual Fallback
                </span>
                <span className="text-[10px] text-zinc-500 font-sans">
                  Query the endpoint for models or manually add model names if the endpoint is offline or private.
                </span>
              </div>
              <button
                type="button"
                onClick={handleFetchModels}
                disabled={previewMutation.isPending || !baseUrl}
                className="px-2.5 py-1 rounded bg-terminal-amber/10 hover:bg-terminal-amber/20 text-terminal-amber font-mono text-[11px] border border-terminal-amber/40 flex items-center gap-1.5 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {previewMutation.isPending ? (
                  <>
                    <Loader2 className="w-3 h-3 animate-spin" />
                    Fetching...
                  </>
                ) : (
                  <>
                    <RefreshCw className="w-3 h-3" />
                    Fetch Models Live
                  </>
                )}
              </button>
            </div>

            {previewNotice && (
              <div className="p-2 bg-amber-950/30 border border-amber-800/40 rounded text-amber-300 text-[10px] font-mono">
                {previewNotice}
              </div>
            )}

            {/* Current Selected Models Tags */}
            <div className="flex flex-wrap gap-1.5 p-2.5 rounded bg-[#09090b] border border-zinc-800 min-h-[42px] items-center">
              {models.map((m) => (
                <span
                  key={m}
                  className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-200 font-mono text-[11px] flex items-center gap-1 border border-zinc-700"
                >
                  <span>{m}</span>
                  <button
                    type="button"
                    onClick={() => removeModel(m)}
                    className="text-zinc-400 hover:text-rose-400 cursor-pointer"
                    title={`Remove ${m}`}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>

            {/* Manual Model Input Fallback */}
            <form onSubmit={handleManualAdd} className="flex items-center gap-2">
              <input
                type="text"
                value={manualModel}
                onChange={(e) => setManualModel(e.target.value)}
                placeholder="Manual model fallback (e.g. llama3.1:70b, deepseek-coder-v2)"
                className="flex-1 bg-[#09090b] border border-zinc-700 px-2.5 py-1 rounded font-mono text-xs text-white focus:outline-none focus:border-terminal-amber"
              />
              <button
                type="submit"
                disabled={!manualModel.trim()}
                className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-white font-mono text-xs border border-zinc-700 disabled:opacity-40 cursor-pointer"
              >
                + Add Model
              </button>
            </form>

            {/* Discovered models quick-picker if fetched */}
            {discoveredModels.length > 0 && (
              <div className="flex flex-col gap-1 mt-1">
                <span className="text-[10px] font-mono text-zinc-500 uppercase">Discovered from endpoint:</span>
                <div className="flex flex-wrap gap-1">
                  {discoveredModels.map((dm) => {
                    const isSelected = models.includes(dm);
                    return (
                      <button
                        key={dm}
                        type="button"
                        onClick={() => (isSelected ? removeModel(dm) : addModel(dm))}
                        className={`px-2 py-0.5 rounded font-mono text-[10px] border cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-terminal-amber/20 border-terminal-amber text-terminal-amber font-bold'
                            : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:text-zinc-200'
                        }`}
                      >
                        {isSelected && '✓ '}
                        {dm}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2.5 px-5 py-3 border-t border-[#27272a] bg-[#121216] shrink-0">
          <button
            type="button"
            onClick={handleClose}
            disabled={isSaving}
            className="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-mono text-xs border border-zinc-700 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            data-testid="save-endpoint-btn"
            disabled={isSaving || !displayLabel.trim() || !urlCheck.isValid}
            className="px-4 py-1.5 rounded bg-terminal-amber hover:bg-amber-400 disabled:opacity-40 disabled:hover:bg-terminal-amber text-black font-mono text-xs font-bold transition-colors flex items-center gap-1.5 cursor-pointer"
          >
            {isSaving ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Saving...
              </>
            ) : isEditing ? (
              'Save Changes'
            ) : (
              'Create Endpoint'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

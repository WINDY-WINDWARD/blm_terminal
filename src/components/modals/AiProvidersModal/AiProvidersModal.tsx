'use client';

import React, { useRef, useCallback } from 'react';
import { useAtom } from 'jotai';
import { Cpu, Globe, Key, Loader2, RefreshCw, Server, X } from 'lucide-react';
import { aiProvidersModalTabAtom, type AiProvidersTabId } from '@/store/terminalStore';
import { useAiRoutesQuery } from '@/hooks/useAiRoutes';
import { useModalFocusTrap } from '@/hooks/useModalFocusTrap';
import { TopSummary } from './TopSummary';
import { OAuthAccountsTab } from './OAuthAccountsTab';
import { CustomEndpointsTabPlaceholder } from './CustomEndpointsTabPlaceholder';
import { DirectProvidersTabPlaceholder } from './DirectProvidersTabPlaceholder';

interface AiProvidersModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const TABS: { id: AiProvidersTabId; label: string; icon: React.ReactNode }[] = [
  { id: 'oauth', label: 'OAUTH ACCOUNTS', icon: <Key className="w-3.5 h-3.5" /> },
  { id: 'custom', label: 'CUSTOM ENDPOINTS', icon: <Globe className="w-3.5 h-3.5" /> },
  { id: 'direct', label: 'DIRECT PROVIDERS', icon: <Cpu className="w-3.5 h-3.5" /> },
];

export function AiProvidersModal({ isOpen, onClose }: AiProvidersModalProps) {
  const [activeTab, setActiveTab] = useAtom(aiProvidersModalTabAtom);
  const { data, isLoading, isError, error, refetch } = useAiRoutesQuery();
  const modalRef = useRef<HTMLDivElement>(null);

  const handleClose = useCallback(() => {
    onClose();
  }, [onClose]);

  // Modal focus trap & scoped Escape handling
  useModalFocusTrap({
    id: 'ai-providers-modal',
    isOpen,
    onClose: handleClose,
    containerRef: modalRef,
  });

  if (!isOpen) return null;

  return (
    <div
      ref={modalRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="ai-providers-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200 select-none outline-none"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div className="relative w-full max-w-5xl bg-[#09090b] border border-[#27272a] rounded-lg shadow-2xl flex flex-col max-h-[90vh] h-[85vh] overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#27272a] bg-[#121216] shrink-0">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded bg-terminal-amber/10 border border-terminal-amber/30 text-terminal-amber">
              <Server className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2
                  id="ai-providers-modal-title"
                  className="text-sm font-bold tracking-wider text-white uppercase font-mono"
                >
                  AI PROVIDER ROUTES & OAUTH MANAGER
                </h2>
              </div>
              <p className="text-[11px] text-zinc-400 font-sans">
                Manage OAuth subscriptions, enterprise custom endpoints, routing strategy, and direct API providers.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={handleClose}
            aria-label="Close AI providers modal"
            className="p-1 rounded text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body Container */}
        <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-zinc-400 font-mono text-xs">
              <Loader2 className="w-7 h-7 animate-spin text-terminal-amber" />
              <span>Loading provider routes and credentials...</span>
            </div>
          )}

          {isError && (
            <div className="p-4 rounded-lg bg-rose-950/40 border border-rose-800 text-rose-200 flex flex-col gap-2 font-mono text-xs">
              <span className="font-bold uppercase tracking-wider text-rose-400">Failed to load provider routes</span>
              <p className="text-zinc-300">{error instanceof Error ? error.message : 'Unknown network error'}</p>
              <button
                type="button"
                onClick={() => refetch()}
                className="self-start px-3 py-1 mt-1 rounded bg-rose-900/60 hover:bg-rose-800 text-white font-mono text-xs flex items-center gap-1.5 cursor-pointer"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Retry
              </button>
            </div>
          )}

          {data && (
            <>
              {/* Top Summary Bar */}
              <TopSummary data={data} />

              {/* Tab Navigation Strip */}
              <div
                role="tablist"
                aria-label="Provider configuration sections"
                className="flex items-center gap-1 border-b border-[#27272a] pt-1"
              >
                {TABS.map((tab) => {
                  const isActive = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      role="tab"
                      aria-selected={isActive}
                      aria-controls={`panel-${tab.id}`}
                      id={`tab-${tab.id}`}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      className={`flex items-center gap-2 px-4 py-2 font-mono text-xs font-semibold tracking-wider transition-all border-b-2 -mb-px cursor-pointer ${
                        isActive
                          ? 'border-terminal-amber text-terminal-amber bg-terminal-amber/5'
                          : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
                      }`}
                    >
                      {tab.icon}
                      {tab.label}
                    </button>
                  );
                })}
              </div>

              {/* Active Tab Panel */}
              <div
                role="tabpanel"
                id={`panel-${activeTab}`}
                aria-labelledby={`tab-${activeTab}`}
                className="pt-1 focus:outline-none"
              >
                {activeTab === 'oauth' && (
                  <OAuthAccountsTab routes={data.routes} activeRouteId={data.active_route_id} />
                )}
                {activeTab === 'custom' && (
                  <CustomEndpointsTabPlaceholder routes={data.routes} activeRouteId={data.active_route_id} />
                )}
                {activeTab === 'direct' && (
                  <DirectProvidersTabPlaceholder routes={data.routes} activeRouteId={data.active_route_id} />
                )}
              </div>
            </>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-between px-5 py-2.5 border-t border-[#27272a] bg-[#0c0c0f] shrink-0 text-[11px] font-mono text-zinc-400">
          <div className="flex items-center gap-2">
            <span className="text-zinc-500">
              Press{' '}
              <kbd className="px-1 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">ESC</kbd> to
              close
            </span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-500">Zero secrets stored on renderer</span>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-white font-mono text-xs border border-zinc-700 transition-colors cursor-pointer"
          >
            [CLOSE]
          </button>
        </div>
      </div>
    </div>
  );
}

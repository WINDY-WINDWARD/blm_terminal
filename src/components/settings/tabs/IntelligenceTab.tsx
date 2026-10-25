'use client';

import React from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { RouteModelCatalogResponse, RouteModelCatalogEntry } from '@/types/aiRoutes';
import { RouteModelSelect } from '@/components/ai/RouteModelSelect';
import { BentoCard } from './BentoCard';
import type { BrowserProvision } from './types';

export interface IntelligenceTabProps {
  scrapingConsent: boolean | null;
  onUpdateConsent: (val: boolean) => void;
  consentSyncStatus: string | null;
  browserProvision: BrowserProvision | null;
  browserFetchBusy: boolean;
  onBrowserRetry: () => void;
  isAdmin: boolean;
  aiAuthStatus: { provider: string; is_configured: boolean } | null;
  activeRoute: { display_label?: string; id?: string } | undefined;
  activeRouteId?: string;
  isRoutesLoading: boolean;
  oauthAccountCount: number;
  customEndpointCount: number;
  directKeyCount: number;
  onOpenManageProviders: () => void;
  configError: string | null;
  onRetryConfig: () => void;
  aiHunterModel: string;
  onAiHunterModelChange: (value: string) => void;
  aiVerifierModel: string;
  onAiVerifierModelChange: (value: string) => void;
  routeModels: RouteModelCatalogEntry[];
  routeModelsQuery: UseQueryResult<RouteModelCatalogResponse, Error>;
  configLoading: boolean;
}

export function IntelligenceTab({
  scrapingConsent,
  onUpdateConsent,
  consentSyncStatus,
  browserProvision,
  browserFetchBusy,
  onBrowserRetry,
  isAdmin,
  aiAuthStatus,
  activeRoute,
  activeRouteId,
  isRoutesLoading,
  oauthAccountCount,
  customEndpointCount,
  directKeyCount,
  onOpenManageProviders,
  configError,
  onRetryConfig,
  aiHunterModel,
  onAiHunterModelChange,
  aiVerifierModel,
  onAiVerifierModelChange,
  routeModels,
  routeModelsQuery,
  configLoading,
}: IntelligenceTabProps) {
  return (
    <>
      {/* Data Extraction & Privacy */}
      <BentoCard
        icon="◐"
        title="Data Extraction & Privacy"
        blurb="Controls whether the terminal may run headless browser automation to harvest deep fundamentals and premium news tokens. Safe Mode disables all external scraping."
        badge={
          <span
            className={`text-[10px] px-1.5 py-0.5 font-mono ${
              scrapingConsent === true
                ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                : scrapingConsent === null
                ? 'bg-amber-950 text-amber-400 border border-amber-800'
                : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
            }`}
          >
            {scrapingConsent === true
              ? 'Advanced Extraction Active'
              : scrapingConsent === null
              ? 'Consent Required'
              : 'Safe Mode (Anonymous)'}
          </span>
        }
        className="col-span-1 md:col-span-2 lg:col-span-4"
      >
        <div className="flex flex-col gap-1.5">
          <p className="text-[10px] text-white/60 leading-relaxed">
            When Advanced Extraction is enabled, the terminal operates generic headless automation on your behalf to harvest deep company fundamentals and premium news tokens. In Safe Mode, external scraping is disabled.
          </p>
          <div className="flex items-center gap-2 mt-1">
            <button
              type="button"
              onClick={() => onUpdateConsent(false)}
              disabled={scrapingConsent !== true}
              className={`px-3 py-1 text-[11px] font-mono rounded border transition ${
                scrapingConsent !== true
                  ? 'bg-zinc-800/60 text-zinc-500 border-zinc-700/50 cursor-not-allowed opacity-60'
                  : 'bg-zinc-800 text-zinc-300 border-zinc-600 hover:bg-zinc-700 hover:text-white cursor-pointer'
              }`}
            >
              Disable (Safe Mode)
            </button>
            <button
              type="button"
              onClick={() => onUpdateConsent(true)}
              disabled={scrapingConsent === true}
              className={`px-3 py-1 text-[11px] font-mono rounded border transition ${
                scrapingConsent === true
                  ? 'bg-zinc-800/60 text-zinc-500 border-zinc-700/50 cursor-not-allowed opacity-60'
                  : 'bg-blue-600 text-white border-blue-500 hover:bg-blue-500 cursor-pointer font-semibold shadow-sm'
              }`}
            >
              Enable Advanced Extraction
            </button>
          </div>
          {consentSyncStatus && (
            <div className="text-[10px] text-terminal-amber animate-pulse mt-0.5">
              {consentSyncStatus}
            </div>
          )}
          {scrapingConsent === true && browserProvision && browserProvision.state !== 'ready' && (
            <div className="mt-1 rounded border border-zinc-700/60 bg-zinc-900/60 px-2.5 py-2 text-[10px] font-mono">
              <div className="flex items-center justify-between gap-2">
                <span
                  className={
                    browserProvision.state === 'failed'
                      ? 'text-red-400'
                      : browserProvision.state === 'downloading'
                      ? 'text-terminal-amber animate-pulse'
                      : 'text-zinc-400'
                  }
                >
                  {browserProvision.state === 'downloading'
                    ? `Downloading extraction browser${
                        browserProvision.total > 0
                          ? ` — ${Math.round((browserProvision.downloaded / browserProvision.total) * 100)}%`
                          : '…'
                      }`
                    : browserProvision.state === 'failed'
                    ? `Browser download failed${browserProvision.error ? `: ${browserProvision.error}` : ''}`
                    : 'Extraction browser not installed yet — starting download…'}
                </span>
                {(browserProvision.state === 'failed' || browserProvision.state === 'missing') && (
                  <button
                    type="button"
                    onClick={onBrowserRetry}
                    disabled={browserFetchBusy}
                    className="shrink-0 px-2 py-0.5 rounded border border-blue-500 bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60 cursor-pointer"
                  >
                    {browserFetchBusy ? 'Starting…' : 'Retry'}
                  </button>
                )}
              </div>
              {browserProvision.state === 'downloading' && browserProvision.total > 0 && (
                <div className="mt-1.5 h-1 rounded bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full bg-terminal-amber transition-all"
                    style={{
                      width: `${Math.min(
                        100,
                        Math.round((browserProvision.downloaded / browserProvision.total) * 100),
                      )}%`,
                    }}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </BentoCard>

      {isAdmin && (
        <>
          {/* AI Provider */}
          <BentoCard
            icon="✦"
            title="AI Provider"
            blurb="Your active route and configured provider resources. Add and manage accounts, endpoints, and keys in the provider manager."
            badge={
              <span className="inline-flex items-center gap-1.5 font-mono text-[10px]">
                <span
                  className={`inline-block w-2 h-2 rounded-full ${
                    aiAuthStatus?.is_configured
                      ? 'bg-terminal-green'
                      : aiAuthStatus
                      ? 'bg-terminal-red'
                      : 'bg-zinc-500'
                  }`}
                />
                <span className={aiAuthStatus?.is_configured ? 'text-terminal-green' : 'text-zinc-400'}>
                  {aiAuthStatus ? (aiAuthStatus.is_configured ? 'CONNECTED' : 'NOT CONNECTED') : 'CHECKING'}
                </span>
              </span>
            }
            className="col-span-1 md:col-span-2 lg:col-span-2"
          >
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1">
                <span className="text-terminal-amber text-[10px] uppercase tracking-widest">Active Route</span>
                <span className="text-white text-xs font-mono">
                  {activeRoute?.display_label ?? (isRoutesLoading ? 'Loading routes…' : 'No active route')}
                </span>
                <span className="text-white/50 text-[10px] font-mono">
                  {activeRouteId ?? 'No route selected'}
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[10px] font-mono">
                <span className="text-white/70">OAuth accounts: {oauthAccountCount}</span>
                <span className="text-white/70">Custom endpoints: {customEndpointCount}</span>
                <span className="text-white/70">Direct keys: {directKeyCount}</span>
              </div>
              <button
                type="button"
                onClick={onOpenManageProviders}
                className="self-start px-2.5 py-1 rounded bg-terminal-amber/10 hover:bg-terminal-amber/20 text-terminal-amber font-mono text-[10px] font-bold border border-terminal-amber/40 transition-colors cursor-pointer"
              >
                MANAGE PROVIDERS →
              </button>
            </div>
          </BentoCard>

          {/* Background Worker Models */}
          <BentoCard
            icon="◇"
            title="Background Worker Models"
            blurb="Models for the background AI-picks worker. The hunter scans the market; the verifier double-checks. Applies to future runs."
            className="col-span-1 md:col-span-2 lg:col-span-2"
          >
            <div className="flex flex-col gap-2">
              {configError && (
                <div
                  role="alert"
                  className="flex items-center justify-between text-xs text-red-400 bg-red-950/40 border border-red-800/50 px-2.5 py-1.5 rounded"
                >
                  <span>{configError}</span>
                  <button
                    type="button"
                    onClick={onRetryConfig}
                    className="text-terminal-amber underline hover:text-terminal-amber/80 cursor-pointer text-[11px] font-mono"
                  >
                    Retry
                  </button>
                </div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                <RouteModelSelect
                  label="Hunter Model"
                  value={aiHunterModel}
                  routes={routeModels}
                  helperText="Scans the market for opportunities — pick a smarter, more capable model."
                  isLoading={routeModelsQuery.isLoading || configLoading}
                  loadError={routeModelsQuery.isError || Boolean(configError)}
                  onRetry={() => {
                    if (routeModelsQuery.isError) void routeModelsQuery.refetch();
                    if (configError) onRetryConfig();
                  }}
                  onChange={onAiHunterModelChange}
                />
                <RouteModelSelect
                  label="Verifier Model"
                  value={aiVerifierModel}
                  routes={routeModels}
                  helperText="Double-checks the hunter's picks — a faster, less capable model is fine."
                  isLoading={routeModelsQuery.isLoading || configLoading}
                  loadError={routeModelsQuery.isError || Boolean(configError)}
                  onRetry={() => {
                    if (routeModelsQuery.isError) void routeModelsQuery.refetch();
                    if (configError) onRetryConfig();
                  }}
                  onChange={onAiVerifierModelChange}
                />
              </div>
            </div>
          </BentoCard>
        </>
      )}
    </>
  );
}

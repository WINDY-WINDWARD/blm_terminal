'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAtom } from 'jotai';
import {
  ALERT_SUMMARY_CACHE_VERSION,
  alertSummariesCacheAtom,
  isAlertSummaryValid,
  isAlertDigestBias,
  getAlertsSnapshotFingerprint,
  getTodayLocalDateString,
  type AlertDigestBias,
  type AlertSummarySourceItem,
  type CachedAlertSummary,
} from '@/store/terminalStore';

interface AlertSummaryModalProps {
  symbol: string;
  alerts: AlertSummarySourceItem[];
  onClose: () => void;
}

type ActiveAlertDigest = Pick<
  CachedAlertSummary,
  'summary' | 'bias' | 'trigger' | 'invalidation' | 'risk'
>;

interface AlertDigestResponse extends ActiveAlertDigest {
  input_tokens?: number;
  output_tokens?: number;
  model?: string;
}

const BIAS_STYLES: Record<AlertDigestBias, string> = {
  bullish: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/35',
  bearish: 'bg-rose-500/10 text-rose-300 border-rose-500/35',
  mixed: 'bg-amber-500/10 text-amber-300 border-amber-500/35',
  neutral: 'bg-zinc-500/10 text-zinc-300 border-zinc-500/35',
};

export function AlertSummaryModal({ symbol, alerts, onClose }: AlertSummaryModalProps) {
  const normSymbol = symbol.trim().toUpperCase();
  const [cache, setCache] = useAtom(alertSummariesCacheAtom);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const cachedEntry = useMemo(() => {
    return cache[normSymbol];
  }, [cache, normSymbol]);

  const isValidCached = useMemo(() => {
    return isAlertSummaryValid(cachedEntry, alerts);
  }, [cachedEntry, alerts]);

  const [activeDigest, setActiveDigest] = useState<ActiveAlertDigest | null>(
    isValidCached && cachedEntry
      ? {
          summary: cachedEntry.summary,
          bias: cachedEntry.bias,
          trigger: cachedEntry.trigger,
          invalidation: cachedEntry.invalidation,
          risk: cachedEntry.risk,
        }
      : null
  );
  const [isFromCache, setIsFromCache] = useState<boolean>(isValidCached);
  const [summaryTimestamp, setSummaryTimestamp] = useState<number>(
    isValidCached && cachedEntry ? cachedEntry.cachedAt : 0
  );

  const handleFetchSummary = useCallback(async () => {
    if (alerts.length === 0) {
      setError('No alerts available to summarize.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const payload = {
        symbol: normSymbol,
        alerts: alerts.map((a) => ({
          id: a.id,
          trigger_type: a.trigger_type,
          message: a.message,
          triggered_at: a.triggered_at,
          triggered_date: a.triggered_date,
        })),
        max_tokens: 2048,
      };

      const res = await fetch('/api/py/ai/alerts/summarize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        if (res.status === 503) {
          throw new Error('AI provider is not configured. Please set an API key in Settings → AI.');
        }
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || `AI summarizer failed (${res.status})`);
      }

      const data = (await res.json()) as AlertDigestResponse;
      if (
        !data.summary?.trim() ||
        !isAlertDigestBias(data.bias) ||
        !data.trigger?.trim() ||
        !data.invalidation?.trim() ||
        !data.risk?.trim()
      ) {
        throw new Error('AI returned an incomplete alert digest. Please regenerate.');
      }

      const generatedDigest: ActiveAlertDigest = {
        summary: data.summary.trim(),
        bias: data.bias,
        trigger: data.trigger.trim(),
        invalidation: data.invalidation.trim(),
        risk: data.risk.trim(),
      };
      const now = Date.now();
      const todayDate = getTodayLocalDateString();
      const fingerprint = getAlertsSnapshotFingerprint(alerts);

      const newEntry: CachedAlertSummary = {
        symbol: normSymbol,
        ...generatedDigest,
        cachedAt: now,
        localDate: todayDate,
        alertCount: alerts.length,
        latestAlertFingerprint: fingerprint,
        cacheVersion: ALERT_SUMMARY_CACHE_VERSION,
        model: data.model,
      };

      setCache((prev) => ({
        ...prev,
        [normSymbol]: newEntry,
      }));

      setActiveDigest(generatedDigest);
      setIsFromCache(false);
      setSummaryTimestamp(now);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate alert summary.';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  }, [alerts, normSymbol, setCache]);

  const initialCheckedRef = React.useRef(false);

  // On mount: if valid cache exists, show it; otherwise automatically fetch
  useEffect(() => {
    if (initialCheckedRef.current) return;
    initialCheckedRef.current = true;

    if (isValidCached && cachedEntry) {
      setActiveDigest({
        summary: cachedEntry.summary,
        bias: cachedEntry.bias,
        trigger: cachedEntry.trigger,
        invalidation: cachedEntry.invalidation,
        risk: cachedEntry.risk,
      });
      setIsFromCache(true);
      setSummaryTimestamp(cachedEntry.cachedAt);
    } else {
      handleFetchSummary();
    }
  }, [isValidCached, cachedEntry, handleFetchSummary]);

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleCopy = async () => {
    if (!activeDigest) return;
    const copyText = [
      `${normSymbol} — ${activeDigest.bias.toUpperCase()}`,
      activeDigest.summary,
      '',
      `TRIGGER: ${activeDigest.trigger}`,
      `INVALIDATION: ${activeDigest.invalidation}`,
      `RISK: ${activeDigest.risk}`,
    ].join('\n');
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Fallback
    }
  };

  const formattedTime = useMemo(() => {
    if (!summaryTimestamp) return '';
    const d = new Date(summaryTimestamp);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }, [summaryTimestamp]);

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 font-mono select-none"
      onClick={onClose}
    >
      <div
        className="bg-[#0c0c0f] border border-[#27272a] rounded-lg shadow-2xl w-full max-w-xl flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="alert-digest-title"
      >
        {/* Header */}
        <div className="p-3.5 border-b border-[#27272a] flex items-center justify-between bg-[#121216]">
          <div className="flex items-center gap-2">
            <span
              id="alert-digest-title"
              className="text-sm font-extrabold text-amber-400 tracking-wider flex items-center gap-1.5"
            >
              <span>🤖</span>
              <span>AI ALERT DIGEST: {normSymbol}</span>
            </span>
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                isFromCache
                  ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                  : 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
              }`}
            >
              {isFromCache ? 'CACHED' : 'GENERATED'}
            </span>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1 text-zinc-400 hover:text-white rounded hover:bg-zinc-800 transition-colors cursor-pointer"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-4 space-y-3.5">
          {/* Metadata chips */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] bg-zinc-800/80 text-zinc-300 border border-zinc-700/60 px-2 py-0.5 rounded font-bold">
              {alerts.length} {alerts.length === 1 ? 'ALERT' : 'ALERTS'}
            </span>
            {formattedTime && (
              <span className="text-[10px] bg-zinc-800/80 text-zinc-300 border border-zinc-700/60 px-2 py-0.5 rounded tabular-nums">
                {formattedTime}
              </span>
            )}
            <span className="text-[10px] bg-amber-500/10 text-amber-400/90 border border-amber-500/25 px-2 py-0.5 rounded font-bold">
              VALID TODAY · EXPIRES ON NEW ALERT
            </span>
          </div>

          {/* Digest card (Concept B) */}
          <div className="bg-[#121216] border border-amber-400/25 rounded-md p-4 min-h-[140px] flex flex-col justify-center relative overflow-hidden shadow-inner">
            {isLoading ? (
              <div className="py-8 text-center text-amber-400 text-xs flex flex-col items-center justify-center gap-2">
                <span className="animate-spin text-base">⟳</span>
                <span className="font-bold tracking-wider animate-pulse uppercase">
                  SUMMARIZING {alerts.length} ALERTS FOR {normSymbol}...
                </span>
                <span className="text-[10px] text-zinc-500">
                  Synthesizing technical signals, volume patterns, and deal triggers
                </span>
              </div>
            ) : error ? (
              <div className="py-6 text-center text-rose-400 text-xs flex flex-col items-center justify-center gap-2">
                <span className="text-xl">⚠️</span>
                <span className="font-bold">SYNTHESIS FAILED</span>
                <p className="text-zinc-400 max-w-md text-[11px] leading-relaxed">{error}</p>
                <button
                  type="button"
                  onClick={handleFetchSummary}
                  className="mt-2 px-3 py-1 rounded bg-amber-400/10 hover:bg-amber-400/20 text-amber-400 border border-amber-400/40 text-xs font-bold transition-all cursor-pointer"
                >
                  Retry
                </button>
              </div>
            ) : activeDigest ? (
              <div className="space-y-3">
                <div className="flex items-start gap-3">
                  <span className={`shrink-0 text-[10px] font-extrabold px-2 py-0.5 rounded border tracking-wider ${BIAS_STYLES[activeDigest.bias]}`}>
                    {activeDigest.bias.toUpperCase()}
                  </span>
                  <p className="text-zinc-100 text-sm leading-relaxed whitespace-normal selection:bg-amber-400 selection:text-black">
                    {activeDigest.summary}
                  </p>
                </div>
                <div className="grid gap-2 border-t border-zinc-800 pt-3">
                  {[
                    ['TRIGGER', activeDigest.trigger],
                    ['INVALIDATION', activeDigest.invalidation],
                    ['RISK', activeDigest.risk],
                  ].map(([label, value]) => (
                    <div key={label} className="grid grid-cols-[86px_1fr] gap-2 text-xs leading-relaxed">
                      <span className="text-[10px] font-bold tracking-wider text-zinc-500 pt-0.5">{label}</span>
                      <span className="text-zinc-200">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-zinc-500 text-sm">No digest generated yet.</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-[#27272a] bg-[#121216] flex items-center justify-between gap-2">
          <span className="text-[10px] text-zinc-500 leading-tight truncate">
            Cached for {normSymbol} today. Automatically invalidates when new alerts arrive.
          </span>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={handleCopy}
              disabled={isLoading || !activeDigest}
              className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-zinc-800 text-zinc-200 hover:text-white border border-zinc-700 text-xs font-bold transition-all flex items-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <span>{copied ? '✓' : '📋'}</span>
              <span>{copied ? 'COPIED' : 'COPY'}</span>
            </button>

            <button
              type="button"
              onClick={handleFetchSummary}
              disabled={isLoading || alerts.length === 0}
              className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-amber-400/20 hover:text-amber-300 border border-zinc-700 hover:border-amber-400 text-amber-400 text-xs font-bold transition-all flex items-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              title="Force regenerate summary from currently loaded alerts"
            >
              <span>🔄</span>
              <span>REGENERATE</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-bold transition-all cursor-pointer"
            >
              CLOSE
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


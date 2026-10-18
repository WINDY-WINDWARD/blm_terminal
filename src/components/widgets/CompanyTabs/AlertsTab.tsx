'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertSummaryModal } from '../AlertSummaryModal';

interface Notification {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
  trigger_type: string;
  message: string;
  triggered_at: string;
  triggered_date: string;
  is_read: boolean;
}

export function AlertsTab({ symbol }: { symbol: string }) {
  const [showAiSummary, setShowAiSummary] = useState(false);

  const { data: personalNotifs, isLoading: pLoading } = useQuery<Notification[]>({
    queryKey: ['notifications'],
    queryFn: async () => {
      const res = await fetch('/api/py/notifications');
      if (!res.ok) return [];
      return res.json();
    }
  });

  const { data: globalNotifs, isLoading: gLoading } = useQuery<Notification[]>({
    queryKey: ['notifications', 'global'],
    queryFn: async () => {
      const res = await fetch('/api/py/notifications/global');
      if (!res.ok) return [];
      return res.json();
    }
  });

  if (pLoading || gLoading) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-sm text-terminal-amber animate-pulse">
        LOADING ALERTS...
      </div>
    );
  }

  const allNotifs = [...(personalNotifs || []), ...(globalNotifs || [])];
  
  // Filter for the active symbol
  const relevantNotifs = allNotifs
    .filter(n => n.symbol?.toUpperCase() === symbol.toUpperCase())
    .sort((a, b) => new Date(b.triggered_at).getTime() - new Date(a.triggered_at).getTime());

  return (
    <div className="h-full w-full flex flex-col font-mono bg-terminal-bg">
      <div className="p-2 border-b border-terminal-gray/40 flex items-center justify-between bg-terminal-bg shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs text-terminal-amber/90 font-bold uppercase tracking-wider">
            Alerts ({relevantNotifs.length})
          </span>
        </div>
        <button
          type="button"
          onClick={() => setShowAiSummary(true)}
          disabled={relevantNotifs.length === 0}
          className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-amber-400/20 hover:text-amber-300 border border-zinc-700 hover:border-amber-400 text-zinc-200 text-xs font-bold transition-all flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          title={relevantNotifs.length === 0 ? "No alerts to summarize" : `AI summarize alerts for ${symbol}`}
        >
          <span>🤖</span>
          <span>AI Summarize</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {relevantNotifs.length === 0 ? (
          <div className="text-white/60 text-center py-4 text-sm">No alerts found for {symbol}</div>
        ) : (
          relevantNotifs.map((notif, i) => (
            <div
              key={`${notif.id}-${i}`}
              className="border border-terminal-gray/30 rounded p-2 hover:bg-terminal-gray/10 transition-colors duration-300 ease-out"
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-terminal-amber/80 text-xs uppercase">{notif.trigger_type.replace(/_/g, ' ')}</span>
                <span className="text-white/40 text-xs">
                  {new Date(notif.triggered_at).toLocaleString()}
                </span>
              </div>
              <p className="text-white text-sm leading-relaxed">{notif.message}</p>
            </div>
          ))
        )}
      </div>

      {showAiSummary && (
        <AlertSummaryModal
          symbol={symbol}
          alerts={relevantNotifs}
          onClose={() => setShowAiSummary(false)}
        />
      )}
    </div>
  );
}

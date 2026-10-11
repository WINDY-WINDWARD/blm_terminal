'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';

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
    </div>
  );
}
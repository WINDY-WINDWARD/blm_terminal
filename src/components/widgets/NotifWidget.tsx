'use client';

import React, { useState } from 'react';
import { useAtomValue, useAtom } from 'jotai';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { activeExchangeAtom, activeSymbolAtom, watchlistsAtom, type Watchlist } from '@/store/terminalStore';

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

type NotifTab = 'all' | 'breakout' | 'volume' | 'movers' | 'deals' | 'insider';

const TAB_TRIGGERS: Record<NotifTab, string[]> = {
  all: [],
  breakout: ['52w_high_breakout', '52w_low_breakout'],
  volume: ['volume_breakout'],
  movers: ['top_gainer', 'top_loser'],
  deals: ['bulk_deal', 'block_deal'],
  insider: ['insider_buy', 'insider_sell'],
};

function getBadgeColor(triggerType: string): string {
  if (triggerType.startsWith('52w_')) return 'bg-terminal-amber text-black';
  if (triggerType === 'volume_breakout') return 'bg-cyan-600 text-white';
  if (triggerType === 'top_gainer') return 'bg-terminal-green text-black';
  if (triggerType === 'top_loser') return 'bg-terminal-red text-white';
  if (triggerType === 'bulk_deal') return 'bg-orange-600 text-white';
  if (triggerType === 'block_deal') return 'bg-orange-700 text-white';
  if (triggerType === 'insider_buy') return 'bg-purple-600 text-white';
  if (triggerType === 'insider_sell') return 'bg-purple-700 text-white';
  return 'bg-terminal-gray text-white';
}

function getBadgeLabel(triggerType: string): string {
  if (triggerType === '52w_high_breakout') return '52W HIGH';
  if (triggerType === '52w_low_breakout') return '52W LOW';
  if (triggerType === 'volume_breakout') return 'VOL';
  if (triggerType === 'top_gainer') return 'GAINER';
  if (triggerType === 'top_loser') return 'LOSER';
  if (triggerType === 'bulk_deal') return 'BULK';
  if (triggerType === 'block_deal') return 'BLOCK';
  if (triggerType === 'insider_buy') return 'INS BUY';
  if (triggerType === 'insider_sell') return 'INS SELL';
  return triggerType.toUpperCase();
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  return `${hh}:${mm}`;
}

export function NotifWidget() {
  const queryClient = useQueryClient();
  const watchlists = useAtomValue(watchlistsAtom);
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<number>(
    watchlists.length > 0 ? watchlists[0].id : 1,
  );
  const [activeTab, setActiveTab] = useState<NotifTab>('all');
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

  const { data, isLoading, isError, error, refetch } = useQuery<Notification[]>({
    queryKey: ['notifications', selectedWatchlistId],
    queryFn: async () => {
      const res = await fetch(`/api/py/notifications?watchlist_id=${selectedWatchlistId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  const dismissMutation = useMutation({
    mutationFn: async (id: number) => {
        const res = await fetch(
          `/api/py/notifications/${id}?watchlist_id=${selectedWatchlistId}`,
        { method: 'DELETE' },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const clearAllMutation = useMutation({
    mutationFn: async () => {
        const res = await fetch(
          `/api/py/notifications?all=true&watchlist_id=${selectedWatchlistId}`,
        { method: 'DELETE' },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const handleRowClick = (n: Notification) => {
    setActiveSymbol(n.symbol);
    setActiveExchange(n.exchange);
  };

  const handleDismiss = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    dismissMutation.mutate(id);
  };

  const filteredNotifications = (data ?? []).filter((n) => {
    if (activeTab === 'all') return true;
    return TAB_TRIGGERS[activeTab].includes(n.trigger_type);
  });

  const selectedWatchlist = watchlists.find((wl) => wl.id === selectedWatchlistId);

  const tabs: { id: NotifTab; label: string }[] = [
    { id: 'all', label: 'ALL' },
    { id: 'breakout', label: 'BREAKOUT' },
    { id: 'volume', label: 'VOLUME' },
    { id: 'movers', label: 'MOVERS' },
    { id: 'deals', label: 'DEALS' },
    { id: 'insider', label: 'INSIDER' },
  ];

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">LOADING NOTIFICATIONS...</span>
      </div>
    );
  }

  if (isError) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2 px-4 text-center">
        <span className="text-terminal-red font-bold uppercase">Fetch Failed</span>
        <span className="text-white text-[10px] max-w-xs">{errMsg}</span>
        <button
          onClick={() => refetch()}
          className="text-terminal-amber text-[10px] underline hover:text-white"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-center gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase shrink-0">NOTIF</span>
        <select
          value={selectedWatchlistId}
          onChange={(e) => setSelectedWatchlistId(Number(e.target.value))}
          className="bg-terminal-bg text-terminal-amber text-[10px] border border-terminal-gray px-1 py-px max-w-[120px] truncate"
        >
          {watchlists.map((wl: Watchlist) => (
            <option key={wl.id} value={wl.id}>{wl.name}</option>
          ))}
        </select>
        <span className="text-white/60 text-[10px] shrink-0">
          ({(data ?? []).length})
        </span>
        {(data ?? []).length > 0 && (
          <button
            onClick={() => clearAllMutation.mutate()}
            className="ml-auto text-[9px] text-white/50 hover:text-terminal-red transition-colors shrink-0"
          >
            CLEAR ALL
          </button>
        )}
      </div>

      <div className="flex-shrink-0 flex border-b border-terminal-gray/60 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-2 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors border-b-2 whitespace-nowrap ${
              activeTab === tab.id
                ? 'bg-terminal-amber text-black font-bold -mb-px'
                : 'text-white/50 hover:text-white hover:bg-zinc-900 border-transparent'
            }`}
            style={activeTab === tab.id ? { borderBottomColor: '#ffb900' } : undefined}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {filteredNotifications.length === 0 ? (
          <div className="text-white/40 text-[10px] py-4 text-center">
            No alerts for {selectedWatchlist?.name ?? `watchlist ${selectedWatchlistId}`}.
          </div>
        ) : (
          <div className="flex flex-col gap-px">
            {filteredNotifications.map((n) => (
              <div
                key={n.id}
                onClick={() => handleRowClick(n)}
                className="flex items-center gap-2 px-2 py-[4px] bg-zinc-900 hover:bg-zinc-800 cursor-pointer group border border-terminal-gray/20 rounded-sm"
              >
                <span className={`shrink-0 text-[8px] font-bold px-1 py-px rounded ${getBadgeColor(n.trigger_type)}`}>
                  {getBadgeLabel(n.trigger_type)}
                </span>
                <span className="font-bold text-terminal-amber text-[11px] shrink-0">
                  {n.symbol}
                </span>
                <span
                  className="text-white/80 text-[10px] truncate flex-1 min-w-0"
                  title={n.message}
                >
                  {n.message}
                </span>
                <span className="text-white/40 text-[9px] shrink-0">{formatTime(n.triggered_at)}</span>
                <button
                  onClick={(e) => handleDismiss(e, n.id)}
                  className="shrink-0 text-white/30 hover:text-terminal-red text-[11px] w-4 text-center opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Dismiss"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

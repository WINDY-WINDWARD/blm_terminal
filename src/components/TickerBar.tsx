'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { tickerSourceAtom, type Watchlist } from '@/store/terminalStore';
import { marketWsService } from '@/lib/marketWs';
import type { SymbolDataExtract } from '@/lib/nseTypes';

interface WatchlistItem {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
}

interface TopMoverItem {
  symbol: string;
  ltp?: string | number;
  lastPrice?: string | number;
  close?: string | number;
  pChange?: string | number;
  perChange?: string | number;
}

interface AIPick {
  id: number;
  symbol: string;
  status: 'NEW' | 'ACTED_ON' | 'CLOSED' | 'ABANDONED';
}

interface TickerEntry {
  symbol: string;
  isAiPick: boolean;
  ltp: number | null;
  pChange: number | null;
}

function extractNumber(val: string | number | undefined | null): number | null {
  if (val == null) return null;
  const n = typeof val === 'string' ? parseFloat(val) : val;
  return isNaN(n) ? null : n;
}

function TickerItem({ entry }: { entry: TickerEntry }) {
  const isUp = (entry.pChange ?? 0) > 0;
  const isDown = (entry.pChange ?? 0) < 0;
  const changeColor = isUp ? 'text-terminal-green' : isDown ? 'text-terminal-red' : 'text-white/60';

  return (
    <span className="shrink-0 flex items-center gap-1.5 px-3">
      {entry.isAiPick && (
        <span className="text-terminal-amber font-bold text-[10px]">[AI]</span>
      )}
      <span className={`font-bold ${entry.isAiPick ? 'text-terminal-amber' : 'text-white'}`}>
        {entry.symbol}
      </span>
      {entry.ltp != null && (
        <span className="text-white/80">{entry.ltp.toFixed(2)}</span>
      )}
      {entry.pChange != null && (
        <span className={changeColor}>
          {isUp ? '+' : ''}{entry.pChange.toFixed(2)}%
        </span>
      )}
    </span>
  );
}

export function TickerBar() {
  const tickerSource = useAtomValue(tickerSourceAtom);
  const [liveData, setLiveData] = useState<Record<string, SymbolDataExtract>>({});

  // Fetch watchlists (shared cache with WatchWidget)
  const { data: watchlists = [] } = useQuery<Watchlist[]>({
    queryKey: ['watchlists'],
    queryFn: async () => {
      const res = await fetch('/api/watchlists');
      if (!res.ok) throw new Error('Failed to fetch watchlists');
      return res.json();
    },
    staleTime: 300_000,
  });

  // Fetch AI picks
  const { data: aiPicks = [] } = useQuery<AIPick[]>({
    queryKey: ['ai-picks'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/picks');
      if (!res.ok) throw new Error('Failed to fetch AI picks');
      return res.json();
    },
    refetchInterval: 60_000,
  });

  const activeAiSymbols = useMemo(
    () => new Set(aiPicks.filter((p) => p.status !== 'CLOSED' && p.status !== 'ABANDONED').map((p) => p.symbol)),
    [aiPicks],
  );

  // Resolve the watchlist source
  const resolvedWatchlistId = useMemo(() => {
    if (tickerSource === 'top') return null;
    if (tickerSource === 'default') {
      return watchlists.length > 0 ? watchlists[0].id : null;
    }
    const id = parseInt(tickerSource.replace('watchlist:', ''), 10);
    return isNaN(id) ? null : id;
  }, [tickerSource, watchlists]);

  // Fetch watchlist items
  const { data: watchlistItems = [] } = useQuery<WatchlistItem[]>({
    queryKey: ['watchlist', resolvedWatchlistId],
    queryFn: async () => {
      const res = await fetch(`/api/watchlist?watchlist_id=${resolvedWatchlistId}`);
      if (!res.ok) throw new Error('Failed to fetch watchlist');
      return res.json();
    },
    staleTime: 60_000,
    enabled: resolvedWatchlistId !== null,
  });

  const useTopMovers =
    tickerSource === 'top' ||
    (tickerSource === 'default' && resolvedWatchlistId === null) ||
    (resolvedWatchlistId !== null && watchlistItems.length === 0);

  // Fetch top movers when needed
  const { data: gainers = [] } = useQuery<TopMoverItem[]>({
    queryKey: ['market/top-gainers', 'allSec'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/top-gainers?category=allSec');
      if (!res.ok) throw new Error('Failed to fetch top gainers');
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    enabled: useTopMovers,
  });

  const { data: losers = [] } = useQuery<TopMoverItem[]>({
    queryKey: ['market/top-losers', 'allSec'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/top-losers?category=allSec');
      if (!res.ok) throw new Error('Failed to fetch top losers');
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    enabled: useTopMovers,
  });

  // Build merged symbol list (deduplicated)
  const allSymbols = useMemo(() => {
    const symbols: string[] = [];

    if (useTopMovers) {
      for (const item of gainers) {
        if (item.symbol && !symbols.includes(item.symbol)) symbols.push(item.symbol);
      }
      for (const item of losers) {
        if (item.symbol && !symbols.includes(item.symbol)) symbols.push(item.symbol);
      }
    } else {
      for (const item of watchlistItems) {
        if (item.symbol && !symbols.includes(item.symbol)) symbols.push(item.symbol);
      }
    }

    for (const sym of activeAiSymbols) {
      if (!symbols.includes(sym)) symbols.push(sym);
    }

    return symbols;
  }, [useTopMovers, gainers, losers, watchlistItems, activeAiSymbols]);

  // Static data map for initial display
  const staticDataMap = useMemo(() => {
    const map: Record<string, { ltp: number | null; pChange: number | null }> = {};
    if (useTopMovers) {
      for (const item of gainers) {
        map[item.symbol] = {
          ltp: extractNumber(item.ltp ?? item.lastPrice ?? item.close),
          pChange: extractNumber(item.pChange ?? item.perChange),
        };
      }
      for (const item of losers) {
        if (!map[item.symbol]) {
          map[item.symbol] = {
            ltp: extractNumber(item.ltp ?? item.lastPrice ?? item.close),
            pChange: extractNumber(item.pChange ?? item.perChange),
          };
        }
      }
    }
    return map;
  }, [useTopMovers, gainers, losers]);

  // WebSocket subscription
  const handleSymbolData = useCallback((symbol: string, data: SymbolDataExtract | null) => {
    if (data) {
      setLiveData((prev) => {
        if (prev[symbol] === data) return prev;
        return { ...prev, [symbol]: data };
      });
    }
  }, []);

  useEffect(() => {
    if (allSymbols.length === 0) return;

    marketWsService.requestSymbolData(allSymbols);
    const unsub = marketWsService.onSymbolData(handleSymbolData);

    const interval = setInterval(() => {
      marketWsService.requestSymbolData(allSymbols);
    }, 30_000);

    return () => {
      unsub();
      clearInterval(interval);
    };
  }, [allSymbols, handleSymbolData]);

  // Build final entries
  const entries: TickerEntry[] = useMemo(() => {
    return allSymbols.map((symbol) => {
      const live = liveData[symbol];
      const stat = staticDataMap[symbol];
      return {
        symbol,
        isAiPick: activeAiSymbols.has(symbol),
        ltp: live?.ltp ?? stat?.ltp ?? null,
        pChange: live?.pChange ?? stat?.pChange ?? null,
      };
    });
  }, [allSymbols, liveData, staticDataMap, activeAiSymbols]);

  if (entries.length === 0) return null;

  // Duplicate entries for seamless infinite scroll
  const trackItems = [...entries, ...entries];
  const duration = Math.max(15, entries.length * 1.5);

  return (
    <div className="h-7 bg-[#0a0a0a] border-t border-terminal-gray/40 overflow-hidden shrink-0">
      <style>{`
        @keyframes ticker-marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .ticker-track {
          animation: ticker-marquee linear infinite;
        }
        .ticker-track:hover {
          animation-play-state: paused;
        }
      `}</style>
      <div
        className="ticker-track flex items-center h-full whitespace-nowrap"
        style={{ animationDuration: `${duration}s`, width: 'max-content' }}
      >
        {trackItems.map((entry, i) => (
          <TickerItem key={`${entry.symbol}-${i}`} entry={entry} />
        ))}
      </div>
    </div>
  );
}

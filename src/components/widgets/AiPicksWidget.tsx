'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { useAtom, useAtomValue } from 'jotai';
import { activeSymbolAtom, tickDataAtom, authAtom } from '@/store/terminalStore';
import { marketWsService } from '@/lib/marketWs';
import { AiPickModal, type AIPick } from './AiPickModal';

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 flex items-center gap-1 active:scale-[0.96] ${
        active
          ? 'bg-terminal-amber text-black font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent'
      }`}
    >
      {label}
    </button>
  );
}

function getActionPill(pick: AIPick) {
  if (!pick.notes || pick.notes.length === 0) return null;
  // find the latest note with an action or verdict
  const note = [...pick.notes].reverse().find(n => n.action || n.verdict);
  if (!note) return null;
  
  const label = note.action || note.verdict;
  if (!label) return null;
  
  let colorCls = 'bg-zinc-800 text-white border-zinc-600';
  const uc = label.toUpperCase();
  if (uc === 'BUY' || uc === 'BULLISH') colorCls = 'bg-green-900/40 text-green-400 border-green-800';
  else if (uc === 'SELL' || uc === 'BEARISH' || uc === 'CLOSE' || uc === 'ABANDON') colorCls = 'bg-red-900/40 text-red-400 border-red-800';
  else if (uc === 'HOLD' || uc === 'NEUTRAL') colorCls = 'bg-blue-900/40 text-blue-400 border-blue-800';
  
  return <span className={cn('px-1.5 py-0.5 text-[10px] rounded-sm font-bold border', colorCls)}>{uc}</span>;
}

export function AiPicksWidget({ panelId }: { panelId: string }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'PICKS' | 'ACTIVE' | 'HISTORY' | 'ABANDONED'>('PICKS');
  const [selectedPickId, setSelectedPickId] = useState<number | null>(null);
  const [showDisclaimer, setShowDisclaimer] = useState(true);
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [tickData, setTickData] = useAtom(tickDataAtom);
  const auth = useAtomValue(authAtom);

  React.useEffect(() => {
    const timer = setTimeout(() => setShowDisclaimer(false), 4000);
    return () => clearTimeout(timer);
  }, []);

  const { data: picks, isLoading, error } = useQuery<AIPick[]>({
    queryKey: ['ai-picks'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/picks');
      if (!res.ok) throw new Error('Failed to fetch AI Picks');
      return res.json();
    },
    refetchInterval: 60000,
  });

  // Create stable dependency string for WebSocket subscription
  const filteredPicks = picks?.filter((p) => {
    if (activeTab === 'PICKS') return p.status === 'NEW';
    if (activeTab === 'ACTIVE') return p.status === 'ACTED_ON';
    if (activeTab === 'HISTORY') return p.status === 'CLOSED';
    if (activeTab === 'ABANDONED') return p.status === 'ABANDONED';
    return false;
  }) || [];

  const activeSymbolsStr = filteredPicks.map(p => p.symbol).sort().join(',');

  // Safe real-time data subscription with stable dependency
  React.useEffect(() => {
    if (!activeSymbolsStr) return;
    const symbols = activeSymbolsStr.split(',');
    
    // 1. Send initial request and setup periodic refresh
    marketWsService.requestSymbolData(symbols);
    const interval = setInterval(() => {
      marketWsService.requestSymbolData(symbols);
    }, 60000);

    // 2. Listen for WebSocket responses and populate global tick data
    const unsub = marketWsService.onSymbolData((symbol, data) => {
      if (data && symbols.includes(symbol)) {
        setTickData((prev) => ({
          ...prev,
          [`${symbol}.NSE`]: { 
            symbol, 
            exchange: 'NSE', 
            ltp: data.ltp, 
            pChange: data.pChange, 
            yearHigh: data.yearHigh, 
            yearLow: data.yearLow 
          },
        }));
      }
    });

    // 3. Cleanup on unmount or when dependencies change
    return () => {
      clearInterval(interval);
      unsub();
    };
  }, [activeSymbolsStr, setTickData]);

  const updateStatusMutation = useMutation({
    mutationFn: async ({ id, status, exit_price }: { id: number; status: string; exit_price?: number }) => {
      const res = await fetch(`/api/py/ai/picks/${id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, exit_price }),
      });
      if (res.status === 403) throw new Error('Permission denied: Admin access required');
      if (!res.ok) throw new Error('Failed to update status');
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai-picks'] }),
  });

  const selectedPick = picks?.find((p) => p.id === selectedPickId) || null;

  if (isLoading) {
    return (
      <div className="flex h-full w-full items-center justify-center font-mono text-xs bg-terminal-bg text-white/80">
        <span className="text-terminal-amber animate-pulse">LOADING AI PICKS...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full w-full items-center justify-center font-mono text-xs bg-terminal-bg text-red-500">
        <span>ERROR: {error instanceof Error ? error.message : 'Failed to load'}</span>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-terminal-bg font-mono text-xs text-white/80 relative">
      {showDisclaimer && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="border border-terminal-amber/50 bg-black p-4 text-center text-terminal-amber animate-pulse max-w-sm shadow-xl">
            <div className="font-bold mb-2 uppercase text-sm">⚠️ Disclaimer</div>
            <div className="text-[10px] leading-relaxed">
              AI can make mistakes and the user takes all responsibility for any actions taken using the AI's advice/recommendations.
            </div>
          </div>
        </div>
      )}

      {/* Header Tabs */}
      <div className="flex shrink-0 items-center border-b border-terminal-gray/50">
        <TabButton
          active={activeTab === 'PICKS'}
          onClick={() => {
            setActiveTab('PICKS');
            setSelectedPickId(null);
          }}
          label="PICKS"
        />
        <TabButton
          active={activeTab === 'ACTIVE'}
          onClick={() => {
            setActiveTab('ACTIVE');
            setSelectedPickId(null);
          }}
          label="ACTIVE"
        />
        <TabButton
          active={activeTab === 'HISTORY'}
          onClick={() => {
            setActiveTab('HISTORY');
            setSelectedPickId(null);
          }}
          label="HISTORY"
        />
        <TabButton
          active={activeTab === 'ABANDONED'}
          onClick={() => {
            setActiveTab('ABANDONED');
            setSelectedPickId(null);
          }}
          label="ABANDONED"
        />
      </div>

      {/* Picks List */}
      <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1.5">
        {filteredPicks.length === 0 ? (
          <div className="text-center text-white/50 py-8 font-bold">NO {activeTab} PICKS</div>
        ) : (
          filteredPicks.map((pick) => {
            // Calculate PnL (Live vs Closed)
            const currentLivePrice = tickData[`${pick.symbol}.NSE`]?.ltp;
            const isClosed = pick.status === 'CLOSED';
            const referencePrice = isClosed ? pick.exit_price : currentLivePrice;

            let pnlDisplay = '-';
            let pnlColor = 'text-white/50';
            if (referencePrice && pick.entry_price) {
              const pnlPct = ((referencePrice - pick.entry_price) / pick.entry_price) * 100;
              pnlDisplay = `${pnlPct > 0 ? '+' : ''}${pnlPct.toFixed(2)}%`;
              pnlColor = pnlPct > 0 ? 'text-terminal-green' : 'text-terminal-red';
            }

            const formattedDate = pick.created_at
              ? new Date(pick.created_at).toLocaleString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: false,
                })
              : '';
            
            return (
              <div 
                key={pick.id} 
                onClick={() => setSelectedPickId(pick.id)}
                className={cn(
                  "group flex items-center justify-between border px-3 py-2 cursor-pointer transition-all duration-150 rounded-sm active:scale-[0.99]",
                  pick.status === 'ABANDONED' 
                    ? "border-zinc-800 bg-zinc-950/40 hover:bg-zinc-900/40 hover:border-zinc-700" 
                    : "border-terminal-gray/70 bg-black/60 hover:bg-zinc-900/60 hover:border-terminal-amber/60 hover:shadow-[0_0_8px_rgba(255,182,0,0.08)]"
                )}
              >
                {/* Left side info */}
                <div className="flex items-center gap-2.5 flex-wrap min-w-0">
                  <span 
                    className={cn(
                      "text-[13px] font-bold tracking-wide transition-colors group-hover:text-white",
                      pick.status === 'ABANDONED' ? "text-white/40" : "text-terminal-amber"
                    )}
                    onClick={(e) => { 
                      e.stopPropagation(); 
                      setActiveSymbol(pick.symbol); 
                    }}
                    title="Set as active symbol"
                  >
                    {pick.symbol}
                  </span>

                  <span className={cn(
                    'px-1.5 py-0.5 text-[10px] rounded-sm font-bold border',
                    pick.direction === 'LONG' ? 'bg-green-900/30 text-green-400 border-green-800/60' : 'bg-red-900/30 text-red-400 border-red-800/60'
                  )}>
                    {pick.direction}
                  </span>

                  {getActionPill(pick)}

                  <span className="text-[10px] uppercase text-white/50 border border-terminal-gray/50 px-1 py-0.2 rounded-sm">
                    {pick.status}
                  </span>

                  {formattedDate && (
                    <span className="text-[10px] text-white/40 font-mono hidden sm:inline">
                      {formattedDate}
                    </span>
                  )}
                </div>
                
                {/* Right side stats & view action */}
                <div className="flex items-center gap-3 text-[10px] font-mono shrink-0 ml-2">
                  <span className={`font-bold ${pnlColor}`}>{pnlDisplay}</span>
                  <span className="text-white/40 hidden md:inline">E:<span className="text-white ml-0.5">{pick.entry_price}</span></span>
                  <span className="text-white/40 hidden md:inline">TP:<span className="text-terminal-green ml-0.5">{pick.take_profit}</span></span>
                  <span className="text-white/40 hidden md:inline">SL:<span className="text-terminal-red ml-0.5">{pick.stop_loss}</span></span>
                  
                  <span className="text-terminal-amber/70 group-hover:text-terminal-amber group-hover:translate-x-0.5 transition-all text-xs font-bold pl-1">
                    DETAILS ↗
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Persistent Bottom Banner */}
      <div className="shrink-0 bg-terminal-amber/10 border-t border-terminal-amber/30 p-1.5 text-center text-[9px] text-terminal-amber/80 font-bold tracking-wide uppercase">
        AI can make mistakes. Verify before taking action.
      </div>

      {/* Modern Cyberpunk AI Modal */}
      {selectedPick && (
        <AiPickModal
          pick={selectedPick}
          onClose={() => setSelectedPickId(null)}
          currentLivePrice={tickData[`${selectedPick.symbol}.NSE`]?.ltp}
          onSelectSymbol={(sym) => setActiveSymbol(sym)}
          isAdmin={auth?.user?.is_admin}
          onUpdateStatus={updateStatusMutation.mutate}
        />
      )}
    </div>
  );
}

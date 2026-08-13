'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { useAtom, useAtomValue } from 'jotai';
import { activeSymbolAtom, tickDataAtom, authAtom } from '@/store/terminalStore';
import { marketWsService } from '@/lib/marketWs';

interface PickNote {
  timestamp: string;
  note: string;
  model: string;
  verdict?: string;
  technical?: string;
  fundamental?: string;
  catalyst?: string;
  risk?: string;
  action?: string;
}

interface AIPick {
  id: number;
  symbol: string;
  direction: 'LONG' | 'SHORT';
  entry_price: number;
  take_profit: number;
  stop_loss: number;
  exit_price?: number | null;
  status: 'NEW' | 'ACTED_ON' | 'CLOSED' | 'ABANDONED';
  notes: PickNote[];
  created_at: string;
  updated_at: string;
  status_updated_at: string;
}

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 flex items-center gap-1 ${
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
  const [expandedId, setExpandedId] = useState<number | null>(null);
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
             setExpandedId(null);
           }}
           label="PICKS"
         />
         <TabButton
           active={activeTab === 'ACTIVE'}
           onClick={() => {
             setActiveTab('ACTIVE');
             setExpandedId(null);
           }}
           label="ACTIVE"
         />
         <TabButton
           active={activeTab === 'HISTORY'}
           onClick={() => {
             setActiveTab('HISTORY');
             setExpandedId(null);
           }}
           label="HISTORY"
         />
         <TabButton
           active={activeTab === 'ABANDONED'}
           onClick={() => {
             setActiveTab('ABANDONED');
             setExpandedId(null);
           }}
           label="ABANDONED"
         />
       </div>

      {/* Picks List */}
      <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-2">
        {filteredPicks.length === 0 ? (
          <div className="text-center text-white/50 py-4 font-bold">NO {activeTab} PICKS</div>
        ) : (
          filteredPicks.map((pick) => {
            const isExpanded = expandedId === pick.id;
            
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
                className={cn(
                  "flex flex-col border p-2 hover:bg-zinc-900/40 transition-colors",
                  pick.status === 'ABANDONED' 
                    ? "border-zinc-700 bg-zinc-950/50 hover:bg-zinc-900/20" 
                    : "border-terminal-gray bg-black"
                )}
              >
                
                {/* Header Row */}
                <div 
                  className="flex items-center justify-between cursor-pointer"
                  onClick={() => setExpandedId(isExpanded ? null : pick.id)}
                >
                  <div className="flex items-center gap-3">
                    <span 
                      className={cn(
                        "text-[13px] cursor-pointer hover:text-white hover:underline transition-colors font-bold",
                        pick.status === 'ABANDONED' ? "text-white/40" : "text-terminal-amber"
                      )}
                      onClick={(e) => { e.stopPropagation(); setActiveSymbol(pick.symbol); }}
                    >
                      {pick.symbol}
                    </span>
                    <span className={cn(
                      'px-1.5 py-0.5 text-[10px] rounded-sm font-bold border border-transparent',
                      pick.direction === 'LONG' ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
                    )}>
                      {pick.direction}
                    </span>
                    {getActionPill(pick)}
                    <span className="text-[10px] uppercase text-white/50 border border-terminal-gray px-1">
                      {pick.status}
                    </span>
                    {formattedDate && (
                      <span className="text-[10px] text-white/40 font-mono">
                        {formattedDate}
                      </span>
                    )}
                  </div>
                  
                   <div className="flex items-center gap-3 text-[10px] text-white/60 font-mono">
                    <span className={`font-bold ${pnlColor}`}>PnL: {pnlDisplay}</span>
                    <span>E:<span className="text-white ml-1">{pick.entry_price}</span></span>
                    <span>TP:<span className="text-terminal-green ml-1">{pick.take_profit}</span></span>
                    <span>SL:<span className="text-terminal-red ml-1">{pick.stop_loss}</span></span>
                    <span className="text-white/50 text-[10px] w-4 text-right">
                      {isExpanded ? '▾' : '▸'}
                    </span>
                   </div>
                </div>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="mt-3 pt-3 border-t border-terminal-gray flex flex-col gap-2">
                    <div className="text-terminal-amber mb-1 font-bold text-[10px] uppercase">TIMELINE</div>
                    <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                      {pick.notes.map((n, i) => {
                        if (n.model === 'market-context') {
                          return (
                            <details key={i} className="group bg-zinc-900/50 rounded-sm border border-terminal-gray/50">
                              <summary className="flex cursor-pointer list-none items-center justify-between p-2 text-[10px] text-white/50 hover:text-white/80 transition-colors">
                                <div className="flex items-center gap-2">
                                  <span className="text-terminal-amber/60">🌐 MARKET CONTEXT</span>
                                  <span>{new Date(n.timestamp).toLocaleString()}</span>
                                </div>
                                <span className="group-open:rotate-180 transition-transform">▾</span>
                              </summary>
                              <div className="p-2 pt-0 text-white/70 text-[11px] leading-relaxed whitespace-pre-wrap border-t border-terminal-gray/30 mt-1">
                                {n.note}
                              </div>
                            </details>
                          );
                        }

                        return (
                          <div key={i} className="flex flex-col gap-1 bg-zinc-900 p-2 rounded-sm border border-terminal-gray">
                            <div className="flex justify-between text-[10px] text-white/40">
                              <span>{new Date(n.timestamp).toLocaleString()}</span>
                              <span className="text-terminal-amber/60">{n.model}</span>
                            </div>
                            <div className="text-white/90 text-[11px] leading-relaxed whitespace-pre-wrap">
                              {n.note}
                            </div>
                            {(n.technical || n.fundamental || n.catalyst || n.risk) && (
                              <div className="mt-1 pt-1 border-t border-zinc-800 flex flex-col gap-1 text-[11px]">
                                {n.technical && <div><span className="text-terminal-blue font-bold uppercase">TECH:</span> <span className="text-white/80">{n.technical}</span></div>}
                                {n.fundamental && <div><span className="text-terminal-purple font-bold uppercase">FUND:</span> <span className="text-white/80">{n.fundamental}</span></div>}
                                {n.catalyst && <div><span className="text-terminal-amber font-bold uppercase">CAT:</span> <span className="text-white/80">{n.catalyst}</span></div>}
                                {n.risk && <div><span className="text-red-400 font-bold uppercase">RISK:</span> <span className="text-white/80">{n.risk}</span></div>}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    
                     {/* Actions */}
                     {activeTab === 'PICKS' && pick.status === 'NEW' && auth?.user?.is_admin && (
                       <div className="flex mt-2">
                         <button
                           onClick={(e) => { e.stopPropagation(); updateStatusMutation.mutate({ id: pick.id, status: 'ACTED_ON' }); }}
                           className="bg-terminal-amber/10 border border-terminal-amber text-terminal-amber px-3 py-1 text-[10px] hover:bg-terminal-amber/20 transition-colors font-bold uppercase tracking-wider"
                         >
                           [ MARK ACTED ON ]
                         </button>
                       </div>
                     )}
                     {activeTab === 'ACTIVE' && pick.status === 'ACTED_ON' && auth?.user?.is_admin && (
                       <div className="flex mt-2">
                         <button
                           onClick={(e) => { e.stopPropagation(); updateStatusMutation.mutate({ id: pick.id, status: 'CLOSED', exit_price: currentLivePrice }); }}
                           className="bg-red-900/20 border border-red-500/50 text-red-400 px-3 py-1 text-[10px] hover:bg-red-900/40 transition-colors font-bold uppercase tracking-wider"
                         >
                           [ CLOSE POSITION ]
                         </button>
                       </div>
                     )}
                     {activeTab === 'ABANDONED' && pick.status === 'ABANDONED' && (
                       <div className="text-white/40 mt-2 text-[10px] italic">
                         Position was automatically abandoned due to no action taken.
                       </div>
                     )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Persistent Bottom Banner */}
      <div className="shrink-0 bg-terminal-amber/10 border-t border-terminal-amber/30 p-2 text-center text-[10px] text-terminal-amber/80 font-bold tracking-wide">
        AI CAN MAKE MISTAKES AND THE USER TAKES ALL RESPONSIBILITY FOR ANY ACTIONS TAKEN USING THE AI'S ADVICE/RECOMMENDATIONS.
      </div>
    </div>
  );
}

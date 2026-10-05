'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import { activeSymbolAtom, tickDataAtom, authAtom, layoutToastAtom } from '@/store/terminalStore';
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

function ActionButton({
  onClick,
  loading,
  disabled,
  label,
  title,
  icon,
}: {
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
  label: string;
  title?: string;
  icon?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      title={title}
      className={cn(
        'px-2 py-1 text-[10px] font-mono uppercase tracking-wider transition-all border flex items-center gap-1.5 rounded-sm select-none',
        disabled || loading
          ? 'opacity-40 cursor-not-allowed border-zinc-800 bg-zinc-950 text-white/40'
          : 'border-terminal-amber/40 bg-terminal-amber/10 text-terminal-amber hover:bg-terminal-amber hover:text-black hover:border-terminal-amber active:scale-[0.96] shadow-[0_0_6px_rgba(255,182,0,0.1)]'
      )}
    >
      {loading ? (
        <span className="inline-block w-2.5 h-2.5 border border-current border-t-transparent rounded-full animate-spin" />
      ) : (
        icon
      )}
      <span>{label}</span>
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

export function AiPicksWidget({ panelId: _panelId }: { panelId?: string }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'PICKS' | 'ACTIVE' | 'HISTORY' | 'ABANDONED'>('PICKS');
  const [selectedPickId, setSelectedPickId] = useState<number | null>(null);
  const [showDisclaimer, setShowDisclaimer] = useState(true);
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [tickData, setTickData] = useAtom(tickDataAtom);
  const auth = useAtomValue(authAtom);
  const setLayoutToast = useSetAtom(layoutToastAtom);
  const [triggeringMode, setTriggeringMode] = useState<'hunter' | 'verifier' | null>(null);

  // Poll background job statuses to track running state & granular progress
  interface JobStatusData {
    job_key: string;
    name: string;
    status: string;
    progress_percent: number;
    progress_message?: string;
    last_triggered_at?: string;
    last_completed_at?: string;
  }

  const { data: morningJob } = useQuery<JobStatusData>({
    queryKey: ['job-status', 'job.ai_picks_morning'],
    queryFn: async () => {
      const res = await fetch('/api/py/jobs/job.ai_picks_morning');
      if (!res.ok) return null;
      return res.json();
    },
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 1500 : 10000),
  });

  const { data: eveningJob } = useQuery<JobStatusData>({
    queryKey: ['job-status', 'job.ai_picks_evening'],
    queryFn: async () => {
      const res = await fetch('/api/py/jobs/job.ai_picks_evening');
      if (!res.ok) return null;
      return res.json();
    },
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 1500 : 10000),
  });

  const isMorningRunning = morningJob?.status === 'running';
  const isEveningRunning = eveningJob?.status === 'running';
  const isAnyRunning = isMorningRunning || isEveningRunning;
  const activeRunningJob = isMorningRunning ? morningJob : isEveningRunning ? eveningJob : null;
  const activeJobTitle = isMorningRunning ? 'AI Hunter & Verifier (Morning)' : 'AI Evaluator (Evening)';

  // Auto-refresh picks when background run transitions from running to idle/completed
  const prevRunningRef = React.useRef(false);
  React.useEffect(() => {
    if (prevRunningRef.current && !isAnyRunning) {
      queryClient.invalidateQueries({ queryKey: ['ai-picks'] });
    }
    prevRunningRef.current = isAnyRunning;
  }, [isAnyRunning, queryClient]);

  const handleTriggerRun = async (mode: 'hunter' | 'verifier') => {
    if (triggeringMode || isAnyRunning) return;
    setTriggeringMode(mode);

    try {
      const res = await fetch(`/api/py/ai/picks/trigger?mode=${mode}`, {
        method: 'POST',
      });

      const data = await res.json().catch(() => null);

      if (res.status === 403) {
        setLayoutToast({
          visible: true,
          message: 'Permission denied: Admin privileges required to trigger AI runs.',
          type: 'error',
        });
        return;
      }

      if (!res.ok) {
        setLayoutToast({
          visible: true,
          message: data?.detail || data?.message || `Failed to trigger ${mode} run.`,
          type: 'error',
        });
        return;
      }

      if (data?.ok) {
        setLayoutToast({
          visible: true,
          message: data.message || `Successfully triggered ${mode} run.`,
          type: 'success',
        });
        // Immediately refresh job statuses and picks
        queryClient.invalidateQueries({ queryKey: ['job-status'] });
        queryClient.invalidateQueries({ queryKey: ['ai-picks'] });
      } else {
        setLayoutToast({
          visible: true,
          message: data?.message || `Trigger rejected (cooldown active).`,
          type: 'error',
        });
      }
    } catch (err: unknown) {
      const errorMsg = err instanceof Error ? err.message : 'Network error';
      setLayoutToast({
        visible: true,
        message: `Trigger error: ${errorMsg}`,
        type: 'error',
      });
    } finally {
      setTimeout(() => {
        setTriggeringMode(null);
      }, 1500);
    }
  };

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
    refetchInterval: 15000,
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
              AI can make mistakes and the user takes all responsibility for any actions taken using the AI&apos;s advice/recommendations.
            </div>
          </div>
        </div>
      )}

      {/* Header Tabs & Actions */}
      <div className="flex shrink-0 items-center justify-between border-b border-terminal-gray/50 px-1 gap-2 flex-wrap">
        <div className="flex items-center overflow-x-auto">
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

        {auth?.user?.is_admin && (
          <div className="flex items-center gap-1.5 py-1 shrink-0 ml-auto">
            <ActionButton
              onClick={() => handleTriggerRun('hunter')}
              loading={isMorningRunning || triggeringMode === 'hunter'}
              disabled={isAnyRunning || triggeringMode !== null}
              label={isMorningRunning ? 'HUNTER RUNNING...' : 'RUN HUNTER'}
              title="Trigger Hunter (Morning loop) pre-market scan"
              icon={
                <svg className="w-2.5 h-2.5 text-terminal-amber" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clipRule="evenodd" />
                </svg>
              }
            />
            <ActionButton
              onClick={() => handleTriggerRun('verifier')}
              loading={isEveningRunning || triggeringMode === 'verifier'}
              disabled={isAnyRunning || triggeringMode !== null}
              label={isEveningRunning ? 'VERIFIER RUNNING...' : 'RUN VERIFIER'}
              title="Trigger Verifier / Evaluator (Evening loop) review"
              icon={
                <svg className="w-2.5 h-2.5 text-terminal-amber" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              }
            />
          </div>
        )}
      </div>

      {/* Sleek Cyberpunk Live Progress Bar Banner */}
      {isAnyRunning && activeRunningJob && (
        <div className="shrink-0 bg-zinc-950 border-b border-terminal-amber/30 px-3 py-2 transition-all duration-300">
          <div className="flex items-center justify-between text-[11px] mb-1.5">
            <div className="flex items-center gap-2 min-w-0">
              <span className="flex h-2 w-2 relative shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-terminal-amber opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-terminal-amber" />
              </span>
              <span className="font-bold text-terminal-amber tracking-wider uppercase text-[10px] shrink-0">
                {activeJobTitle}
              </span>
              <span className="text-white/30 text-[10px] hidden sm:inline">|</span>
              <span className="text-white/80 text-[10px] truncate">
                {activeRunningJob.progress_message || 'Executing agent loop...'}
              </span>
            </div>
            <div className="flex items-center gap-2 font-mono text-[10px] text-terminal-amber font-bold shrink-0 ml-2">
              <span>{activeRunningJob.progress_percent || 0}%</span>
            </div>
          </div>

          {/* Progress Track */}
          <div className="w-full bg-zinc-900 h-1.5 rounded-full overflow-hidden border border-zinc-800">
            <div
              className="bg-gradient-to-r from-amber-600 via-terminal-amber to-amber-300 h-full transition-all duration-500 rounded-full shadow-[0_0_8px_rgba(255,182,0,0.4)]"
              style={{ width: `${Math.max(activeRunningJob.progress_percent || 5, 5)}%` }}
            />
          </div>
        </div>
      )}

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

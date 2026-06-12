'use client';

import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom } from '@/store/terminalStore';

interface PickNote {
  timestamp: string;
  note: string;
  model: string;
}

interface AIPick {
  id: number;
  symbol: string;
  direction: 'LONG' | 'SHORT';
  entry_price: number;
  take_profit: number;
  stop_loss: number;
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
      className={`px-2 py-0.5 text-[10px] font-mono uppercase transition-colors ${
        active
          ? 'bg-terminal-amber text-black font-semibold'
          : 'text-white/50 hover:text-white hover:bg-zinc-800'
      }`}
    >
      {label}
    </button>
  );
}

export function AiPicksWidget({ panelId }: { panelId: string }) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'ACTIVE' | 'HISTORY'>('ACTIVE');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data: picks, isLoading, error } = useQuery<AIPick[]>({
    queryKey: ['ai-picks'],
    queryFn: async () => {
      const res = await fetch('/api/py/ai/picks');
      if (!res.ok) throw new Error('Failed to fetch AI Picks');
      return res.json();
    },
    refetchInterval: 60000,
  });

  const updateStatusMutation = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: string }) => {
      const res = await fetch(`/api/py/ai/picks/${id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
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

  const filteredPicks = picks?.filter((p) =>
    activeTab === 'ACTIVE'
      ? ['NEW', 'ACTED_ON'].includes(p.status)
      : ['CLOSED', 'ABANDONED'].includes(p.status)
  ) || [];

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-terminal-bg font-mono text-xs text-white/80">
      {/* Header Tabs */}
      <div className="flex shrink-0 items-center border-b border-terminal-gray/30 px-3 py-1 gap-3 bg-terminal-bg">
        <span className="text-terminal-amber font-bold text-[11px] uppercase shrink-0">PICKS</span>
        <div className="flex items-center gap-1">
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
        </div>
      </div>

      {/* Picks List */}
      <div className="flex-1 overflow-y-auto min-h-0 p-2">
        {filteredPicks.length === 0 ? (
          <div className="text-center text-white/50 py-4 font-bold">NO {activeTab} PICKS</div>
        ) : (
          filteredPicks.map((pick) => {
            const isExpanded = expandedId === pick.id;
            return (
              <div key={pick.id} className="border border-terminal-gray/50 mb-1 overflow-hidden">
                {/* Header Row (Accordion Button) */}
                <button 
                  type="button"
                  onClick={() => setExpandedId(isExpanded ? null : pick.id)}
                  className="w-full flex items-center justify-between px-2 py-1.5 bg-zinc-900 hover:bg-zinc-800 text-left transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="font-bold text-terminal-amber text-[11px] uppercase tracking-wider">{pick.symbol}</span>
                    <span className={cn(
                      'px-1.5 py-0.5 text-[9px] rounded-sm font-bold uppercase tracking-wider',
                      pick.direction === 'LONG' ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400'
                    )}>
                      {pick.direction}
                    </span>
                    <span className="text-[9px] uppercase text-white/50 border border-terminal-gray px-1">
                      {pick.status}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-3 text-[10px] text-white/60 font-mono">
                    <span>E:<span className="text-white ml-1">{pick.entry_price}</span></span>
                    <span>TP:<span className="text-terminal-green ml-1">{pick.take_profit}</span></span>
                    <span>SL:<span className="text-terminal-red ml-1">{pick.stop_loss}</span></span>
                    <span className="text-white/50 text-[10px] w-4 text-right">
                      {isExpanded ? '▾' : '▸'}
                    </span>
                  </div>
                </button>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="bg-black p-2 border-t border-terminal-gray/50 flex flex-col gap-2">
                    <div className="text-terminal-amber mb-1 font-bold text-[10px] uppercase">TIMELINE</div>
                    <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                      {pick.notes.map((n, i) => (
                        <div key={i} className="flex flex-col gap-1 bg-zinc-900/80 p-2 rounded-sm border border-terminal-gray/30">
                          <div className="flex justify-between text-[10px] text-white/40">
                            <span>{new Date(n.timestamp).toLocaleString()}</span>
                            <span className="text-terminal-amber/60">{n.model}</span>
                          </div>
                          <div className="text-white/80 text-[11px] leading-relaxed whitespace-pre-wrap">
                            {n.note}
                          </div>
                        </div>
                      ))}
                    </div>
                    
                    {/* Actions */}
                    {activeTab === 'ACTIVE' && (
                      <div className="flex mt-2">
                        {pick.status === 'NEW' ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); updateStatusMutation.mutate({ id: pick.id, status: 'ACTED_ON' }); }}
                            className="bg-terminal-amber/10 border border-terminal-amber text-terminal-amber px-3 py-1 text-[10px] hover:bg-terminal-amber/20 transition-colors font-bold uppercase tracking-wider"
                          >
                            [ MARK ACTED ON ]
                          </button>
                        ) : pick.status === 'ACTED_ON' ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); updateStatusMutation.mutate({ id: pick.id, status: 'CLOSED' }); }}
                            className="bg-red-900/20 border border-red-500/50 text-red-400 px-3 py-1 text-[10px] hover:bg-red-900/40 transition-colors font-bold uppercase tracking-wider"
                          >
                            [ CLOSE POSITION ]
                          </button>
                        ) : null}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

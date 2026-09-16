'use client';

import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom';
import { cn } from '@/lib/utils';

export interface PickNote {
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

export interface AIPick {
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

interface AiPickModalProps {
  pick: AIPick;
  onClose: () => void;
  currentLivePrice?: number;
  onSelectSymbol?: (symbol: string) => void;
  isAdmin?: boolean;
  onUpdateStatus?: (params: { id: number; status: string; exit_price?: number }) => void;
}

export function AiPickModal({
  pick,
  onClose,
  currentLivePrice,
  onSelectSymbol,
  isAdmin = false,
  onUpdateStatus,
}: AiPickModalProps) {
  const [mounted, setMounted] = useState(false);
  const [animateIn, setAnimateIn] = useState(false);

  useEffect(() => {
    setMounted(true);
    // Request an animation frame to trigger the enter transition smoothly
    const timer = setTimeout(() => setAnimateIn(true), 10);
    return () => clearTimeout(timer);
  }, []);

  // Keyboard escape listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  if (!mounted) return null;

  const isClosed = pick.status === 'CLOSED';
  const referencePrice = isClosed ? pick.exit_price : currentLivePrice;

  let pnlDisplay = '-';
  let pnlColor = 'text-white/50';
  let pnlPctVal: number | null = null;
  if (referencePrice && pick.entry_price) {
    pnlPctVal = ((referencePrice - pick.entry_price) / pick.entry_price) * 100;
    pnlDisplay = `${pnlPctVal > 0 ? '+' : ''}${pnlPctVal.toFixed(2)}%`;
    pnlColor = pnlPctVal > 0 ? 'text-terminal-green' : 'text-terminal-red';
  }

  const formattedDate = pick.created_at
    ? new Date(pick.created_at).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '';

  const modalContent = (
    <div
      className={cn(
        'fixed inset-0 z-[9999] flex items-center justify-center p-3 sm:p-6 bg-black/80 backdrop-blur-sm transition-opacity duration-200 ease-out',
        animateIn ? 'opacity-100' : 'opacity-0'
      )}
      onClick={onClose}
    >
      <div
        className={cn(
          'relative flex flex-col w-full max-w-2xl max-h-[88vh] bg-zinc-950 border border-terminal-amber/50 rounded-lg shadow-[0_0_24px_rgba(255,182,0,0.12),0_12px_40px_rgba(0,0,0,0.8)] overflow-hidden font-mono transition-transform duration-200 ease-out',
          animateIn ? 'translate-y-0 scale-100' : 'translate-y-3 scale-[0.98]'
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Decorative Top Cyberpunk Scanline */}
        <div className="h-0.5 w-full bg-gradient-to-r from-transparent via-terminal-amber to-transparent opacity-80 shrink-0" />

        {/* Modal Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-terminal-gray/60 px-4 py-3 bg-zinc-900/60">
          <div className="flex items-center gap-3">
            <button
              onClick={() => onSelectSymbol?.(pick.symbol)}
              title="View in chart"
              className="text-lg font-bold text-terminal-amber hover:text-white tracking-wide transition-colors active:scale-[0.96] flex items-center gap-1.5"
            >
              <span>{pick.symbol}</span>
              <span className="text-[10px] px-1 py-0.5 border border-terminal-amber/40 rounded text-terminal-amber/80 font-normal">
                NSE
              </span>
            </button>

            <span
              className={cn(
                'px-2 py-0.5 text-xs rounded-sm font-bold border',
                pick.direction === 'LONG'
                  ? 'bg-green-950/60 text-green-400 border-green-700/60'
                  : 'bg-red-950/60 text-red-400 border-red-700/60'
              )}
            >
              {pick.direction}
            </span>

            <span className="text-[11px] uppercase tracking-wider text-white/50 border border-terminal-gray px-1.5 py-0.5 rounded-sm">
              {pick.status}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {pnlPctVal !== null && (
              <div className="flex items-center gap-1.5 bg-black/50 px-2.5 py-1 rounded border border-terminal-gray/40 text-xs">
                <span className="text-white/40 text-[10px]">LIVE PNL:</span>
                <span className={cn('font-bold font-mono', pnlColor)}>{pnlDisplay}</span>
              </div>
            )}
            <button
              onClick={onClose}
              className="w-7 h-7 flex items-center justify-center rounded border border-terminal-gray/60 text-white/60 hover:text-white hover:border-terminal-amber/80 hover:bg-zinc-800 transition-colors active:scale-[0.96]"
              aria-label="Close modal"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Key Metrics Banner */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 px-4 py-2.5 bg-black/40 border-b border-terminal-gray/40 text-[11px] shrink-0">
          <div className="flex flex-col">
            <span className="text-white/40 text-[9px] uppercase tracking-wider">Entry Price</span>
            <span className="text-white font-bold text-xs">{pick.entry_price.toFixed(2)}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-white/40 text-[9px] uppercase tracking-wider">Take Profit</span>
            <span className="text-terminal-green font-bold text-xs">{pick.take_profit.toFixed(2)}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-white/40 text-[9px] uppercase tracking-wider">Stop Loss</span>
            <span className="text-terminal-red font-bold text-xs">{pick.stop_loss.toFixed(2)}</span>
          </div>
          <div className="flex flex-col">
            <span className="text-white/40 text-[9px] uppercase tracking-wider">
              {isClosed ? 'Exit Price' : 'Current LTP'}
            </span>
            <span className="text-terminal-amber font-bold text-xs">
              {referencePrice ? referencePrice.toFixed(2) : '-'}
            </span>
          </div>
        </div>

        {/* Scrollable Timeline Content */}
        <div className="flex-1 overflow-y-auto min-h-0 p-4 space-y-4">
          <div className="flex items-center justify-between text-[11px] pb-1 border-b border-terminal-gray/40">
            <div className="text-terminal-amber font-bold uppercase tracking-wider flex items-center gap-1.5">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-terminal-amber animate-pulse" />
              INTELLIGENCE TIMELINE ({pick.notes.length})
            </div>
            {formattedDate && (
              <span className="text-white/40 text-[10px]">{formattedDate}</span>
            )}
          </div>

          <div className="relative pl-4 sm:pl-6 border-l-2 border-terminal-amber/20 space-y-5 my-2">
            {pick.notes.map((n, i) => {
              const isMarketContext = n.model === 'market-context';
              const noteDate = n.timestamp
                ? new Date(n.timestamp).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false,
                  })
                : '';

              if (isMarketContext) {
                return (
                  <div key={i} className="relative group">
                    {/* Timeline Node Icon */}
                    <div className="absolute -left-[21px] sm:-left-[29px] top-1.5 w-3 h-3 rounded-full bg-zinc-950 border-2 border-terminal-amber/60 flex items-center justify-center" />
                    
                    <details className="bg-zinc-900/40 rounded border border-terminal-gray/50 overflow-hidden group/ctx">
                      <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-xs text-white/60 hover:text-white/90 hover:bg-zinc-800/40 transition-colors">
                        <div className="flex items-center gap-2">
                          <span className="text-terminal-amber font-bold text-[11px] tracking-wide">
                            🌐 MARKET CONTEXT
                          </span>
                          <span className="text-white/40 text-[10px]">{new Date(n.timestamp).toLocaleString()}</span>
                        </div>
                        <span className="text-terminal-amber/70 group-open/ctx:rotate-180 transition-transform duration-150 text-xs">
                          ▾
                        </span>
                      </summary>
                      <div className="px-3.5 py-3 text-white/80 text-xs leading-relaxed border-t border-terminal-gray/30 whitespace-pre-wrap bg-black/30 font-mono">
                        {n.note}
                      </div>
                    </details>
                  </div>
                );
              }

              return (
                <div key={i} className="relative">
                  {/* Timeline Node Icon */}
                  <div className="absolute -left-[21px] sm:-left-[29px] top-2 w-3 h-3 rounded-full bg-terminal-amber/80 border-2 border-zinc-950" />

                  <div className="flex flex-col bg-zinc-900/70 p-3.5 rounded border border-terminal-gray/60 shadow-sm gap-2">
                    <div className="flex items-center justify-between text-[11px] border-b border-terminal-gray/30 pb-1.5">
                      <span className="text-white/40 font-mono">
                        {new Date(n.timestamp).toLocaleDateString()} {noteDate}
                      </span>
                      <div className="flex items-center gap-2">
                        {n.verdict && (
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-terminal-amber/20 text-terminal-amber border border-terminal-amber/40 uppercase">
                            {n.verdict}
                          </span>
                        )}
                        <span className="text-terminal-amber/80 text-[10px] tracking-wide uppercase px-1.5 py-0.5 bg-black/40 rounded border border-terminal-gray/40">
                          {n.model}
                        </span>
                      </div>
                    </div>

                    <div className="text-white/90 text-xs sm:text-sm leading-relaxed whitespace-pre-wrap font-mono">
                      {n.note}
                    </div>

                    {(n.technical || n.fundamental || n.catalyst || n.risk) && (
                      <div className="mt-2 pt-2 border-t border-terminal-gray/40 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                        {n.technical && (
                          <div className="p-2 bg-black/40 rounded border border-terminal-gray/30">
                            <span className="text-terminal-blue font-bold uppercase text-[10px] block mb-0.5">
                              TECH ANALYSIS:
                            </span>
                            <span className="text-white/80 text-[11px] leading-snug">{n.technical}</span>
                          </div>
                        )}
                        {n.fundamental && (
                          <div className="p-2 bg-black/40 rounded border border-terminal-gray/30">
                            <span className="text-purple-400 font-bold uppercase text-[10px] block mb-0.5">
                              FUNDAMENTAL:
                            </span>
                            <span className="text-white/80 text-[11px] leading-snug">{n.fundamental}</span>
                          </div>
                        )}
                        {n.catalyst && (
                          <div className="p-2 bg-black/40 rounded border border-terminal-gray/30">
                            <span className="text-terminal-amber font-bold uppercase text-[10px] block mb-0.5">
                              CATALYST:
                            </span>
                            <span className="text-white/80 text-[11px] leading-snug">{n.catalyst}</span>
                          </div>
                        )}
                        {n.risk && (
                          <div className="p-2 bg-black/40 rounded border border-terminal-gray/30">
                            <span className="text-terminal-red font-bold uppercase text-[10px] block mb-0.5">
                              RISK FACTOR:
                            </span>
                            <span className="text-white/80 text-[11px] leading-snug">{n.risk}</span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Modal Sticky Footer / Actions */}
        <div className="shrink-0 flex items-center justify-between border-t border-terminal-gray/60 px-4 py-3 bg-zinc-900/80">
          <div className="text-[10px] text-white/40 tracking-wider">
            ESC OR CLICK OUTSIDE TO CLOSE
          </div>

          <div className="flex items-center gap-2">
            {pick.status === 'NEW' && isAdmin && onUpdateStatus && (
              <button
                onClick={() => {
                  onUpdateStatus({ id: pick.id, status: 'ACTED_ON' });
                  onClose();
                }}
                className="bg-terminal-amber/15 border border-terminal-amber text-terminal-amber px-3.5 py-1.5 text-xs hover:bg-terminal-amber hover:text-black transition-colors duration-150 font-bold uppercase tracking-wider rounded active:scale-[0.96]"
              >
                [ MARK ACTED ON ]
              </button>
            )}

            {pick.status === 'ACTED_ON' && isAdmin && onUpdateStatus && (
              <button
                onClick={() => {
                  onUpdateStatus({
                    id: pick.id,
                    status: 'CLOSED',
                    exit_price: currentLivePrice,
                  });
                  onClose();
                }}
                className="bg-red-950/40 border border-red-500/80 text-red-400 px-3.5 py-1.5 text-xs hover:bg-red-600 hover:text-white transition-colors duration-150 font-bold uppercase tracking-wider rounded active:scale-[0.96]"
              >
                [ CLOSE POSITION ]
              </button>
            )}

            <button
              onClick={onClose}
              className="bg-zinc-800 hover:bg-zinc-700 text-white/80 border border-terminal-gray px-3.5 py-1.5 text-xs font-bold uppercase tracking-wider rounded transition-colors duration-150 active:scale-[0.96]"
            >
              DISMISS
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return ReactDOM.createPortal(modalContent, document.body);
}

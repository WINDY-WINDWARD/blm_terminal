'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import type { Watchlist } from '@/store/terminalStore';

// ─── Types ────────────────────────────────────────────────────────────────────

interface WatchlistItem {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
}

interface IndividualStats {
  annual_return: number;
  annual_volatility: number;
  sharpe: number;
}

interface OptimizeResult {
  weights: Record<string, number>;
  expected_annual_return: number;
  expected_annual_volatility: number;
  sharpe_ratio: number;
  correlation_matrix: Record<string, Record<string, number>>;
  individual_stats: Record<string, IndividualStats>;
  period_used: string;
  objective_used: string;
  symbols_used: string[];
  symbols_failed: string[];
  computed_at: string;
}

interface WatchlistPreviewItem {
  symbol: string;
  annual_return_1y: number | null;
  annual_volatility_1y: number | null;
  current_price: number | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function corrColor(val: number): string {
  if (val === 1) return '#1e3a5f';
  const abs = Math.abs(val);
  const hue = val < 0 ? 120 : 0;
  return `hsl(${hue}, ${Math.round(abs * 70)}%, ${Math.round(20 + (1 - abs) * 15)}%)`;
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function PortfolioWidget() {
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<number>(1);
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set());
  const [period, setPeriod] = useState<'1y' | '2y' | '3y'>('2y');
  const [objective, setObjective] = useState<'max_sharpe' | 'min_volatility' | 'risk_parity'>('max_sharpe');

  // Fetch available watchlists
  const { data: watchlists = [] } = useQuery<Watchlist[]>({
    queryKey: ['watchlists'],
    queryFn: async () => {
      const res = await fetch('/api/watchlists');
      if (!res.ok) throw new Error('Failed to fetch watchlists');
      return res.json();
    },
  });

  // Fetch items for the selected watchlist
  const { data: watchlistItems = [] } = useQuery<WatchlistItem[]>({
    queryKey: ['watchlist', selectedWatchlistId],
    queryFn: async () => {
      const res = await fetch(`/api/watchlist?watchlist_id=${selectedWatchlistId}`);
      if (!res.ok) throw new Error('Failed to fetch watchlist');
      return res.json();
    },
  });

  const watchlistSymbols = useMemo(() => {
    const syms = watchlistItems.map((i) => i.symbol);
    return [...new Set(syms)];
  }, [watchlistItems]);

  // Clear selected symbols when switching watchlists
  useEffect(() => {
    setSelectedSymbols(new Set());
  }, [selectedWatchlistId]);

  const previewSymbolsParam = useMemo(() => watchlistSymbols.join(','), [watchlistSymbols]);

  const { data: previewData = [] } = useQuery<WatchlistPreviewItem[]>({
    queryKey: ['portfolio-preview', previewSymbolsParam],
    queryFn: async () => {
      if (!previewSymbolsParam) return [];
      const res = await fetch(`/api/py/portfolio/watchlist-preview?symbols=${encodeURIComponent(previewSymbolsParam)}`);
      if (!res.ok) throw new Error('Preview fetch failed');
      return res.json();
    },
    enabled: previewSymbolsParam.length > 0,
    staleTime: 1000 * 60 * 15,
  });

  const previewMap = useMemo(() => {
    const map: Record<string, WatchlistPreviewItem> = {};
    for (const item of previewData) map[item.symbol] = item;
    return map;
  }, [previewData]);

  const { mutate: runOptimize, data: result, isPending: isOptimizing } = useMutation<OptimizeResult, Error>({
    mutationFn: async () => {
      const symbols = Array.from(selectedSymbols);
      const res = await fetch('/api/py/portfolio/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols, period, objective, risk_free_rate: 0.065 }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || 'Optimization failed');
      }
      return res.json();
    },
  });

  const toggleSymbol = (sym: string) => {
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  };

  const selectAll = () => setSelectedSymbols(new Set(watchlistSymbols));
  const clearAll = () => setSelectedSymbols(new Set());
  const canOptimize = selectedSymbols.size >= 3;

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-terminal-bg overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">Portfolio Optimizer</span>
        <span className="text-white/40 text-[10px]">MPT via PyPortfolioOpt</span>
      </div>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Left: Selection */}
        <div className="w-52 shrink-0 border-r border-terminal-gray flex flex-col overflow-hidden">
          {/* Watchlist selector */}
          <div className="px-2 py-1 border-b border-terminal-gray/30">
            <select
              value={selectedWatchlistId}
              onChange={(e) => setSelectedWatchlistId(Number(e.target.value))}
              className="bg-terminal-bg border border-terminal-gray/40 text-white/70 text-[10px] rounded px-1 py-0.5 w-full"
            >
              {watchlists.map((wl) => (
                <option key={wl.id} value={wl.id}>
                  {wl.name} ({wl.item_count ?? 0})
                </option>
              ))}
              {watchlists.length === 0 && <option value={1}>Default</option>}
            </select>
          </div>

          <div className="flex items-center justify-between px-2 py-1 border-b border-terminal-gray/30">
            <span className="text-[10px] text-white/40 uppercase tracking-wider">Stocks</span>
            <div className="flex gap-1">
              <button onClick={selectAll} className="text-[9px] text-blue-400/60 hover:text-blue-400 transition-colors">All</button>
              <span className="text-white/10">|</span>
              <button onClick={clearAll} className="text-[9px] text-white/30 hover:text-white/60 transition-colors">None</button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-2 py-1 space-y-0.5">
            {watchlistSymbols.length === 0 && (
              <div className="text-[10px] text-white/20 text-center py-4">No watchlist items</div>
            )}
            {watchlistSymbols.map((sym) => {
              const checked = selectedSymbols.has(sym);
              const preview = previewMap[sym];
              return (
                <label
                  key={sym}
                  className={cn(
                    'flex items-center gap-1.5 px-1 py-0.5 rounded cursor-pointer transition-colors',
                    checked ? 'bg-blue-500/10' : 'hover:bg-white/5'
                  )}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleSymbol(sym)}
                    className="accent-blue-400 w-3 h-3"
                  />
                  <span className={cn('text-[10px] font-medium', checked ? 'text-blue-300' : 'text-white/60')}>
                    {sym}
                  </span>
                  {preview?.annual_return_1y != null && (
                    <span className={cn('text-[9px] ml-auto', preview.annual_return_1y >= 0 ? 'text-green-400/70' : 'text-red-400/70')}>
                      {preview.annual_return_1y >= 0 ? '+' : ''}{preview.annual_return_1y.toFixed(1)}%
                    </span>
                  )}
                </label>
              );
            })}
          </div>

          {/* Controls */}
          <div className="border-t border-terminal-gray/30 px-2 py-1.5 space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-white/40 w-14">Period</span>
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value as '1y' | '2y' | '3y')}
                className="bg-terminal-bg border border-terminal-gray/40 text-white/70 text-[10px] rounded px-1 py-0.5 flex-1"
              >
                <option value="1y">1 Year</option>
                <option value="2y">2 Years</option>
                <option value="3y">3 Years</option>
              </select>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] text-white/40 w-14">Objective</span>
              <select
                value={objective}
                onChange={(e) => setObjective(e.target.value as 'max_sharpe' | 'min_volatility' | 'risk_parity')}
                className="bg-terminal-bg border border-terminal-gray/40 text-white/70 text-[10px] rounded px-1 py-0.5 flex-1"
              >
                <option value="max_sharpe">Max Sharpe</option>
                <option value="min_volatility">Min Volatility</option>
                <option value="risk_parity">Risk Parity</option>
              </select>
            </div>
            <button
              onClick={() => runOptimize()}
              disabled={!canOptimize || isOptimizing}
              className={cn(
                'w-full text-[10px] font-medium py-1 rounded border transition-colors',
                canOptimize && !isOptimizing
                  ? 'border-blue-400/50 text-blue-300 hover:bg-blue-500/10'
                  : 'border-white/10 text-white/20 cursor-not-allowed'
              )}
            >
              {isOptimizing ? 'Optimizing…' : `Optimize (${selectedSymbols.size})`}
            </button>
            {!canOptimize && selectedSymbols.size > 0 && (
              <div className="text-[9px] text-red-400/60 text-center">Select at least 3 stocks</div>
            )}
          </div>
        </div>

        {/* Right: Results */}
        <div className="flex-1 overflow-y-auto px-3 py-2 min-w-0">
          {!result ? (
            <div className="h-full flex flex-col items-center justify-center gap-2 text-white/20 text-[11px]">
              <span className="text-2xl opacity-20">◈</span>
              <span>Select stocks and click Optimize</span>
              <span className="text-[10px] opacity-60">Minimum 3 symbols required</span>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {/* Portfolio Stats */}
              <div className="flex gap-4">
                <div className="flex flex-col">
                  <span className="text-[9px] text-white/40 uppercase tracking-wider">Expected Return</span>
                  <span className="text-terminal-amber font-bold text-sm">{(result.expected_annual_return * 100).toFixed(1)}%</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[9px] text-white/40 uppercase tracking-wider">Volatility</span>
                  <span className="text-terminal-amber font-bold text-sm">{(result.expected_annual_volatility * 100).toFixed(1)}%</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[9px] text-white/40 uppercase tracking-wider">Sharpe Ratio</span>
                  <span className="text-terminal-amber font-bold text-sm">{result.sharpe_ratio.toFixed(2)}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[9px] text-white/40 uppercase tracking-wider">Period</span>
                  <span className="text-white/60 text-sm">{result.period_used}</span>
                </div>
              </div>

              {/* Weights */}
              <div>
                <div className="text-[9px] text-white/40 uppercase tracking-wider mb-1.5">
                  Optimal Weights
                </div>
                <div className="space-y-1">
                  {Object.entries(result.weights)
                    .sort(([, a], [, b]) => b - a)
                    .map(([sym, w]) => (
                      <div key={sym} className="flex items-center gap-2 text-[11px]">
                        <span className="w-16 text-white/60 text-right">{sym}</span>
                        <div className="flex-1 bg-white/5 rounded-full h-2">
                          <div className="bg-blue-400 h-2 rounded-full" style={{ width: `${(w * 100).toFixed(1)}%` }} />
                        </div>
                        <span className="w-10 text-white/80">{(w * 100).toFixed(1)}%</span>
                      </div>
                    ))}
                </div>
              </div>

              {/* Correlation Heatmap */}
              {result.symbols_used.length > 0 && (
                <div>
                  <div className="text-[9px] text-white/40 uppercase tracking-wider mb-1.5">
                    Correlation Matrix
                  </div>
                  <div className="overflow-x-auto">
                    <div className="inline-grid" style={{ gridTemplateColumns: `repeat(${result.symbols_used.length + 1}, minmax(40px, 1fr))` }}>
                      {/* Header row */}
                      <div className="text-[9px] text-white/20 p-1" />
                      {result.symbols_used.map((sym) => (
                        <div key={sym} className="text-[9px] text-white/40 text-center p-1">{sym}</div>
                      ))}
                      {/* Data rows */}
                      {result.symbols_used.map((rowSym) => (
                        <React.Fragment key={rowSym}>
                          <div className="text-[9px] text-white/40 text-right p-1">{rowSym}</div>
                          {result.symbols_used.map((colSym) => {
                            const val = result.correlation_matrix[rowSym]?.[colSym] ?? 0;
                            return (
                              <div
                                key={colSym}
                                className="text-[9px] text-center p-1 rounded-sm"
                                style={{ backgroundColor: corrColor(val), color: Math.abs(val) > 0.5 ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.4)' }}
                                title={`${rowSym} vs ${colSym}: ${val.toFixed(3)}`}
                              >
                                {val.toFixed(2)}
                              </div>
                            );
                          })}
                        </React.Fragment>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Individual Stats */}
              <div>
                <div className="text-[9px] text-white/40 uppercase tracking-wider mb-1.5">
                  Per-Symbol Statistics
                </div>
                <table className="w-full text-[10px] border-collapse">
                  <thead>
                    <tr className="text-white/30 text-left">
                      <th className="pb-1">Symbol</th>
                      <th className="pb-1 text-right">Ann Return</th>
                      <th className="pb-1 text-right">Ann Vol</th>
                      <th className="pb-1 text-right">Sharpe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.symbols_used.map((sym) => {
                      const stats = result.individual_stats[sym];
                      if (!stats) return null;
                      return (
                        <tr key={sym} className="border-t border-white/5">
                          <td className="py-1 text-white/60">{sym}</td>
                          <td className="py-1 text-right text-white/80">{(stats.annual_return * 100).toFixed(1)}%</td>
                          <td className="py-1 text-right text-white/80">{(stats.annual_volatility * 100).toFixed(1)}%</td>
                          <td className="py-1 text-right text-white/80">{stats.sharpe.toFixed(2)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Failed symbols */}
              {result.symbols_failed.length > 0 && (
                <div className="text-[9px] text-red-400/60">
                  Failed to fetch data for: {result.symbols_failed.join(', ')}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

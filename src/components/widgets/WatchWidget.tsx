'use client';

import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAtom, useSetAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, tickDataAtom } from '@/store/terminalStore';
import { wsService } from '@/lib/socket';
import type { TickData } from '@/lib/socket';

interface WatchlistItem {
  id: number;
  symbol: string;
  exchange: string;
}

interface ChangeRanges {
  oneDayPercent: number | null;
  oneWeekPercent: number | null;
  oneMonthPercent: number | null;
  threeMonthPercent: number | null;
  sixMonthPercent: number | null;
  oneYearPercent: number | null;
  twoYearPercent: number | null;
  threeYearPercent: number | null;
  fiveYearPercent: number | null;
}

async function fetchWatchlist(): Promise<WatchlistItem[]> {
  const res = await fetch('/api/watchlist');
  if (!res.ok) throw new Error('Failed to fetch watchlist');
  return res.json() as Promise<WatchlistItem[]>;
}

async function addSymbol(symbol: string, exchange: string): Promise<WatchlistItem> {
  const res = await fetch('/api/watchlist', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, exchange }),
  });
  if (!res.ok) throw new Error('Failed to add symbol');
  return res.json() as Promise<WatchlistItem>;
}

async function removeSymbol(id: number): Promise<void> {
  const res = await fetch(`/api/watchlist?id=${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to remove symbol');
}

function useChangeRanges(symbol: string) {
  return useQuery({
    queryKey: ['market/change-ranges', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/market/change-ranges/${encodeURIComponent(symbol)}`);
      if (!res.ok) return null;
      return res.json() as Promise<ChangeRanges>;
    },
    staleTime: 300_000,
    enabled: !!symbol,
  });
}

function formatRange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-terminal-gray">—</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green' : 'text-terminal-red'}>
      {isUp ? '+' : ''}{val.toFixed(1)}%
    </span>
  );
}

export function WatchWidget() {
  const qc = useQueryClient();
  const [activeSymbol, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [activeExchange, setActiveExchange] = useAtom(activeExchangeAtom);
  const [tickData, setTickData] = useAtom(tickDataAtom);

  const [newSymbol, setNewSymbol] = useState('');
  const [newExchange, setNewExchange] = useState('NSE');

  const { data: watchlist = [], isLoading, isError } = useQuery({
    queryKey: ['watchlist'],
    queryFn: fetchWatchlist,
    staleTime: Infinity,
  });

  const addMutation = useMutation({
    mutationFn: ({ symbol, exchange }: { symbol: string; exchange: string }) =>
      addSymbol(symbol, exchange),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['watchlist'] });
      setNewSymbol('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => removeSymbol(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['watchlist'] }),
  });

  // Subscribe to WS mode 2 for all watchlist symbols
  useEffect(() => {
    if (!watchlist.length) return;
    for (const item of watchlist) {
      wsService.subscribe(item.symbol, item.exchange, 2);
    }
    return () => {
      for (const item of watchlist) {
        wsService.unsubscribe(item.symbol, item.exchange, 2);
      }
    };
  }, [watchlist]);

  // Collect ticks into tickDataAtom
  useEffect(() => {
    const unsub = wsService.onTick((data: TickData) => {
      const key = `${data.symbol}.${data.exchange}`;
      setTickData((prev) => ({ ...prev, [key]: data }));
    });
    return unsub;
  }, [setTickData]);

  const handleRowClick = (item: WatchlistItem) => {
    setActiveSymbol(item.symbol);
    setActiveExchange(item.exchange);
  };

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const s = newSymbol.trim().toUpperCase();
    const ex = newExchange.trim().toUpperCase();
    if (!s || !ex) return;
    addMutation.mutate({ symbol: s, exchange: ex });
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden">
      {/* Add symbol form */}
      <form
        onSubmit={handleAdd}
        className="flex gap-1 p-1 border-b border-terminal-gray flex-shrink-0"
      >
        <input
          type="text"
          value={newExchange}
          onChange={(e) => setNewExchange(e.target.value.toUpperCase())}
          placeholder="NSE"
          className="w-12 bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase text-center"
        />
        <input
          type="text"
          value={newSymbol}
          onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
          placeholder="SYMBOL"
          className="flex-1 bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase"
        />
        <button
          type="submit"
          disabled={addMutation.isPending}
          className="px-2 py-0.5 bg-blue-800 hover:bg-blue-700 text-white border border-blue-500 disabled:opacity-50"
        >
          +ADD
        </button>
      </form>

      {/* Watchlist table */}
      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="p-2 text-terminal-gray">LOADING WATCHLIST...</div>
        )}
        {isError && (
          <div className="p-2 text-terminal-red">FAILED TO LOAD WATCHLIST</div>
        )}
        {!isLoading && !isError && (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead className="bg-blue-900 text-white sticky top-0">
                <tr>
                  <th className="p-1 border border-terminal-gray">SYMBOL</th>
                  <th className="p-1 border border-terminal-gray text-right">LTP</th>
                  <th className="p-1 border border-terminal-gray text-right">CHG%</th>
                  <th className="p-1 border border-terminal-gray text-right">1W%</th>
                  <th className="p-1 border border-terminal-gray text-right">1M%</th>
                  <th className="p-1 border border-terminal-gray text-right">3M%</th>
                  <th className="p-1 border border-terminal-gray text-right">6M%</th>
                  <th className="p-1 border border-terminal-gray text-right">1Y%</th>
                  <th className="p-1 border border-terminal-gray text-right">2Y%</th>
                  <th className="p-1 border border-terminal-gray text-right">3Y%</th>
                  <th className="p-1 border border-terminal-gray text-right">5Y%</th>
                  <th className="p-1 border border-terminal-gray w-6"></th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map((item) => {
                  const key = `${item.symbol}.${item.exchange}`;
                  const tick = tickData[key];
                  const ltp = tick?.ltp;
                  let chgPct = tick?.change_percent;
                  if (chgPct == null && tick && tick.ltp != null && tick.open != null) {
                    chgPct = ((tick.ltp - tick.open) / tick.open) * 100;
                  }
                  const isUp = (chgPct ?? 0) >= 0;
                  const colorClass = isUp ? 'text-terminal-green' : 'text-terminal-red';
                  const isActive =
                    activeSymbol === item.symbol && activeExchange === item.exchange;

                  const { data: ranges, isLoading: rangesLoading } = useChangeRanges(item.symbol);

                  return (
                    <tr
                      key={item.id}
                      onClick={() => handleRowClick(item)}
                      className={`border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer ${
                        isActive ? 'bg-zinc-800' : ''
                      }`}
                    >
                      <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">
                        <span>{item.symbol}</span>
                        <span className="text-terminal-gray text-[9px] ml-1">{item.exchange}</span>
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {ltp != null ? ltp.toFixed(2) : <span className="text-terminal-gray">—</span>}
                      </td>
                      <td className={`p-1 text-right border-r border-terminal-gray ${colorClass}`}>
                        {chgPct != null
                          ? `${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%`
                          : <span className="text-terminal-gray">—</span>}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.oneWeekPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.oneMonthPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.threeMonthPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.sixMonthPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.oneYearPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.twoYearPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.threeYearPercent)}
                      </td>
                      <td className="p-1 text-right border-r border-terminal-gray">
                        {rangesLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.fiveYearPercent)}
                      </td>
                      <td className="p-1 text-center">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            removeMutation.mutate(item.id);
                          }}
                          className="text-terminal-gray hover:text-terminal-red text-[10px]"
                          title="Remove"
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {watchlist.length === 0 && !isLoading && (
                  <tr>
                    <td colSpan={12} className="p-2 text-terminal-gray text-center">
                      No symbols. Add one above.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

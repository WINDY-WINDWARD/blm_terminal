'use client';

import React, { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { symbolPerPanelAtom, exchangePerPanelAtom, focusedPanelAtom, tickDataAtom, topSymbolsAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';

interface TopSymbolRow {
  symbol: string;
  exchange: string;
  ltp: number;
  chgPct: number;
  volume: number;
}

function formatVolume(v: number): string {
  if (v >= 10_000_000) return `${(v / 10_000_000).toFixed(1)}Cr`;
  if (v >= 100_000)    return `${(v / 100_000).toFixed(1)}L`;
  if (v >= 1_000)      return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

export function TopWidget() {
  const [symbolPerPanel, setSymbolPerPanel] = useAtom(symbolPerPanelAtom);
  const [exchangePerPanel, setExchangePerPanel] = useAtom(exchangePerPanelAtom);
  const [focusedPanel] = useAtom(focusedPanelAtom);
  const [tickData] = useAtom(tickDataAtom);
  const [topSymbols, setTopSymbols] = useAtom(topSymbolsAtom);

  // Load top symbols from DB on mount
  const { data: dbSymbols = [] } = useQuery({
    queryKey: ['top-symbols'],
    queryFn: async () => {
      const res = await fetch('/api/top-symbols');
      if (!res.ok) throw new Error('Failed to fetch top symbols');
      return res.json() as Promise<Array<{ id: number; symbol: string; exchange: string }>>;
    },
    staleTime: 60_000,
  });

  // Sync DB symbols into atom
  useEffect(() => {
    setTopSymbols(dbSymbols.map(({ symbol, exchange }) => ({ symbol, exchange })));
  }, [dbSymbols, setTopSymbols]);

  // Fetch live quotes for all top symbols (poll every 5s)
  const { data: quotesMap = {} } = useQuery({
    queryKey: ['top-quotes', topSymbols.map((s) => `${s.symbol}.${s.exchange}`).join(',')],
    queryFn: async () => {
      if (!topSymbols.length) return {};
      const results = await Promise.allSettled(
        topSymbols.map((s) => OpenAlgoClient.getQuote(s.symbol, s.exchange))
      );
      const map: Record<string, { ltp: number; chgPct: number; volume: number }> = {};
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && r.value.data) {
          const key = `${topSymbols[i].symbol}.${topSymbols[i].exchange}`;
          const d = r.value.data;
          const chgPct = d.prev_close > 0
            ? ((d.ltp - d.prev_close) / d.prev_close) * 100
            : 0;
          map[key] = { ltp: d.ltp, chgPct, volume: d.volume };
        }
      });
      return map;
    },
    enabled: topSymbols.length > 0,
    refetchInterval: 5_000,
    staleTime: 4_000,
  });

  // Build rows — merge live WS tick over REST quote
  const rows: TopSymbolRow[] = topSymbols
    .map((s) => {
      const key = `${s.symbol}.${s.exchange}`;
      const tick = tickData[key];
      const quote = quotesMap[key];
      const ltp = tick?.ltp ?? quote?.ltp ?? 0;
      const chgPct = tick?.change_percent ?? quote?.chgPct ?? 0;
      const volume = tick?.volume ?? quote?.volume ?? 0;
      return { symbol: s.symbol, exchange: s.exchange, ltp, chgPct, volume };
    })
    .sort((a, b) => Math.abs(b.chgPct) - Math.abs(a.chgPct));

  const handleRowClick = (row: TopSymbolRow) => {
    setSymbolPerPanel((prev) => ({ ...prev, [focusedPanel]: row.symbol }));
    setExchangePerPanel((prev) => ({ ...prev, [focusedPanel]: row.exchange }));
  };

  if (topSymbols.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-terminal-gray gap-2 p-4">
        <span>No symbols configured.</span>
        <span>Use the SETTINGS widget to add symbols.</span>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
      <table className="w-full text-left border-collapse">
        <thead className="bg-blue-900 text-white sticky top-0">
          <tr>
            <th className="p-1 border border-terminal-gray">SYMBOL</th>
            <th className="p-1 border border-terminal-gray text-right">CHG%</th>
            <th className="p-1 border border-terminal-gray text-right">LTP</th>
            <th className="p-1 border border-terminal-gray text-right">VOL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isUp = row.chgPct >= 0;
            const colorClass = isUp ? 'text-terminal-green' : 'text-terminal-red';
            return (
              <tr
                key={`${row.symbol}.${row.exchange}`}
                onClick={() => handleRowClick(row)}
                className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer"
              >
                <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">
                  <span>{row.symbol}</span>
                  <span className="text-terminal-gray text-[9px] ml-1">{row.exchange}</span>
                </td>
                <td className={`p-1 text-right border-r border-terminal-gray font-bold ${colorClass}`}>
                  {row.chgPct !== 0
                    ? `${isUp ? '+' : ''}${row.chgPct.toFixed(2)}%`
                    : <span className="text-terminal-gray">—</span>}
                </td>
                <td className="p-1 text-right border-r border-terminal-gray">
                  {row.ltp > 0 ? row.ltp.toFixed(2) : <span className="text-terminal-gray">—</span>}
                </td>
                <td className="p-1 text-right text-terminal-gray">
                  {row.volume > 0 ? formatVolume(row.volume) : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

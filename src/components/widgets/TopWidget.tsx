'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom, useSetAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, tickDataAtom, topSymbolsAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';

interface TopSymbolRow {
  symbol: string;
  exchange: string;
  ltp: number;
  chg1d: number;
  chg1w: number | null;
  chg1m: number | null;
  chg3m: number | null;
  chg1y: number | null;
  chg3y: number | null;
  chg5y: number | null;
  volume: number;
}

type SortKey = 'symbol' | 'ltp' | 'chg1d' | 'chg1w' | 'chg1m' | 'chg3m' | 'chg1y' | 'chg3y' | 'chg5y' | 'volume';
type SortDir = 'asc' | 'desc';

function formatVolume(v: number): string {
  if (v >= 10_000_000) return `${(v / 10_000_000).toFixed(1)}Cr`;
  if (v >= 100_000)    return `${(v / 100_000).toFixed(1)}L`;
  if (v >= 1_000)      return `${(v / 1_000).toFixed(0)}K`;
  return String(v);
}

function formatChg(val: number | null): React.ReactNode {
  if (val === null) return <span className="text-zinc-600">—</span>;
  if (val === 0) return <span className="text-zinc-400">0.00%</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green font-bold' : 'text-terminal-red font-bold'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
}

/** Return a date string "YYYY-MM-DD" offset by `days` from today */
function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Compute % change from first bar open to last bar close */
function pctChange(bars: { open: number; close: number }[]): number | null {
  if (!bars.length) return null;
  const start = bars[0].open;
  const end = bars[bars.length - 1].close;
  if (!start) return null;
  return ((end - start) / start) * 100;
}

export function TopWidget() {
  const setActiveSymbol = useSetAtom(activeSymbolAtom);
  const setActiveExchange = useSetAtom(activeExchangeAtom);
  const [tickData] = useAtom(tickDataAtom);
  const [topSymbols, setTopSymbols] = useAtom(topSymbolsAtom);

  const [sortKey, setSortKey] = useState<SortKey>('chg1d');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

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
      const map: Record<string, { ltp: number; chg1d: number; volume: number }> = {};
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && r.value.data) {
          const key = `${topSymbols[i].symbol}.${topSymbols[i].exchange}`;
          const d = r.value.data;
          const chg1d = d.prev_close > 0
            ? ((d.ltp - d.prev_close) / d.prev_close) * 100
            : 0;
          map[key] = { ltp: d.ltp, chg1d, volume: d.volume };
        }
      });
      return map;
    },
    enabled: topSymbols.length > 0,
    refetchInterval: 5_000,
    staleTime: 4_000,
  });

  // Date boundaries
  const today = new Date().toISOString().slice(0, 10);
  const d5y = daysAgo(365 * 5);

  // Fetch 5y of daily bars per symbol once — covers all sub-periods (refresh every 15 min)
  const symbolsKey = topSymbols.map((s) => `${s.symbol}.${s.exchange}`).join(',');

  const { data: histMap = {} } = useQuery({
    queryKey: ['top-hist', symbolsKey, today],
    queryFn: async () => {
      if (!topSymbols.length) return {};
      const results = await Promise.allSettled(
        topSymbols.map((s) =>
          OpenAlgoClient.getHistory(s.symbol, s.exchange, 'D', d5y, today)
        )
      );
      const map: Record<string, { open: number; close: number; timestamp: number }[]> = {};
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && r.value.data) {
          const key = `${topSymbols[i].symbol}.${topSymbols[i].exchange}`;
          map[key] = r.value.data.map((b) => ({
            open: b.open,
            close: b.close,
            timestamp: b.timestamp,
          }));
        }
      });
      return map;
    },
    enabled: topSymbols.length > 0,
    refetchInterval: 15 * 60_000,
    staleTime: 14 * 60_000,
  });

  /** Filter bars to those on-or-after `fromDateStr` (YYYY-MM-DD) */
  const barsFrom = useCallback(
    (bars: { open: number; close: number; timestamp: number }[], fromDateStr: string) => {
      const fromEpoch = new Date(fromDateStr).getTime() / 1000;
      return bars.filter((b) => b.timestamp >= fromEpoch);
    },
    []
  );

  // Build rows — merge live WS tick over REST quote + historical pct changes
  const rows: TopSymbolRow[] = topSymbols.map((s) => {
    const key = `${s.symbol}.${s.exchange}`;
    const tick = tickData[key];
    const quote = quotesMap[key];
    const ltp = tick?.ltp ?? quote?.ltp ?? 0;
    const chg1d = tick?.change_percent ?? quote?.chg1d ?? 0;
    const volume = tick?.volume ?? quote?.volume ?? 0;

    const bars = histMap[key] ?? [];
    const chg1w = pctChange(barsFrom(bars, daysAgo(7)));
    const chg1m = pctChange(barsFrom(bars, daysAgo(30)));
    const chg3m = pctChange(barsFrom(bars, daysAgo(90)));
    const chg1y = pctChange(barsFrom(bars, daysAgo(365)));
    const chg3y = pctChange(barsFrom(bars, daysAgo(365 * 3)));
    const chg5y = pctChange(barsFrom(bars, daysAgo(365 * 5)));

    return { symbol: s.symbol, exchange: s.exchange, ltp, chg1d, chg1w, chg1m, chg3m, chg1y, chg3y, chg5y, volume };
  });

  // ─── Sorting ──────────────────────────────────────────────────────────────────

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const sortedRows = [...rows].sort((a, b) => {
    const aVal = a[sortKey as keyof TopSymbolRow];
    const bVal = b[sortKey as keyof TopSymbolRow];

    // Nulls always sink to the bottom
    if (aVal === null && bVal === null) return 0;
    if (aVal === null) return 1;
    if (bVal === null) return -1;

    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }

    const diff = (aVal as number) - (bVal as number);
    return sortDir === 'asc' ? diff : -diff;
  });

  const handleRowClick = (row: TopSymbolRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange(row.exchange);
  };

  if (topSymbols.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-terminal-gray gap-2 p-4">
        <span>No symbols configured.</span>
        <span>Use the SETTINGS widget to add symbols.</span>
      </div>
    );
  }

  // ─── Sortable header cell ─────────────────────────────────────────────────────

  function Th({ col, label, right }: { col: SortKey; label: string; right?: boolean }) {
    const active = sortKey === col;
    const arrow = active ? (sortDir === 'desc' ? ' ▼' : ' ▲') : '';
    return (
      <th
        className={[
          'p-1 border border-terminal-gray whitespace-nowrap select-none cursor-pointer hover:bg-blue-800',
          right ? 'text-right' : '',
          active ? 'text-terminal-amber' : 'text-white',
        ].join(' ')}
        onClick={() => handleSort(col)}
      >
        {label}{arrow}
      </th>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
      <table className="w-full text-left border-collapse">
        <thead className="bg-blue-900 sticky top-0">
          <tr>
            <Th col="symbol" label="SYMBOL" />
            <Th col="chg1d"  label="CHG 1D%"  right />
            <Th col="chg1w"  label="CHG 1W%"  right />
            <Th col="chg1m"  label="CHG 1M%"  right />
            <Th col="chg3m"  label="CHG 3M%"  right />
            <Th col="chg1y"  label="CHG 1Y%"  right />
            <Th col="chg3y"  label="CHG 3Y%"  right />
            <Th col="chg5y"  label="CHG 5Y%"  right />
            <Th col="ltp"    label="LTP"       right />
            <Th col="volume" label="VOL"       right />
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => {
            const isUp1d = row.chg1d >= 0;
            const color1d = isUp1d ? 'text-terminal-green' : 'text-terminal-red';
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
                <td className={`p-1 text-right border-r border-terminal-gray font-bold ${color1d}`}>
                  {row.chg1d !== 0
                    ? `${isUp1d ? '+' : ''}${row.chg1d.toFixed(2)}%`
                    : <span className="text-zinc-400">—</span>}
                </td>
                <td className="p-1 text-right border-r border-terminal-gray">{formatChg(row.chg1w)}</td>
                <td className="p-1 text-right border-r border-terminal-gray">{formatChg(row.chg1m)}</td>
                <td className="p-1 text-right border-r border-terminal-gray">{formatChg(row.chg3m)}</td>
                <td className="p-1 text-right border-r border-terminal-gray">{formatChg(row.chg1y)}</td>
                <td className="p-1 text-right border-r border-terminal-gray">{formatChg(row.chg3y)}</td>
                <td className="p-1 text-right border-r border-terminal-gray">{formatChg(row.chg5y)}</td>
                <td className="p-1 text-right border-r border-terminal-gray text-zinc-300">
                  {row.ltp > 0 ? row.ltp.toFixed(2) : <span className="text-zinc-400">—</span>}
                </td>
                <td className="p-1 text-right text-zinc-300">
                  {row.volume > 0 ? formatVolume(row.volume) : <span className="text-zinc-400">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

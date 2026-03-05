'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom, useSetAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, tickDataAtom, topSymbolsAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';

interface TopSymbolRow {
  symbol: string;
  exchange: string;
  ltp: number;
  chg1d: number;
  chg1w: number | null | 'err';
  chg1m: number | null | 'err';
  chg3m: number | null | 'err';
  chg1y: number | null | 'err';
  chg3y: number | null | 'err';
  chg5y: number | null | 'err';
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

function formatChg(val: number | null | 'err'): React.ReactNode {
  if (val === 'err') return <span className="text-terminal-red text-[9px]">ERR</span>;
  if (val === null) return <span className="text-zinc-600">—</span>;
  if (val === 0) return <span className="text-zinc-400">0.00%</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green font-bold' : 'text-terminal-red font-bold'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
}

/** Return a date string "YYYY-MM-DD" in IST. */
function formatDateIST(date: Date): string {
  return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
}

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return formatDateIST(d);
}

/**
 * Fetch the closing price of the bar closest to `periodDays` ago for a symbol.
 * Tries a ±15-day window first; widens to ±30 days if no bars are returned.
 * Returns null if no bars found after widening, or 'err' if all attempts fail
 * with an unexpected error.
 */
async function fetchAnchorClose(
  symbol: string,
  exchange: string,
  periodDays: number
): Promise<number | null | 'err'> {
  for (const halfWindow of [15, 30]) {
    const start = daysAgo(periodDays + halfWindow);
    const end   = daysAgo(Math.max(0, periodDays - halfWindow));
    try {
      const res = await OpenAlgoClient.getHistory(symbol, exchange, 'D', start, end);
      if (res.data && res.data.length > 0) {
        // Return the close of the last bar in the window (closest to anchor date)
        return res.data[res.data.length - 1].close;
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[TopWidget] anchor fetch failed for ${symbol}/${exchange} period=${periodDays}d window=±${halfWindow}d: ${msg}`);
      return 'err';
    }
  }
  // Both windows returned empty data
  console.warn(`[TopWidget] no anchor bars for ${symbol}/${exchange} period=${periodDays}d after widening to ±30d`);
  return 'err';
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
  const symbolsKey = useMemo(
    () => topSymbols.map((s) => `${s.symbol}.${s.exchange}`).join(','),
    [topSymbols]
  );

  const { data: quotesMap = {} } = useQuery({
    queryKey: ['top-quotes', symbolsKey],
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

  // ─── Per-period anchor queries ────────────────────────────────────────────────
  // One query per period — 6 total regardless of symbol count.
  // Each fires N parallel sub-requests (one per symbol via Promise.allSettled).
  // Staggered refetchInterval so they don't all hit the API at the same moment.

  const makeAnchorQueryFn = (periodDays: number) => async () => {
    if (!topSymbols.length) return {} as Record<string, number | null | 'err'>;
    const results = await Promise.allSettled(
      topSymbols.map((s) => fetchAnchorClose(s.symbol, s.exchange, periodDays))
    );
    const map: Record<string, number | null | 'err'> = {};
    results.forEach((r, i) => {
      const key = `${topSymbols[i].symbol}.${topSymbols[i].exchange}`;
      map[key] = r.status === 'fulfilled' ? r.value : 'err';
    });
    return map;
  };

  const enabled = topSymbols.length > 0;

  const { data: anchor1w = {} } = useQuery({
    queryKey: ['top-anchor', '1w', symbolsKey],
    queryFn: makeAnchorQueryFn(7),
    enabled,
    refetchInterval: 15 * 60_000,
    staleTime: 14 * 60_000,
  });
  const { data: anchor1m = {} } = useQuery({
    queryKey: ['top-anchor', '1m', symbolsKey],
    queryFn: makeAnchorQueryFn(30),
    enabled,
    refetchInterval: 20 * 60_000,
    staleTime: 19 * 60_000,
  });
  const { data: anchor3m = {} } = useQuery({
    queryKey: ['top-anchor', '3m', symbolsKey],
    queryFn: makeAnchorQueryFn(90),
    enabled,
    refetchInterval: 25 * 60_000,
    staleTime: 24 * 60_000,
  });
  const { data: anchor1y = {} } = useQuery({
    queryKey: ['top-anchor', '1y', symbolsKey],
    queryFn: makeAnchorQueryFn(365),
    enabled,
    refetchInterval: 30 * 60_000,
    staleTime: 29 * 60_000,
  });
  const { data: anchor3y = {} } = useQuery({
    queryKey: ['top-anchor', '3y', symbolsKey],
    queryFn: makeAnchorQueryFn(365 * 3),
    enabled,
    refetchInterval: 35 * 60_000,
    staleTime: 34 * 60_000,
  });
  const { data: anchor5y = {} } = useQuery({
    queryKey: ['top-anchor', '5y', symbolsKey],
    queryFn: makeAnchorQueryFn(365 * 5),
    enabled,
    refetchInterval: 40 * 60_000,
    staleTime: 39 * 60_000,
  });

  // ─── Compute % change from anchor close to current LTP ───────────────────────

  function anchorPct(
    anchorMap: Record<string, number | null | 'err'>,
    key: string,
    ltp: number
  ): number | null | 'err' {
    const anchor = anchorMap[key];
    if (anchor === undefined) return null;   // not yet loaded
    if (anchor === 'err') return 'err';
    if (anchor === null) return null;
    if (anchor === 0 || ltp === 0) return null;
    return ((ltp - anchor) / anchor) * 100;
  }

  // Build rows — merge live WS tick over REST quote + historical pct changes
  const rows: TopSymbolRow[] = topSymbols.map((s) => {
    const key = `${s.symbol}.${s.exchange}`;
    const tick = tickData[key];
    const quote = quotesMap[key];
    const ltp = tick?.ltp ?? quote?.ltp ?? 0;
    const chg1d = tick?.change_percent ?? quote?.chg1d ?? 0;
    const volume = tick?.volume ?? quote?.volume ?? 0;

    return {
      symbol: s.symbol,
      exchange: s.exchange,
      ltp,
      chg1d,
      volume,
      chg1w: anchorPct(anchor1w, key, ltp),
      chg1m: anchorPct(anchor1m, key, ltp),
      chg3m: anchorPct(anchor3m, key, ltp),
      chg1y: anchorPct(anchor1y, key, ltp),
      chg3y: anchorPct(anchor3y, key, ltp),
      chg5y: anchorPct(anchor5y, key, ltp),
    };
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
    const aRaw = a[sortKey as keyof TopSymbolRow];
    const bRaw = b[sortKey as keyof TopSymbolRow];

    // 'err' and null sink to the bottom (treat as -Infinity for desc sort)
    const aVal = (aRaw === null || aRaw === 'err') ? null : aRaw;
    const bVal = (bRaw === null || bRaw === 'err') ? null : bRaw;

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



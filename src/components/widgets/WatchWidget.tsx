'use client';

import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, tickDataAtom, watchlistColumnsAtom } from '@/store/terminalStore';
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

interface NseSymbolData {
  equityResponse?: Array<{
    orderBook?: { lastPrice?: number };
    tradeInfo?: { lastPrice?: number };
    metaData?: { pChange?: number };
    priceInfo?: { yearHigh?: number; yearLow?: number };
  }>;
}

interface SymbolQuote {
  ltp: number;
  pChange: number;
  yearHigh?: number;
  yearLow?: number;
}

interface AutocompleteResult {
  symbol: string;
  companyName: string;
}

async function searchSymbols(query: string): Promise<AutocompleteResult[]> {
  if (!query || query.length < 1) return [];
  const res = await fetch(`/api/py/stockuniverse/search/${encodeURIComponent(query)}`);
  if (!res.ok) return [];
  return res.json() as Promise<AutocompleteResult[]>;
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

function useSymbolData(symbol: string) {
  return useQuery<SymbolQuote | null>({
    queryKey: ['market/symbol-data', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/market/symbol-data/${encodeURIComponent(symbol)}`);
      if (!res.ok) return null;
      const payload = (await res.json()) as NseSymbolData;
      const equity = payload.equityResponse?.[0];
      const ltp = equity?.orderBook?.lastPrice ?? equity?.tradeInfo?.lastPrice ?? 0;
      const pChange = equity?.metaData?.pChange ?? 0;
      const yearHigh = equity?.priceInfo?.yearHigh;
      const yearLow = equity?.priceInfo?.yearLow;
      if (!ltp) return null;
      return { ltp, pChange, yearHigh, yearLow };
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    enabled: !!symbol,
  });
}

function useChangeRanges(symbol: string) {
  return useQuery<ChangeRanges | null>({
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

function formatPrice(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-terminal-gray">—</span>;
  return <span>{val.toFixed(2)}</span>;
}

interface WatchRowProps {
  item: WatchlistItem;
  isActive: boolean;
  columns: string[];
  onRowClick: (item: WatchlistItem) => void;
  onRemove: (id: number) => void;
  removing: boolean;
}

function WatchRow({ item, isActive, columns, onRowClick, onRemove, removing }: WatchRowProps) {
  const { data: symbolData, isLoading: symbolLoading } = useSymbolData(item.symbol);
  const { data: ranges, isLoading: rangesLoading } = useChangeRanges(item.symbol);

  const ltp = symbolData?.ltp ?? null;
  const chgPct = symbolData?.pChange ?? null;
  const yearHigh = symbolData?.yearHigh;
  const yearLow = symbolData?.yearLow;
  const isUp = (chgPct ?? 0) >= 0;
  const colorClass = isUp ? 'text-terminal-green' : 'text-terminal-red';
  const dash = <span className="text-terminal-gray">—</span>;

  const renderCell = (col: string) => {
    switch (col) {
      case 'ltp':
        return symbolLoading ? dash : ltp != null ? ltp.toFixed(2) : dash;
      case 'chg':
        return symbolLoading
          ? dash
          : chgPct != null
          ? (
              <span className={colorClass}>
                {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
              </span>
            )
          : dash;
      case '1w':
        return rangesLoading ? dash : formatRange(ranges?.oneWeekPercent);
      case '1m':
        return rangesLoading ? dash : formatRange(ranges?.oneMonthPercent);
      case '3m':
        return rangesLoading ? dash : formatRange(ranges?.threeMonthPercent);
      case '6m':
        return rangesLoading ? dash : formatRange(ranges?.sixMonthPercent);
      case '1y':
        return rangesLoading ? dash : formatRange(ranges?.oneYearPercent);
      case '2y':
        return rangesLoading ? dash : formatRange(ranges?.twoYearPercent);
      case '3y':
        return rangesLoading ? dash : formatRange(ranges?.threeYearPercent);
      case '5y':
        return rangesLoading ? dash : formatRange(ranges?.fiveYearPercent);
      case '52wh':
        return symbolLoading ? dash : formatPrice(yearHigh);
      case '52wl':
        return symbolLoading ? dash : formatPrice(yearLow);
      default:
        return null;
    }
  };

  return (
    <tr
      onClick={() => onRowClick(item)}
      className={`border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer ${
        isActive ? 'bg-zinc-800' : ''
      }`}
    >
      <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">
        <span>{item.symbol}</span>
        <span className="text-terminal-gray text-[9px] ml-1">{item.exchange}</span>
      </td>
      {columns.map((col) => (
        <td key={col} className="p-1 text-right border-r border-terminal-gray">
          {renderCell(col)}
        </td>
      ))}
      <td className="p-1 text-center">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove(item.id);
          }}
          disabled={removing}
          className="text-terminal-gray hover:text-terminal-red text-[10px] disabled:opacity-50"
          title="Remove"
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

const COLUMN_LABELS: Record<string, string> = {
  ltp: 'LTP',
  chg: 'CHG%',
  '1w': '1W%',
  '1m': '1M%',
  '3m': '3M%',
  '6m': '6M%',
  '1y': '1Y%',
  '2y': '2Y%',
  '3y': '3Y%',
  '5y': '5Y%',
  '52wh': '52W HIGH',
  '52wl': '52W LOW',
};

export function WatchWidget() {
  const qc = useQueryClient();
  const [activeSymbol, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [activeExchange, setActiveExchange] = useAtom(activeExchangeAtom);
  const [, setTickData] = useAtom(tickDataAtom);
  const [watchlistColumns] = useAtom(watchlistColumnsAtom);

  const [newSymbol, setNewSymbol] = useState('');
  const [newExchange, setNewExchange] = useState('NSE');
  const [autocompleteResults, setAutocompleteResults] = useState<AutocompleteResult[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = React.useRef<NodeJS.Timeout | null>(null);

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

  const handleSymbolChange = (value: string) => {
    setNewSymbol(value.toUpperCase());
    setActiveIndex(-1);
    
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    
    if (!value.trim()) {
      setAutocompleteResults([]);
      setShowDropdown(false);
      return;
    }
    
    debounceRef.current = setTimeout(async () => {
      const results = await searchSymbols(value.trim().toUpperCase());
      setAutocompleteResults(results);
      setShowDropdown(results.length > 0);
    }, 300);
  };

  const handleSelectResult = (result: AutocompleteResult) => {
    setNewSymbol(result.symbol);
    setShowDropdown(false);
    setAutocompleteResults([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showDropdown) return;
    
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => Math.min(prev + 1, autocompleteResults.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => Math.max(prev - 1, -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0 && autocompleteResults[activeIndex]) {
        handleSelectResult(autocompleteResults[activeIndex]);
      }
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
    }
  };

  // Keep WS subscriptions alive so ChartWidget and tickDataAtom stay populated
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

  // Forward WS ticks into the global tickDataAtom for ChartWidget
  useEffect(() => {
    const unsub = wsService.onTick((data: TickData) => {
      const key = `${data.symbol}.${data.exchange}`;
      setTickData((prev) => ({ ...prev, [key]: data }));
    });
    return unsub;
  }, [setTickData]);

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const handleRowClick = (item: WatchlistItem) => {
    setActiveSymbol(item.symbol);
    setActiveExchange(item.exchange);
  };

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const s = newSymbol.trim().toUpperCase();
    const ex = newExchange.trim().toUpperCase();
    if (!s || !ex) return;
    setShowDropdown(false);
    setAutocompleteResults([]);
    addMutation.mutate({ symbol: s, exchange: ex });
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden relative">
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
        <div className="flex-1 relative">
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => handleSymbolChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
            placeholder="SYMBOL"
            className="w-full bg-black border border-terminal-gray text-terminal-amber px-1 py-0.5 uppercase"
          />
          {showDropdown && autocompleteResults.length > 0 && (
            <div
              className="absolute z-50 w-full bg-black border border-terminal-gray mt-0.5 max-h-48 overflow-auto"
            >
              {autocompleteResults.slice(0, 10).map((result, index) => (
                <div
                  key={result.symbol}
                  onClick={() => handleSelectResult(result)}
                  className={`px-1 py-0.5 cursor-pointer hover:bg-zinc-800 ${
                    index === activeIndex ? 'bg-zinc-800 text-terminal-amber' : 'text-terminal-gray'
                  }`}
                >
                  <span className="text-terminal-amber font-bold">{result.symbol}</span>
                  <span className="ml-1 truncate">{result.companyName}</span>
                </div>
              ))}
            </div>
          )}
        </div>
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
                  {watchlistColumns.map((col) => (
                    <th key={col} className="p-1 border border-terminal-gray text-right">
                      {COLUMN_LABELS[col] || col}
                    </th>
                  ))}
                  <th className="p-1 border border-terminal-gray w-6"></th>
                </tr>
              </thead>
              <tbody>
                {watchlist.map((item) => (
                  <WatchRow
                    key={item.id}
                    item={item}
                    columns={watchlistColumns}
                    isActive={activeSymbol === item.symbol && activeExchange === item.exchange}
                    onRowClick={handleRowClick}
                    onRemove={(id) => removeMutation.mutate(id)}
                    removing={removeMutation.isPending}
                  />
                ))}
                {watchlist.length === 0 && (
                  <tr>
                    <td colSpan={watchlistColumns.length + 2} className="p-2 text-terminal-gray text-center">
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

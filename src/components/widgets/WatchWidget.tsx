'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { 
  activeSymbolAtom, 
  activeExchangeAtom, 
  tickDataAtom, 
  watchlistColumnsAtom,
  watchlistsAtom,
  activeWatchlistIdAtom,
  type Watchlist
} from '@/store/terminalStore';
import { wsService } from '@/lib/socket';
import type { TickData } from '@/lib/socket';

interface WatchlistItem {
  id: number;
  watchlist_id: number;
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

interface AutocompleteResult {
  symbol: string;
  companyName: string;
}

// Derived row: combines watchlist item with all sortable values
interface WatchRowData {
  item: WatchlistItem;
  ltp: number | null;
  chgPct: number | null;
  oneWeek: number | null;
  oneMonth: number | null;
  threeMonth: number | null;
  sixMonth: number | null;
  oneYear: number | null;
  twoYear: number | null;
  threeYear: number | null;
  fiveYear: number | null;
  yearHigh: number | null;
  yearLow: number | null;
  fairValue: number | null;
  isLoading: boolean;
}

type SortColumn =
  | 'symbol'
  | 'exchange'
  | 'ltp'
  | 'chg'
  | '1w'
  | '1m'
  | '3m'
  | '6m'
  | '1y'
  | '2y'
  | '3y'
  | '5y'
  | '52wh'
  | '52wl'
  | 'msfv';

type SortDirection = 'asc' | 'desc';

interface ColumnConfig {
  key: SortColumn;
  label: string;
  textAlign: 'center' | 'right';
  defaultSort: SortDirection;
}

const SORTABLE_COLUMNS: Record<string, ColumnConfig> = {
  symbol: { key: 'symbol', label: 'SYMBOL', textAlign: 'center', defaultSort: 'asc' },
  exchange: { key: 'exchange', label: 'EXCHANGE', textAlign: 'center', defaultSort: 'asc' },
  ltp: { key: 'ltp', label: 'LTP', textAlign: 'right', defaultSort: 'desc' },
  chg: { key: 'chg', label: 'CHG%', textAlign: 'right', defaultSort: 'desc' },
  '1w': { key: '1w', label: '1W%', textAlign: 'right', defaultSort: 'desc' },
  '1m': { key: '1m', label: '1M%', textAlign: 'right', defaultSort: 'desc' },
  '3m': { key: '3m', label: '3M%', textAlign: 'right', defaultSort: 'desc' },
  '6m': { key: '6m', label: '6M%', textAlign: 'right', defaultSort: 'desc' },
  '1y': { key: '1y', label: '1Y%', textAlign: 'right', defaultSort: 'desc' },
  '2y': { key: '2y', label: '2Y%', textAlign: 'right', defaultSort: 'desc' },
  '3y': { key: '3y', label: '3Y%', textAlign: 'right', defaultSort: 'desc' },
  '5y': { key: '5y', label: '5Y%', textAlign: 'right', defaultSort: 'desc' },
  '52wh': { key: '52wh', label: '52W HIGH', textAlign: 'right', defaultSort: 'desc' },
  '52wl': { key: '52wl', label: '52W LOW', textAlign: 'right', defaultSort: 'desc' },
  msfv: { key: 'msfv', label: 'MS FV', textAlign: 'right', defaultSort: 'desc' },
};

function compareValues(a: unknown, b: unknown, direction: SortDirection): number {
  // Nulls sort last
  const aNull = a === null || a === undefined;
  const bNull = b === null || b === undefined;
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  // Numeric
  if (typeof a === 'number' && typeof b === 'number') {
    const result = a - b;
    return direction === 'asc' ? result : -result;
  }

  // String
  if (typeof a === 'string' && typeof b === 'string') {
    const result = a.localeCompare(b);
    return direction === 'asc' ? result : -result;
  }

  return 0;
}

function formatRange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-white/60">—</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green' : 'text-terminal-red'}>
      {isUp ? '+' : ''}{val.toFixed(1)}%
    </span>
  );
}

function formatPrice(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-white/60">—</span>;
  return <span>{val.toFixed(2)}</span>;
}

interface WatchRowProps {
  rowData: WatchRowData;
  isActive: boolean;
  columns: string[];
  onRowClick: (item: WatchlistItem) => void;
  onRemove: (id: number) => void;
  removing: boolean;
  flash: 'up' | 'down' | null;
}

function WatchRow({ rowData, isActive, columns, onRowClick, onRemove, removing, flash }: WatchRowProps) {
  const { item, ltp, chgPct, oneWeek, oneMonth, threeMonth, sixMonth, oneYear, twoYear, threeYear, fiveYear, yearHigh, yearLow, fairValue, isLoading } = rowData;
  const isUp = (chgPct ?? 0) >= 0;
  const colorClass = isUp ? 'text-terminal-green' : 'text-terminal-red';
  const dash = <span className="text-white/60">—</span>;

  const renderCell = (col: string) => {
    switch (col) {
      case 'ltp':
        return isLoading ? dash : ltp != null ? (
          <span className={flash === 'up' ? 'animate-flash-green' : flash === 'down' ? 'animate-flash-red' : ''}>
            {ltp.toFixed(2)}
          </span>
        ) : dash;
      case 'chg':
        return isLoading
          ? dash
          : chgPct != null
          ? (
              <span className={colorClass}>
                {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
              </span>
            )
          : dash;
      case '1w':
        return formatRange(oneWeek);
      case '1m':
        return formatRange(oneMonth);
      case '3m':
        return formatRange(threeMonth);
      case '6m':
        return formatRange(sixMonth);
      case '1y':
        return formatRange(oneYear);
      case '2y':
        return formatRange(twoYear);
      case '3y':
        return formatRange(threeYear);
      case '5y':
        return formatRange(fiveYear);
      case '52wh':
        return isLoading ? dash : formatPrice(yearHigh);
      case '52wl':
        return isLoading ? dash : formatPrice(yearLow);
      case 'msfv':
        return isLoading ? dash : fairValue != null ? (
          <span className="text-terminal-amber">₹{fairValue.toFixed(2)}</span>
        ) : dash;
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
      <td className="p-1 text-center border-r border-terminal-gray">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove(item.id);
          }}
          disabled={removing}
          className="text-terminal-red hover:text-red-400 text-xs font-bold disabled:opacity-40"
          title="Remove"
        >
          ✕
        </button>
      </td>
      <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">
        <span>{item.symbol}</span>
        <span className="text-white/60 text-[9px] ml-1">{item.exchange}</span>
      </td>
      {columns.map((col) => (
        <td key={col} className="p-1 text-right border-r border-terminal-gray">
          {renderCell(col)}
        </td>
      ))}
    </tr>
  );
}

async function searchSymbols(query: string): Promise<AutocompleteResult[]> {
  if (!query || query.length < 1) return [];
  const res = await fetch(`/api/py/stockuniverse/search/${encodeURIComponent(query)}`);
  if (!res.ok) return [];
  return res.json() as Promise<AutocompleteResult[]>;
}

async function fetchWatchlist(watchlistId: number = 1): Promise<WatchlistItem[]> {
  const res = await fetch(`/api/watchlist?watchlist_id=${watchlistId}`);
  if (!res.ok) throw new Error('Failed to fetch watchlist');
  return res.json() as Promise<WatchlistItem[]>;
}

async function addSymbol(symbol: string, exchange: string, watchlistId: number = 1): Promise<WatchlistItem> {
  const res = await fetch(`/api/watchlist?watchlist_id=${watchlistId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbol, exchange }),
  });
  if (!res.ok) throw new Error('Failed to add symbol');
  return res.json() as Promise<WatchlistItem>;
}

async function removeSymbol(id: number, watchlistId: number = 1): Promise<void> {
  const res = await fetch(`/api/watchlist?id=${id}&watchlist_id=${watchlistId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to remove symbol');
}

async function fetchWatchlists(): Promise<Watchlist[]> {
  const res = await fetch('/api/watchlists');
  if (!res.ok) throw new Error('Failed to fetch watchlists');
  return res.json() as Promise<Watchlist[]>;
}

async function createWatchlist(name: string): Promise<Watchlist> {
  const res = await fetch('/api/watchlists', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error('Failed to create watchlist');
  return res.json() as Promise<Watchlist>;
}

export function WatchWidget() {
  const qc = useQueryClient();
  const [activeSymbol, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [activeExchange, setActiveExchange] = useAtom(activeExchangeAtom);
  const [, setTickData] = useAtom(tickDataAtom);
  const [watchlistColumns] = useAtom(watchlistColumnsAtom);
  const [watchlists, setWatchlists] = useAtom(watchlistsAtom);
  const [activeWatchlistId, setActiveWatchlistId] = useAtom(activeWatchlistIdAtom);

  const [newSymbol, setNewSymbol] = useState('');
  const [newExchange, setNewExchange] = useState('NSE');
  const [autocompleteResults, setAutocompleteResults] = useState<AutocompleteResult[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [sortColumn, setSortColumn] = useState<SortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newWatchlistName, setNewWatchlistName] = useState('');
  const debounceRef = React.useRef<NodeJS.Timeout | null>(null);
  const prevPricesRef = useRef<Map<string, number>>(new Map());
  const [flashStates, setFlashStates] = useState<Map<string, 'up' | 'down'>>(new Map());

  // Fetch watchlists on mount
  useQuery({
    queryKey: ['watchlists'],
    queryFn: async () => {
      const data = await fetchWatchlists();
      setWatchlists(data);
      return data;
    },
    staleTime: 300_000,
  });

  // Current watchlist data
  const { data: watchlist = [], isLoading, isError } = useQuery({
    queryKey: ['watchlist', activeWatchlistId],
    queryFn: () => fetchWatchlist(activeWatchlistId),
    staleTime: Infinity,
  });

  // Fetch data for all symbols in parallel using useQueries
  const symbolQueries = useQueries({
    queries: watchlist.map((item) => ({
      queryKey: ['market/symbol-data', item.symbol],
      queryFn: async () => {
        const res = await fetch(`/api/py/market/symbol-data/${encodeURIComponent(item.symbol)}`);
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
      enabled: !!item.symbol,
    })),
  });

  const rangeQueries = useQueries({
    queries: watchlist.map((item) => ({
      queryKey: ['market/change-ranges', item.symbol],
      queryFn: async () => {
        const res = await fetch(`/api/py/market/change-ranges/${encodeURIComponent(item.symbol)}`);
        if (!res.ok) return null;
        return res.json() as Promise<ChangeRanges>;
      },
      staleTime: 300_000,
      enabled: !!item.symbol,
    })),
  });

  const fairValueQueries = useQueries({
    queries: watchlist.map((item) => ({
      queryKey: ['morningstar/fairvalue', item.symbol],
      queryFn: async () => {
        const res = await fetch(`/api/py/morningstar/fairvalue/${encodeURIComponent(item.symbol)}`);
        if (!res.ok) return null;
        const data = await res.json();
        return data.fairValue as number | null;
      },
      staleTime: 300_000,
      enabled: !!item.symbol,
    })),
  });

  // Build derived row data
  const rowDataList: WatchRowData[] = watchlist.map((item, idx) => {
    const quote = symbolQueries[idx];
    const ranges = rangeQueries[idx];
    const fairValue = fairValueQueries[idx];

    return {
      item,
      ltp: quote?.data?.ltp ?? null,
      chgPct: quote?.data?.pChange ?? null,
      oneWeek: ranges?.data?.oneWeekPercent ?? null,
      oneMonth: ranges?.data?.oneMonthPercent ?? null,
      threeMonth: ranges?.data?.threeMonthPercent ?? null,
      sixMonth: ranges?.data?.sixMonthPercent ?? null,
      oneYear: ranges?.data?.oneYearPercent ?? null,
      twoYear: ranges?.data?.twoYearPercent ?? null,
      threeYear: ranges?.data?.threeYearPercent ?? null,
      fiveYear: ranges?.data?.fiveYearPercent ?? null,
      yearHigh: quote?.data?.yearHigh ?? null,
      yearLow: quote?.data?.yearLow ?? null,
      fairValue: fairValue?.data ?? null,
      isLoading: (quote?.isLoading ?? false) || (ranges?.isLoading ?? false) || (fairValue?.isLoading ?? false),
    };
  });

  // Detect price changes on REST refetch and trigger flash
  useEffect(() => {
    symbolQueries.forEach((query, idx) => {
      if (query.data?.ltp !== undefined && query.dataUpdatedAt) {
        const item = watchlist[idx];
        if (!item) return;
        const key = item.symbol;
        const prevPrice = prevPricesRef.current.get(key);
        if (prevPrice !== undefined && query.data.ltp !== prevPrice) {
          const direction = query.data.ltp > prevPrice ? 'up' : 'down';
          setFlashStates((prev) => {
            const next = new Map(prev);
            next.set(key, direction);
            return next;
          });
          setTimeout(() => {
            setFlashStates((prev) => {
              const next = new Map(prev);
              next.delete(key);
              return next;
            });
          }, 400);
        }
        prevPricesRef.current.set(key, query.data.ltp);
      }
    });
  }, [symbolQueries, watchlist]);

  const handleHeaderClick = (column: SortColumn) => {
    const colConfig = SORTABLE_COLUMNS[column];
    if (!colConfig) return;

    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection(colConfig.defaultSort);
    }
  };

  // Sort rows
  const sortedRowData = (() => {
    if (!sortColumn) return rowDataList;

    return [...rowDataList].sort((a, b) => {
      let aVal: unknown;
      let bVal: unknown;

      switch (sortColumn) {
        case 'symbol':
          aVal = a.item.symbol;
          bVal = b.item.symbol;
          break;
        case 'exchange':
          aVal = a.item.exchange;
          bVal = b.item.exchange;
          break;
        case 'ltp':
          aVal = a.ltp;
          bVal = b.ltp;
          break;
        case 'chg':
          aVal = a.chgPct;
          bVal = b.chgPct;
          break;
        case '1w':
          aVal = a.oneWeek;
          bVal = b.oneWeek;
          break;
        case '1m':
          aVal = a.oneMonth;
          bVal = b.oneMonth;
          break;
        case '3m':
          aVal = a.threeMonth;
          bVal = b.threeMonth;
          break;
        case '6m':
          aVal = a.sixMonth;
          bVal = b.sixMonth;
          break;
        case '1y':
          aVal = a.oneYear;
          bVal = b.oneYear;
          break;
        case '2y':
          aVal = a.twoYear;
          bVal = b.twoYear;
          break;
        case '3y':
          aVal = a.threeYear;
          bVal = b.threeYear;
          break;
        case '5y':
          aVal = a.fiveYear;
          bVal = b.fiveYear;
          break;
        case '52wh':
          aVal = a.yearHigh;
          bVal = b.yearHigh;
          break;
        case '52wl':
          aVal = a.yearLow;
          bVal = b.yearLow;
          break;
        case 'msfv':
          aVal = a.fairValue;
          bVal = b.fairValue;
          break;
        default:
          return 0;
      }

      return compareValues(aVal, bVal, sortDirection);
    });
  })();

  const getSortIndicator = (column: SortColumn) => {
    if (sortColumn !== column) return '';
    return sortDirection === 'asc' ? ' ▲' : ' ▼';
  };

  const addMutation = useMutation({
    mutationFn: ({ symbol, exchange }: { symbol: string; exchange: string }) =>
      addSymbol(symbol, exchange, activeWatchlistId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['watchlist', activeWatchlistId] });
      void qc.invalidateQueries({ queryKey: ['watchlists'] });
      setNewSymbol('');
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => removeSymbol(id, activeWatchlistId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['watchlist', activeWatchlistId] });
      void qc.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });

  const createWatchlistMutation = useMutation({
    mutationFn: (name: string) => createWatchlist(name),
    onSuccess: (newWatchlist) => {
      void qc.invalidateQueries({ queryKey: ['watchlists'] });
      setActiveWatchlistId(newWatchlist.id);
      setShowCreateModal(false);
      setNewWatchlistName('');
    },
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

      const prevPrice = prevPricesRef.current.get(key);
      if (prevPrice !== undefined && data.ltp !== undefined && data.ltp !== prevPrice) {
        const direction = data.ltp > prevPrice ? 'up' : 'down';
        const key2 = `${data.symbol}`;
        setFlashStates((prev) => {
          const next = new Map(prev);
          next.set(key2, direction);
          return next;
        });
        prevPricesRef.current.set(key, data.ltp);
        setTimeout(() => {
          setFlashStates((prev) => {
            const next = new Map(prev);
            next.delete(key2);
            return next;
          });
        }, 400);
      }
      if (data.ltp !== undefined) {
        prevPricesRef.current.set(key, data.ltp);
      }
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

  const handleCreateWatchlist = (e: React.FormEvent) => {
    e.preventDefault();
    const name = newWatchlistName.trim();
    if (!name) return;
    if (name.length > 32) return;
    if (!/^[A-Za-z-]+$/.test(name)) return;
    createWatchlistMutation.mutate(name);
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden relative">
      {/* Watchlist selector header */}
      <div className="flex items-center gap-1 px-2 py-1 border-b border-terminal-gray bg-blue-950 flex-shrink-0">
        <span className="text-white/60 uppercase text-[10px]">Watchlist:</span>
        <select
          value={activeWatchlistId}
          onChange={(e) => setActiveWatchlistId(Number(e.target.value))}
          className="bg-black border border-terminal-gray text-terminal-amber px-2 py-0.5 uppercase text-xs"
        >
          {watchlists.map((wl) => (
            <option key={wl.id} value={wl.id}>
              {wl.name}
            </option>
          ))}
        </select>
        <button
          onClick={() => setShowCreateModal(true)}
          className="ml-1 text-terminal-amber hover:text-white text-xs font-bold border border-terminal-amber hover:bg-terminal-amber hover:text-black px-1.5 py-0.5"
          title="Create new watchlist"
        >
          +
        </button>
      </div>

      {/* Create watchlist modal */}
      {showCreateModal && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/70">
          <div className="bg-black border border-terminal-amber p-3 w-64">
            <div className="text-terminal-amber font-bold mb-2 text-center">NEW WATCHLIST</div>
            <form onSubmit={handleCreateWatchlist}>
              <input
                type="text"
                value={newWatchlistName}
                onChange={(e) => setNewWatchlistName(e.target.value)}
                placeholder="Name (letters, hyphen)"
                maxLength={32}
                pattern="^[A-Za-z-]+$"
                className="w-full bg-black border border-terminal-gray text-terminal-amber px-2 py-1 uppercase mb-2"
                autoFocus
              />
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateModal(false);
                    setNewWatchlistName('');
                  }}
                  className="px-2 py-1 text-white border border-terminal-gray hover:bg-terminal-gray"
                >
                  CANCEL
                </button>
                <button
                  type="submit"
                  disabled={createWatchlistMutation.isPending || !newWatchlistName.trim() || !/^[A-Za-z-]+$/.test(newWatchlistName.trim())}
                  className="px-2 py-1 bg-terminal-amber text-black font-bold hover:bg-amber-400 disabled:opacity-50"
                >
                  CREATE
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

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
            <div className="absolute z-50 w-full bg-black border border-terminal-gray mt-0.5 max-h-48 overflow-auto">
              {autocompleteResults.slice(0, 10).map((result, index) => (
                <div
                  key={result.symbol}
                  onClick={() => handleSelectResult(result)}
                  className={`px-1 py-0.5 cursor-pointer hover:bg-zinc-800 ${
                    index === activeIndex ? 'bg-zinc-800 text-terminal-amber' : 'text-white/70'
                  }`}
                >
                  <span className="text-terminal-amber font-bold">{result.symbol}</span>
                  <span className="ml-1 truncate text-white/80">{result.companyName}</span>
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
        {isLoading && <div className="p-2 text-white">LOADING WATCHLIST...</div>}
        {isError && <div className="p-2 text-terminal-red">FAILED TO LOAD WATCHLIST</div>}
        {!isLoading && !isError && (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead className="bg-blue-900 text-white sticky top-0">
                <tr>
                  <th className="p-1 border border-terminal-gray w-6"></th>
                  <th
                    onClick={() => handleHeaderClick('symbol')}
                    className="p-1 border border-terminal-gray cursor-pointer hover:text-terminal-amber transition-colors"
                  >
                    SYMBOL{getSortIndicator('symbol')}
                  </th>
                  {watchlistColumns.map((col) => {
                    const colConfig = SORTABLE_COLUMNS[col];
                    return (
                      <th
                        key={col}
                        onClick={() => handleHeaderClick(colConfig?.key || (col as SortColumn))}
                        className={`p-1 border border-terminal-gray cursor-pointer hover:text-terminal-amber transition-colors ${
                          colConfig?.textAlign === 'right' ? 'text-right' : 'text-center'
                        }`}
                      >
                        {colConfig?.label || col}
                        {getSortIndicator(colConfig?.key || (col as SortColumn))}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {sortedRowData.map((rowData) => (
                  <WatchRow
                    key={rowData.item.id}
                    rowData={rowData}
                    columns={watchlistColumns}
                    isActive={
                      activeSymbol === rowData.item.symbol &&
                      activeExchange === rowData.item.exchange
                    }
                    onRowClick={handleRowClick}
                    onRemove={(id) => removeMutation.mutate(id)}
                    removing={removeMutation.isPending && removeMutation.variables === rowData.item.id}
                    flash={flashStates.get(rowData.item.symbol) ?? null}
                  />
                ))}
                {watchlist.length === 0 && (
                  <tr>
                    <td
                      colSpan={watchlistColumns.length + 2}
                      className="p-2 text-white text-center"
                    >
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

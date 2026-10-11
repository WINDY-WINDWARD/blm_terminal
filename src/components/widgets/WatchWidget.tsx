'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useQueries, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { useAtom, useAtomValue } from 'jotai';
import { 
  activeSymbolAtom, 
  activeExchangeAtom, 
  tickDataAtom, 
  watchlistColumnsAtom,
  watchlistsAtom,
  activeWatchlistIdAtom,
  activePanelsAtom,
  notifSymbolFilterAtom,
  type Watchlist
} from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';
import type { ChangeRanges, SymbolDataExtract } from '@/lib/nseTypes';
import type { EventCalendarItem } from '@/app/api/event-calendar/route';

interface WatchlistItem {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
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
  alertCount: number;
  symbolLoading: boolean;
  rangesLoading: boolean;
  fairValueLoading: boolean;
}

interface ResultCellValue {
  date: string;
  status: 'upcoming' | 'past';
}

type SortColumn =
  | 'symbol'
  | 'exchange'
  | 'ltp'
  | 'chg'
  | 'momentum'
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
  | 'msfv'
  | 'results'
  | 'alerts';

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
  momentum: { key: 'momentum', label: 'MOMENTUM (1W-1Y)', textAlign: 'center', defaultSort: 'desc' },
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
  msfv: { key: 'msfv', label: 'MS FAIR VALUE', textAlign: 'right', defaultSort: 'desc' },
  results: { key: 'results', label: 'RESULTS', textAlign: 'center', defaultSort: 'asc' },
  alerts: { key: 'alerts', label: 'ALERTS', textAlign: 'center', defaultSort: 'desc' },
};

function formatResultsDate(dateStr: string): string {
  const match = dateStr.match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/);
  if (!match) return dateStr;
  return `${match[1]} ${match[2]}`;
}

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
  if (val == null || isNaN(val)) return <span className="text-zinc-500">—</span>;
  const isUp = val >= 0;
  return (
    <span className={`font-semibold tabular-nums ${isUp ? 'text-terminal-green' : 'text-terminal-red'}`}>
      {isUp ? '+' : ''}{val.toFixed(1)}%
    </span>
  );
}

function formatPrice(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-zinc-500">—</span>;
  return <span className="text-zinc-200 tabular-nums">{val.toFixed(2)}</span>;
}

interface WatchRowProps {
  rowData: WatchRowData;
  isActive: boolean;
  columns: string[];
  resultDates: Map<string, ResultCellValue>;
  onRowClick: (item: WatchlistItem) => void;
  onRemove: (id: number) => void;
  removing: boolean;
  flash: 'up' | 'down' | null;
  onAlertClick: (symbol: string) => void;
}

function WatchRow({ rowData, isActive, columns, resultDates, onRowClick, onRemove, removing, flash, onAlertClick }: WatchRowProps) {
  const { item, ltp, chgPct, oneWeek, oneMonth, threeMonth, sixMonth, oneYear, twoYear, threeYear, fiveYear, yearHigh, yearLow, fairValue, alertCount, symbolLoading, rangesLoading, fairValueLoading } = rowData;
  const isUp = (chgPct ?? 0) >= 0;
  const dash = <span className="text-zinc-500">—</span>;

  const renderCell = (col: string) => {
    switch (col) {
      case 'ltp':
        return symbolLoading ? dash : ltp != null ? (
          <span className={`text-white font-mono font-semibold tabular-nums ${flash === 'up' ? 'animate-flash-green' : flash === 'down' ? 'animate-flash-red' : ''}`}>
            {ltp.toFixed(2)}
          </span>
        ) : dash;
      case 'chg':
        return symbolLoading
          ? dash
          : chgPct != null
          ? (
              <span className={`px-1.5 py-0.5 rounded font-bold tabular-nums text-xs ${
                isUp ? 'text-terminal-green bg-emerald-500/10' : 'text-terminal-red bg-rose-500/10'
              }`}>
                {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
              </span>
            )
          : dash;
      case 'momentum': {
        if (rangesLoading) return dash;
        const periods = [
          { label: '1W', val: oneWeek },
          { label: '1M', val: oneMonth },
          { label: '3M', val: threeMonth },
          { label: '6M', val: sixMonth },
          { label: '1Y', val: oneYear },
        ];
        return (
          <div className="inline-flex items-center justify-center gap-0.5">
            {periods.map(({ label, val }) => {
              if (val == null || isNaN(val)) {
                return (
                  <span
                    key={label}
                    className="w-3.5 h-3.5 rounded-[2px] bg-zinc-800/80 text-zinc-500 text-[8px] flex items-center justify-center font-bold"
                    title={`${label}: —`}
                  >
                    -
                  </span>
                );
              }
              const isPeriodUp = val >= 0;
              return (
                <span
                  key={label}
                  className={`w-3.5 h-3.5 rounded-[2px] text-[8px] flex items-center justify-center font-bold border ${
                    isPeriodUp
                      ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40'
                      : 'bg-rose-500/20 text-rose-400 border-rose-500/40'
                  }`}
                  title={`${label}: ${isPeriodUp ? '+' : ''}${val.toFixed(1)}%`}
                >
                  {isPeriodUp ? '▲' : '▼'}
                </span>
              );
            })}
          </div>
        );
      }
      case '1w':
        return rangesLoading ? dash : formatRange(oneWeek);
      case '1m':
        return rangesLoading ? dash : formatRange(oneMonth);
      case '3m':
        return rangesLoading ? dash : formatRange(threeMonth);
      case '6m':
        return rangesLoading ? dash : formatRange(sixMonth);
      case '1y':
        return rangesLoading ? dash : formatRange(oneYear);
      case '2y':
        return rangesLoading ? dash : formatRange(twoYear);
      case '3y':
        return rangesLoading ? dash : formatRange(threeYear);
      case '5y':
        return rangesLoading ? dash : formatRange(fiveYear);
      case '52wh':
        return symbolLoading ? dash : formatPrice(yearHigh);
      case '52wl':
        return symbolLoading ? dash : formatPrice(yearLow);
      case 'msfv': {
        if (fairValueLoading) return dash;
        if (fairValue == null) return dash;
        const upsidePct = ltp != null && ltp > 0 ? ((fairValue - ltp) / ltp) * 100 : null;
        return (
          <div className="flex flex-col items-end leading-tight">
            <span className="text-terminal-amber font-bold tabular-nums">₹{fairValue.toFixed(2)}</span>
            {upsidePct != null && (
              <span className={`text-[9px] font-semibold tabular-nums ${upsidePct >= 0 ? 'text-terminal-green' : 'text-terminal-red'}`}>
                {upsidePct >= 0 ? `+${upsidePct.toFixed(1)}% Undervalued` : `${upsidePct.toFixed(1)}% Premium`}
              </span>
            )}
          </div>
        );
      }
      case 'results': {
        const result = resultDates.get(item.symbol.toUpperCase());
        if (!result) return dash;
        const isUpcoming = result.status === 'upcoming';
        return (
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold tabular-nums border ${
            isUpcoming
              ? 'text-terminal-green bg-emerald-500/10 border-emerald-500/30'
              : 'text-zinc-400 bg-zinc-800/80 border-zinc-700/50'
          }`}>
            {formatResultsDate(result.date)}
          </span>
        );
      }
      case 'alerts':
        return (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onAlertClick(item.symbol);
            }}
            title={`${alertCount} unread alert${alertCount !== 1 ? 's' : ''} in last 2 days — click to filter NOTIF panel`}
            className={`px-2 py-0.5 text-[10px] font-bold tabular-nums rounded transition-all cursor-pointer select-none inline-flex items-center gap-1 border ${
              alertCount > 0
                ? 'bg-terminal-amber/15 text-terminal-amber border-terminal-amber/40 hover:bg-terminal-amber hover:text-black hover:border-terminal-amber shadow-sm'
                : 'bg-zinc-800/60 text-zinc-500 border-zinc-700/40 hover:text-zinc-300'
            }`}
          >
            <span className="text-[9px]">🔔</span>
            <span>{alertCount > 0 ? alertCount : '—'}</span>
          </button>
        );
      default:
        return null;
    }
  };

  return (
    <tr
      onClick={() => onRowClick(item)}
      className={`border-b border-[#27272a]/70 hover:bg-zinc-900/60 cursor-pointer transition-colors ${
        isActive ? 'bg-terminal-amber/5 border-l-2 border-l-terminal-amber' : ''
      }`}
    >
      <td className="p-1 text-center border-r border-[#27272a]/50 w-7">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove(item.id);
          }}
          disabled={removing}
          className="text-zinc-500 hover:text-rose-400 text-xs font-bold transition-colors disabled:opacity-40 cursor-pointer"
          title="Remove"
        >
          ✕
        </button>
      </td>
      <td className="p-1.5 border-r border-[#27272a]/50 text-terminal-amber font-bold whitespace-nowrap">
        <span>{item.symbol}</span>
        <span className="text-zinc-400 text-[9px] bg-zinc-800/80 px-1 py-0.5 rounded ml-1.5 font-normal tracking-wide">{item.exchange}</span>
      </td>
      {columns.map((col) => {
        const isCenter = col === 'alerts' || col === 'results' || col === 'momentum';
        return (
          <td
            key={col}
            className={`p-1.5 border-r border-[#27272a]/50 ${isCenter ? 'text-center' : 'text-right'}`}
          >
            {renderCell(col)}
          </td>
        );
      })}
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
  const activePanels = useAtomValue(activePanelsAtom);
  const [, setNotifSymbolFilter] = useAtom(notifSymbolFilterAtom);

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

  const { data: eventCalendar = [] } = useQuery({
    queryKey: ['event-calendar'],
    queryFn: async () => {
      const res = await fetch('/api/event-calendar');
      if (!res.ok) return [] as EventCalendarItem[];
      return (await res.json()) as EventCalendarItem[];
    },
    staleTime: 900_000,
    refetchInterval: 900_000,
  });

  const { data: pastResults = [] } = useQuery({
    queryKey: ['event-calendar-past'],
    queryFn: async () => {
      const res = await fetch('/api/event-calendar/past');
      if (!res.ok) return [] as EventCalendarItem[];
      return (await res.json()) as EventCalendarItem[];
    },
    staleTime: 900_000,
    refetchInterval: 900_000,
  });

  const resultDates = React.useMemo(() => {
    const map = new Map<string, ResultCellValue>();
    for (const item of pastResults) {
      const purpose = item.purpose.toLowerCase();
      if (!purpose.includes('financial results')) continue;
      const symbol = item.symbol.toUpperCase();
      if (!map.has(symbol)) {
        map.set(symbol, { date: item.date, status: 'past' });
      }
    }
    for (const item of eventCalendar) {
      const purpose = item.purpose.toLowerCase();
      if (!purpose.includes('financial results') && !purpose.includes('dividend')) continue;
      const symbol = item.symbol.toUpperCase();
      map.set(symbol, { date: item.date, status: 'upcoming' });
    }
    return map;
  }, [eventCalendar, pastResults]);

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
  // ── Market data via WebSocket (change-ranges + symbol-data) ─────────────────
  // Replaces N parallel HTTP useQueries calls with a single batched WS request.
  const [symbolDataMap, setSymbolDataMap] = useState<Map<string, SymbolDataExtract>>(new Map());
  const [changeRangesMap, setChangeRangesMap] = useState<Map<string, ChangeRanges>>(new Map());
  // Track which symbols have received at least one response (for isLoading)
  const [symbolDataReceived, setSymbolDataReceived] = useState<Set<string>>(new Set());
  const [changeRangesReceived, setChangeRangesReceived] = useState<Set<string>>(new Set());

  // Subscribe to WS responses and issue requests when watchlist changes
  useEffect(() => {
    if (watchlist.length === 0) return;

    const symbols = watchlist.map((i) => i.symbol).filter(Boolean);

    // Subscribe to change-ranges responses
    const unsubRanges = marketDataService.onChangeRanges((symbol, data) => {
      if (data) {
        setChangeRangesMap((prev) => {
          const next = new Map(prev);
          next.set(symbol, data);
          return next;
        });
      }
      setChangeRangesReceived((prev) => {
        if (prev.has(symbol)) return prev;
        const next = new Set(prev);
        next.add(symbol);
        return next;
      });
    });

    // Subscribe to symbol-data responses — also populates global tickDataAtom
    const unsubSymbol = marketDataService.onSymbolData((symbol, data) => {
      if (data) {
        // Feed global tick data atom for OrderWidget / PosWidget consumers
        const exchange = watchlist.find((i) => i.symbol === symbol)?.exchange ?? 'NSE';
        setTickData((prev) => ({
          ...prev,
          [`${symbol}.${exchange}`]: { symbol, exchange, ltp: data.ltp, pChange: data.pChange, yearHigh: data.yearHigh, yearLow: data.yearLow, updatedAt: Date.now() },
        }));

        setSymbolDataMap((prev) => {
          const prevData = prev.get(symbol);
          const ltpChanged = prevData !== undefined && prevData.ltp !== data.ltp;
          // Trigger flash on LTP change
          if (ltpChanged) {
            const direction = data.ltp > prevData!.ltp ? 'up' : 'down';
            setFlashStates((fs) => {
              const next = new Map(fs);
              next.set(symbol, direction);
              return next;
            });
            setTimeout(() => {
              setFlashStates((fs) => {
                const next = new Map(fs);
                next.delete(symbol);
                return next;
              });
            }, 400);
          }
          const next = new Map(prev);
          next.set(symbol, data);
          return next;
        });
      }
      setSymbolDataReceived((prev) => {
        if (prev.has(symbol)) return prev;
        const next = new Set(prev);
        next.add(symbol);
        return next;
      });
    });

    // Request data for all symbols in this watchlist
    marketDataService.requestChangeRanges(symbols);
    marketDataService.requestSymbolData(symbols);

    // Periodic refresh matching original staleTime intervals
    const symbolDataInterval = setInterval(() => {
      marketDataService.requestSymbolData(symbols);
    }, 60_000);
    const changeRangesInterval = setInterval(() => {
      marketDataService.requestChangeRanges(symbols);
    }, 300_000);

    return () => {
      unsubRanges();
      unsubSymbol();
      clearInterval(symbolDataInterval);
      clearInterval(changeRangesInterval);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchlist.map((i) => i.symbol).join(',')]);

  const symbolsList = watchlist.map((i) => i.symbol).filter(Boolean);
  const fairValueBatchQuery = useQuery({
    queryKey: ['morningstar/fairvalue-batch', symbolsList],
    queryFn: async () => {
      if (symbolsList.length === 0) return {};
      const res = await fetch(`/api/py/morningstar/fairvalue/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: symbolsList }),
      });
      if (!res.ok) return {};
      const data = await res.json();
      return data as Record<string, { fairValue: number | null }>;
    },
    staleTime: 300_000,
    enabled: symbolsList.length > 0,
    placeholderData: keepPreviousData,
  });

  // Fetch unread notification counts for the active watchlist (2-day window).
  // A single query for all symbols — count per-symbol client-side to avoid N requests.
  const { data: notifCountData } = useQuery<Array<{ symbol: string }>>({
    queryKey: ['notifications-count', activeWatchlistId, 'unread'],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/notifications?watchlist_id=${activeWatchlistId}&days=2&read_filter=unread`,
      );
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });

  const alertCountMap = React.useMemo(() => {
    const map = new Map<string, number>();
    for (const n of notifCountData ?? []) {
      map.set(n.symbol, (map.get(n.symbol) ?? 0) + 1);
    }
    return map;
  }, [notifCountData]);

  // Cross-widget: set symbol filter on NotifWidget when NOTIF panel is open
  const handleAlertClick = useCallback(
    (symbol: string) => {
      const isNotifOpen = Object.values(activePanels).includes('NOTIF');
      if (isNotifOpen) setNotifSymbolFilter(symbol);
    },
    [activePanels, setNotifSymbolFilter],
  );

  // Build derived row data
  const rowDataList: WatchRowData[] = watchlist.map((item, idx) => {
    const quote = symbolDataMap.get(item.symbol);
    const ranges = changeRangesMap.get(item.symbol);
    const fvRaw = fairValueBatchQuery.data?.[item.symbol]?.fairValue;
    const fairValue = typeof fvRaw === 'number' ? fvRaw : typeof fvRaw === 'string' ? parseFloat(fvRaw) : null;

    const symbolLoading = !symbolDataReceived.has(item.symbol);
    const rangesLoading = !changeRangesReceived.has(item.symbol);

    return {
      item,
      ltp: quote?.ltp ?? null,
      chgPct: quote?.pChange ?? null,
      oneWeek: ranges?.oneWeekPercent ?? null,
      oneMonth: ranges?.oneMonthPercent ?? null,
      threeMonth: ranges?.threeMonthPercent ?? null,
      sixMonth: ranges?.sixMonthPercent ?? null,
      oneYear: ranges?.oneYearPercent ?? null,
      twoYear: ranges?.twoYearPercent ?? null,
      threeYear: ranges?.threeYearPercent ?? null,
      fiveYear: ranges?.fiveYearPercent ?? null,
      yearHigh: quote?.yearHigh ?? null,
      yearLow: quote?.yearLow ?? null,
      fairValue,
      alertCount: alertCountMap.get(item.symbol) ?? 0,
      symbolLoading,
      rangesLoading,
      fairValueLoading: fairValueBatchQuery.isLoading,
    };
  });

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
        case 'momentum':
          aVal = a.oneWeek;
          bVal = b.oneWeek;
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
        case 'results':
          aVal = resultDates.get(a.item.symbol.toUpperCase()) ?? null;
          bVal = resultDates.get(b.item.symbol.toUpperCase()) ?? null;
          break;
        case 'alerts':
          aVal = a.alertCount;
          bVal = b.alertCount;
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

  const advCount = rowDataList.filter((r) => (r.chgPct ?? 0) > 0).length;
  const decCount = rowDataList.filter((r) => (r.chgPct ?? 0) < 0).length;

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden relative bg-[#0a0a0a]">
      {/* Bento Toolbar Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-2.5 py-2 border-b border-[#27272a] bg-[#09090b] flex-shrink-0">
        {/* Watchlist selector */}
        <div className="flex items-center gap-1.5">
          <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider mr-0.5">LIST:</span>
          <div className="flex items-center gap-1 bg-[#141418] border border-[#27272a] rounded px-1.5 py-0.5">
            <select
              value={activeWatchlistId}
              onChange={(e) => setActiveWatchlistId(Number(e.target.value))}
              className="bg-transparent border-0 text-terminal-amber font-bold text-xs uppercase outline-none cursor-pointer pr-1"
            >
              {watchlists.map((wl) => (
                <option key={wl.id} value={wl.id} className="bg-[#141418] text-zinc-200">
                  {wl.name}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => setShowCreateModal(true)}
            className="text-terminal-amber hover:text-black hover:bg-terminal-amber text-xs font-bold border border-terminal-amber/50 hover:border-terminal-amber rounded px-2 py-0.5 transition-colors cursor-pointer"
            title="Create new watchlist"
          >
            +
          </button>
        </div>

        {/* Add symbol form */}
        <form
          onSubmit={handleAdd}
          className="flex items-center gap-1.5 flex-1 max-w-sm min-w-[240px]"
        >
          <input
            type="text"
            value={newExchange}
            onChange={(e) => setNewExchange(e.target.value.toUpperCase())}
            placeholder="NSE"
            className="w-11 bg-[#141418] border border-[#27272a] focus:border-terminal-amber text-terminal-amber font-bold px-1 py-1 uppercase text-center rounded text-xs outline-none transition-colors"
          />
          <div className="flex-1 relative">
            <input
              type="text"
              value={newSymbol}
              onChange={(e) => handleSymbolChange(e.target.value)}
              onKeyDown={handleKeyDown}
              onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
              placeholder="ADD SYMBOL (e.g. INFY)..."
              className="w-full bg-[#141418] border border-[#27272a] focus:border-terminal-amber text-white placeholder:text-zinc-600 px-2 py-1 uppercase rounded text-xs outline-none transition-colors"
            />
            {showDropdown && autocompleteResults.length > 0 && (
              <div className="absolute z-50 w-full bg-[#121216] border border-[#27272a] rounded shadow-2xl mt-1 max-h-48 overflow-auto">
                {autocompleteResults.slice(0, 10).map((result, index) => (
                  <div
                    key={result.symbol}
                    onClick={() => handleSelectResult(result)}
                    className={`px-2 py-1 cursor-pointer transition-colors flex items-center justify-between ${
                      index === activeIndex ? 'bg-zinc-800 text-terminal-amber' : 'text-zinc-300 hover:bg-zinc-800/80 hover:text-terminal-amber'
                    }`}
                  >
                    <span className="font-bold">{result.symbol}</span>
                    <span className="text-[10px] text-zinc-400 truncate max-w-[150px]">{result.companyName}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={addMutation.isPending}
            className="px-3 py-1 bg-terminal-amber hover:bg-amber-400 text-black font-bold border border-terminal-amber rounded text-xs disabled:opacity-50 transition-colors shadow-sm cursor-pointer whitespace-nowrap"
          >
            +ADD
          </button>
        </form>

        {/* Breadth & Sort Indicators */}
        <div className="hidden lg:flex items-center gap-2 text-[10px] text-zinc-400 pl-1 whitespace-nowrap">
          <span>SORT: <strong className="text-terminal-amber font-mono font-bold uppercase">{sortColumn ? `${sortColumn} (${sortDirection})` : 'DEFAULT'}</strong></span>
          <span>•</span>
          <span>ADV: <strong className="text-terminal-green font-bold">{advCount}</strong> / DEC: <strong className="text-terminal-red font-bold">{decCount}</strong></span>
        </div>
      </div>

      {/* Create watchlist modal */}
      {showCreateModal && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xs">
          <div className="bg-[#09090b] border border-terminal-amber/60 rounded p-4 w-72 shadow-2xl">
            <div className="text-terminal-amber font-bold mb-3 text-center text-sm tracking-wider">NEW WATCHLIST</div>
            <form onSubmit={handleCreateWatchlist}>
              <input
                type="text"
                value={newWatchlistName}
                onChange={(e) => setNewWatchlistName(e.target.value)}
                placeholder="NAME (LETTERS, HYPHEN)"
                maxLength={32}
                pattern="^[A-Za-z-]+$"
                className="w-full bg-[#141418] border border-[#27272a] focus:border-terminal-amber text-terminal-amber px-2 py-1.5 uppercase mb-3 rounded text-xs outline-none transition-colors"
                autoFocus
              />
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreateModal(false);
                    setNewWatchlistName('');
                  }}
                  className="px-2.5 py-1 text-zinc-300 border border-[#27272a] hover:bg-zinc-800 rounded text-xs transition-colors cursor-pointer"
                >
                  CANCEL
                </button>
                <button
                  type="submit"
                  disabled={createWatchlistMutation.isPending || !newWatchlistName.trim() || !/^[A-Za-z-]+$/.test(newWatchlistName.trim())}
                  className="px-3 py-1 bg-terminal-amber text-black font-bold hover:bg-amber-400 rounded text-xs disabled:opacity-50 transition-colors cursor-pointer"
                >
                  CREATE
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Watchlist table */}
      <div className="flex-1 overflow-auto bg-[#0a0a0a]">
        {isLoading && <div className="p-3 text-terminal-amber animate-pulse">LOADING WATCHLIST...</div>}
        {isError && <div className="p-3 text-terminal-red font-bold">FAILED TO LOAD WATCHLIST</div>}
        {!isLoading && !isError && (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse min-w-[700px]">
              <thead className="bg-[#121216] text-zinc-400 font-mono text-[11px] uppercase tracking-wider sticky top-0 z-10 border-b border-[#27272a]">
                <tr>
                  <th className="p-1.5 border-r border-[#27272a]/60 w-7 text-center">✕</th>
                  <th
                    onClick={() => handleHeaderClick('symbol')}
                    className="p-1.5 border-r border-[#27272a]/60 cursor-pointer hover:text-terminal-amber hover:bg-[#18181d] transition-colors whitespace-nowrap select-none"
                  >
                    SYMBOL{getSortIndicator('symbol')}
                  </th>
                  {watchlistColumns.map((col) => {
                    const colConfig = SORTABLE_COLUMNS[col];
                    return (
                      <th
                        key={col}
                        onClick={() => handleHeaderClick(colConfig?.key || (col as SortColumn))}
                        className={`p-1.5 border-r border-[#27272a]/60 cursor-pointer hover:text-terminal-amber hover:bg-[#18181d] transition-colors whitespace-nowrap select-none ${
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
                    resultDates={resultDates}
                    isActive={
                      activeSymbol === rowData.item.symbol &&
                      activeExchange === rowData.item.exchange
                    }
                    onRowClick={handleRowClick}
                    onRemove={(id) => removeMutation.mutate(id)}
                    removing={removeMutation.isPending && removeMutation.variables === rowData.item.id}
                    flash={flashStates.get(rowData.item.symbol) ?? null}
                    onAlertClick={handleAlertClick}
                  />
                ))}
                {watchlist.length === 0 && (
                  <tr>
                    <td
                      colSpan={watchlistColumns.length + 2}
                      className="p-6 text-zinc-400 text-center"
                    >
                      No symbols in this watchlist. Add one above.
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

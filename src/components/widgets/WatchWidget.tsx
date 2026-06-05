'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useQuery, useQueries, useMutation, useQueryClient } from '@tanstack/react-query';
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
import { marketWsService } from '@/lib/marketWs';
import type { ChangeRanges, SymbolDataExtract } from '@/lib/marketWs';
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
  isLoading: boolean;
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
  resultDates: Map<string, ResultCellValue>;
  onRowClick: (item: WatchlistItem) => void;
  onRemove: (id: number) => void;
  removing: boolean;
  flash: 'up' | 'down' | null;
  onAlertClick: (symbol: string) => void;
}

function WatchRow({ rowData, isActive, columns, resultDates, onRowClick, onRemove, removing, flash, onAlertClick }: WatchRowProps) {
  const { item, ltp, chgPct, oneWeek, oneMonth, threeMonth, sixMonth, oneYear, twoYear, threeYear, fiveYear, yearHigh, yearLow, fairValue, alertCount, isLoading } = rowData;
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
      case 'results': {
        const result = resultDates.get(item.symbol.toUpperCase());
        if (!result) return dash;
        return (
          <span className={result.status === 'upcoming' ? 'text-terminal-green font-semibold' : 'text-terminal-amber font-semibold'}>
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
            className="w-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-terminal-amber
              bg-zinc-600 hover:bg-zinc-500 active:bg-zinc-700
              border border-zinc-500
              shadow-[0_2px_0_#18181b,inset_0_1px_0_rgba(255,255,255,0.12)]
              active:shadow-[inset_0_2px_3px_rgba(0,0,0,0.45)] active:translate-y-px
              transition-colors select-none cursor-pointer rounded-sm"
          >
            {alertCount > 0 ? alertCount : '—'}
          </button>
        );
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
        <td
          key={col}
          className={`p-1 border-r border-terminal-gray ${col === 'alerts' ? 'text-center' : 'text-right'}`}
        >
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
    const unsubRanges = marketWsService.onChangeRanges((symbol, data) => {
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
    const unsubSymbol = marketWsService.onSymbolData((symbol, data) => {
      if (data) {
        // Feed global tick data atom for OrderWidget / PosWidget consumers
        const exchange = watchlist.find((i) => i.symbol === symbol)?.exchange ?? 'NSE';
        setTickData((prev) => ({
          ...prev,
          [`${symbol}.${exchange}`]: { symbol, exchange, ltp: data.ltp, pChange: data.pChange, yearHigh: data.yearHigh, yearLow: data.yearLow },
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
    marketWsService.requestChangeRanges(symbols);
    marketWsService.requestSymbolData(symbols);

    // Periodic refresh matching original staleTime intervals
    const symbolDataInterval = setInterval(() => {
      marketWsService.requestSymbolData(symbols);
    }, 60_000);
    const changeRangesInterval = setInterval(() => {
      marketWsService.requestChangeRanges(symbols);
    }, 300_000);

    return () => {
      unsubRanges();
      unsubSymbol();
      clearInterval(symbolDataInterval);
      clearInterval(changeRangesInterval);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchlist.map((i) => i.symbol).join(',')]);

  const fairValueQueries = useQueries({
    queries: watchlist.map((item) => ({
      queryKey: ['morningstar/fairvalue', item.symbol],
      queryFn: async () => {
        const res = await fetch(`/api/py/morningstar/fairvalue/${encodeURIComponent(item.symbol)}`);
        if (!res.ok) return null;
        const data = await res.json();
        const fv = data?.fairValue;
        return typeof fv === 'number' ? fv : typeof fv === 'string' ? parseFloat(fv) : null;
      },
      staleTime: 300_000,
      enabled: !!item.symbol,
    })),
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
    const fairValue = fairValueQueries[idx];

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
      fairValue: fairValue?.data ?? null,
      alertCount: alertCountMap.get(item.symbol) ?? 0,
      isLoading: symbolLoading || rangesLoading || (fairValue?.isLoading ?? false),
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

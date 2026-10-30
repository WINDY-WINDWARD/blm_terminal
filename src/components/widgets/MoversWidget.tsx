'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import {
  activeSymbolAtom,
  activeExchangeAtom,
  moversColumnOrderAtom,
  moversColumnsAtom,
  moversCategoryAtom,
} from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';
import type { ChangeRanges, SymbolDataExtract } from '@/lib/nseTypes';
import { reorderColumns, type ColumnDropPlacement } from '@/lib/columnOrder';
import {
  MOVER_COLUMN_LABELS,
  compareMoverRows,
  computeMoverAlignment,
  getMoverColumnDefaultDirection,
  getVisibleMoverColumns,
  type MoverColumnKey,
  type MoverQuoteData,
  type MoverView,
  type SortDirection,
} from '@/lib/moversColumns';

export interface MoverRow {
  symbol: string;
  close: string;
  pChange: number;
  open?: string;
  high?: string;
  low?: string;
  vol?: number;
  turnover?: number;
  caDate?: string;
  caPurpose?: string;
}

export interface TopMoverItem {
  symbol: string;
  lastPrice?: string | number;
  close?: string | number;
  ltp?: string | number;
  open_price?: string | number;
  high_price?: string | number;
  low_price?: string | number;
  pChange?: string | number;
  perChange?: string | number;
  trade_quantity?: string | number;
  turnover?: string | number;
  ca_ex_dt?: string;
  ca_purpose?: string;
}

interface MoverCategory {
  key: string;
  label: string;
}

const MOVERS_PAGE_SIZE = 6;

async function fetchTopMovers(
  category: string,
  type: 'gainers' | 'losers' = 'gainers'
): Promise<TopMoverItem[]> {
  const endpoint = type === 'losers' ? 'top-losers' : 'top-gainers';
  const res = await fetch(`/api/py/market/${endpoint}?category=${encodeURIComponent(category)}`);
  if (!res.ok) throw new Error(`Failed to fetch top ${type}`);
  return res.json();
}

function formatPrice(val: number): string {
  return val.toFixed(2);
}

function formatChange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-zinc-400">&mdash;</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-emerald-400 font-bold tabular-nums' : 'text-rose-400 font-bold tabular-nums'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
}

function formatRange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-zinc-400">&mdash;</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-emerald-400 tabular-nums' : 'text-rose-400 tabular-nums'}>
      {isUp ? '+' : ''}{val.toFixed(1)}%
    </span>
  );
}

function formatPriceCell(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-zinc-400">&mdash;</span>;
  return <span className="tabular-nums">{val.toFixed(2)}</span>;
}

function formatPriceStr(val: string | undefined): React.ReactNode {
  if (!val || val === '—') return <span className="text-zinc-400">&mdash;</span>;
  return <span className="tabular-nums">{val}</span>;
}

function formatVol(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val) || val === 0) return <span className="text-zinc-400">&mdash;</span>;
  if (val >= 1_00_00_000) return <span className="tabular-nums">{(val / 1_00_00_000).toFixed(1)}Cr</span>;
  if (val >= 1_00_000) return <span className="tabular-nums">{(val / 1_00_000).toFixed(1)}L</span>;
  return <span className="tabular-nums">{(val / 1000).toFixed(1)}K</span>;
}

function formatTurnover(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val) || val === 0) return <span className="text-zinc-400">&mdash;</span>;
  return <span className="tabular-nums">&#8377;{(val).toFixed(0)}Cr</span>;
}

function formatCaDt(val: string | undefined, purpose: string | undefined): React.ReactNode {
  if (!val || val === '-') return <span className="text-zinc-400">&mdash;</span>;
  return <span title={purpose || ''}>{val}</span>;
}

function useMoverMarketData(symbols: string[], needsRanges: boolean, needsQuotes: boolean) {
  const symbolsKey = symbols.join('|');
  const [rangesBySymbol, setRangesBySymbol] = useState<Record<string, ChangeRanges | null>>({});
  const [quotesBySymbol, setQuotesBySymbol] = useState<Record<string, MoverQuoteData | null>>({});

  useEffect(() => {
    const activeSymbols = symbolsKey ? symbolsKey.split('|') : [];
    if (activeSymbols.length === 0) return;
    const activeSet = new Set(activeSymbols);
    let unsubscribeRanges: (() => void) | undefined;
    let unsubscribeQuotes: (() => void) | undefined;

    if (needsRanges) {
      unsubscribeRanges = marketDataService.onChangeRanges((symbol, data) => {
        if (!activeSet.has(symbol)) return;
        setRangesBySymbol((current) => ({ ...current, [symbol]: data }));
      });
      marketDataService.requestChangeRanges(activeSymbols);
    }

    if (needsQuotes) {
      unsubscribeQuotes = marketDataService.onSymbolData((symbol, data: SymbolDataExtract | null) => {
        if (!activeSet.has(symbol)) return;
        setQuotesBySymbol((current) => ({
          ...current,
          [symbol]: data ? { yearHigh: data.yearHigh, yearLow: data.yearLow } : null,
        }));
      });
      marketDataService.requestSymbolData(activeSymbols);
    }

    return () => {
      unsubscribeRanges?.();
      unsubscribeQuotes?.();
    };
  }, [symbolsKey, needsRanges, needsQuotes]);

  return {
    rangesBySymbol,
    quotesBySymbol,
    isRangesLoading: (symbol: string) => needsRanges && !Object.prototype.hasOwnProperty.call(rangesBySymbol, symbol),
    isQuoteLoading: (symbol: string) => needsQuotes && !Object.prototype.hasOwnProperty.call(quotesBySymbol, symbol),
  };
}

function useMoverCategories() {
  return useQuery<MoverCategory[]>({
    queryKey: ['market/movers-categories'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/movers-categories');
      if (!res.ok) return [];
      return res.json();
    },
    staleTime: 86_400_000,
  });
}

const DEFAULT_CATEGORIES: MoverCategory[] = [
  { key: 'allSec', label: 'ALL MKT' },
  { key: 'NIFTY', label: 'NIFTY 50' },
  { key: 'BANKNIFTY', label: 'NIFTY BANK' },
  { key: 'NIFTYNEXT50', label: 'NEXT 50' },
  { key: 'FOSec', label: 'F&O' },
  { key: 'SecGtr20', label: '>₹20' },
  { key: 'SecLwr20', label: '<₹20' },
];

const VIEW_ACTIVE_CLASSES: Record<MoverView, string> = {
  matrix: 'border-terminal-amber bg-terminal-amber text-black shadow-[0_0_8px_rgba(245,158,11,0.3)]',
  gainers: 'border-emerald-300 bg-emerald-400 text-black shadow-[0_0_8px_rgba(52,211,153,0.25)]',
  losers: 'border-rose-300 bg-rose-400 text-black shadow-[0_0_8px_rgba(251,113,133,0.25)]',
};

const VIEW_INACTIVE_CLASSES: Record<MoverView, string> = {
  matrix: 'border-transparent text-terminal-amber/70 hover:bg-terminal-amber/10 hover:text-terminal-amber',
  gainers: 'border-transparent text-emerald-400/70 hover:bg-emerald-500/10 hover:text-emerald-400',
  losers: 'border-transparent text-rose-400/70 hover:bg-rose-500/10 hover:text-rose-400',
};

const VIEW_DOT_CLASSES: Record<MoverView, string> = {
  matrix: 'bg-terminal-amber',
  gainers: 'bg-emerald-400',
  losers: 'bg-rose-400',
};

const COLUMN_VISIBILITY: Partial<Record<MoverColumnKey, string>> = {
  velocity: 'hidden @3xl:table-cell',
  radar: 'hidden @3xl:table-cell',
  vol: 'hidden @3xl:table-cell',
  trnvr: 'hidden @4xl:table-cell',
  open: 'hidden @4xl:table-cell',
  high: 'hidden @4xl:table-cell',
  low: 'hidden @4xl:table-cell',
  ca: 'hidden @4xl:table-cell',
  '2y': 'hidden @4xl:table-cell',
  '3y': 'hidden @4xl:table-cell',
  '5y': 'hidden @4xl:table-cell',
  '52wh': 'hidden @4xl:table-cell',
  '52wl': 'hidden @4xl:table-cell',
};

const CATEGORY_SHORT_LABELS: Record<string, string> = {
  allSec: 'ALL MKT',
  NIFTY: 'NIFTY 50',
  BANKNIFTY: 'NIFTY BANK',
  NIFTYNEXT50: 'NEXT 50',
  NIFTYIT: 'NIFTY IT',
  SecGtr20: '>₹20',
  SecLwr20: '<₹20',
  FOSec: 'F&O',
};

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&#8377;/g, '₹');
}

function mapItemToRow(item: TopMoverItem): MoverRow {
  return {
    symbol: item.symbol,
    close: formatPrice(parseFloat(String(item.ltp || item.close || item.lastPrice || '0'))),
    pChange: parseFloat(String(item.perChange || item.pChange || '0')),
    open: item.open_price != null ? formatPrice(parseFloat(String(item.open_price))) : undefined,
    high: item.high_price != null ? formatPrice(parseFloat(String(item.high_price))) : undefined,
    low: item.low_price != null ? formatPrice(parseFloat(String(item.low_price))) : undefined,
    vol: item.trade_quantity != null ? Number(item.trade_quantity) : undefined,
    turnover: item.turnover != null ? Number(item.turnover) : undefined,
    caDate: item.ca_ex_dt,
    caPurpose: item.ca_purpose,
  };
}

interface HeatSegment {
  label: '1W' | '1M' | '3M' | '6M' | '1Y';
  value: number | null | undefined;
}

function MomentumHeatStrip({
  ranges,
  pChange: _pChange,
}: {
  ranges: ChangeRanges | null;
  pChange?: number;
}) {
  const segments: HeatSegment[] = [
    { label: '1W', value: ranges?.oneWeekPercent },
    { label: '1M', value: ranges?.oneMonthPercent },
    { label: '3M', value: ranges?.threeMonthPercent },
    { label: '6M', value: ranges?.sixMonthPercent },
    { label: '1Y', value: ranges?.oneYearPercent },
  ];

  return (
    <div className="flex items-center justify-center gap-1 flex-wrap sm:flex-nowrap">
      {segments.map((seg) => {
        const hasVal = seg.value != null && !Number.isNaN(seg.value);
        if (!hasVal) {
          return (
            <div
              key={seg.label}
              title={`${seg.label}: Awaiting data`}
              className="px-1.5 py-0.5 rounded text-[10px] font-mono tabular-nums border text-zinc-500 bg-[#121216] border-[#27272a] whitespace-nowrap"
            >
              {seg.label} —
            </div>
          );
        }

        const effectiveVal = seg.value as number;
        const isUp = effectiveVal >= 0;
        const arrow = isUp ? '▲' : '▼';
        const sign = isUp ? '+' : '';
        const formatted =
          Math.abs(effectiveVal) >= 10
            ? `${sign}${effectiveVal.toFixed(0)}%`
            : `${sign}${effectiveVal.toFixed(1)}%`;

        const pillTone = isUp
          ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
          : 'text-rose-400 bg-rose-500/10 border-rose-500/30';

        return (
          <div
            key={seg.label}
            title={`${seg.label}: ${sign}${effectiveVal.toFixed(2)}%`}
            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold tabular-nums border whitespace-nowrap transition-transform hover:scale-105 ${pillTone}`}
          >
            {arrow} {seg.label} {formatted}
          </div>
        );
      })}
    </div>
  );
}

interface MoverRowProps {
  row: MoverRow;
  columns: MoverColumnKey[];
  ranges: ChangeRanges | null;
  rangesLoading: boolean;
  quote: MoverQuoteData | null;
  quoteLoading: boolean;
  onClick: () => void;
}

interface TopMoversRowProps extends MoverRowProps {
  rank: number;
}

function moverCellClass(column: MoverColumnKey): string {
  const alignment = column === 'ticker'
    ? 'text-left'
    : column === 'momentum' || column === 'velocity' || column === 'radar'
      ? 'text-center'
      : 'text-right';
  return `py-1.5 px-1.5 @3xl:py-2 @3xl:px-2 border-r border-[#27272a]/50 ${alignment} ${COLUMN_VISIBILITY[column] ?? ''}`;
}

function renderMoverCell({
  row,
  column,
  ranges,
  rangesLoading,
  quote,
  quoteLoading,
  rank,
  showBias,
}: Omit<MoverRowProps, 'columns' | 'onClick'> & {
  column: MoverColumnKey;
  rank?: number;
  showBias?: boolean;
}) {
  const dash = <span className="text-zinc-400">&mdash;</span>;
  const alignment = computeMoverAlignment(ranges, row.pChange);
  const isPositive = row.pChange >= 0;

  switch (column) {
    case 'ticker':
      return (
        <div className="flex items-center gap-2">
          {rank != null && <span className="text-zinc-400">#{rank}</span>}
          <span className="font-bold text-white transition-colors">
            {row.symbol}
          </span>
          {showBias && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-bold ${
                isPositive ? 'text-emerald-400 bg-emerald-500/10' : 'text-rose-400 bg-rose-500/10'
              }`}
            >
              {isPositive ? 'BULL' : 'BEAR'}
            </span>
          )}
        </div>
      );
    case 'ltp':
      return <span className="font-bold text-white tabular-nums">&#8377;{row.close}</span>;
    case 'chg':
      return formatChange(row.pChange);
    case 'momentum':
      return rangesLoading ? dash : <MomentumHeatStrip ranges={ranges} pChange={row.pChange} />;
    case 'velocity':
      if (rangesLoading) return dash;
      return (
        <div
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border ${
            alignment.velocity >= 70
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : alignment.velocity >= 45
              ? 'bg-terminal-amber/10 border-terminal-amber/30 text-terminal-amber'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
          }`}
        >
          <span className="font-extrabold text-xs tabular-nums">{alignment.velocity} / 100</span>
        </div>
      );
    case 'vol':
      return <span className="font-bold text-terminal-amber tabular-nums">{formatVol(row.vol)}</span>;
    case 'trnvr':
      return <span className="font-bold text-terminal-amber tabular-nums">{formatTurnover(row.turnover)}</span>;
    case 'radar':
      if (rangesLoading) return dash;
      return (
        <span className={`text-[10px] font-bold px-2 py-0.5 rounded border whitespace-nowrap ${alignment.badgeClass}`}>
          {alignment.label}
        </span>
      );
    case 'open':
      return formatPriceStr(row.open);
    case 'high':
      return formatPriceStr(row.high);
    case 'low':
      return formatPriceStr(row.low);
    case 'ca':
      return formatCaDt(row.caDate, row.caPurpose);
    case '2y':
      return rangesLoading ? dash : formatRange(ranges?.twoYearPercent);
    case '3y':
      return rangesLoading ? dash : formatRange(ranges?.threeYearPercent);
    case '5y':
      return rangesLoading ? dash : formatRange(ranges?.fiveYearPercent);
    case '52wh':
      return quoteLoading ? dash : formatPriceCell(quote?.yearHigh);
    case '52wl':
      return quoteLoading ? dash : formatPriceCell(quote?.yearLow);
    default:
      return null;
  }
}

function TopMoversRow({ row, rank, columns, ranges, rangesLoading, quote, quoteLoading, onClick }: TopMoversRowProps) {
  return (
    <tr onClick={onClick} className="cursor-pointer border-b border-[#27272a]/60 hover:bg-[#14141a] transition-colors">
      {columns.map((column) => (
        <td key={column} className={moverCellClass(column)}>
          {renderMoverCell({ row, column, ranges, rangesLoading, quote, quoteLoading, rank })}
        </td>
      ))}
    </tr>
  );
}

function MomentumMatrixRow({ row, columns, ranges, rangesLoading, quote, quoteLoading, onClick }: MoverRowProps) {
  return (
    <tr
      onClick={onClick}
      className="hover:bg-[#14141a] transition-colors cursor-pointer group border-b border-[#27272a]/50"
    >
      {columns.map((column) => (
        <td key={column} className={moverCellClass(column)}>
          {renderMoverCell({ row, column, ranges, rangesLoading, quote, quoteLoading, showBias: true })}
        </td>
      ))}
    </tr>
  );
}

export function MoversWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [moversColumns] = useAtom(moversColumnsAtom);
  const [moversColumnOrder, setMoversColumnOrder] = useAtom(moversColumnOrderAtom);
  const [moversCategory, setMoversCategory] = useAtom(moversCategoryAtom);

  const [activeView, setActiveView] = useState<MoverView>('matrix');
  const [page, setPage] = useState(0);
  const [sortState, setSortState] = useState<{ key: MoverColumnKey; direction: SortDirection }>({
    key: 'chg',
    direction: 'desc',
  });
  const [searchQuery, setSearchQuery] = useState('');
  const [draggedColumn, setDraggedColumn] = useState<MoverColumnKey | null>(null);
  const [columnDropTarget, setColumnDropTarget] = useState<{ key: MoverColumnKey; placement: ColumnDropPlacement } | null>(null);
  const suppressColumnClickRef = useRef(false);

  const { data: categories = [] } = useMoverCategories();

  const { data: gainers = [], isLoading: gainersLoading } = useQuery<TopMoverItem[]>({
    queryKey: ['market/top-gainers', moversCategory],
    queryFn: () => fetchTopMovers(moversCategory, 'gainers'),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: losers = [], isLoading: losersLoading } = useQuery<TopMoverItem[]>({
    queryKey: ['market/top-losers', moversCategory],
    queryFn: () => fetchTopMovers(moversCategory, 'losers'),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const gainerRows: MoverRow[] = useMemo(() => gainers.map(mapItemToRow), [gainers]);
  const loserRows: MoverRow[] = useMemo(() => losers.map(mapItemToRow), [losers]);

  const displayCategories = categories.length > 0 ? categories : DEFAULT_CATEGORIES;
  const visibleColumns = useMemo(
    () => getVisibleMoverColumns(moversColumnOrder, activeView, moversColumns),
    [moversColumnOrder, activeView, moversColumns],
  );

  const filteredGainers = useMemo(() => {
    if (!searchQuery.trim()) return gainerRows;
    const q = searchQuery.trim().toUpperCase();
    return gainerRows.filter((r) => r.symbol.toUpperCase().includes(q));
  }, [gainerRows, searchQuery]);

  const filteredLosers = useMemo(() => {
    if (!searchQuery.trim()) return loserRows;
    const q = searchQuery.trim().toUpperCase();
    return loserRows.filter((r) => r.symbol.toUpperCase().includes(q));
  }, [loserRows, searchQuery]);

  const matrixRows = useMemo(() => {
    const map = new Map<string, MoverRow>();
    for (const r of filteredGainers) map.set(r.symbol, r);
    for (const r of filteredLosers) map.set(r.symbol, r);
    return Array.from(map.values());
  }, [filteredGainers, filteredLosers]);

  const activeRows = activeView === 'gainers'
    ? filteredGainers
    : activeView === 'losers'
      ? filteredLosers
      : matrixRows;
  const activeSymbols = useMemo(() => activeRows.map((row) => row.symbol), [activeRows]);
  const needsRanges = visibleColumns.some((column) => ['momentum', 'velocity', 'radar', '2y', '3y', '5y'].includes(column))
    || ['momentum', 'velocity', 'radar', '2y', '3y', '5y'].includes(sortState.key);
  const needsQuotes = visibleColumns.some((column) => column === '52wh' || column === '52wl')
    || sortState.key === '52wh'
    || sortState.key === '52wl';
  const {
    rangesBySymbol,
    quotesBySymbol,
    isRangesLoading,
    isQuoteLoading,
  } = useMoverMarketData(activeSymbols, needsRanges, needsQuotes);

  const orderedRows = useMemo(() => (
    [...activeRows].sort((a, b) => compareMoverRows(
      a,
      b,
      sortState.key,
      sortState.direction,
      rangesBySymbol,
      quotesBySymbol,
    ))
  ), [activeRows, sortState, rangesBySymbol, quotesBySymbol]);

  const pageCount = Math.max(1, Math.ceil(orderedRows.length / MOVERS_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pagedRows = orderedRows.slice(
    currentPage * MOVERS_PAGE_SIZE,
    (currentPage + 1) * MOVERS_PAGE_SIZE,
  );

  const handleViewChange = (view: MoverView) => {
    setActiveView(view);
    setPage(0);
    setSortState({ key: 'chg', direction: view === 'losers' ? 'asc' : 'desc' });
  };

  const handleHeaderClick = (column: MoverColumnKey) => {
    if (suppressColumnClickRef.current) return;
    setSortState((current) => current.key === column
      ? { key: column, direction: current.direction === 'asc' ? 'desc' : 'asc' }
      : { key: column, direction: getMoverColumnDefaultDirection(column) });
    setPage(0);
  };

  const handleColumnDragStart = (event: React.DragEvent<HTMLTableCellElement>, key: MoverColumnKey) => {
    suppressColumnClickRef.current = true;
    setDraggedColumn(key);
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', key);
  };

  const handleColumnDragOver = (event: React.DragEvent<HTMLTableCellElement>, key: MoverColumnKey) => {
    if (!draggedColumn || draggedColumn === key) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    const rect = event.currentTarget.getBoundingClientRect();
    const placement: ColumnDropPlacement = event.clientX < rect.left + rect.width / 2 ? 'before' : 'after';
    setColumnDropTarget((current) => (
      current?.key === key && current.placement === placement ? current : { key, placement }
    ));
  };

  const clearColumnDrag = () => {
    setDraggedColumn(null);
    setColumnDropTarget(null);
    window.setTimeout(() => {
      suppressColumnClickRef.current = false;
    }, 0);
  };

  const handleColumnDrop = (event: React.DragEvent<HTMLTableCellElement>, key: MoverColumnKey) => {
    event.preventDefault();
    if (!draggedColumn || draggedColumn === key) {
      clearColumnDrag();
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const placement: ColumnDropPlacement = columnDropTarget?.key === key
      ? columnDropTarget.placement
      : event.clientX < rect.left + rect.width / 2
        ? 'before'
        : 'after';
    setMoversColumnOrder((current) => reorderColumns(current, draggedColumn, key, placement));
    clearColumnDrag();
  };

  const handleRowClick = (row: MoverRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
  };

  const handleCategoryChange = (category: string) => {
    setMoversCategory(category);
    setPage(0);
  };

  if (gainersLoading || losersLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-white bg-[#09090b] gap-2 p-4">
        <span className="text-terminal-amber font-bold uppercase tracking-wider animate-pulse">
          Loading movers...
        </span>
      </div>
    );
  }

  if (gainerRows.length === 0 && loserRows.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-white bg-[#09090b] gap-2 p-4">
        <span className="text-zinc-300">No data available.</span>
      </div>
    );
  }

  return (
    <div data-testid="movers-widget" className="h-full w-full flex flex-col font-mono text-xs bg-[#09090b] text-zinc-100 overflow-hidden">
      {/* Timeframe & Category Selector Toolbar */}
      <div className="bg-[#0c0c0f] border-b border-[#27272a] px-3 py-2.5 flex flex-wrap items-center justify-between gap-2.5 flex-shrink-0">
        {/* Category Selector Pills bound to moversCategoryAtom */}
        <div data-widget-tour="movers-universe-bar" className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-terminal-amber mr-1">
            UNIVERSE:
          </span>
          <div className="flex flex-wrap items-center gap-1 bg-[#121216] p-1 rounded border border-[#27272a]">
            {displayCategories.map((cat) => {
              const isSelected = moversCategory === cat.key;
              return (
                <button
                  key={cat.key}
                  onClick={() => handleCategoryChange(cat.key)}
                  className={`px-2.5 py-1 rounded text-[11px] font-mono font-bold uppercase tracking-wider transition-all cursor-pointer ${
                    isSelected
                      ? 'bg-terminal-amber text-black border border-terminal-amber shadow-[0_0_8px_rgba(245,158,11,0.3)]'
                      : 'text-zinc-300 hover:text-white hover:bg-zinc-800/70 border border-transparent'
                  }`}
                >
                  {CATEGORY_SHORT_LABELS[cat.key] || decodeHtmlEntities(cat.label)}
                </button>
              );
            })}
          </div>
        </div>

        {/* Quick Filter */}
        <div className="flex items-center gap-2">
          <input
            data-widget-tour="movers-filter-input"
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter ticker..."
            className="w-48 bg-[#121216] border border-[#27272a] focus:border-terminal-amber text-xs text-white px-2.5 py-1 rounded outline-none placeholder:text-zinc-400 font-mono transition-colors"
          />
        </div>
      </div>

      {/* 4-Column Bento Matrix */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
        {/* =================================================================== */}
        {/* CARD 1: MULTI-PERIOD MOMENTUM MATRIX (col-span-1 md:col-span-4 lg:col-span-4) */}
        {/* =================================================================== */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border border-[#27272a] bg-[#0c0c0f] p-2.5 shadow-md transition-colors hover:border-zinc-600 sm:p-3">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 mb-2.5 border-b border-[#27272a]/70">
            <div className="flex flex-wrap items-center gap-2">
              <span data-testid="movers-active-view" className="flex items-center gap-1.5 text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                <span className={`w-2 h-2 rounded-full ${VIEW_DOT_CLASSES[activeView]}`} />
                {activeView === 'matrix' ? 'Multi-Period Momentum Matrix' : activeView === 'gainers' ? 'Top Gainers' : 'Top Losers'}
              </span>
              <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-2 py-0.5 rounded border border-[#27272a]">
                {activeView === 'matrix' ? '1W • 1M • 3M • 6M • 1Y RETURN ALIGNMENT' : `${activeRows.length} SYMBOLS`}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">VIEW:</span>
              <div
                role="tablist"
                aria-label="Movers views"
                data-widget-tour="movers-view-tabs"
                className="flex items-center gap-1 rounded-md border border-[#27272a] bg-[#121216] p-1"
              >
                {(['matrix', 'gainers', 'losers'] as MoverView[]).map((view) => (
                  <button
                    key={view}
                    type="button"
                    role="tab"
                    aria-selected={activeView === view}
                    data-active={activeView === view}
                    onClick={() => handleViewChange(view)}
                    className={`rounded border px-2.5 py-1.5 text-[11px] font-bold uppercase transition-colors ${
                      activeView === view
                        ? VIEW_ACTIVE_CLASSES[view]
                        : VIEW_INACTIVE_CLASSES[view]
                    }`}
                  >
                    {view}
                  </button>
                ))}
              </div>
              {activeView === 'matrix' && (
                <>
                  <span className="ml-1 text-[10px] font-bold uppercase tracking-wider text-zinc-500">SORT:</span>
                  <button
                    type="button"
                    aria-pressed={sortState.key === 'chg' && sortState.direction === 'desc'}
                    onClick={() => { setSortState({ key: 'chg', direction: 'desc' }); setPage(0); }}
                    className={`rounded border px-2.5 py-1.5 text-[11px] font-bold whitespace-nowrap ${sortState.key === 'chg' && sortState.direction === 'desc' ? 'border-emerald-300 bg-emerald-400 text-black' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'}`}
                  >
                    ▲ Gains
                  </button>
                  <button
                    type="button"
                    aria-pressed={sortState.key === 'chg' && sortState.direction === 'asc'}
                    onClick={() => { setSortState({ key: 'chg', direction: 'asc' }); setPage(0); }}
                    className={`rounded border px-2.5 py-1.5 text-[11px] font-bold whitespace-nowrap ${sortState.key === 'chg' && sortState.direction === 'asc' ? 'border-rose-300 bg-rose-400 text-black' : 'border-rose-500/30 bg-rose-500/10 text-rose-400'}`}
                  >
                    ▼ Drops
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
            <table data-testid="movers-matrix-table" className="w-full border-collapse text-left font-mono tabular-nums">
              <thead
                data-widget-tour="movers-matrix-columns"
                className="sticky top-0 z-10 border-b border-[#27272a] bg-[#121216] text-[10px] uppercase tracking-wider text-zinc-400"
              >
                <tr>
                  {visibleColumns.map((column) => {
                    const isSorted = sortState.key === column;
                    const label = column === 'ticker' && activeView !== 'matrix'
                      ? 'Rank & Ticker'
                      : MOVER_COLUMN_LABELS[column];
                    const alignment = column === 'ticker'
                      ? 'text-left'
                      : ['momentum', 'velocity', 'radar'].includes(column)
                        ? 'text-center'
                        : 'text-right';
                    const dropPlacement = columnDropTarget?.key === column ? columnDropTarget.placement : null;

                    return (
                      <th
                        key={column}
                        scope="col"
                        data-column-key={column}
                        draggable
                        aria-label={label}
                        aria-sort={isSorted ? (sortState.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
                        onClick={() => handleHeaderClick(column)}
                        onDragStart={(event) => handleColumnDragStart(event, column)}
                        onDragOver={(event) => handleColumnDragOver(event, column)}
                        onDrop={(event) => handleColumnDrop(event, column)}
                        onDragEnd={clearColumnDrag}
                        title={`${label} — click to sort, drag to reorder`}
                        className={`relative cursor-grab select-none whitespace-nowrap border-b border-r border-[#27272a] px-1.5 py-1.5 @3xl:px-2 @3xl:py-2 font-bold transition-colors active:cursor-grabbing ${alignment} ${COLUMN_VISIBILITY[column] ?? ''} ${
                          isSorted ? 'text-terminal-amber' : 'text-zinc-400 hover:text-zinc-200'
                        } ${draggedColumn === column ? 'opacity-40' : ''}`}
                      >
                        <span aria-hidden className="mr-1 text-[9px] text-zinc-600">⠿</span>
                        <span>{label}</span>
                        {isSorted && (
                          <span className="ml-1 text-terminal-amber" aria-hidden>
                            {sortState.direction === 'asc' ? '▲' : '▼'}
                          </span>
                        )}
                        {dropPlacement && (
                          <span
                            aria-hidden
                            data-drop-indicator={dropPlacement}
                            className={`pointer-events-none absolute inset-y-0 w-0.5 bg-terminal-amber ${
                              dropPlacement === 'before' ? '-left-px' : '-right-px'
                            }`}
                          />
                        )}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="text-xs">
                {pagedRows.map((row, index) => activeView === 'matrix' ? (
                  <MomentumMatrixRow
                    key={`matrix-${row.symbol}`}
                    row={row}
                    columns={visibleColumns}
                    ranges={rangesBySymbol[row.symbol] ?? null}
                    rangesLoading={isRangesLoading(row.symbol)}
                    quote={quotesBySymbol[row.symbol] ?? null}
                    quoteLoading={isQuoteLoading(row.symbol)}
                    onClick={() => handleRowClick(row)}
                  />
                ) : (
                  <TopMoversRow
                    key={`${activeView}-${row.symbol}`}
                    row={row}
                    rank={currentPage * MOVERS_PAGE_SIZE + index + 1}
                    columns={visibleColumns}
                    ranges={rangesBySymbol[row.symbol] ?? null}
                    rangesLoading={isRangesLoading(row.symbol)}
                    quote={quotesBySymbol[row.symbol] ?? null}
                    quoteLoading={isQuoteLoading(row.symbol)}
                    onClick={() => handleRowClick(row)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div
            data-widget-tour="movers-pagination-controls"
            className="flex shrink-0 items-center justify-between gap-2 border-t border-[#27272a] px-2.5 py-2 text-zinc-300 sm:px-3"
          >
            <span className="font-mono text-[11px] tabular-nums" aria-live="polite">
              PAGE {currentPage + 1} OF {pageCount} · {orderedRows.length} ROWS
            </span>
            <div className="flex gap-1.5">
              <button type="button" aria-label="Previous page" onClick={() => setPage((previous) => Math.max(0, previous - 1))} disabled={currentPage === 0} className="rounded border border-[#3f3f46] bg-[#121216] px-2.5 py-1.5 text-[11px] font-bold text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40">← PREV</button>
              <button type="button" aria-label="Next page" onClick={() => setPage((previous) => Math.min(pageCount - 1, previous + 1))} disabled={currentPage >= pageCount - 1} className="rounded border border-[#3f3f46] bg-[#121216] px-2.5 py-1.5 text-[11px] font-bold text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40">NEXT →</button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

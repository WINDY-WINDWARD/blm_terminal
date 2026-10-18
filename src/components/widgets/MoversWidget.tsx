'use client';

import React, { useState, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import {
  activeSymbolAtom,
  activeExchangeAtom,
  moversColumnsAtom,
  moversCategoryAtom,
} from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';
import type { ChangeRanges, SymbolDataExtract } from '@/lib/nseTypes';

export interface MoverQuote {
  yearHigh?: number;
  yearLow?: number;
}

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

type MoversView = 'matrix' | 'gainers' | 'losers';

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

/**
 * Per-symbol hook: returns change-ranges data via the market WebSocket service.
 * The service debounces concurrent calls from multiple rows into one WS message.
 */
function useChangeRanges(symbol: string) {
  const [data, setData] = useState<ChangeRanges | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!symbol) return;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsLoading(true);

    const unsub = marketDataService.onChangeRanges((sym, rangesData) => {
      if (sym !== symbol) return;
      setData(rangesData);
      setIsLoading(false);
    });

    marketDataService.requestChangeRanges([symbol]);

    return unsub;
  }, [symbol]);

  return { data, isLoading };
}

/**
 * Per-symbol hook: returns symbol-data (52w high/low) via the market WebSocket service.
 * Only requests data when enabled (i.e. when 52w columns are visible).
 */
function useMoverQuote(symbol: string, enabled: boolean) {
  const [data, setData] = useState<MoverQuote | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!symbol || !enabled) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setIsLoading(false);
      return;
    }

    setIsLoading(true);

    const unsub = marketDataService.onSymbolData((sym, symData: SymbolDataExtract | null) => {
      if (sym !== symbol) return;
      setData(symData ? { yearHigh: symData.yearHigh, yearLow: symData.yearLow } : null);
      setIsLoading(false);
    });

    marketDataService.requestSymbolData([symbol]);

    return unsub;
  }, [symbol, enabled]);

  return { data, isLoading };
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

const COLUMN_LABELS: Record<string, string> = {
  close: 'CLOSE',
  chg: 'CHG%',
  open: 'OPEN',
  high: 'HIGH',
  low: 'LOW',
  vol: 'VOL',
  trnvr: 'TRNVR',
  ca: 'CA',
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

function computeAlignmentMeta(ranges: ChangeRanges | null, pChange: number) {
  if (!ranges) {
    return {
      bullCount: 0,
      velocity: 50,
      label: 'AWAITING RANGES',
      badgeClass: 'text-zinc-400 bg-zinc-800/40 border-zinc-700',
    };
  }

  const validVals = [
    ranges.oneWeekPercent,
    ranges.oneMonthPercent,
    ranges.threeMonthPercent,
    ranges.sixMonthPercent,
    ranges.oneYearPercent,
  ].filter((v): v is number => v != null && !Number.isNaN(v));

  if (validVals.length === 0) {
    return {
      bullCount: 0,
      velocity: 50,
      label: 'NO HISTORICAL DATA',
      badgeClass: 'text-zinc-400 bg-zinc-800/40 border-zinc-700',
    };
  }

  const bullCount = validVals.filter((v) => v >= 0).length;
  const baseVelocity = Math.min(
    99,
    Math.max(12, Math.round(50 + pChange * 3 + (bullCount - validVals.length / 2) * 8))
  );

  if (bullCount >= Math.ceil(validVals.length * 0.8)) {
    return {
      bullCount,
      velocity: Math.max(70, baseVelocity),
      label: `▲ ACCELERATING (${bullCount}/${validVals.length})`,
      badgeClass: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    };
  }
  if (bullCount >= Math.ceil(validVals.length * 0.4)) {
    return {
      bullCount,
      velocity: baseVelocity,
      label: `◈ CONSOLIDATING (${bullCount}/${validVals.length})`,
      badgeClass: 'text-terminal-amber bg-terminal-amber/10 border-terminal-amber/30',
    };
  }
  return {
    bullCount,
    velocity: Math.min(35, baseVelocity),
    label: `▼ BEARISH DRIFT (${bullCount}/${validVals.length})`,
    badgeClass: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
  };
}

interface MomentumMatrixRowProps {
  row: MoverRow;
  onClick: () => void;
  extraColumns: string[];
  moversColumns: string[];
}

interface TopMoversRowProps {
  row: MoverRow;
  rank: number;
  moversColumns: string[];
  extraColumns: string[];
  onClick: () => void;
}

function TopMoversRow({ row, rank, moversColumns, extraColumns, onClick }: TopMoversRowProps) {
  const needs52w = moversColumns.includes('52wh') || moversColumns.includes('52wl');
  const { data: ranges, isLoading: rangesLoading } = useChangeRanges(row.symbol);
  const { data: quote, isLoading: quoteLoading } = useMoverQuote(row.symbol, needs52w);
  const dash = <span className="text-zinc-400">&mdash;</span>;

  const renderExtraCell = (column: string) => {
    switch (column) {
      case 'open': return formatPriceStr(row.open);
      case 'high': return formatPriceStr(row.high);
      case 'low': return formatPriceStr(row.low);
      case 'vol': return formatVol(row.vol);
      case 'trnvr': return formatTurnover(row.turnover);
      case 'ca': return formatCaDt(row.caDate, row.caPurpose);
      case '2y': return rangesLoading ? dash : formatRange(ranges?.twoYearPercent);
      case '3y': return rangesLoading ? dash : formatRange(ranges?.threeYearPercent);
      case '5y': return rangesLoading ? dash : formatRange(ranges?.fiveYearPercent);
      case '52wh': return quoteLoading ? dash : formatPriceCell(quote?.yearHigh);
      case '52wl': return quoteLoading ? dash : formatPriceCell(quote?.yearLow);
      default: return null;
    }
  };

  return (
    <tr onClick={onClick} className="cursor-pointer border-b border-[#27272a]/60 hover:bg-[#14141a]">
      <td className="py-2 pr-2"><span className="mr-2 text-zinc-400">#{rank}</span><span className="font-bold text-white">{row.symbol}</span></td>
      <td className="px-2 py-2 text-right font-bold text-white">&#8377;{row.close}</td>
      <td className="px-2 py-2 text-right">{formatChange(row.pChange)}</td>
      {moversColumns.includes('vol') && <td className="px-2 py-2 text-right text-terminal-amber">{formatVol(row.vol)}</td>}
      {moversColumns.includes('trnvr') && <td className="px-2 py-2 text-right text-terminal-amber">{formatTurnover(row.turnover)}</td>}
      {extraColumns.map((column) => (
        <td key={column} className="px-2 py-2 text-right text-zinc-300">{renderExtraCell(column)}</td>
      ))}
    </tr>
  );
}

function MomentumMatrixRow({
  row,
  onClick,
  extraColumns,
  moversColumns,
}: MomentumMatrixRowProps) {
  const { data: ranges, isLoading: rangesLoading } = useChangeRanges(row.symbol);
  const needs52w = extraColumns.includes('52wh') || extraColumns.includes('52wl');
  const { data: quote, isLoading: quoteLoading } = useMoverQuote(row.symbol, needs52w);

  const isPositive = row.pChange >= 0;
  const alignment = computeAlignmentMeta(ranges, row.pChange);
  const dash = <span className="text-zinc-400">&mdash;</span>;

  const renderExtraCell = (col: string) => {
    switch (col) {
      case 'open':
        return formatPriceStr(row.open);
      case 'high':
        return formatPriceStr(row.high);
      case 'low':
        return formatPriceStr(row.low);
      case 'vol':
        return formatVol(row.vol);
      case 'trnvr':
        return formatTurnover(row.turnover);
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
  };

  return (
    <tr
      onClick={onClick}
      className="hover:bg-[#14141a] transition-colors cursor-pointer group border-b border-[#27272a]/50"
    >
      <td className="py-2 pr-2">
        <div className="flex items-center gap-2">
          <span
            className={`font-bold text-xs sm:text-sm transition-colors ${
              isPositive
                ? 'text-white group-hover:text-terminal-amber'
                : 'text-white group-hover:text-rose-400'
            }`}
          >
            {row.symbol}
          </span>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-bold ${
              isPositive
                ? 'text-emerald-400 bg-emerald-500/10'
                : 'text-rose-400 bg-rose-500/10'
            }`}
          >
            {isPositive ? 'BULL' : 'BEAR'}
          </span>
        </div>
      </td>
      <td className="py-2 px-2 text-right font-bold text-white tabular-nums text-xs sm:text-sm">
        &#8377;{row.close}
      </td>
      <td className="py-2 px-2 text-right tabular-nums text-xs">
        {formatChange(row.pChange)}
      </td>
      <td className="py-2 px-2">
        <MomentumHeatStrip
          ranges={ranges}
          pChange={row.pChange}
        />
      </td>
      <td className="py-2 px-2 text-center">
        <div
          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border ${
            alignment.velocity >= 70
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : alignment.velocity >= 45
              ? 'bg-terminal-amber/10 border-terminal-amber/30 text-terminal-amber'
              : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
          }`}
        >
          <span className="font-extrabold text-xs tabular-nums">
            {alignment.velocity} / 100
          </span>
        </div>
      </td>
      {moversColumns.includes('vol') && <td className="py-2 px-2 text-right font-bold text-terminal-amber tabular-nums text-xs">{formatVol(row.vol)}</td>}
      {moversColumns.includes('trnvr') && <td className="py-2 px-2 text-right font-bold text-terminal-amber tabular-nums text-xs">{formatTurnover(row.turnover)}</td>}
      <td className="py-2 pl-2 text-center">
        <span
          className={`text-[10px] font-bold px-2 py-0.5 rounded border whitespace-nowrap ${alignment.badgeClass}`}
        >
          {alignment.label}
        </span>
      </td>
      {extraColumns.filter((col) => moversColumns.includes(col)).map((col) => (
        <td key={col} className="py-2 px-2 text-right text-xs text-zinc-300 tabular-nums">
          {renderExtraCell(col)}
        </td>
      ))}
    </tr>
  );
}

export function MoversWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [moversColumns] = useAtom(moversColumnsAtom);
  const [moversCategory, setMoversCategory] = useAtom(moversCategoryAtom);

  const [activeView, setActiveView] = useState<MoversView>('matrix');
  const [page, setPage] = useState(0);
  const [allSortOrder, setAllSortOrder] = useState<'gains' | 'drops'>('gains');
  const [searchQuery, setSearchQuery] = useState('');

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

  const extraColumns = useMemo(
    () =>
      moversColumns.filter((column) => ['open', 'high', 'low', 'ca', '2y', '3y', '5y', '52wh', '52wl'].includes(column)),
    [moversColumns]
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
    const combined = Array.from(map.values());
    if (allSortOrder === 'drops') {
      return combined.sort((a, b) => a.pChange - b.pChange);
    }
    return combined.sort((a, b) => b.pChange - a.pChange);
  }, [filteredGainers, filteredLosers, allSortOrder]);

  const activeRows = activeView === 'gainers'
    ? filteredGainers
    : activeView === 'losers'
      ? filteredLosers
      : matrixRows;
  const pageCount = Math.max(1, Math.ceil(activeRows.length / MOVERS_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pagedRows = activeRows.slice(
    currentPage * MOVERS_PAGE_SIZE,
    (currentPage + 1) * MOVERS_PAGE_SIZE,
  );

  const handleViewChange = (view: MoversView) => {
    setActiveView(view);
    setPage(0);
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
        <div className="flex flex-wrap items-center gap-1.5">
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
              <span className="flex items-center gap-1.5 text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                <span className="w-2 h-2 rounded-full bg-terminal-amber" />
                {activeView === 'matrix' ? 'Multi-Period Momentum Matrix' : activeView === 'gainers' ? 'Top Gainers' : 'Top Losers'}
              </span>
              <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-2 py-0.5 rounded border border-[#27272a]">
                {activeView === 'matrix' ? '1W • 1M • 3M • 6M • 1Y RETURN ALIGNMENT' : `${activeRows.length} SYMBOLS`}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div role="tablist" aria-label="Movers views" className="flex items-center gap-1 rounded-md border border-[#27272a] bg-[#121216] p-1">
                {(['matrix', 'gainers', 'losers'] as MoversView[]).map((view) => (
                  <button
                    key={view}
                    type="button"
                    role="tab"
                    aria-selected={activeView === view}
                    onClick={() => handleViewChange(view)}
                    className={`rounded px-2.5 py-1.5 text-[11px] font-bold uppercase transition-colors ${
                      activeView === view
                        ? 'bg-terminal-amber text-black'
                        : 'text-zinc-300 hover:bg-zinc-800 hover:text-white'
                    }`}
                  >
                    {view}
                  </button>
                ))}
              </div>
              {activeView === 'matrix' && (
                <>
                  <button
                    type="button"
                    aria-pressed={allSortOrder === 'gains'}
                    onClick={() => { setAllSortOrder('gains'); setPage(0); }}
                    className={`rounded border px-2.5 py-1.5 text-[11px] font-bold ${allSortOrder === 'gains' ? 'border-emerald-300 bg-emerald-400 text-black' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'}`}
                  >
                    ▲ Gains
                  </button>
                  <button
                    type="button"
                    aria-pressed={allSortOrder === 'drops'}
                    onClick={() => { setAllSortOrder('drops'); setPage(0); }}
                    className={`rounded border px-2.5 py-1.5 text-[11px] font-bold ${allSortOrder === 'drops' ? 'border-rose-300 bg-rose-400 text-black' : 'border-rose-500/30 bg-rose-500/10 text-rose-400'}`}
                  >
                    ▼ Drops
                  </button>
                </>
              )}
            </div>
          </div>

        <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
            <table data-testid="movers-matrix-table" className="w-full text-left font-mono tabular-nums border-collapse min-w-[780px]">
              <thead>
                <tr className="text-[10px] uppercase text-zinc-400 border-b border-[#27272a]">
                  <th className="pb-2 font-bold">{activeView === 'matrix' ? 'Ticker & Bias' : 'Rank & Ticker'}</th>
                  <th className="pb-2 font-bold text-right">LTP (&#8377;)</th>
                  <th className="pb-2 font-bold text-right">Day %</th>
                  {activeView === 'matrix' && <th className="pb-2 font-bold text-center">
                    5-Period Momentum Alignment (1W / 1M / 3M / 6M / 1Y)
                  </th>}
                  {activeView === 'matrix' && <th className="pb-2 font-bold text-center">Velocity Score</th>}
                  {moversColumns.includes('vol') && <th className="pb-2 font-bold text-right">Volume</th>}
                  {moversColumns.includes('trnvr') && <th className="pb-2 font-bold text-right">Turnover</th>}
                  {activeView === 'matrix' && <th className="pb-2 font-bold text-center">Radar Status</th>}
                  {extraColumns.filter((col) => moversColumns.includes(col)).map((col) => (
                    <th key={col} className="pb-2 font-bold text-right">
                      {COLUMN_LABELS[col] || col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-xs">
                {pagedRows.map((row, index) => activeView === 'matrix' ? (
                  <MomentumMatrixRow
                    key={`matrix-${row.symbol}`}
                    row={row}
                    onClick={() => handleRowClick(row)}
                    extraColumns={extraColumns}
                    moversColumns={moversColumns}
                  />
                ) : (
                  <TopMoversRow
                    key={`${activeView}-${row.symbol}`}
                    row={row}
                    rank={currentPage * MOVERS_PAGE_SIZE + index + 1}
                    moversColumns={moversColumns}
                    extraColumns={extraColumns.filter((column) => moversColumns.includes(column))}
                    onClick={() => handleRowClick(row)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex shrink-0 items-center justify-between gap-2 border-t border-[#27272a] px-2.5 py-2 text-zinc-300 sm:px-3">
            <span className="font-mono text-[11px] tabular-nums" aria-live="polite">
              PAGE {currentPage + 1} OF {pageCount} · {activeRows.length} ROWS
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

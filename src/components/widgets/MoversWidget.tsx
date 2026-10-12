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

type TimeframeFocus = 'INTRADAY' | '1-WEEK' | '1-MONTH' | '3-MONTH' | '52-WEEK';
type MatrixFilter = 'ALL' | 'GAINERS' | 'LOSERS';

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

const TIMEFRAME_PILLS: TimeframeFocus[] = [
  'INTRADAY',
  '1-WEEK',
  '1-MONTH',
  '3-MONTH',
  '52-WEEK',
];

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
  highlighted?: boolean;
}

function MomentumHeatStrip({
  ranges,
  pChange: _pChange,
  timeframeFocus,
}: {
  ranges: ChangeRanges | null;
  pChange?: number;
  timeframeFocus: TimeframeFocus;
}) {
  const segments: HeatSegment[] = [
    {
      label: '1W',
      value: ranges?.oneWeekPercent,
      highlighted: timeframeFocus === '1-WEEK',
    },
    {
      label: '1M',
      value: ranges?.oneMonthPercent,
      highlighted: timeframeFocus === '1-MONTH',
    },
    {
      label: '3M',
      value: ranges?.threeMonthPercent,
      highlighted: timeframeFocus === '3-MONTH',
    },
    {
      label: '6M',
      value: ranges?.sixMonthPercent,
      highlighted: false,
    },
    {
      label: '1Y',
      value: ranges?.oneYearPercent,
      highlighted: timeframeFocus === '52-WEEK',
    },
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
              className={`px-1.5 py-0.5 rounded text-[10px] font-mono tabular-nums border text-zinc-500 bg-[#121216] border-[#27272a] whitespace-nowrap ${
                seg.highlighted ? 'ring-1 ring-terminal-amber' : ''
              }`}
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

        const ringTone = seg.highlighted ? 'ring-1 ring-terminal-amber' : '';

        return (
          <div
            key={seg.label}
            title={`${seg.label}: ${sign}${effectiveVal.toFixed(2)}%`}
            className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold tabular-nums border whitespace-nowrap transition-transform hover:scale-105 ${pillTone} ${ringTone}`}
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
  timeframeFocus: TimeframeFocus;
  extraColumns: string[];
}

function MomentumMatrixRow({
  row,
  onClick,
  timeframeFocus,
  extraColumns,
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
          timeframeFocus={timeframeFocus}
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
      <td className="py-2 px-2 text-right font-bold text-terminal-amber tabular-nums text-xs">
        {row.vol ? formatVol(row.vol) : formatTurnover(row.turnover)}
      </td>
      <td className="py-2 pl-2 text-center">
        <span
          className={`text-[10px] font-bold px-2 py-0.5 rounded border whitespace-nowrap ${alignment.badgeClass}`}
        >
          {alignment.label}
        </span>
      </td>
      {extraColumns.map((col) => (
        <td key={col} className="py-2 px-2 text-right text-xs text-zinc-300 tabular-nums">
          {renderExtraCell(col)}
        </td>
      ))}
    </tr>
  );
}

interface GainerBentoRowProps {
  row: MoverRow;
  rank: number;
  maxGain: number;
  onClick: () => void;
}

function GainerBentoRow({ row, rank, maxGain, onClick }: GainerBentoRowProps) {
  const { data: quote } = useMoverQuote(row.symbol, true);
  const rankBadge = `#${String(rank).padStart(2, '0')}`;
  const barWidth = Math.min(100, Math.max(15, maxGain > 0 ? (Math.abs(row.pChange) / maxGain) * 100 : 50));

  const closeNum = parseFloat(row.close);
  const highNum = row.high ? parseFloat(row.high) : null;
  const targetHigh = quote?.yearHigh ?? highNum;

  let proximityNode: React.ReactNode = (
    <span className="text-emerald-400 font-bold text-[11px] tabular-nums">ATH (0.0%)</span>
  );

  if (targetHigh && targetHigh > 0 && !Number.isNaN(closeNum)) {
    const diffPct = ((closeNum - targetHigh) / targetHigh) * 100;
    if (diffPct >= -0.35) {
      proximityNode = (
        <span className="text-emerald-400 font-bold text-[11px] tabular-nums">
          ATH (0.0%)
        </span>
      );
    } else {
      proximityNode = (
        <span className="text-zinc-200 font-bold text-[11px] tabular-nums">
          {diffPct.toFixed(1)}% from 52WH
        </span>
      );
    }
  }

  return (
    <tr
      onClick={onClick}
      className="hover:bg-[#14141a] transition-colors cursor-pointer group border-b border-[#27272a]/50"
    >
      <td className="py-2 pr-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-terminal-amber bg-terminal-amber/10 border border-terminal-amber/30 px-1.5 py-0.5 rounded font-bold tabular-nums">
            {rankBadge}
          </span>
          <span className="font-bold text-white group-hover:text-terminal-amber text-xs transition-colors">
            {row.symbol}
          </span>
        </div>
      </td>
      <td className="py-2 px-2 text-right font-bold text-white tabular-nums text-xs">
        &#8377;{row.close}
      </td>
      <td className="py-2 px-2 text-right">
        <div className="flex items-center justify-end gap-1.5">
          <div className="w-12 h-1.5 bg-zinc-800 rounded-full overflow-hidden hidden sm:block">
            <div
              className="h-full bg-emerald-400 rounded-full"
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <span className="text-emerald-400 font-bold tabular-nums text-xs">
            +{ Math.abs(row.pChange).toFixed(2) }%
          </span>
        </div>
      </td>
      <td className="py-2 px-2 text-right">
        <span className="text-[11px] text-zinc-200 bg-[#14141a] border border-[#27272a] px-1.5 py-0.5 rounded font-mono tabular-nums">
          {row.turnover ? `₹${row.turnover.toFixed(0)} Cr` : row.vol ? formatVol(row.vol) : '—'}
        </span>
      </td>
      <td className="py-2 pl-2 text-right">{proximityNode}</td>
    </tr>
  );
}

interface LoserBentoRowProps {
  row: MoverRow;
  rank: number;
  maxLoss: number;
  onClick: () => void;
}

function LoserBentoRow({ row, rank, maxLoss, onClick }: LoserBentoRowProps) {
  const rankBadge = `#${String(rank).padStart(2, '0')}`;
  const absDrop = Math.abs(row.pChange);
  const barWidth = Math.min(100, Math.max(15, maxLoss > 0 ? (absDrop / maxLoss) * 100 : 50));

  const circuitLimit = absDrop > 10 ? 20 : 10;
  const distToCircuit = Math.max(0.2, circuitLimit - absDrop);
  const isNearCircuit = distToCircuit <= 5.5 || rank <= 3;

  return (
    <tr
      onClick={onClick}
      className="hover:bg-[#14141a] transition-colors cursor-pointer group border-b border-[#27272a]/50"
    >
      <td className="py-2 pr-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-rose-400 bg-rose-500/10 border border-rose-500/30 px-1.5 py-0.5 rounded font-bold tabular-nums">
            {rankBadge}
          </span>
          <span className="font-bold text-white group-hover:text-rose-400 text-xs transition-colors">
            {row.symbol}
          </span>
        </div>
      </td>
      <td className="py-2 px-2 text-right font-bold text-white tabular-nums text-xs">
        &#8377;{row.close}
      </td>
      <td className="py-2 px-2 text-right">
        <div className="flex items-center justify-end gap-1.5">
          <div className="w-12 h-1.5 bg-zinc-800 rounded-full overflow-hidden hidden sm:block">
            <div
              className="h-full bg-rose-400 rounded-full"
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <span className="text-rose-400 font-bold tabular-nums text-xs">
            -{absDrop.toFixed(2)}%
          </span>
        </div>
      </td>
      <td className="py-2 px-2 text-right">
        <span className="text-[11px] text-zinc-200 bg-[#14141a] border border-[#27272a] px-1.5 py-0.5 rounded font-mono tabular-nums">
          {row.turnover ? `₹${row.turnover.toFixed(0)} Cr` : row.vol ? formatVol(row.vol) : '—'}
        </span>
      </td>
      <td className="py-2 pl-2 text-right">
        {isNearCircuit ? (
          <span className="text-[10px] font-bold text-terminal-amber bg-terminal-amber/10 border border-terminal-amber/40 px-1.5 py-0.5 rounded whitespace-nowrap tabular-nums">
            ⚠️ {distToCircuit.toFixed(1)}% to Lower Circuit
          </span>
        ) : (
          <span className="text-[10px] font-medium text-zinc-300 bg-zinc-800/80 border border-[#27272a] px-1.5 py-0.5 rounded whitespace-nowrap tabular-nums">
            Safe ({distToCircuit.toFixed(1)}% to LC)
          </span>
        )}
      </td>
    </tr>
  );
}

export function MoversWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [moversColumns] = useAtom(moversColumnsAtom);
  const [moversCategory, setMoversCategory] = useAtom(moversCategoryAtom);

  const [timeframeFocus, setTimeframeFocus] = useState<TimeframeFocus>('1-MONTH');
  const [matrixFilter, setMatrixFilter] = useState<MatrixFilter>('ALL');
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
      moversColumns.filter(
        (c) => !['close', 'chg', '1w', '1m', '3m', '6m', '1y'].includes(c)
      ),
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
    if (matrixFilter === 'GAINERS') return filteredGainers;
    if (matrixFilter === 'LOSERS') return filteredLosers;
    const map = new Map<string, MoverRow>();
    for (const r of filteredGainers) map.set(r.symbol, r);
    for (const r of filteredLosers) map.set(r.symbol, r);
    const combined = Array.from(map.values());
    if (allSortOrder === 'drops') {
      return combined.sort((a, b) => a.pChange - b.pChange);
    }
    return combined.sort((a, b) => b.pChange - a.pChange);
  }, [filteredGainers, filteredLosers, matrixFilter, allSortOrder]);

  const handleRowClick = (row: MoverRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
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

  const maxGain = filteredGainers.reduce((acc, r) => Math.max(acc, Math.abs(r.pChange)), 1);
  const maxLoss = filteredLosers.reduce((acc, r) => Math.max(acc, Math.abs(r.pChange)), 1);
  const severeLoserCount = filteredLosers.filter((r) => Math.abs(r.pChange) >= 4).length;

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-[#09090b] text-zinc-100 overflow-auto">
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
                  onClick={() => setMoversCategory(cat.key)}
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
      <div className="grid grid-cols-1 md:grid-cols-4 lg:grid-cols-4 gap-3 p-3">
        {/* =================================================================== */}
        {/* CARD 1: MULTI-PERIOD MOMENTUM MATRIX (col-span-1 md:col-span-4 lg:col-span-4) */}
        {/* =================================================================== */}
        <div className="col-span-1 md:col-span-4 lg:col-span-4 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-2 mb-2.5 border-b border-[#27272a]/70">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-terminal-amber" />
                Multi-Period Momentum Matrix
              </span>
              <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-2 py-0.5 rounded border border-[#27272a]">
                1W • 1M • 3M • 6M • 1Y RETURN ALIGNMENT
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1 bg-[#121216] p-1 rounded-md border border-[#27272a]">
                {(['ALL', 'GAINERS', 'LOSERS'] as MatrixFilter[]).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setMatrixFilter(mode)}
                    className={`px-3 py-1 rounded text-[11px] font-mono font-extrabold uppercase cursor-pointer transition-all ${
                      matrixFilter === mode
                        ? 'bg-amber-400 text-black border border-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.5)]'
                        : 'text-zinc-400 hover:text-white hover:bg-zinc-800 border border-transparent'
                    }`}
                  > 
                    {mode}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => {
                  setAllSortOrder('gains');
                  if (matrixFilter === 'LOSERS') setMatrixFilter('ALL');
                }}
                className={`text-[11px] font-mono px-3 py-1 rounded border font-extrabold transition-all cursor-pointer ${
                  allSortOrder === 'gains' && (matrixFilter === 'ALL' || matrixFilter === 'GAINERS')
                    ? 'text-black bg-emerald-400 border-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.5)]'
                    : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30 hover:bg-emerald-500/20'
                }`}
                title="Sort by highest % gains first"
              >
                ▲ Gains
              </button>
              <button
                type="button"
                onClick={() => {
                  setAllSortOrder('drops');
                  if (matrixFilter === 'GAINERS') setMatrixFilter('ALL');
                }}
                className={`text-[11px] font-mono px-3 py-1 rounded border font-extrabold transition-all cursor-pointer ${
                  allSortOrder === 'drops' && (matrixFilter === 'ALL' || matrixFilter === 'LOSERS')
                    ? 'text-black bg-rose-400 border-rose-300 shadow-[0_0_12px_rgba(244,63,94,0.5)]'
                    : 'text-rose-400 bg-rose-500/10 border-rose-500/30 hover:bg-rose-500/20'
                }`}
                title="Sort by steepest % drops first"
              >
                ▼ Drops
              </button>
            </div>
          </div>

          <div className="overflow-x-auto max-h-[500px] overflow-y-auto pr-1">
            <table className="w-full text-left font-mono tabular-nums border-collapse min-w-[780px]">
              <thead>
                <tr className="text-[10px] uppercase text-zinc-400 border-b border-[#27272a]">
                  <th className="pb-2 font-bold">Ticker &amp; Bias</th>
                  <th className="pb-2 font-bold text-right">LTP (&#8377;)</th>
                  <th className="pb-2 font-bold text-right">Day %</th>
                  <th className="pb-2 font-bold text-center">
                    5-Period Momentum Alignment (1W / 1M / 3M / 6M / 1Y)
                  </th>
                  <th className="pb-2 font-bold text-center">Velocity Score</th>
                  <th className="pb-2 font-bold text-right">Vol / Trnvr</th>
                  <th className="pb-2 font-bold text-center">Radar Status</th>
                  {extraColumns.map((col) => (
                    <th key={col} className="pb-2 font-bold text-right">
                      {COLUMN_LABELS[col] || col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-xs">
                {matrixRows.map((row) => (
                  <MomentumMatrixRow
                    key={`matrix-${row.symbol}`}
                    row={row}
                    onClick={() => handleRowClick(row)}
                    timeframeFocus={timeframeFocus}
                    extraColumns={extraColumns}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* =================================================================== */}
        {/* CARD 2: TOP GAINERS BENTO (col-span-1 md:col-span-2 lg:col-span-2)  */}
        {/* =================================================================== */}
        <div className="col-span-1 md:col-span-2 lg:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a]/70">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-emerald-400" />
                  Top Gainers
                </span>
                <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                  HIGH VELOCITY
                </span>
              </div>
              <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30 tabular-nums">
                ▲ {filteredGainers.length} ADVANCING
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono tabular-nums border-collapse">
                <thead>
                  <tr className="text-[10px] uppercase text-zinc-400 border-b border-[#27272a]">
                    <th className="pb-1.5 font-bold"># Rank &amp; Ticker</th>
                    <th className="pb-1.5 font-bold text-right">LTP (&#8377;)</th>
                    <th className="pb-1.5 font-bold text-right">% Change</th>
                    <th className="pb-1.5 font-bold text-right">Turnover</th>
                    <th className="pb-1.5 font-bold text-right">52W High Proximity</th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {filteredGainers.slice(0, 8).map((row, idx) => (
                    <GainerBentoRow
                      key={row.symbol}
                      row={row}
                      rank={idx + 1}
                      maxGain={maxGain}
                      onClick={() => handleRowClick(row)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-2.5 pt-2 border-t border-[#27272a]/70 flex items-center justify-between text-[11px] font-mono text-zinc-400">
            <span>
              Peak Gain:{' '}
              <b className="text-emerald-400 tabular-nums">
                +{maxGain.toFixed(2)}%
              </b>
            </span>
            <span className="text-zinc-300">
              Category:{' '}
              <b className="text-terminal-amber">
                {CATEGORY_SHORT_LABELS[moversCategory] || moversCategory}
              </b>
            </span>
          </div>
        </div>

        {/* =================================================================== */}
        {/* CARD 3: TOP LOSERS & CIRCUIT PROXIMITY BENTO (col-span-1 md:col-span-2 lg:col-span-2) */}
        {/* =================================================================== */}
        <div className="col-span-1 md:col-span-2 lg:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a]/70">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-rose-400" />
                  Top Losers &amp; Circuit Proximity
                </span>
                <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                  CIRCUIT WATCH
                </span>
              </div>
              <span className="text-[10px] text-rose-400 font-mono font-bold bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/30 tabular-nums">
                ▼ {filteredLosers.length} DECLINING
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono tabular-nums border-collapse">
                <thead>
                  <tr className="text-[10px] uppercase text-zinc-400 border-b border-[#27272a]">
                    <th className="pb-1.5 font-bold"># Rank &amp; Ticker</th>
                    <th className="pb-1.5 font-bold text-right">LTP (&#8377;)</th>
                    <th className="pb-1.5 font-bold text-right">% Change</th>
                    <th className="pb-1.5 font-bold text-right">Turnover</th>
                    <th className="pb-1.5 font-bold text-right">Circuit Proximity</th>
                  </tr>
                </thead>
                <tbody className="text-xs">
                  {filteredLosers.slice(0, 8).map((row, idx) => (
                    <LoserBentoRow
                      key={row.symbol}
                      row={row}
                      rank={idx + 1}
                      maxLoss={maxLoss}
                      onClick={() => handleRowClick(row)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="mt-2.5 pt-2 border-t border-[#27272a]/70 flex items-center justify-between text-[11px] font-mono text-zinc-400">
            <span>
              Severe Drops (&gt; 4%):{' '}
              <b className="text-rose-400 tabular-nums">{severeLoserCount} Stocks</b>
            </span>
            <span className="text-zinc-300">
              Steepest Drop:{' '}
              <b className="text-rose-400 tabular-nums">-{maxLoss.toFixed(2)}%</b>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

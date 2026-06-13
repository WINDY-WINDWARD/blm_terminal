'use client';

import React, { useState, useEffect } from 'react';
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

interface MoverQuote {
  yearHigh?: number;
  yearLow?: number;
}

interface MoverRow {
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

interface TopMoverItem {
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

function formatPrice(val: number): string {
  return val.toFixed(2);
}

function formatChange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-white/60">&mdash;</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green font-bold' : 'text-terminal-red font-bold'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
}

function formatRange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-white/60">&mdash;</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green' : 'text-terminal-red'}>
      {isUp ? '+' : ''}{val.toFixed(1)}%
    </span>
  );
}

function formatPriceCell(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-white/60">&mdash;</span>;
  return <span>{val.toFixed(2)}</span>;
}

function formatPriceStr(val: string | undefined): React.ReactNode {
  if (!val || val === '—') return <span className="text-white/60">&mdash;</span>;
  return <span>{val}</span>;
}

function formatVol(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val) || val === 0) return <span className="text-white/60">&mdash;</span>;
  if (val >= 1_00_00_000) return <span>{(val / 1_00_00_000).toFixed(1)}Cr</span>;
  if (val >= 1_00_000) return <span>{(val / 1_00_000).toFixed(1)}L</span>;
  return <span>{(val / 1000).toFixed(1)}K</span>;
}

function formatTurnover(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val) || val === 0) return <span className="text-white/60">&mdash;</span>;
  return <span>&#8377;{(val).toFixed(0)}Cr</span>;
}

function formatCaDt(val: string | undefined, purpose: string | undefined): React.ReactNode {
  if (!val || val === '-') return <span className="text-white/60">&mdash;</span>;
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

const CATEGORY_SHORT_LABELS: Record<string, string> = {
  allSec: 'ALL',
  NIFTY: 'NIFTY50',
  BANKNIFTY: 'BANKNIFTY',
  NIFTYNEXT50: 'NEXT50',
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

interface MoverRowProps {
  row: MoverRow;
  columns: string[];
  onClick: () => void;
  colorClass: string;
}

function MoverRowComponent({ row, columns, onClick, colorClass }: MoverRowProps) {
  const { data: ranges, isLoading: rangesLoading } = useChangeRanges(row.symbol);
  const needs52w = columns.includes('52wh') || columns.includes('52wl');
  const { data: quote, isLoading: quoteLoading } = useMoverQuote(row.symbol, needs52w);

  const yearHigh = quote?.yearHigh;
  const yearLow = quote?.yearLow;
  const dash = <span className="text-white/60">&mdash;</span>;

  const renderCell = (col: string) => {
    switch (col) {
      case 'close':
        return row.close;
      case 'chg':
        return formatChange(row.pChange);
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
        return quoteLoading ? dash : formatPriceCell(yearHigh);
      case '52wl':
        return quoteLoading ? dash : formatPriceCell(yearLow);
      default:
        return null;
    }
  };

  return (
    <tr
      onClick={onClick}
      className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer"
    >
      <td className={`font-bold ${colorClass}`}>{row.symbol}</td>
      {columns.map((col) => (
        <td key={col} className="text-right">
          {renderCell(col)}
        </td>
      ))}
    </tr>
  );
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

export function MoversWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [moversColumns] = useAtom(moversColumnsAtom);
  const [moversCategory, setMoversCategory] = useAtom(moversCategoryAtom);

  const { data: categories = [] } = useMoverCategories();

  const { data: gainers = [], isLoading: gainersLoading } = useQuery<TopMoverItem[]>({
    queryKey: ['market/top-gainers', moversCategory],
    queryFn: async () => {
      const res = await fetch(`/api/py/market/top-gainers?category=${encodeURIComponent(moversCategory)}`);
      if (!res.ok) throw new Error('Failed to fetch top gainers');
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: losers = [], isLoading: losersLoading } = useQuery<TopMoverItem[]>({
    queryKey: ['market/top-losers', moversCategory],
    queryFn: async () => {
      const res = await fetch(`/api/py/market/top-losers?category=${encodeURIComponent(moversCategory)}`);
      if (!res.ok) throw new Error('Failed to fetch top losers');
      return res.json();
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const gainerRows: MoverRow[] = gainers.map(mapItemToRow);
  const loserRows: MoverRow[] = losers.map(mapItemToRow);

  const handleRowClick = (row: MoverRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
  };

  if (gainersLoading || losersLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-white gap-2 p-4">
        <span>Loading movers...</span>
      </div>
    );
  }

  if (gainerRows.length === 0 && loserRows.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-white gap-2 p-4">
        <span>No data available.</span>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
      {/* Category Tabs */}
      {categories.length > 0 && (
        <div className="flex-shrink-0 flex gap-0.5 px-2 pt-1.5 pb-0.5 overflow-x-auto border-b border-terminal-gray">
          {categories.map((cat) => (
            <button
              key={cat.key}
              onClick={() => setMoversCategory(cat.key)}
              className={`flex-shrink-0 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded-t border-b-2 transition-colors ${
                moversCategory === cat.key
                  ? 'text-terminal-amber border-terminal-amber bg-amber-900/20'
                  : 'text-white/50 border-transparent hover:text-white hover:border-white/30'
              }`}
            >
              {CATEGORY_SHORT_LABELS[cat.key] || decodeHtmlEntities(cat.label)}
            </button>
          ))}
        </div>
      )}

      {/* Top Gainers */}
      <div className="flex-1 bg-terminal-bg p-2 border-b border-terminal-green">
        <div className="text-terminal-green font-bold uppercase text-[10px] tracking-widest mb-1">Top Gainers</div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[600px]">
            <thead className="text-terminal-green text-[9px] font-bold uppercase">
              <tr>
                <th className="w-12">SYMBOL</th>
                {moversColumns.map((col) => (
                  <th key={col} className="text-right">{COLUMN_LABELS[col] || col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="text-terminal-amber text-[10px]">
              {gainerRows.map((row) => (
                <MoverRowComponent
                  key={row.symbol}
                  row={row}
                  columns={moversColumns}
                  onClick={() => handleRowClick(row)}
                  colorClass="text-terminal-green"
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Top Losers */}
      <div className="flex-1 bg-terminal-bg p-2 border-b border-terminal-red">
        <div className="text-terminal-red font-bold uppercase text-[10px] tracking-widest mb-1">Top Losers</div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[600px]">
            <thead className="text-terminal-red text-[9px] font-bold uppercase">
              <tr>
                <th className="w-12">SYMBOL</th>
                {moversColumns.map((col) => (
                  <th key={col} className="text-right">{COLUMN_LABELS[col] || col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="text-terminal-amber text-[10px]">
              {loserRows.map((row) => (
                <MoverRowComponent
                  key={row.symbol}
                  row={row}
                  columns={moversColumns}
                  onClick={() => handleRowClick(row)}
                  colorClass="text-terminal-red"
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

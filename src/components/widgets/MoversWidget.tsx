'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom, moversColumnsAtom } from '@/store/terminalStore';

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

interface MoverQuote {
  yearHigh?: number;
  yearLow?: number;
}

interface MoverRow {
  symbol: string;
  close: string;
  pChange: number;
}

function formatPrice(val: number): string {
  return val.toFixed(2);
}

function formatChange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-terminal-gray">—</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green font-bold' : 'text-terminal-red font-bold'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
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

function formatPriceCell(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-terminal-gray">—</span>;
  return <span>{val.toFixed(2)}</span>;
}

function useChangeRanges(symbol: string) {
  return useQuery({
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

function useMoverQuote(symbol: string) {
  return useQuery<MoverQuote | null>({
    queryKey: ['market/mover-quote', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/market/symbol-data/${encodeURIComponent(symbol)}`);
      if (!res.ok) return null;
      const payload = (await res.json()) as NseSymbolData;
      const equity = payload.equityResponse?.[0];
      return {
        yearHigh: equity?.priceInfo?.yearHigh,
        yearLow: equity?.priceInfo?.yearLow,
      };
    },
    staleTime: 60_000,
    enabled: !!symbol,
  });
}

interface MoverRowProps {
  row: MoverRow;
  columns: string[];
  onClick: () => void;
  colorClass: string;
}

function MoverRowComponent({ row, columns, onClick, colorClass }: MoverRowProps) {
  const { data: ranges, isLoading: rangesLoading } = useChangeRanges(row.symbol);
  const { data: quote, isLoading: quoteLoading } = useMoverQuote(row.symbol);

  const yearHigh = quote?.yearHigh;
  const yearLow = quote?.yearLow;
  const dash = <span className="text-terminal-gray">—</span>;

  const renderCell = (col: string) => {
    switch (col) {
      case 'close':
        return row.close;
      case 'chg':
        return formatChange(row.pChange);
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

export function MoversWidget() {
  const [activeSymbol, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [moversColumns] = useAtom(moversColumnsAtom);

  const { data: gainers = [], isLoading: gainersLoading } = useQuery({
    queryKey: ['market/top-gainers'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/top-gainers');
      if (!res.ok) throw new Error('Failed to fetch top gainers');
      return res.json() as Promise<any[]>;
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const { data: losers = [], isLoading: losersLoading } = useQuery({
    queryKey: ['market/top-losers'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/top-losers');
      if (!res.ok) throw new Error('Failed to fetch top losers');
      return res.json() as Promise<any[]>;
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const gainerRows: MoverRow[] = gainers.map((item) => ({
    symbol: item.symbol,
    close: formatPrice(parseFloat(item.lastPrice || item.close || '0')),
    pChange: parseFloat(item.pChange),
  }));

  const loserRows: MoverRow[] = losers.map((item) => ({
    symbol: item.symbol,
    close: formatPrice(parseFloat(item.lastPrice || item.close || '0')),
    pChange: parseFloat(item.pChange),
  }));

  const handleRowClick = (row: MoverRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
  };

  if (gainersLoading || losersLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-terminal-gray gap-2 p-4">
        <span>Loading movers...</span>
      </div>
    );
  }

  if (gainerRows.length === 0 && loserRows.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-terminal-gray gap-2 p-4">
        <span>No data available.</span>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-auto">
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

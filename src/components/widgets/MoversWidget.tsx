'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom } from '@/store/terminalStore';

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

interface MoverRowProps {
  row: MoverRow;
  onClick: () => void;
  colorClass: string;
}

function MoverRowComponent({ row, onClick, colorClass }: MoverRowProps) {
  const { data: ranges, isLoading } = useChangeRanges(row.symbol);

  return (
    <tr
      onClick={onClick}
      className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer"
    >
      <td className={`font-bold ${colorClass}`}>{row.symbol}</td>
      <td className="text-right">{row.close}</td>
      <td className="text-right">{formatChange(row.pChange)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.oneWeekPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.oneMonthPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.threeMonthPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.sixMonthPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.oneYearPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.twoYearPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.threeYearPercent)}</td>
      <td className="text-right">{isLoading ? <span className="text-terminal-gray">—</span> : formatRange(ranges?.fiveYearPercent)}</td>
    </tr>
  );
}

export function MoversWidget() {
  const [activeSymbol, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

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
                <th className="text-right">CLOSE</th>
                <th className="text-right">CHG%</th>
                <th className="text-right">1W%</th>
                <th className="text-right">1M%</th>
                <th className="text-right">3M%</th>
                <th className="text-right">6M%</th>
                <th className="text-right">1Y%</th>
                <th className="text-right">2Y%</th>
                <th className="text-right">3Y%</th>
                <th className="text-right">5Y%</th>
              </tr>
            </thead>
            <tbody className="text-terminal-amber text-[10px]">
              {gainerRows.map((row) => (
                <MoverRowComponent
                  key={row.symbol}
                  row={row}
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
                <th className="text-right">CLOSE</th>
                <th className="text-right">CHG%</th>
                <th className="text-right">1W%</th>
                <th className="text-right">1M%</th>
                <th className="text-right">3M%</th>
                <th className="text-right">6M%</th>
                <th className="text-right">1Y%</th>
                <th className="text-right">2Y%</th>
                <th className="text-right">3Y%</th>
                <th className="text-right">5Y%</th>
              </tr>
            </thead>
            <tbody className="text-terminal-amber text-[10px]">
              {loserRows.map((row) => (
                <MoverRowComponent
                  key={row.symbol}
                  row={row}
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

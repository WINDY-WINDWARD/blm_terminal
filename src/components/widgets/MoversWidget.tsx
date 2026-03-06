'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom } from '@/store/terminalStore';

interface MoverRow {
  symbol: string;
  open: string;
  high: string;
  low: string;
  lastPrice: string;
  pChange: number;
}

function formatPrice(val: number): string {
  return val.toFixed(2);
}

function formatChange(val: number): React.ReactNode {
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green font-bold' : 'text-terminal-red font-bold'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
}

function formatNumber(val: number): string {
  if (val >= 1e9) return (val / 1e9).toFixed(1) + 'B';
  if (val >= 1e6) return (val / 1e6).toFixed(1) + 'M';
  if (val >= 1e3) return (val / 1e3).toFixed(1) + 'K';
  return String(val);
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
    open: formatPrice(parseFloat(item.open)),
    high: formatPrice(parseFloat(item.dayHigh)),
    low: formatPrice(parseFloat(item.dayLow)),
    lastPrice: formatPrice(parseFloat(item.lastPrice)),
    pChange: parseFloat(item.pChange),
  }));

  const loserRows: MoverRow[] = losers.map((item) => ({
    symbol: item.symbol,
    open: formatPrice(parseFloat(item.open)),
    high: formatPrice(parseFloat(item.dayHigh)),
    low: formatPrice(parseFloat(item.dayLow)),
    lastPrice: formatPrice(parseFloat(item.lastPrice)),
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
        <table className="w-full text-left border-collapse">
          <thead className="text-terminal-green text-[9px] font-bold uppercase">
            <tr>
              <th className="w-12">SYMBOL</th>
              <th className="text-right">OPEN</th>
              <th className="text-right">HIGH</th>
              <th className="text-right">LOW</th>
              <th className="text-right">LTP</th>
              <th className="text-right">CHG%</th>
            </tr>
          </thead>
          <tbody className="text-terminal-amber text-[10px]">
            {gainerRows.map((row) => (
              <tr
                key={row.symbol}
                onClick={() => handleRowClick(row)}
                className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer"
              >
                <td className="font-bold text-terminal-green">{row.symbol}</td>
                <td className="text-right">{row.open}</td>
                <td className="text-right">{row.high}</td>
                <td className="text-right">{row.low}</td>
                <td className="text-right">{row.lastPrice}</td>
                <td className="text-right">{formatChange(row.pChange)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Top Losers */}
      <div className="flex-1 bg-terminal-bg p-2 border-b border-terminal-red">
        <div className="text-terminal-red font-bold uppercase text-[10px] tracking-widest mb-1">Top Losers</div>
        <table className="w-full text-left border-collapse">
          <thead className="text-terminal-red text-[9px] font-bold uppercase">
            <tr>
              <th className="w-12">SYMBOL</th>
              <th className="text-right">OPEN</th>
              <th className="text-right">HIGH</th>
              <th className="text-right">LOW</th>
              <th className="text-right">LTP</th>
              <th className="text-right">CHG%</th>
            </tr>
          </thead>
          <tbody className="text-terminal-amber text-[10px]">
            {loserRows.map((row) => (
              <tr
                key={row.symbol}
                onClick={() => handleRowClick(row)}
                className="border-b border-terminal-gray hover:bg-zinc-900 cursor-pointer"
              >
                <td className="font-bold text-terminal-red">{row.symbol}</td>
                <td className="text-right">{row.open}</td>
                <td className="text-right">{row.high}</td>
                <td className="text-right">{row.low}</td>
                <td className="text-right">{row.lastPrice}</td>
                <td className="text-right">{formatChange(row.pChange)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
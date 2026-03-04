'use client';

import React, { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { tickDataAtom } from '@/store/terminalStore';
import { OpenAlgoClient } from '@/lib/openalgo';
import type { PositionData } from '@/lib/openalgo';

export function PosWidget() {
  const [tickData] = useAtom(tickDataAtom);

  const {
    data: posData,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['positionbook'],
    queryFn: () => OpenAlgoClient.getPositionBook(),
    refetchInterval: 5_000,
    staleTime: 4_000,
    retry: 1,
  });

  const positions: PositionData[] = posData?.data ?? [];

  // Filter to only open positions (non-zero qty)
  const openPositions = positions.filter((p) => Number(p.quantity) !== 0);

  const totalPnl = openPositions.reduce((acc, p) => acc + parseFloat(p.pnl ?? '0'), 0);

  if (isLoading) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-xs text-terminal-gray">
        LOADING POSITIONS...
      </div>
    );
  }

  if (isError) {
    const msg = error instanceof Error ? error.message : 'Unknown error';
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2">
        <span className="text-terminal-red">POSITIONS UNAVAILABLE</span>
        <span className="text-terminal-gray text-[10px]">{msg}</span>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden">
      {/* Total P&L header */}
      <div className="flex justify-between px-2 py-1 bg-terminal-gray font-bold flex-shrink-0">
        <span>TOTAL P&amp;L:</span>
        <span className={totalPnl >= 0 ? 'text-terminal-green' : 'text-terminal-red'}>
          {totalPnl >= 0 ? '+' : ''}
          {totalPnl.toFixed(2)}
        </span>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full text-left border-collapse">
          <thead className="bg-blue-900 text-white sticky top-0">
            <tr>
              <th className="p-1 border border-terminal-gray">SYMBOL</th>
              <th className="p-1 border border-terminal-gray text-right">QTY</th>
              <th className="p-1 border border-terminal-gray text-right">AVG</th>
              <th className="p-1 border border-terminal-gray text-right">LTP</th>
              <th className="p-1 border border-terminal-gray text-right">P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {openPositions.map((row, i) => {
              const pnl = parseFloat(row.pnl ?? '0');
              const isPos = pnl >= 0;
              const colorClass = isPos ? 'text-terminal-green' : 'text-terminal-red';
              const qty = Number(row.quantity);

              // Prefer live tick LTP over API ltp field
              const tickKey = `${row.symbol}.${row.exchange}`;
              const liveLtp = tickData[tickKey]?.ltp;
              const ltpDisplay = liveLtp != null
                ? liveLtp.toFixed(2)
                : row.ltp ?? '—';

              return (
                <tr key={i} className="border-b border-terminal-gray hover:bg-zinc-900">
                  <td className="p-1 border-r border-terminal-gray text-terminal-amber font-bold">
                    <span>{row.symbol}</span>
                    <span className="text-terminal-gray text-[9px] ml-1">{row.product}</span>
                  </td>
                  <td className={`p-1 text-right border-r border-terminal-gray ${qty >= 0 ? 'text-terminal-green' : 'text-terminal-red'}`}>
                    {qty}
                  </td>
                  <td className="p-1 text-right border-r border-terminal-gray">
                    {parseFloat(row.average_price).toFixed(2)}
                  </td>
                  <td className="p-1 text-right border-r border-terminal-gray text-terminal-amber">
                    {ltpDisplay}
                  </td>
                  <td className={`p-1 text-right font-bold ${colorClass}`}>
                    {isPos ? '+' : ''}
                    {pnl.toFixed(2)}
                  </td>
                </tr>
              );
            })}
            {openPositions.length === 0 && (
              <tr>
                <td colSpan={5} className="p-2 text-terminal-gray text-center">
                  No open positions
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

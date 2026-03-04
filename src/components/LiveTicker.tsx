'use client';

import React, { useEffect } from 'react';
import { useAtom } from 'jotai';
import { tickDataAtom } from '@/store/terminalStore';
import { wsService } from '@/lib/socket';
import type { TickData } from '@/lib/socket';

// Default symbols to show in the ticker (watchlist ticks + these fallbacks)
const TICKER_SYMBOLS = [
  { symbol: 'RELIANCE', exchange: 'NSE' },
  { symbol: 'TCS', exchange: 'NSE' },
  { symbol: 'INFY', exchange: 'NSE' },
  { symbol: 'HDFCBANK', exchange: 'NSE' },
  { symbol: 'ITC', exchange: 'NSE' },
  { symbol: 'SBIN', exchange: 'NSE' },
];

export function LiveTicker() {
  const [tickData, setTickData] = useAtom(tickDataAtom);

  // Subscribe to LTP mode (mode 1) for ticker symbols
  useEffect(() => {
    for (const s of TICKER_SYMBOLS) {
      wsService.subscribe(s.symbol, s.exchange, 1);
    }
    const unsub = wsService.onTick((data: TickData) => {
      const key = `${data.symbol}.${data.exchange}`;
      setTickData((prev) => ({ ...prev, [key]: data }));
    });
    return () => {
      unsub();
      for (const s of TICKER_SYMBOLS) {
        wsService.unsubscribe(s.symbol, s.exchange, 1);
      }
    };
  }, [setTickData]);

  // Build ticker items from live ticks or fall back to symbol name only
  const items = TICKER_SYMBOLS.map((s) => {
    const key = `${s.symbol}.${s.exchange}`;
    const tick = tickData[key];
    return {
      label: `${s.exchange}:${s.symbol}`,
      ltp: tick?.ltp ?? null,
      chgPct: tick?.change_percent ?? null,
    };
  });

  return (
    <div className="h-6 bg-terminal-gray border-t border-terminal-gray flex items-center overflow-hidden whitespace-nowrap text-xs font-mono shrink-0">
      <div className="animate-ticker inline-flex">
        {[...items, ...items].map((item, i) => {
          const isUp = (item.chgPct ?? 0) >= 0;
          return (
            <span key={i} className="mx-6 inline-flex items-center gap-1">
              <span className="text-terminal-amber">{item.label}</span>
              {item.ltp != null ? (
                <span className={isUp ? 'text-terminal-green' : 'text-terminal-red'}>
                  {item.ltp.toFixed(2)}
                  {item.chgPct != null && ` (${isUp ? '+' : ''}${item.chgPct.toFixed(2)}%)`}
                </span>
              ) : (
                <span className="text-terminal-gray">—</span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

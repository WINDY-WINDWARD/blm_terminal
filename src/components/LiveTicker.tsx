'use client';

import React, { useEffect } from 'react';
import { useAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import { tickDataAtom } from '@/store/terminalStore';
import { wsService } from '@/lib/socket';
import type { TickData } from '@/lib/socket';

// Shape returned by /api/py/market/top-gainers and top-losers
interface NseEquity {
  symbol: string;
  lastPrice: number;
  change: number;
  pChange: number;
  previousClose: number;
}

/** NSE returns numeric fields as comma-formatted strings like "2,450.30" — normalise to number. */
function toNum(val: unknown): number {
  if (typeof val === 'number') return val;
  if (typeof val === 'string') return parseFloat(val.replace(/,/g, '')) || 0;
  return 0;
}

function normalise(raw: Record<string, unknown>[]): NseEquity[] {
  return raw.map((r) => ({
    symbol: String(r.symbol ?? ''),
    lastPrice: toNum(r.lastPrice),
    change: toNum(r.change),
    pChange: toNum(r.pChange),
    previousClose: toNum(r.previousClose),
  }));
}

async function fetchTopMovers(): Promise<{ gainers: NseEquity[]; losers: NseEquity[] }> {
  const [gRes, lRes] = await Promise.all([
    fetch('/api/py/market/top-gainers'),
    fetch('/api/py/market/top-losers'),
  ]);

  if (!gRes.ok || !lRes.ok) {
    throw new Error('Failed to fetch top movers from backend');
  }

  const [rawGainers, rawLosers]: [Record<string, unknown>[], Record<string, unknown>[]] =
    await Promise.all([gRes.json(), lRes.json()]);

  return { gainers: normalise(rawGainers), losers: normalise(rawLosers) };
}

export function LiveTicker() {
  const [tickData, setTickData] = useAtom(tickDataAtom);

  const { data: movers } = useQuery({
    queryKey: ['ticker-top-movers'],
    queryFn: fetchTopMovers,
    refetchInterval: 60_000, // refresh every 60 s
    staleTime: 30_000,
  });

  // Subscribe to live WS ticks for all symbols shown in the ticker
  useEffect(() => {
    if (!movers) return;

    const symbols = [
      ...movers.gainers.map((s) => s.symbol),
      ...movers.losers.map((s) => s.symbol),
    ];

    for (const sym of symbols) {
      wsService.subscribe(sym, 'NSE', 1);
    }

    const unsub = wsService.onTick((data: TickData) => {
      const key = `${data.symbol}.${data.exchange}`;
      setTickData((prev) => ({ ...prev, [key]: data }));
    });

    return () => {
      unsub();
      for (const sym of symbols) {
        wsService.unsubscribe(sym, 'NSE', 1);
      }
    };
  }, [movers, setTickData]);

  // Build display items — overlay live WS tick where available, else use backend snapshot
  const items = React.useMemo(() => {
    if (!movers) return [];

    const toItem = (equity: NseEquity, kind: 'gainer' | 'loser') => {
      const key = `${equity.symbol}.NSE`;
      const tick = tickData[key];
      return {
        label: `NSE:${equity.symbol}`,
        ltp: tick?.ltp ?? equity.lastPrice,
        chgPct: tick?.change_percent ?? equity.pChange,
        kind,
      };
    };

    return [
      ...movers.gainers.map((e) => toItem(e, 'gainer')),
      ...movers.losers.map((e) => toItem(e, 'loser')),
    ];
  }, [movers, tickData]);

  if (items.length === 0) {
    return (
      <div className="h-6 bg-terminal-bg border-t border-terminal-gray flex items-center
                      overflow-hidden whitespace-nowrap text-xs font-mono shrink-0 px-4">
        <span className="text-terminal-gray">Loading market data…</span>
      </div>
    );
  }

  return (
    <div className="h-6 bg-terminal-bg border-t border-terminal-gray flex items-center
                    overflow-hidden whitespace-nowrap text-xs font-mono shrink-0">
      <div className="animate-ticker inline-flex">
        {[...items, ...items].map((item, i) => {
          const isUp = (item.chgPct ?? 0) >= 0;
          const chgColor = isUp ? 'text-terminal-green' : 'text-terminal-red';
          return (
            <span key={i} className="mx-6 inline-flex items-center gap-1">
              <span className="text-terminal-amber">{item.label}</span>
              <span className={chgColor}>
                {item.ltp.toFixed(2)}
                {item.chgPct != null &&
                  ` (${isUp ? '+' : ''}${item.chgPct.toFixed(2)}%)`}
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

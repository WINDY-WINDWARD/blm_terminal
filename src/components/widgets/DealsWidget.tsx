'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom } from '@/store/terminalStore';

// ─── Types ────────────────────────────────────────────────────────────────────

interface TradeRecord {
  period: string | null;
  person: string | null;
  category: string | null;
  quantity_raw: string | null;
  quantity: number | null;
  direction: 'up' | 'down' | null;
  avg_price_raw: string | null;
  avg_price: number | null;
  value_raw: string | null;
  value: number | null;
  value_in: string | null;
  small_quantity: boolean;
}

interface ScreenerTradesResponse {
  insider_trades: TradeRecord[];
  bulk_deals: TradeRecord[];
  block_deals: TradeRecord[];
}

type Tab = 'insider' | 'bulk' | 'block';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null, decimals = 0): string {
  if (n === null) return '—';
  return n.toLocaleString('en-IN', { maximumFractionDigits: decimals });
}

function DirectionCell({ record }: { record: TradeRecord }) {
  // Insider trades have direction + quantity; deals have quantity_raw like "B"/"Sale"
  if (record.direction === 'up') {
    const qty = record.quantity !== null ? fmt(record.quantity) : record.quantity_raw ?? '—';
    return <span className="text-terminal-green font-bold">▲ {qty}</span>;
  }
  if (record.direction === 'down') {
    const qty = record.quantity !== null ? fmt(Math.abs(record.quantity)) : record.quantity_raw ?? '—';
    return <span className="text-terminal-red font-bold">▼ {qty}</span>;
  }
  // Bulk/block: quantity_raw holds "B" / "Sale" etc., quantity is null
  const raw = record.quantity_raw ?? '—';
  const upper = raw.toUpperCase();
  if (upper === 'B' || upper === 'BUY')
    return <span className="text-terminal-green font-bold">BUY</span>;
  if (upper === 'S' || upper === 'SALE' || upper === 'SELL')
    return <span className="text-terminal-red font-bold">SELL</span>;
  return <span className="text-white/60">{raw}</span>;
}

function ValueCell({ record }: { record: TradeRecord }) {
  if (record.value === null) return <span className="text-white/40">—</span>;
  const suffix = record.value_in === 'lacs' ? 'L' : record.value_in === 'price' ? '₹' : '';
  return (
    <span className="text-terminal-amber">
      {record.value_in === 'price' ? `${suffix}${fmt(record.value)}` : `${fmt(record.value)}${suffix}`}
    </span>
  );
}

interface SectionTableProps {
  rows: TradeRecord[];
  showCategory: boolean;
}

function SectionTable({ rows, showCategory }: SectionTableProps) {
  if (rows.length === 0) {
    return <div className="text-white/40 text-[10px] py-2 px-1">No records</div>;
  }

  return (
    <table className="w-full border-collapse text-[10px]">
      <thead className="sticky top-0 bg-terminal-bg z-10">
        <tr className="text-[9px] text-white/60 uppercase border-b border-terminal-gray/60">
          <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Period</th>
          <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Person</th>
          {showCategory && (
            <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Category</th>
          )}
          <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Qty / Dir</th>
          <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">Avg Price</th>
          <th className="text-right pb-1 font-normal whitespace-nowrap">Value</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={`${row.period}-${row.person}-${i}`}
            className="border-b border-terminal-gray/30 hover:bg-zinc-900"
          >
            <td className="py-[3px] pr-2 text-white whitespace-nowrap">
              {row.period ?? '—'}
            </td>
            <td
              className="py-[3px] pr-2 text-white max-w-[120px] truncate"
              title={row.person ?? undefined}
            >
              {row.person ?? <span className="text-white/40">—</span>}
            </td>
            {showCategory && (
              <td
                className="py-[3px] pr-2 text-white/60 max-w-[100px] truncate text-[9px]"
                title={row.category ?? undefined}
              >
                {row.category || <span className="text-white/30">—</span>}
              </td>
            )}
            <td className="py-[3px] pr-2 whitespace-nowrap">
              <DirectionCell record={row} />
            </td>
            <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
              {row.avg_price !== null ? fmt(row.avg_price) : (row.avg_price_raw ?? '—')}
            </td>
            <td className="py-[3px] text-right whitespace-nowrap">
              <ValueCell record={row} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function DealsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const [activeTab, setActiveTab] = useState<Tab>('insider');

  const { data, isLoading, isError, error } = useQuery<ScreenerTradesResponse>({
    queryKey: ['screener/trades', symbol],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/screener/trades/${encodeURIComponent(symbol)}`,
      );
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const json = (await res.json()) as { detail?: string };
          if (json.detail) detail = json.detail;
        } catch { /* ignore */ }
        const err = new Error(detail);
        (err as Error & { status: number }).status = res.status;
        throw err;
      }
      return res.json() as Promise<ScreenerTradesResponse>;
    },
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: !!symbol,
  });

  // ── No symbol ─────────────────────────────────────────────────────────────

  if (!symbol) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-xs text-white/40">
        No symbol selected
      </div>
    );
  }

  // ── Loading ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">LOADING DEALS...</span>
        <span className="text-white text-[10px]">{symbol}</span>
      </div>
    );
  }

  // ── Error ──────────────────────────────────────────────────────────────────

  if (isError || !data) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    const status = (error as Error & { status?: number })?.status;
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1 px-4 text-center">
        {status === 503 ? (
          <>
            <span className="text-terminal-red font-bold uppercase">Session Unavailable</span>
            <span className="text-white text-[10px]">
              screener.in session not found — log in and restart the backend.
            </span>
          </>
        ) : status === 404 ? (
          <>
            <span className="text-terminal-red font-bold uppercase">Symbol Not Found</span>
            <span className="text-white text-[10px]">{symbol} was not found on screener.in</span>
          </>
        ) : (
          <>
            <span className="text-terminal-red font-bold uppercase">Fetch Failed</span>
            <span className="text-white text-[10px] max-w-xs">{errMsg}</span>
          </>
        )}
      </div>
    );
  }

  // ── Data ───────────────────────────────────────────────────────────────────

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'insider', label: 'Insider',  count: data.insider_trades.length },
    { id: 'bulk',    label: 'Bulk',     count: data.bulk_deals.length     },
    { id: 'block',   label: 'Block',    count: data.block_deals.length    },
  ];

  const activeRows =
    activeTab === 'insider' ? data.insider_trades :
    activeTab === 'bulk'    ? data.bulk_deals     :
                              data.block_deals;

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">

      {/* Header */}
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Deals &amp; Insider Trades
        </span>
        <span className="text-white text-[10px] flex-shrink-0">{symbol}</span>
      </div>

      {/* Tabs */}
      <div className="flex-shrink-0 flex border-b border-terminal-gray/60">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors border-b-2 ${
              activeTab === tab.id
                ? 'bg-terminal-amber text-black font-bold -mb-px'
                : 'text-white/50 hover:text-white hover:bg-zinc-900 border-transparent'
            }`}
            style={activeTab === tab.id ? { borderBottomColor: '#ffb900' } : undefined}
          >
            {tab.label}
            <span className={`ml-1 text-[9px] ${activeTab === tab.id ? 'text-black/60' : 'text-white/30'}`}>
              ({tab.count})
            </span>
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        <SectionTable
          rows={activeRows}
          showCategory={activeTab === 'insider'}
        />
      </div>
    </div>
  );
}

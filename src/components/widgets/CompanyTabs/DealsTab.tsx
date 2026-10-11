'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchIinvestAll,
  type IinvestAllResponse,
  type IinvestInsiderRow,
} from '@/lib/iinvest';
import { IinvestGenericTable, type IinvestColumn } from './IinvestGenericTable';

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

type Tab = 'insider' | 'bulk' | 'block' | 'sast';

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
  if (record.value === null) return <span className="text-white/60">—</span>;
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
    return <div className="text-white/60 text-sm py-2 px-1">No records</div>;
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead className="sticky top-0 bg-terminal-bg z-10">
        <tr className="text-xs text-white/60 uppercase border-b border-terminal-gray/60">
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
              {row.person ?? <span className="text-white/60">—</span>}
            </td>
            {showCategory && (
              <td
                className="py-[3px] pr-2 text-white/60 max-w-[100px] truncate text-xs"
                title={row.category ?? undefined}
              >
                {row.category || <span className="text-white/60">—</span>}
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

// ─── iinvest → TradeRecord mapper ────────────────────────────────────────────

function mapIinvestInsiderToTradeRecords(rows: IinvestInsiderRow[]): TradeRecord[] {
  const toNum = (v: string | number | undefined): number | null => {
    if (v === undefined || v === null) return null;
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return rows.map((r) => {
    const type = String(r.f_12 || '').toUpperCase();
    const direction: 'up' | 'down' | null =
      type === 'B' || type === 'BUY' ? 'up'
      : type === 'S' || type === 'SELL' || type === 'SALE' ? 'down'
      : null;
    return {
      period: r.f_28 ?? null,
      person: r.f_4 ?? null,
      category: r.f_5 ?? null,
      quantity_raw: r.f_12 ?? null,
      quantity: toNum(r.f_10),
      direction,
      avg_price_raw: null,
      avg_price: null,
      value_raw: null,
      value: null,
      value_in: null,
      small_quantity: false,
    };
  });
}

function mapIinvestBlockToTradeRecords(rows: Array<Record<string, unknown>>): TradeRecord[] {
  const toNum = (v: unknown): number | null => {
    if (v === undefined || v === null) return null;
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return rows.map((r) => {
    const type = String(r.f_33 || '').toUpperCase();
    const direction: 'up' | 'down' | null =
      type === 'B' || type === 'BUY' ? 'up'
      : type === 'S' || type === 'SELL' || type === 'SALE' ? 'down'
      : null;
    return {
      period: (r.f_35 as string | undefined) ?? null,
      person: (r.f_32 as string | undefined) ?? null,
      category: null,
      quantity_raw: (r.f_33 as string | undefined) ?? null,
      quantity: toNum(r.f_34),
      direction,
      avg_price_raw: null,
      avg_price: toNum(r.f_36),
      value_raw: null,
      value: null,
      value_in: 'price',
      small_quantity: false,
    };
  });
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function DealsTab({ symbol }: { symbol: string }) {
  const [activeTab, setActiveTab] = useState<string>('bulk');
const { data: allData, isLoading: isAllLoading } = useQuery<[ScreenerTradesResponse, IinvestAllResponse]>({
    queryKey: ['deals/all', symbol],
    queryFn: async () => {
      const fetchScreener = async (): Promise<ScreenerTradesResponse> => {
        const res = await fetch(`/api/py/screener/trades/${encodeURIComponent(symbol)}`);
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
      };

      const [screenerRes, iinvestRes] = await Promise.all([
        fetchScreener().catch(() => {
          return { insider_trades: [], bulk_deals: [], block_deals: [] } as ScreenerTradesResponse;
        }),
        fetchIinvestAll(symbol).catch(() => {
          return {} as IinvestAllResponse;
        }),
      ]);
      return [screenerRes, iinvestRes];
    },
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const [screenerTradesData, iinvestAllData] = allData ?? [
    { insider_trades: [], bulk_deals: [], block_deals: [] },
    {},
  ];

  const sastData = iinvestAllData?.sast;
  const iinvestInsider = iinvestAllData?.insider_trading;
  const iinvestBlockData = iinvestAllData?.block_deals;
  const iinvestBulkData = iinvestAllData?.bulk_deals;

  const iinvestBulkCount = iinvestBulkData?.response?.data?.length ?? 0;
  const iinvestBlockCount = iinvestBlockData?.response?.data?.length ?? 0;

  if (!symbol) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-xs text-white/60">
        No symbol selected
      </div>
    );
  }

  const screenerData: ScreenerTradesResponse = screenerTradesData ?? {
    insider_trades: [],
    bulk_deals: [],
    block_deals: [],
  };

  const iinvestInsiderRows = iinvestInsider?.response?.data
    ? mapIinvestInsiderToTradeRecords(iinvestInsider.response.data)
    : [];

  const insiderRows = screenerData.insider_trades.length > 0
    ? screenerData.insider_trades
    : iinvestInsiderRows;
    
  const iinvestBulkRawRows = iinvestBulkData?.response?.data ?? [];
  const iinvestBlockRawRows = iinvestBlockData?.response?.data ?? [];
  const iinvestBulkTradeRecords = mapIinvestBlockToTradeRecords(iinvestBulkRawRows);
  const iinvestBlockTradeRecords = mapIinvestBlockToTradeRecords(iinvestBlockRawRows);
  
  const useIinvestBulk = iinvestBulkCount > 0 && iinvestBulkCount >= screenerData.bulk_deals.length;
  const bulkRows = useIinvestBulk ? iinvestBulkTradeRecords : screenerData.bulk_deals;

  const useIinvestBlock = iinvestBlockCount > 0 && iinvestBlockCount >= screenerData.block_deals.length;
  const blockRows = useIinvestBlock ? iinvestBlockTradeRecords : screenerData.block_deals;

  const tabs: { id: Tab; label: string; count: number; description: string }[] = [
    { id: 'insider', label: 'Insider', count: insiderRows.length, description: 'Buys/sells by directors, officers, promoters, and their relatives (SEBI Reg. 7(2))' },
    { id: 'bulk',    label: 'Bulk',    count: bulkRows.length,    description: 'Bulk deals — single transaction crossing 0.5% of a company’s paid-up capital' },
    { id: 'block',   label: 'Block',   count: blockRows.length,   description: 'Block deals — negotiated trade window 09:15–09:40 IST for 5%+ block size' },
    { id: 'sast',    label: 'SAST',    count: sastData?.response?.data?.length ?? 0, description: 'Substantial Acquisition of Shares & Takeovers (SEBI Reg. 29(2))' },
  ];

  const activeRows: TradeRecord[] =
    activeTab === 'insider' ? insiderRows :
    activeTab === 'bulk'    ? bulkRows    :
    activeTab === 'block'   ? blockRows   :
    [];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">

      {/* Header */}
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Deals &amp; Insider Trades
        </span>
        <span className="text-white text-sm flex-shrink-0">{symbol}</span>
      </div>

      {/* Tabs */}
      <div className="flex-shrink-0 flex border-b border-terminal-gray/60 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-sm font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors border-b-2 whitespace-nowrap ${
              activeTab === tab.id
                ? 'bg-terminal-amber text-black font-bold -mb-px'
                : 'text-white/80 hover:text-white hover:bg-zinc-900 border-transparent'
            }`}
            style={activeTab === tab.id ? { borderBottomColor: '#ffb900' } : undefined}
            title={tab.description}
          >
            {tab.label}
            <span className={`ml-1 text-xs ${activeTab === tab.id ? 'text-black/60' : 'text-white/60'}`}>
              ({tab.count})
            </span>
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {activeTab === 'insider' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING INSIDER TRADES...
          </div>
        ) : activeTab === 'bulk' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING BULK DEALS...
          </div>
        ) : activeTab === 'block' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING BLOCK DEALS...
          </div>
        ) : activeTab === 'sast' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING SAST DISCLOSURES...
          </div>
        ) : activeTab === 'insider' || activeTab === 'bulk' || activeTab === 'block' ? (
          <SectionTable
            rows={activeRows}
            showCategory={activeTab === 'insider'}
          />
        ) : activeTab === 'sast' ? (
          <IinvestGenericTable
            data={sastData?.response?.data ?? []}
            columns={(sastData?.response?.columns ?? []) as IinvestColumn[]}
            emptyMsg="No SAST disclosures on record"
          />
        ) : null}
      </div>
    </div>
  );
}

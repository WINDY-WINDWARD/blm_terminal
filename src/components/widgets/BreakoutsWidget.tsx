'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';

type BreakoutTab = 'high' | 'low';

interface RawBreakoutItem {
  symbol: string;
  series?: string;
  comapnyName?: string;
  companyName?: string;
  new52WHL?: number;
  prev52WHL?: number;
  prevHLDate?: string;
  ltp?: number;
  prevClose?: string | number;
  change?: number;
  pChange?: number;
}

interface BreakoutResponseBase {
  data?: RawBreakoutItem[];
  timestamp?: string;
}

interface BreakoutHighResponse extends BreakoutResponseBase {
  high?: number;
}

interface BreakoutLowResponse extends BreakoutResponseBase {
  low?: number;
}

interface BreakoutRow {
  symbol: string;
  name: string;
  ltp: number | null;
  change: number | null;
  pChange: number | null;
  new52WHL: number | null;
  prev52WHL: number | null;
  prevHLDate: string | null;
}

function formatNumber(value: number | null, digits = 2): string {
  if (value === null || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function ChangeCell({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) {
    return <span className="text-white/40">—</span>;
  }
  const isUp = value > 0;
  const color = isUp ? 'text-terminal-green' : 'text-terminal-red';
  const sign = isUp ? '+' : '';
  return <span className={`${color} font-bold`}>{sign}{formatNumber(value, 2)}</span>;
}

function PercentCell({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) {
    return <span className="text-white/40">—</span>;
  }
  const isUp = value > 0;
  const color = isUp ? 'text-terminal-green' : 'text-terminal-red';
  const sign = isUp ? '+' : '';
  return (
    <span className={`${color} font-bold`}>
      {sign}
      {formatNumber(value, 2)}
      %
    </span>
  );
}

function normalizeRow(item: RawBreakoutItem): BreakoutRow {
  const name = item.companyName ?? item.comapnyName ?? '';

  const parseNum = (v: unknown): number | null => {
    if (v === null || v === undefined) return null;
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (typeof v === 'string') {
      const n = Number(v.replace(/,/g, ''));
      return Number.isFinite(n) ? n : null;
    }
    return null;
  };

  return {
    symbol: item.symbol,
    name,
    ltp: parseNum(item.ltp),
    change: parseNum(item.change),
    pChange: parseNum(item.pChange),
    new52WHL: parseNum(item.new52WHL),
    prev52WHL: parseNum(item.prev52WHL),
    prevHLDate: item.prevHLDate ?? null,
  };
}

interface BreakoutTableProps {
  rows: BreakoutRow[];
  onRowClick: (row: BreakoutRow) => void;
}

function BreakoutTable({ rows, onRowClick }: BreakoutTableProps) {
  if (!rows.length) {
    return (
      <div className="text-white/40 text-[10px] py-2 px-1">
        No breakout symbols in this bucket.
      </div>
    );
  }

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-[10px] min-w-[640px]">
        <thead className="sticky top-0 bg-terminal-bg z-10">
          <tr className="text-[9px] text-white/60 uppercase border-b border-terminal-gray/60">
            <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Symbol</th>
            <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Name</th>
            <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">LTP</th>
            <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">Change</th>
            <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">Change %</th>
            <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">New 52W</th>
            <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">Prev 52W</th>
            <th className="text-right pb-1 font-normal whitespace-nowrap">Prev HL Date</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.symbol}
              onClick={() => onRowClick(row)}
              className="border-b border-terminal-gray/30 hover:bg-zinc-900 cursor-pointer"
            >
              <td className="py-[3px] pr-2 font-bold text-terminal-amber whitespace-nowrap">
                {row.symbol}
              </td>
              <td
                className="py-[3px] pr-2 text-white max-w-[180px] truncate"
                title={row.name}
              >
                {row.name || <span className="text-white/40">—</span>}
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatNumber(row.ltp, 2)}
              </td>
              <td className="py-[3px] pr-2 text-right whitespace-nowrap">
                <ChangeCell value={row.change} />
              </td>
              <td className="py-[3px] pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.pChange} />
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatNumber(row.new52WHL, 2)}
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatNumber(row.prev52WHL, 2)}
              </td>
              <td className="py-[3px] pr-2 text-right text-white/70 whitespace-nowrap">
                {row.prevHLDate ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BreakoutsWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [activeTab, setActiveTab] = useState<BreakoutTab>('high');

  const {
    data: highData,
    isLoading: highLoading,
    isError: highError,
    error: highErr,
  } = useQuery<BreakoutHighResponse>({
    queryKey: ['market/52week-high'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/52week-high');
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const json = (await res.json()) as { detail?: string };
          if (json.detail) detail = json.detail;
        } catch {
          // ignore
        }
        const err = new Error(detail);
        (err as Error & { status: number }).status = res.status;
        throw err;
      }
      return res.json() as Promise<BreakoutHighResponse>;
    },
    staleTime: 3 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const {
    data: lowData,
    isLoading: lowLoading,
    isError: lowError,
    error: lowErr,
  } = useQuery<BreakoutLowResponse>({
    queryKey: ['market/52week-low'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/52week-low');
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const json = (await res.json()) as { detail?: string };
          if (json.detail) detail = json.detail;
        } catch {
          // ignore
        }
        const err = new Error(detail);
        (err as Error & { status: number }).status = res.status;
        throw err;
      }
      return res.json() as Promise<BreakoutLowResponse>;
    },
    staleTime: 3 * 60 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const isLoading = highLoading || lowLoading;

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">
          LOADING BREAKOUTS...
        </span>
      </div>
    );
  }

  if (highError || lowError || !highData || !lowData) {
    const error = (highErr ?? lowErr) as Error & { status?: number } | undefined;
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    const status = error?.status;

    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1 px-4 text-center">
        {status === 503 ? (
          <>
            <span className="text-terminal-red font-bold uppercase">Service Unavailable</span>
            <span className="text-white text-[10px]">
              NSE 52-week breakout data is currently unavailable. Please try again later.
            </span>
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

  const highRows: BreakoutRow[] = (highData.data ?? []).map(normalizeRow);
  const lowRows: BreakoutRow[] = (lowData.data ?? []).map(normalizeRow);

  const activeRows = activeTab === 'high' ? highRows : lowRows;
  const timestamp = activeTab === 'high' ? highData.timestamp : lowData.timestamp;

  const handleRowClick = (row: BreakoutRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
  };

  const tabs: { id: BreakoutTab; label: string; count: number }[] = [
    { id: 'high', label: '52W HIGH', count: highRows.length },
    { id: 'low', label: '52W LOW', count: lowRows.length },
  ];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Breakouts
        </span>
        <span className="text-white/60 text-[10px]">
          NSE 52-week High / Low
        </span>
        {timestamp && (
          <span className="text-white/40 text-[10px] ml-auto">
            as of {timestamp}
          </span>
        )}
      </div>

      <div className="flex-shrink-0 flex border-b border-terminal-gray/60">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors ${
              activeTab === tab.id
                ? 'bg-blue-900 text-white'
                : 'text-white/50 hover:text-white hover:bg-zinc-900'
            }`}
          >
            <span className="inline-flex items-center gap-1">
              <span>{tab.label}</span>
              <span className="inline-flex items-center justify-center min-w-[18px] h-[14px] rounded-full bg-terminal-gray text-[9px] text-white px-1">
                {tab.count}
              </span>
            </span>
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        <BreakoutTable rows={activeRows} onRowClick={handleRowClick} />
      </div>
    </div>
  );
}


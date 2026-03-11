'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';

type BreakoutTab = 'high' | 'low' | 'volume';

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

interface VolumeGainerItem {
  symbol: string;
  companyName: string;
  ltp: number;
  pChange: number;
  volume: number;
  week1AvgVolume: number;
  week1volChange: number;
  week2AvgVolume: number;
  week2volChange: number;
  turnover: number;
}

interface VolumeGainerResponse {
  data?: VolumeGainerItem[];
  timestamp?: string;
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

type SortColumn = 'symbol' | 'name' | 'ltp' | 'change' | 'pChange' | 'new52WHL' | 'prev52WHL' | 'prevHLDate';
type SortDirection = 'asc' | 'desc';

interface BreakoutTableProps {
  rows: BreakoutRow[];
  onRowClick: (row: BreakoutRow) => void;
}

type ColumnConfig = {
  key: SortColumn;
  label: string;
  textAlign: 'left' | 'right';
  defaultSort: SortDirection;
};

const COLUMNS: ColumnConfig[] = [
  { key: 'symbol', label: 'Symbol', textAlign: 'left', defaultSort: 'asc' },
  { key: 'name', label: 'Name', textAlign: 'left', defaultSort: 'asc' },
  { key: 'ltp', label: 'LTP', textAlign: 'right', defaultSort: 'desc' },
  { key: 'change', label: 'Change', textAlign: 'right', defaultSort: 'desc' },
  { key: 'pChange', label: 'Change %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'new52WHL', label: 'New 52W', textAlign: 'right', defaultSort: 'desc' },
  { key: 'prev52WHL', label: 'Prev 52W', textAlign: 'right', defaultSort: 'desc' },
  { key: 'prevHLDate', label: 'Prev HL Date', textAlign: 'right', defaultSort: 'asc' },
];

type VolumeColumnKey = 'symbol' | 'companyName' | 'ltp' | 'pChange' | 'volume' | 'week1AvgVolume' | 'week1volChange' | 'week2AvgVolume' | 'week2volChange' | 'turnover';

type VolumeColumnConfig = {
  key: VolumeColumnKey;
  label: string;
  textAlign: 'left' | 'right';
  defaultSort: SortDirection;
};

const VOLUME_COLUMNS: VolumeColumnConfig[] = [
  { key: 'symbol', label: 'Symbol', textAlign: 'left', defaultSort: 'asc' },
  { key: 'companyName', label: 'Company', textAlign: 'left', defaultSort: 'asc' },
  { key: 'ltp', label: 'LTP', textAlign: 'right', defaultSort: 'desc' },
  { key: 'pChange', label: 'Change %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'volume', label: 'Volume', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week1AvgVolume', label: 'Wk1 Avg', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week1volChange', label: 'Wk1 Chg %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week2AvgVolume', label: 'Wk2 Avg', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week2volChange', label: 'Wk2 Chg %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'turnover', label: 'Turnover ₹Cr', textAlign: 'right', defaultSort: 'desc' },
];

function compareValues(a: unknown, b: unknown, direction: SortDirection): number {
  // Handle nulls and undefined — sort last regardless of direction
  const aNull = a === null || a === undefined;
  const bNull = b === null || b === undefined;
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  // Numeric comparison
  if (typeof a === 'number' && typeof b === 'number') {
    const result = a - b;
    return direction === 'asc' ? result : -result;
  }

  // String comparison (includes date strings)
  if (typeof a === 'string' && typeof b === 'string') {
    const result = a.localeCompare(b);
    return direction === 'asc' ? result : -result;
  }

  return 0;
}

function BreakoutTable({ rows, onRowClick }: BreakoutTableProps) {
  const [sortColumn, setSortColumn] = useState<SortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const handleHeaderClick = (column: SortColumn) => {
    const columnConfig = COLUMNS.find((c) => c.key === column);
    if (!columnConfig) return;

    if (sortColumn === column) {
      // Toggle direction if clicking same column
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      // New column: use default sort direction
      setSortColumn(column);
      setSortDirection(columnConfig.defaultSort);
    }
  };

  // Sort rows
  const sortedRows = (() => {
    if (!sortColumn) return rows;

    return [...rows].sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];
      return compareValues(aVal, bVal, sortDirection);
    });
  })();

  if (!rows.length) {
    return (
      <div className="text-white/40 text-[10px] py-2 px-1">
        No breakout symbols in this bucket.
      </div>
    );
  }

  const getSortIndicator = (column: SortColumn) => {
    if (sortColumn !== column) return '';
    return sortDirection === 'asc' ? ' ▲' : ' ▼';
  };

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-[10px] min-w-[640px]">
        <thead className="sticky top-0 bg-terminal-bg z-10">
          <tr className="text-[9px] text-white/60 uppercase border-b border-terminal-gray/60">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className={`pb-1 font-normal pr-2 whitespace-nowrap cursor-pointer hover:text-white transition-colors ${
                  col.textAlign === 'left' ? 'text-left' : 'text-right'
                }`}
              >
                {col.label}
                {getSortIndicator(col.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
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

function formatVolume(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

interface VolumeTableProps {
  rows: VolumeGainerItem[];
  onRowClick: (row: VolumeGainerItem) => void;
}

function VolumeTable({ rows, onRowClick }: VolumeTableProps) {
  const [sortColumn, setSortColumn] = useState<VolumeColumnKey | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const handleHeaderClick = (column: VolumeColumnKey) => {
    const columnConfig = VOLUME_COLUMNS.find((c) => c.key === column);
    if (!columnConfig) return;

    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection(columnConfig.defaultSort);
    }
  };

  const sortedRows = (() => {
    if (!sortColumn) return rows;

    return [...rows].sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];
      return compareValues(aVal, bVal, sortDirection);
    });
  })();

  if (!rows.length) {
    return (
      <div className="text-white/40 text-[10px] py-2 px-1">
        No volume gainers available.
      </div>
    );
  }

  const getSortIndicator = (column: VolumeColumnKey) => {
    if (sortColumn !== column) return '';
    return sortDirection === 'asc' ? ' ▲' : ' ▼';
  };

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-[10px] min-w-[900px]">
        <thead className="sticky top-0 bg-terminal-bg z-10">
          <tr className="text-[9px] text-white/60 uppercase border-b border-terminal-gray/60">
            {VOLUME_COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className={`pb-1 font-normal pr-2 whitespace-nowrap cursor-pointer hover:text-white transition-colors ${
                  col.textAlign === 'left' ? 'text-left' : 'text-right'
                }`}
              >
                {col.label}
                {getSortIndicator(col.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr
              key={row.symbol}
              onClick={() => onRowClick(row)}
              className="border-b border-terminal-gray/30 hover:bg-zinc-900 cursor-pointer"
            >
              <td className="py-[3px] pr-2 font-bold text-terminal-amber whitespace-nowrap">
                {row.symbol}
              </td>
              <td className="py-[3px] pr-2 text-white max-w-[140px] truncate" title={row.companyName}>
                {row.companyName || <span className="text-white/40">—</span>}
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatNumber(row.ltp, 2)}
              </td>
              <td className="py-[3px] pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.pChange} />
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatVolume(row.volume)}
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatVolume(row.week1AvgVolume)}
              </td>
              <td className="py-[3px] pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.week1volChange} />
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                {formatVolume(row.week2AvgVolume)}
              </td>
              <td className="py-[3px] pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.week2volChange} />
              </td>
              <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
                ₹{formatNumber(row.turnover, 2)}
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

  const {
    data: volumeData,
    isLoading: volumeLoading,
    isError: volumeError,
    error: volumeErr,
  } = useQuery<VolumeGainerResponse>({
    queryKey: ['market/volume-gainers'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/volume-gainers');
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
      return res.json() as Promise<VolumeGainerResponse>;
    },
    staleTime: 25 * 60 * 1000,
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
  const volumeRows: VolumeGainerItem[] = volumeData?.data ?? [];

  const timestamp = activeTab === 'high' ? highData.timestamp : activeTab === 'low' ? lowData.timestamp : volumeData?.timestamp;

  const handleRowClick = (row: BreakoutRow) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
  };

  const handleVolumeRowClick = (row: VolumeGainerItem) => {
    setActiveSymbol(row.symbol);
    setActiveExchange('NSE');
  };

  const tabs: { id: BreakoutTab; label: string; count: number }[] = [
    { id: 'high', label: '52W HIGH', count: highRows.length },
    { id: 'low', label: '52W LOW', count: lowRows.length },
    { id: 'volume', label: 'VOLUME', count: volumeRows.length },
  ];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Breakouts
        </span>
        <span className="text-white/60 text-[10px]">
          {activeTab === 'volume' ? 'Volume Gainers' : 'NSE 52-week High / Low'}
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
        {activeTab === 'volume' ? (
          volumeLoading ? (
            <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs">
              <span className="text-terminal-amber/60 animate-pulse">
                LOADING VOLUME...
              </span>
            </div>
          ) : volumeError || !volumeData ? (
            <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1 px-4 text-center">
              {(volumeErr as Error & { status?: number } | undefined)?.status === 503 ? (
                <>
                  <span className="text-terminal-red font-bold uppercase">Service Unavailable</span>
                  <span className="text-white text-[10px]">
                    Volume data is currently unavailable. Please try again later.
                  </span>
                </>
              ) : (
                <>
                  <span className="text-terminal-red font-bold uppercase">Fetch Failed</span>
                  <span className="text-white text-[10px] max-w-xs">
                    {volumeErr instanceof Error ? volumeErr.message : 'Unknown error'}
                  </span>
                </>
              )}
            </div>
          ) : (
            <VolumeTable rows={volumeRows} onRowClick={handleVolumeRowClick} />
          )
        ) : (
          <BreakoutTable rows={activeTab === 'high' ? highRows : lowRows} onRowClick={handleRowClick} />
        )}
      </div>
    </div>
  );
}


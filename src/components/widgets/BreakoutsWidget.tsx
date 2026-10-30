'use client';

import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';

type BreakoutTab = 'matrix' | 'high' | 'low' | 'volume' | 'repeated';

interface RepeatedItem {
  symbol: string;
  breakout_type: string;
  appearances: number;
  window_days: number;
  last_seen: string;
}

const REPEATED_TYPE_LABELS: Record<string, string> = {
  '52W_HIGH': '52W HIGH',
  '52W_LOW': '52W LOW',
  VOLUME_GAINER: 'VOLUME',
};

const REPEATED_TYPE_COLORS: Record<string, string> = {
  '52W_HIGH': 'bg-terminal-amber/15 text-terminal-amber border border-terminal-amber/40',
  '52W_LOW': 'bg-rose-500/15 text-rose-400 border border-rose-500/40',
  VOLUME_GAINER: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/40',
};

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

function formatVolume(vol: number | null | undefined): string {
  if (vol === null || vol === undefined || Number.isNaN(vol)) return '—';
  if (vol >= 1_00_00_000) return `${(vol / 1_00_00_000).toFixed(2)}Cr`;
  if (vol >= 1_00_000) return `${(vol / 1_00_000).toFixed(2)}L`;
  if (vol >= 1_000) return `${(vol / 1_000).toFixed(1)}K`;
  return String(vol);
}

function ChangeCell({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) {
    return <span className="text-zinc-400">—</span>;
  }
  const isUp = value > 0;
  const color = isUp ? 'text-emerald-400' : 'text-rose-400';
  const sign = isUp ? '+' : '';
  return <span className={`${color} font-bold tabular-nums`}>{sign}{formatNumber(value, 2)}</span>;
}

function PercentCell({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) {
    return <span className="text-zinc-400">—</span>;
  }
  const isUp = value > 0;
  const color = isUp ? 'text-emerald-400' : 'text-rose-400';
  const sign = isUp ? '+' : '';
  return (
    <span className={`${color} font-bold tabular-nums`}>
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
  volumeMap: Map<string, VolumeGainerItem>;
  mode: 'high' | 'low';
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
  { key: 'ltp', label: 'LTP (₹)', textAlign: 'right', defaultSort: 'desc' },
  { key: 'change', label: 'Change', textAlign: 'right', defaultSort: 'desc' },
  { key: 'pChange', label: 'Change %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'new52WHL', label: 'New 52W', textAlign: 'right', defaultSort: 'desc' },
  { key: 'prev52WHL', label: 'Prev 52W', textAlign: 'right', defaultSort: 'desc' },
  { key: 'prevHLDate', label: 'Prev HL Date', textAlign: 'right', defaultSort: 'asc' },
];

type VolumeColumnKey =
  | 'symbol'
  | 'companyName'
  | 'ltp'
  | 'pChange'
  | 'volume'
  | 'week1AvgVolume'
  | 'week1volChange'
  | 'week2AvgVolume'
  | 'week2volChange'
  | 'turnover';

type VolumeColumnConfig = {
  key: VolumeColumnKey;
  label: string;
  textAlign: 'left' | 'right';
  defaultSort: SortDirection;
};

const VOLUME_COLUMNS: VolumeColumnConfig[] = [
  { key: 'symbol', label: 'Symbol', textAlign: 'left', defaultSort: 'asc' },
  { key: 'companyName', label: 'Company', textAlign: 'left', defaultSort: 'asc' },
  { key: 'ltp', label: 'LTP (₹)', textAlign: 'right', defaultSort: 'desc' },
  { key: 'pChange', label: 'Change %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'volume', label: 'Volume', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week1AvgVolume', label: 'Wk1 Avg', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week1volChange', label: 'Wk1 Chg %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week2AvgVolume', label: 'Wk2 Avg', textAlign: 'right', defaultSort: 'desc' },
  { key: 'week2volChange', label: 'Wk2 Chg %', textAlign: 'right', defaultSort: 'desc' },
  { key: 'turnover', label: 'Turnover ₹Cr', textAlign: 'right', defaultSort: 'desc' },
];

function compareValues(a: unknown, b: unknown, direction: SortDirection): number {
  const aNull = a === null || a === undefined;
  const bNull = b === null || b === undefined;
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;

  if (typeof a === 'number' && typeof b === 'number') {
    const result = a - b;
    return direction === 'asc' ? result : -result;
  }

  if (typeof a === 'string' && typeof b === 'string') {
    const result = a.localeCompare(b);
    return direction === 'asc' ? result : -result;
  }

  return 0;
}

function getVolumeShockerMeta(row: BreakoutRow, volumeMap: Map<string, VolumeGainerItem>) {
  const volItem = volumeMap.get(row.symbol.toUpperCase());
  if (volItem && volItem.week1AvgVolume > 0) {
    const mult = volItem.volume / volItem.week1AvgVolume;
    return {
      multiplierText: mult >= 1 ? `⚡ ${mult.toFixed(1)}x Vol` : `${mult.toFixed(1)}x Vol`,
      subText: `₹${formatNumber(volItem.turnover, 0)} Cr T/O`,
    };
  }
  return {
    multiplierText: null as string | null,
    subText: row.prevHLDate ? `Prev: ${row.prevHLDate}` : null,
  };
}

function computeClearanceStatus(row: BreakoutRow, mode: 'high' | 'low') {
  const refPrice = row.prev52WHL;
  const curPrice = row.ltp ?? row.new52WHL;

  if (curPrice !== null && refPrice !== null && refPrice > 0) {
    const diffPct = ((curPrice - refPrice) / refPrice) * 100;
    if (mode === 'high') {
      const sign = diffPct >= 0 ? '+' : '';
      const tag =
        (row.pChange ?? 0) >= 4.8
          ? 'UPPER CIRCUIT'
          : diffPct >= 1.5
          ? 'FRESH ATH'
          : 'MULTI-YR HIGH';
      return {
        tag,
        refLabel: `Cleared 52WH: ₹${formatNumber(refPrice, 2)}`,
        clearanceText: `${sign}${diffPct.toFixed(2)}% Above Resistance`,
      };
    } else {
      const tag = (row.pChange ?? 0) <= -4.5 ? 'CRITICAL BREAKDOWN' : 'NEW 52W LOW';
      return {
        tag,
        refLabel: `Broke 52WL: ₹${formatNumber(refPrice, 2)}`,
        clearanceText: `${diffPct.toFixed(2)}% Below Support`,
      };
    }
  }

  return mode === 'high'
    ? {
        tag: 'FRESH ATH',
        refLabel: `New 52WH: ₹${formatNumber(row.new52WHL, 2)}`,
        clearanceText: 'Confirmed Resistance Breakout',
      }
    : {
        tag: 'NEW 52W LOW',
        refLabel: `New 52WL: ₹${formatNumber(row.new52WHL, 2)}`,
        clearanceText: 'Support Breakdown Alert',
      };
}

function BreakoutBentoCardItem({
  row,
  mode,
  volumeMap,
  onSelect,
}: {
  row: BreakoutRow;
  mode: 'high' | 'low';
  volumeMap: Map<string, VolumeGainerItem>;
  onSelect: (row: BreakoutRow) => void;
}) {
  const isHigh = mode === 'high';
  const clearance = computeClearanceStatus(row, mode);
  const volMeta = getVolumeShockerMeta(row, volumeMap);

  return (
    <div
      onClick={() => onSelect(row)}
      className={`bg-[#121216] border border-[#27272a] rounded p-2.5 transition-all cursor-pointer group flex flex-col @3xl:flex-row @3xl:items-center justify-between gap-2 ${
        isHigh ? 'hover:border-terminal-amber/60' : 'hover:border-rose-500/60'
      }`}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-0.5">
          <span
            className={`font-bold text-sm font-mono transition-colors ${
              isHigh
                ? 'text-white group-hover:text-terminal-amber'
                : 'text-white group-hover:text-rose-400'
            }`}
          >
            {row.symbol}
          </span>
          {row.name && (
            <span className="text-[10px] text-zinc-300 font-mono bg-zinc-800/90 px-1.5 py-0.5 rounded truncate max-w-[140px]">
              {row.name}
            </span>
          )}
          <span
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-bold border ${
              isHigh
                ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
                : 'text-rose-400 bg-rose-500/10 border-rose-500/30'
            }`}
          >
            {clearance.tag}
          </span>
        </div>

        <div className="text-[11px] font-mono text-zinc-300 flex flex-wrap items-center gap-2 tabular-nums">
          <span>{clearance.refLabel}</span>
          <span className="text-zinc-400">•</span>
          <span className={isHigh ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'}>
            {clearance.clearanceText}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between @3xl:justify-end gap-3 flex-shrink-0">
        {(volMeta.multiplierText || volMeta.subText) && (
          <div
            className={`px-2 py-1 rounded text-right ${
              volMeta.multiplierText
                ? 'bg-terminal-amber/10 border border-terminal-amber/40'
                : 'bg-zinc-900/60 border border-zinc-800'
            }`}
          >
            {volMeta.multiplierText && (
              <div className="text-[10px] font-mono uppercase text-terminal-amber font-bold flex items-center gap-1 justify-end tabular-nums">
                <span>{volMeta.multiplierText}</span>
              </div>
            )}
            {volMeta.subText && (
              <div className="text-[10px] font-mono text-zinc-300 tabular-nums">{volMeta.subText}</div>
            )}
          </div>
        )}

        <div className="text-right min-w-[82px]">
          <div className="text-sm font-bold font-mono text-white tabular-nums">
            &#8377;{formatNumber(row.ltp, 2)}
          </div>
          <div className="text-xs font-mono font-bold tabular-nums">
            <PercentCell value={row.pChange} />
          </div>
        </div>
      </div>
    </div>
  );
}

function BreakoutTable({ rows, onRowClick, volumeMap, mode }: BreakoutTableProps) {
  const [sortColumn, setSortColumn] = useState<SortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const handleHeaderClick = (column: SortColumn) => {
    const columnConfig = COLUMNS.find((c) => c.key === column);
    if (!columnConfig) return;

    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection(columnConfig.defaultSort);
    }
  };

  const sortedRows = useMemo(() => {
    if (!sortColumn) return rows;
    return [...rows].sort((a, b) => compareValues(a[sortColumn], b[sortColumn], sortDirection));
  }, [rows, sortColumn, sortDirection]);

  if (!rows.length) {
    return (
      <div className="text-zinc-300 text-xs py-4 px-2 font-mono">
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
      <table className="w-full border-collapse text-xs font-mono tabular-nums min-w-[740px]">
        <thead className="sticky top-0 bg-[#0c0c0f] z-10">
          <tr className="text-[10px] text-zinc-400 uppercase border-b border-[#27272a]">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className={`pb-2 font-bold pr-2 whitespace-nowrap cursor-pointer hover:text-white transition-colors ${
                  col.textAlign === 'left' ? 'text-left' : 'text-right'
                }`}
              >
                {col.label}
                {getSortIndicator(col.key)}
              </th>
            ))}
            <th className="pb-2 font-bold text-right pr-2">Vol Shocker</th>
            <th className="pb-2 font-bold text-right">Clearance Status</th>
          </tr>
        </thead>
        <tbody
          data-widget-tour="breakouts-rows"
          className="divide-y divide-[#27272a]/50"
        >
          {sortedRows.map((row) => {
            const volMeta = getVolumeShockerMeta(row, volumeMap);
            const clearance = computeClearanceStatus(row, mode);
            return (
              <tr
                key={row.symbol}
                onClick={() => onRowClick(row)}
                className="hover:bg-[#14141a] transition-colors cursor-pointer group"
              >
                <td className="py-2 pr-2 font-bold text-terminal-amber group-hover:text-white whitespace-nowrap">
                  {row.symbol}
                </td>
                <td className="py-2 pr-2 text-zinc-200 max-w-[160px] truncate" title={row.name}>
                  {row.name || <span className="text-zinc-400">—</span>}
                </td>
                <td className="py-2 pr-2 text-right font-bold text-white whitespace-nowrap">
                  &#8377;{formatNumber(row.ltp, 2)}
                </td>
                <td className="py-2 pr-2 text-right whitespace-nowrap">
                  <ChangeCell value={row.change} />
                </td>
                <td className="py-2 pr-2 text-right whitespace-nowrap">
                  <PercentCell value={row.pChange} />
                </td>
                <td className="py-2 pr-2 text-right text-zinc-100 whitespace-nowrap">
                  &#8377;{formatNumber(row.new52WHL, 2)}
                </td>
                <td className="py-2 pr-2 text-right text-zinc-300 whitespace-nowrap">
                  &#8377;{formatNumber(row.prev52WHL, 2)}
                </td>
                <td className="py-2 pr-2 text-right text-zinc-300 whitespace-nowrap">
                  {row.prevHLDate ?? <span className="text-zinc-400">—</span>}
                </td>
                <td className="py-2 pr-2 text-right whitespace-nowrap">
                  {volMeta.multiplierText ? (
                    <span className="text-[10px] font-bold text-terminal-amber bg-terminal-amber/10 border border-terminal-amber/30 px-1.5 py-0.5 rounded">
                      {volMeta.multiplierText}
                    </span>
                  ) : (
                    <span className="text-zinc-500 font-mono text-xs">—</span>
                  )}
                </td>
                <td className="py-2 text-right whitespace-nowrap">
                  <span
                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                      mode === 'high'
                        ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30'
                        : 'text-rose-400 bg-rose-500/10 border-rose-500/30'
                    }`}
                  >
                    {clearance.clearanceText}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
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

  const sortedRows = useMemo(() => {
    if (!sortColumn) return rows;
    return [...rows].sort((a, b) => compareValues(a[sortColumn], b[sortColumn], sortDirection));
  }, [rows, sortColumn, sortDirection]);

  if (!rows.length) {
    return (
      <div className="text-zinc-300 text-xs py-4 px-2 font-mono">
        No volume gainers found.
      </div>
    );
  }

  const getSortIndicator = (column: VolumeColumnKey) => {
    if (sortColumn !== column) return '';
    return sortDirection === 'asc' ? ' ▲' : ' ▼';
  };

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-xs font-mono tabular-nums min-w-[900px]">
        <thead className="sticky top-0 bg-[#0c0c0f] z-10">
          <tr className="text-[10px] text-zinc-400 uppercase border-b border-[#27272a]">
            {VOLUME_COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className={`pb-2 font-bold pr-2 whitespace-nowrap cursor-pointer hover:text-white transition-colors ${
                  col.textAlign === 'left' ? 'text-left' : 'text-right'
                }`}
              >
                {col.label}
                {getSortIndicator(col.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#27272a]/50">
          {sortedRows.map((row) => (
            <tr
              key={row.symbol}
              onClick={() => onRowClick(row)}
              className="hover:bg-[#14141a] transition-colors cursor-pointer"
            >
              <td className="py-2 pr-2 font-bold text-terminal-amber whitespace-nowrap">
                {row.symbol}
              </td>
              <td className="py-2 pr-2 text-zinc-200 max-w-[160px] truncate" title={row.companyName}>
                {row.companyName || <span className="text-zinc-400">—</span>}
              </td>
              <td className="py-2 pr-2 text-right font-bold text-white whitespace-nowrap">
                &#8377;{formatNumber(row.ltp, 2)}
              </td>
              <td className="py-2 pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.pChange} />
              </td>
              <td className="py-2 pr-2 text-right text-zinc-100 whitespace-nowrap">
                {formatVolume(row.volume)}
              </td>
              <td className="py-2 pr-2 text-right text-zinc-300 whitespace-nowrap">
                {formatVolume(row.week1AvgVolume)}
              </td>
              <td className="py-2 pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.week1volChange} />
              </td>
              <td className="py-2 pr-2 text-right text-zinc-300 whitespace-nowrap">
                {formatVolume(row.week2AvgVolume)}
              </td>
              <td className="py-2 pr-2 text-right whitespace-nowrap">
                <PercentCell value={row.week2volChange} />
              </td>
              <td className="py-2 pr-2 text-right text-terminal-amber font-bold whitespace-nowrap">
                &#8377;{formatNumber(row.turnover, 2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type RepeatedSortColumn = 'symbol' | 'breakout_type' | 'appearances' | 'window_days' | 'last_seen';

type RepeatedColumnConfig = {
  key: RepeatedSortColumn;
  label: string;
  textAlign: 'left' | 'right';
  defaultSort: SortDirection;
};

const REPEATED_COLUMNS: RepeatedColumnConfig[] = [
  { key: 'symbol', label: 'Symbol', textAlign: 'left', defaultSort: 'asc' },
  { key: 'breakout_type', label: 'Type', textAlign: 'left', defaultSort: 'asc' },
  { key: 'appearances', label: 'Appearances', textAlign: 'right', defaultSort: 'desc' },
  { key: 'window_days', label: 'Window', textAlign: 'right', defaultSort: 'desc' },
  { key: 'last_seen', label: 'Last Seen', textAlign: 'left', defaultSort: 'desc' },
];

interface RepeatedTableProps {
  rows: RepeatedItem[];
  onRowClick: (row: RepeatedItem) => void;
}

function RepeatedTable({ rows, onRowClick }: RepeatedTableProps) {
  const [sortColumn, setSortColumn] = useState<RepeatedSortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const handleHeaderClick = (column: RepeatedSortColumn) => {
    const columnConfig = REPEATED_COLUMNS.find((c) => c.key === column);
    if (!columnConfig) return;
    if (sortColumn === column) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(column);
      setSortDirection(columnConfig.defaultSort);
    }
  };

  const sortedRows = useMemo(() => {
    if (!sortColumn) return rows;
    return [...rows].sort((a, b) => compareValues(a[sortColumn], b[sortColumn], sortDirection));
  }, [rows, sortColumn, sortDirection]);

  if (!rows.length) {
    return (
      <div className="text-zinc-300 text-xs py-4 px-2 font-mono">
        No repeated breakout symbols found in the last 10 calendar days.
      </div>
    );
  }

  const getSortIndicator = (column: RepeatedSortColumn) => {
    if (sortColumn !== column) return '';
    return sortDirection === 'asc' ? ' ▲' : ' ▼';
  };

  const maxAppearances = Math.max(...rows.map((r) => r.appearances), 1);

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-xs font-mono tabular-nums min-w-[520px]">
        <thead className="sticky top-0 bg-[#0c0c0f] z-10">
          <tr className="text-[10px] text-zinc-400 uppercase border-b border-[#27272a]">
            {REPEATED_COLUMNS.map((col) => (
              <th
                key={col.key}
                onClick={() => handleHeaderClick(col.key)}
                className={`pb-2 font-bold pr-2 whitespace-nowrap cursor-pointer hover:text-white transition-colors ${
                  col.textAlign === 'left' ? 'text-left' : 'text-right'
                }`}
              >
                {col.label}
                {getSortIndicator(col.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#27272a]/50">
          {sortedRows.map((row) => {
            const barWidth = maxAppearances > 0 ? (row.appearances / maxAppearances) * 100 : 0;
            return (
              <tr
                key={`${row.symbol}-${row.breakout_type}`}
                onClick={() => onRowClick(row)}
                className="hover:bg-[#14141a] transition-colors cursor-pointer"
              >
                <td className="py-2 pr-2 font-bold text-terminal-amber whitespace-nowrap">
                  {row.symbol}
                </td>
                <td className="py-2 pr-2 whitespace-nowrap">
                  <span
                    className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold ${
                      REPEATED_TYPE_COLORS[row.breakout_type] ?? 'bg-zinc-800 text-zinc-200'
                    }`}
                  >
                    {REPEATED_TYPE_LABELS[row.breakout_type] ?? row.breakout_type}
                  </span>
                </td>
                <td className="py-2 pr-2 text-right whitespace-nowrap">
                  <div className="flex items-center justify-end gap-1.5">
                    <span className="text-white font-bold">{row.appearances}x</span>
                    <div className="w-14 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-terminal-amber rounded-full"
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                  </div>
                </td>
                <td className="py-2 pr-2 text-right text-zinc-300 whitespace-nowrap">
                  {row.window_days}d
                </td>
                <td className="py-2 pr-2 text-zinc-300 whitespace-nowrap">
                  {row.last_seen}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function BreakoutsWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [activeTab, setActiveTab] = useState<BreakoutTab>('matrix');
  const [search, setSearch] = useState('');

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

  const {
    data: repeatedData,
    isLoading: repeatedLoading,
    isError: repeatedError,
    error: repeatedErr,
  } = useQuery<RepeatedItem[]>({
    queryKey: ['breakouts/repeated'],
    queryFn: async () => {
      const res = await fetch('/api/py/breakouts/repeated?window_days=10&min_days=2');
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
      return res.json() as Promise<RepeatedItem[]>;
    },
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const volumeRows: VolumeGainerItem[] = useMemo(() => volumeData?.data ?? [], [volumeData]);
  const volumeMap = useMemo(() => {
    const map = new Map<string, VolumeGainerItem>();
    for (const item of volumeRows) {
      map.set(item.symbol.toUpperCase(), item);
    }
    return map;
  }, [volumeRows]);

  const highRows: BreakoutRow[] = useMemo(
    () => (highData?.data ?? []).map(normalizeRow),
    [highData]
  );
  const lowRows: BreakoutRow[] = useMemo(
    () => (lowData?.data ?? []).map(normalizeRow),
    [lowData]
  );

  const isLoading = highLoading || lowLoading;

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs bg-[#09090b] gap-1">
        <span className="text-terminal-amber font-bold uppercase tracking-wider animate-pulse">
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
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs bg-[#09090b] gap-1 px-4 text-center">
        {status === 503 ? (
          <>
            <span className="text-rose-400 font-bold uppercase">Service Unavailable</span>
            <span className="text-zinc-300 text-xs">
              NSE 52-week breakout data is currently unavailable. Please try again later.
            </span>
          </>
        ) : (
          <>
            <span className="text-rose-400 font-bold uppercase">Fetch Failed</span>
            <span className="text-zinc-300 text-xs max-w-xs">{errMsg}</span>
          </>
        )}
      </div>
    );
  }

  const q = search.trim().toLowerCase();
  const filteredHighRows = highRows.filter(
    (r) => !q || r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)
  );
  const filteredLowRows = lowRows.filter(
    (r) => !q || r.symbol.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)
  );
  const filteredVolumeRows = volumeRows.filter(
    (r) =>
      !q ||
      r.symbol.toLowerCase().includes(q) ||
      (r.companyName || '').toLowerCase().includes(q)
  );
  const filteredRepeatedRows = (repeatedData ?? []).filter(
    (r) => !q || r.symbol.toLowerCase().includes(q)
  );

  const timestamp =
    activeTab === 'low'
      ? lowData.timestamp
      : activeTab === 'volume'
      ? volumeData?.timestamp
      : highData.timestamp;

  const activateSymbol = (symbol: string) => {
    setActiveSymbol(symbol);
    setActiveExchange('NSE');
  };

  const handleRowClick = (row: BreakoutRow) => {
    activateSymbol(row.symbol);
  };

  const handleVolumeRowClick = (row: VolumeGainerItem) => {
    activateSymbol(row.symbol);
  };

  const tabs: { id: BreakoutTab; label: string; count: number }[] = [
    { id: 'matrix', label: 'ALL MATRIX', count: highRows.length + lowRows.length },
    { id: 'high', label: '52W HIGH', count: highRows.length },
    { id: 'low', label: '52W LOW', count: lowRows.length },
    { id: 'volume', label: 'VOLUME SHOCKERS', count: volumeRows.length },
    { id: 'repeated', label: 'REPEATED', count: (repeatedData ?? []).length },
  ];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-[#09090b] text-zinc-100">
      {/* Bento Header Toolbar */}
      <div className="flex-shrink-0 px-3 py-2.5 border-b border-[#27272a] bg-[#0c0c0f] flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-terminal-amber font-bold text-xs uppercase tracking-wider flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-terminal-amber" />
            Breakout &amp; Velocity Radar
          </span>

          <div
            data-widget-tour="breakouts-tabs"
            className="flex flex-wrap items-center gap-1 bg-[#121216] p-1 rounded border border-[#27272a]"
          >
            {tabs.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={isActive}
                  data-widget-tour-click={`tab-${tab.id}`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-2.5 py-1 rounded text-[10px] font-mono font-bold uppercase tracking-wider transition-all cursor-pointer inline-flex items-center gap-1.5 ${
                    isActive
                      ? 'bg-terminal-amber text-black border border-terminal-amber shadow-[0_0_8px_rgba(245,158,11,0.3)]'
                      : 'text-zinc-300 hover:text-white hover:bg-zinc-800/70 border border-transparent'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span
                    className={`inline-flex items-center justify-center min-w-[18px] h-[15px] rounded text-[10px] px-1 tabular-nums ${
                      isActive ? 'bg-black/25 text-black font-extrabold' : 'bg-zinc-800 text-zinc-300'
                    }`}
                  >
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search symbols..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-44 bg-[#121216] border border-[#27272a] focus:border-terminal-amber rounded px-2.5 py-1 text-xs text-white placeholder:text-zinc-400 outline-none transition-colors"
          />
          {timestamp && (
            <span className="text-zinc-400 text-[10px] hidden @3xl:inline tabular-nums">
              {timestamp}
            </span>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-auto p-3 min-h-0">
        {activeTab === 'matrix' ? (
          <div
            data-widget-tour="breakouts-matrix"
            className="grid grid-cols-1 @md:grid-cols-2 @4xl:grid-cols-4 gap-3"
          >
            {/* =============================================================== */}
            {/* 1. 52-WEEK HIGH BREAKOUT RADAR (col-span-2)                     */}
            {/* =============================================================== */}
            <div className="col-span-1 @md:col-span-1 @4xl:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a]/70">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-400" />
                      52-Week High Breakout Radar
                    </span>
                    <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                      ALL-TIME HIGHS
                    </span>
                  </div>
                  <span className="text-[10px] text-terminal-amber font-mono font-bold bg-terminal-amber/10 px-2 py-0.5 rounded border border-terminal-amber/30 tabular-nums">
                    ⚡ {filteredHighRows.length} STOCKS AT 52WH
                  </span>
                </div>

                <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                  {filteredHighRows.length === 0 ? (
                    <div className="text-zinc-400 text-xs py-6 text-center">
                      No 52-week high breakouts match filter.
                    </div>
                  ) : (
                    filteredHighRows.slice(0, 8).map((row) => (
                      <BreakoutBentoCardItem
                        key={`high-${row.symbol}`}
                        row={row}
                        mode="high"
                        volumeMap={volumeMap}
                        onSelect={handleRowClick}
                      />
                    ))
                  )}
                </div>
              </div>

              <div className="mt-2.5 pt-2 border-t border-[#27272a]/70 flex items-center justify-between text-[11px] font-mono text-zinc-400">
                <span>
                  Click any symbol to sync chart &amp; terminal
                </span>
                <button
                  onClick={() => setActiveTab('high')}
                  className="text-terminal-amber hover:underline font-bold cursor-pointer"
                >
                  View All {filteredHighRows.length} →
                </button>
              </div>
            </div>

            {/* =============================================================== */}
            {/* 2. 52-WEEK LOW BREAKDOWN RADAR (col-span-2)                     */}
            {/* =============================================================== */}
            <div className="col-span-1 @md:col-span-1 @4xl:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a]/70">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-rose-400" />
                      52-Week Low Breakdown Radar
                    </span>
                    <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                      SUPPORT BREAKS
                    </span>
                  </div>
                  <span className="text-[10px] text-rose-400 font-mono font-bold bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/30 tabular-nums">
                    ▼ {filteredLowRows.length} STOCKS AT 52WL
                  </span>
                </div>

                <div className="space-y-2 max-h-[420px] overflow-y-auto pr-1">
                  {filteredLowRows.length === 0 ? (
                    <div className="text-zinc-400 text-xs py-6 text-center">
                      No 52-week low breakdowns match filter.
                    </div>
                  ) : (
                    filteredLowRows.slice(0, 8).map((row) => (
                      <BreakoutBentoCardItem
                        key={`low-${row.symbol}`}
                        row={row}
                        mode="low"
                        volumeMap={volumeMap}
                        onSelect={handleRowClick}
                      />
                    ))
                  )}
                </div>
              </div>

              <div className="mt-2.5 pt-2 border-t border-[#27272a]/70 flex items-center justify-between text-[11px] font-mono text-zinc-400">
                <span>
                  1-Click Symbol Sync Active
                </span>
                <button
                  onClick={() => setActiveTab('low')}
                  className="text-rose-400 hover:underline font-bold cursor-pointer"
                >
                  View All {filteredLowRows.length} →
                </button>
              </div>
            </div>

            {/* =============================================================== */}
            {/* 3. VOLUME SHOCKERS & DELIVERY SPIKES (col-span-2)               */}
            {/* =============================================================== */}
            <div
              data-widget-tour="breakouts-volume"
              className="col-span-1 @md:col-span-1 @4xl:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a]/70">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                      Volume Shockers &amp; Surge Radar
                    </span>
                    <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                      VOLUME EXPANSION
                    </span>
                  </div>
                  <span className="text-[10px] text-emerald-400 font-mono font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/30">
                    INSTITUTIONAL FOOTPRINT
                  </span>
                </div>

                <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
                  {volumeLoading ? (
                    <div className="text-terminal-amber text-xs py-4 text-center animate-pulse">
                      Loading volume shockers...
                    </div>
                  ) : filteredVolumeRows.length === 0 ? (
                    <div className="text-zinc-400 text-xs py-4 text-center">
                      No volume shockers available.
                    </div>
                  ) : (
                    filteredVolumeRows.slice(0, 5).map((item) => {
                      const mult =
                        item.week1AvgVolume > 0
                          ? (item.volume / item.week1AvgVolume).toFixed(1)
                          : null;
                      const barPct = mult ? Math.min(100, Math.max(10, Number(mult) * 16)) : 0;
                      return (
                        <div
                          key={item.symbol}
                          onClick={() => handleVolumeRowClick(item)}
                          className="bg-[#121216] border border-[#27272a] hover:border-terminal-amber/60 rounded p-2.5 cursor-pointer transition-colors"
                        >
                          <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-white text-sm">{item.symbol}</span>
                              {mult ? (
                                <span className="text-[10px] text-terminal-amber font-mono bg-terminal-amber/10 border border-terminal-amber/30 px-1.5 py-0.5 rounded font-bold tabular-nums">
                                  ⚡ {mult}x Vol
                                </span>
                              ) : (
                                <span className="text-[10px] text-zinc-400 font-mono bg-zinc-800/60 border border-zinc-700/40 px-1.5 py-0.5 rounded font-bold tabular-nums">
                                  —
                                </span>
                              )}
                            </div>
                            <div className="text-right tabular-nums">
                              <span className="text-xs font-bold text-white mr-2">
                                &#8377;{formatNumber(item.ltp, 2)}
                              </span>
                              <PercentCell value={item.pChange} />
                            </div>
                          </div>
                          <div className="w-full h-2 bg-[#09090b] rounded-full overflow-hidden flex border border-[#27272a] my-1.5">
                            <div
                              className="h-full bg-emerald-400 rounded-full"
                              style={{ width: `${barPct}%` }}
                            />
                          </div>
                          <div className="flex justify-between text-[11px] font-mono text-zinc-300 tabular-nums">
                            <span>
                              Vol: <b className="text-white">{formatVolume(item.volume)}</b> (1W Avg:{' '}
                              {item.week1AvgVolume > 0 ? formatVolume(item.week1AvgVolume) : '—'})
                            </span>
                            <span>
                              Turnover:{' '}
                              <b className="text-terminal-amber">
                                &#8377;{formatNumber(item.turnover, 0)} Cr
                              </b>
                            </span>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="mt-2.5 pt-2 border-t border-[#27272a]/70 flex items-center justify-between text-[11px] font-mono text-zinc-400">
                <span>1W / 2W Relative Volume Comparison</span>
                <button
                  onClick={() => setActiveTab('volume')}
                  className="text-terminal-amber hover:underline font-bold cursor-pointer"
                >
                  Full Volume Table →
                </button>
              </div>
            </div>

            {/* =============================================================== */}
            {/* 4. REPEATED BREAKOUT PERSISTENCE (col-span-2)                   */}
            {/* =============================================================== */}
            <div className="col-span-1 @md:col-span-1 @4xl:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-md p-3.5 transition-colors shadow-md flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a]/70">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                      Repeated Breakout Persistence
                    </span>
                    <span className="text-[10px] text-zinc-300 font-mono bg-[#14141a] px-1.5 py-0.5 rounded border border-[#27272a]">
                      10-DAY WINDOW
                    </span>
                  </div>
                  <span className="text-[10px] text-terminal-amber font-mono font-bold bg-terminal-amber/10 px-2 py-0.5 rounded border border-terminal-amber/30 tabular-nums">
                    {filteredRepeatedRows.length} PERSISTENT
                  </span>
                </div>

                <div className="max-h-[320px] overflow-y-auto pr-1">
                  {repeatedLoading ? (
                    <div className="text-terminal-amber text-xs py-4 text-center animate-pulse">
                      Loading repeated breakouts...
                    </div>
                  ) : (
                    <RepeatedTable
                      rows={filteredRepeatedRows.slice(0, 8)}
                      onRowClick={(row) => activateSymbol(row.symbol)}
                    />
                  )}
                </div>
              </div>

              <div className="mt-2.5 pt-2 border-t border-[#27272a]/70 flex items-center justify-between text-[11px] font-mono text-zinc-400">
                <span>Multi-session breakout conviction tracker</span>
                <button
                  onClick={() => setActiveTab('repeated')}
                  className="text-terminal-amber hover:underline font-bold cursor-pointer"
                >
                  Full Repeated Table →
                </button>
              </div>
            </div>
          </div>
        ) : activeTab === 'repeated' ? (
          <div className="bg-[#0c0c0f] border border-[#27272a] rounded-md p-3.5 shadow-md">
            {repeatedLoading ? (
              <div className="py-12 flex flex-col items-center justify-center font-mono text-xs">
                <span className="text-terminal-amber animate-pulse">
                  LOADING REPEATED BREAKOUTS...
                </span>
              </div>
            ) : repeatedError || !repeatedData ? (
              <div className="py-12 flex flex-col items-center justify-center font-mono text-xs gap-1 px-4 text-center">
                <span className="text-rose-400 font-bold uppercase">Fetch Failed</span>
                <span className="text-zinc-300 text-xs max-w-xs">
                  {repeatedErr instanceof Error ? repeatedErr.message : 'Unknown error'}
                </span>
              </div>
            ) : (
              <RepeatedTable
                rows={filteredRepeatedRows}
                onRowClick={(row) => activateSymbol(row.symbol)}
              />
            )}
          </div>
        ) : activeTab === 'volume' ? (
          <div className="bg-[#0c0c0f] border border-[#27272a] rounded-md p-3.5 shadow-md">
            {volumeLoading ? (
              <div className="py-12 flex flex-col items-center justify-center font-mono text-xs">
                <span className="text-terminal-amber animate-pulse">
                  LOADING VOLUME...
                </span>
              </div>
            ) : volumeError || !volumeData ? (
              <div className="py-12 flex flex-col items-center justify-center font-mono text-xs gap-1 px-4 text-center">
                {(volumeErr as (Error & { status?: number }) | undefined)?.status === 503 ? (
                  <>
                    <span className="text-rose-400 font-bold uppercase">Service Unavailable</span>
                    <span className="text-zinc-300 text-xs">
                      Volume data is currently unavailable. Please try again later.
                    </span>
                  </>
                ) : (
                  <>
                    <span className="text-rose-400 font-bold uppercase">Fetch Failed</span>
                    <span className="text-zinc-300 text-xs max-w-xs">
                      {volumeErr instanceof Error ? volumeErr.message : 'Unknown error'}
                    </span>
                  </>
                )}
              </div>
            ) : (
              <VolumeTable rows={filteredVolumeRows} onRowClick={handleVolumeRowClick} />
            )}
          </div>
        ) : (
          <div className="bg-[#0c0c0f] border border-[#27272a] rounded-md p-3.5 shadow-md">
            <BreakoutTable
              rows={activeTab === 'high' ? filteredHighRows : filteredLowRows}
              onRowClick={handleRowClick}
              volumeMap={volumeMap}
              mode={activeTab === 'high' ? 'high' : 'low'}
            />
          </div>
        )}
      </div>
    </div>
  );
}

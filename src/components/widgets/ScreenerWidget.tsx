'use client';

import React, { useState, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom } from '@/store/terminalStore';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ScreenerResult {
  symbol: string;
  close: number;
  change_today: number;
  returns?: Record<string, number | null>;
  volume_ratio?: number;
  indicators?: Record<string, unknown>;
  indicators_by_interval?: Record<string, Record<string, unknown>>;
  sector?: string | null;
  industry?: string | null;
  pe?: number | null;
  data_points?: number;
  momentum_score?: number | null;
}

interface ScreenerResponse {
  count: number;
  returned: number;
  filters_applied: string[];
  results: ScreenerResult[];
}

type IntervalTab = '1d' | '1h' | 'W' | 'M';
type SortDirection = 'asc' | 'desc';

interface FilterState {
  rsiMin: string;
  rsiMax: string;
  atrPctMin: string;
  atrPctMax: string;
  bbSqueeze: boolean;
  changeTodayMin: string;
  changeTodayMax: string;
  volumeRatioMin: string;
  volumeRatioMax: string;
  sector: string;
  peMin: string;
  peMax: string;
  momentumScoreMin: string;
  limit: string;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const INTERVAL_TABS: { key: IntervalTab; label: string }[] = [
  { key: '1d', label: 'Daily' },
  { key: '1h', label: '1h' },
  { key: 'W', label: 'Weekly' },
  { key: 'M', label: 'Monthly' },
];

const DEFAULT_FILTERS: FilterState = {
  rsiMin: '',
  rsiMax: '',
  atrPctMin: '',
  atrPctMax: '',
  bbSqueeze: false,
  changeTodayMin: '',
  changeTodayMax: '',
  volumeRatioMin: '',
  volumeRatioMax: '',
  sector: '',
  peMin: '',
  peMax: '',
  momentumScoreMin: '',
  limit: '50',
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function parseFloatOrNull(v: string): number | null {
  const n = Number(v.trim());
  return v.trim() === '' || Number.isNaN(n) ? null : n;
}

function getIndicatorValue(
  row: ScreenerResult,
  interval: IntervalTab,
  key: string
): number | null {
  const byInterval = row.indicators_by_interval;
  if (!byInterval) return null;
  const iv = byInterval[interval];
  if (!iv) return null;
  const val = iv[key];
  if (val === null || val === undefined || Number.isNaN(val)) return null;
  return typeof val === 'number' ? val : null;
}

function getIndicatorBool(
  row: ScreenerResult,
  interval: IntervalTab,
  key: string
): boolean {
  const byInterval = row.indicators_by_interval;
  if (!byInterval) return false;
  const iv = byInterval[interval];
  if (!iv) return false;
  return Boolean(iv[key]);
}

// ─── Sort helpers ────────────────────────────────────────────────────────────

type SortColumn =
  | 'symbol'
  | 'close'
  | 'change_today'
  | 'rsi'
  | 'atr_percent'
  | 'sector'
  | 'momentum_score';

function compareValues(a: unknown, b: unknown, direction: SortDirection): number {
  const aNull = a === null || a === undefined || (typeof a === 'number' && Number.isNaN(a));
  const bNull = b === null || b === undefined || (typeof b === 'number' && Number.isNaN(b));
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

// ─── Filter input component ──────────────────────────────────────────────────

interface FilterInputProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: 'text' | 'number';
}

function FilterInput({ label, value, onChange, placeholder, type = 'text' }: FilterInputProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] text-white/50 font-mono uppercase">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-black/30 border border-white/10 rounded px-1.5 py-1 text-[11px] text-white font-mono focus:border-blue-500 outline-none w-full"
      />
    </div>
  );
}

// ─── Main Widget ─────────────────────────────────────────────────────────────

export function ScreenerWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

  const [activeInterval, setActiveInterval] = useState<IntervalTab>('1d');
  const [filters, setFilters] = useState<FilterState>({ ...DEFAULT_FILTERS });
  const [showFilters, setShowFilters] = useState(true);

  const [sortColumn, setSortColumn] = useState<SortColumn>('symbol');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  // Build query params
  const buildParams = useCallback((): string => {
    const params = new URLSearchParams();

    const intervalPrefix = activeInterval === '1d' ? '' : `_${activeInterval}`;

    // Interval-specific indicator filters → filters_json
    const jsonFilters: Record<string, number | boolean | string> = {};

    const rsiMin = parseFloatOrNull(filters.rsiMin);
    const rsiMax = parseFloatOrNull(filters.rsiMax);
    const atrMin = parseFloatOrNull(filters.atrPctMin);
    const atrMax = parseFloatOrNull(filters.atrPctMax);

    if (rsiMin !== null) {
      jsonFilters[activeInterval === '1d' ? 'rsi_min' : `rsi${intervalPrefix}_min`] = rsiMin;
    }
    if (rsiMax !== null) {
      jsonFilters[activeInterval === '1d' ? 'rsi_max' : `rsi${intervalPrefix}_max`] = rsiMax;
    }
    if (atrMin !== null) {
      jsonFilters[activeInterval === '1d' ? 'atr_pct_min' : `atr_pct${intervalPrefix}_min`] = atrMin;
    }
    if (atrMax !== null) {
      jsonFilters[activeInterval === '1d' ? 'atr_pct_max' : `atr_pct${intervalPrefix}_max`] = atrMax;
    }
    if (filters.bbSqueeze) {
      jsonFilters[activeInterval === '1d' ? 'bb_squeeze' : `bb_squeeze${intervalPrefix}`] = true;
    }

    // Shared filters (also go into filters_json for simplicity)
    const changeMin = parseFloatOrNull(filters.changeTodayMin);
    const changeMax = parseFloatOrNull(filters.changeTodayMax);
    const volMin = parseFloatOrNull(filters.volumeRatioMin);
    const volMax = parseFloatOrNull(filters.volumeRatioMax);
    const peMin = parseFloatOrNull(filters.peMin);
    const peMax = parseFloatOrNull(filters.peMax);
    const momentumMin = parseFloatOrNull(filters.momentumScoreMin);

    if (changeMin !== null) jsonFilters['pct_change_today_min'] = changeMin;
    if (changeMax !== null) jsonFilters['pct_change_today_max'] = changeMax;
    if (volMin !== null) jsonFilters['volume_ratio_min'] = volMin;
    if (volMax !== null) jsonFilters['volume_ratio_max'] = volMax;
    if (peMin !== null) jsonFilters['pe_min'] = peMin;
    if (peMax !== null) jsonFilters['pe_max'] = peMax;
    if (momentumMin !== null) jsonFilters['momentum_score_min'] = momentumMin;
    if (filters.sector.trim()) jsonFilters['sector'] = filters.sector.trim();

    if (Object.keys(jsonFilters).length > 0) {
      params.set('filters_json', JSON.stringify(jsonFilters));
    }

    params.set('sort_by', sortColumn);
    params.set('order', sortDirection);
    params.set('limit', filters.limit || '50');

    return params.toString();
  }, [activeInterval, filters, sortColumn, sortDirection]);

  const { data, isLoading, isError, error, refetch } = useQuery<ScreenerResponse>({
    queryKey: ['screener', activeInterval, filters, sortColumn, sortDirection],
    queryFn: async () => {
      const qs = buildParams();
      const res = await fetch(`/api/py/ticker/screener?${qs}`);
      if (!res.ok) {
        const text = await res.text().catch(() => 'Unknown error');
        throw new Error(`HTTP ${res.status}: ${text}`);
      }
      return (await res.json()) as ScreenerResponse;
    },
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  const results = data?.results ?? [];

  const handleHeaderClick = useCallback(
    (column: SortColumn) => {
      if (sortColumn === column) {
        setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortColumn(column);
        setSortDirection('asc');
      }
    },
    [sortColumn]
  );

  const handleRowClick = useCallback(
    (symbol: string) => {
      setActiveSymbol(symbol);
      setActiveExchange('NSE');
    },
    [setActiveSymbol, setActiveExchange]
  );

  const handleFilterChange = useCallback(
    <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
      setFilters((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const resetFilters = useCallback(() => {
    setFilters({ ...DEFAULT_FILTERS });
  }, []);

  const getSortIndicator = (column: SortColumn) => {
    if (sortColumn !== column) return '';
    return sortDirection === 'asc' ? ' ▲' : ' ▼';
  };

  const columns: { key: SortColumn; label: string; align: 'left' | 'right' }[] = [
    { key: 'symbol', label: 'Symbol', align: 'left' },
    { key: 'close', label: 'LTP', align: 'right' },
    { key: 'change_today', label: 'Change %', align: 'right' },
    { key: 'rsi', label: 'RSI', align: 'right' },
    { key: 'atr_percent', label: 'ATR %', align: 'right' },
    { key: 'sector', label: 'Sector', align: 'left' },
    { key: 'momentum_score', label: 'Mom.', align: 'right' },
  ];

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="h-full w-full flex flex-col text-xs font-mono">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1.5 border-b border-white/10 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-terminal-amber font-bold text-[10px] uppercase tracking-wider">
            Screener
          </span>
          {isLoading && (
            <span className="text-white/30 text-[10px] animate-pulse">loading…</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setShowFilters((p) => !p)}
            className="text-[10px] px-2 py-0.5 rounded border border-white/10 hover:bg-white/5 transition-colors"
          >
            {showFilters ? 'Hide Filters' : 'Show Filters'}
          </button>
          <button
            onClick={() => refetch()}
            className="text-[10px] px-2 py-0.5 rounded border border-white/10 hover:bg-white/5 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Interval Tabs */}
      <div className="flex border-b border-white/10 shrink-0">
        {INTERVAL_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveInterval(tab.key)}
            className={`flex-1 py-1 text-[10px] uppercase tracking-wider transition-colors ${
              activeInterval === tab.key
                ? 'bg-white/10 text-white border-b-2 border-terminal-amber'
                : 'text-white/40 hover:text-white/70'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Filter Panel */}
      {showFilters && (
        <div className="shrink-0 border-b border-white/10 px-2 py-2 grid grid-cols-4 gap-2">
          <FilterInput
            label={`RSI min`}
            value={filters.rsiMin}
            onChange={(v) => handleFilterChange('rsiMin', v)}
            placeholder="0"
            type="number"
          />
          <FilterInput
            label={`RSI max`}
            value={filters.rsiMax}
            onChange={(v) => handleFilterChange('rsiMax', v)}
            placeholder="100"
            type="number"
          />
          <FilterInput
            label={`ATR% min`}
            value={filters.atrPctMin}
            onChange={(v) => handleFilterChange('atrPctMin', v)}
            placeholder="0"
            type="number"
          />
          <FilterInput
            label={`ATR% max`}
            value={filters.atrPctMax}
            onChange={(v) => handleFilterChange('atrPctMax', v)}
            placeholder="10"
            type="number"
          />
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px] text-white/50 font-mono uppercase">BB Squeeze</label>
            <button
              onClick={() => handleFilterChange('bbSqueeze', !filters.bbSqueeze)}
              className={`text-[10px] px-2 py-1 rounded border transition-colors text-left ${
                filters.bbSqueeze
                  ? 'bg-terminal-amber text-black border-terminal-amber'
                  : 'bg-black/30 border-white/10 text-white/50'
              }`}
            >
              {filters.bbSqueeze ? 'ON' : 'OFF'}
            </button>
          </div>
          <FilterInput
            label="Change% min"
            value={filters.changeTodayMin}
            onChange={(v) => handleFilterChange('changeTodayMin', v)}
            placeholder="-5"
            type="number"
          />
          <FilterInput
            label="Change% max"
            value={filters.changeTodayMax}
            onChange={(v) => handleFilterChange('changeTodayMax', v)}
            placeholder="5"
            type="number"
          />
          <FilterInput
            label="Vol ratio min"
            value={filters.volumeRatioMin}
            onChange={(v) => handleFilterChange('volumeRatioMin', v)}
            placeholder="1"
            type="number"
          />
          <FilterInput
            label="Vol ratio max"
            value={filters.volumeRatioMax}
            onChange={(v) => handleFilterChange('volumeRatioMax', v)}
            placeholder="5"
            type="number"
          />
          <FilterInput
            label="Sector"
            value={filters.sector}
            onChange={(v) => handleFilterChange('sector', v)}
            placeholder="e.g. Banks"
          />
          <FilterInput
            label="PE min"
            value={filters.peMin}
            onChange={(v) => handleFilterChange('peMin', v)}
            placeholder="0"
            type="number"
          />
          <FilterInput
            label="PE max"
            value={filters.peMax}
            onChange={(v) => handleFilterChange('peMax', v)}
            placeholder="50"
            type="number"
          />
          <FilterInput
            label="Mom score min"
            value={filters.momentumScoreMin}
            onChange={(v) => handleFilterChange('momentumScoreMin', v)}
            placeholder="0"
            type="number"
          />
          <div className="flex flex-col gap-0.5">
            <label className="text-[10px] text-white/50 font-mono uppercase">Limit</label>
            <div className="flex gap-1">
              <input
                type="number"
                value={filters.limit}
                onChange={(e) => handleFilterChange('limit', e.target.value)}
                className="bg-black/30 border border-white/10 rounded px-1.5 py-1 text-[11px] text-white font-mono focus:border-blue-500 outline-none w-full"
              />
              <button
                onClick={resetFilters}
                className="text-[10px] px-2 py-1 rounded border border-white/10 hover:bg-white/5 transition-colors shrink-0"
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div className="shrink-0 px-2 py-1 text-terminal-red text-[10px]">
          Error: {error instanceof Error ? error.message : 'Unknown error'}
        </div>
      )}

      {/* Stats bar */}
      <div className="shrink-0 px-2 py-0.5 text-[10px] text-white/30 border-b border-white/10 flex justify-between">
        <span>
          {data ? `${data.returned} / ${data.count} results` : '—'}
        </span>
        <span className="text-white/20">
          {data?.filters_applied?.length
            ? `filters: ${data.filters_applied.join(', ')}`
            : 'no filters'}
        </span>
      </div>

      {/* Results table */}
      <div className="flex-1 overflow-auto">
        {results.length === 0 ? (
          <div className="h-full flex items-center justify-center text-white/30 text-[10px]">
            {isLoading ? 'Loading…' : 'No results match your filters.'}
          </div>
        ) : (
          <table className="w-full text-[10px]">
            <thead className="sticky top-0 bg-terminal-bg z-10">
              <tr className="border-b border-white/10">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    onClick={() => handleHeaderClick(col.key)}
                    className={`py-1 px-1 cursor-pointer select-none hover:text-white transition-colors ${
                      col.align === 'left' ? 'text-left' : 'text-right'
                    } text-white/50`}
                  >
                    {col.label}
                    <span className="text-terminal-amber">{getSortIndicator(col.key)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((row) => {
                const rsi = getIndicatorValue(row, activeInterval, 'rsi_14');
                const atr = getIndicatorValue(row, activeInterval, 'atr_percent');
                const bbSq = getIndicatorBool(row, activeInterval, 'bb_squeeze');
                const change = row.change_today ?? null;

                return (
                  <tr
                    key={row.symbol}
                    onClick={() => handleRowClick(row.symbol)}
                    className="border-b border-white/5 hover:bg-white/5 cursor-pointer transition-colors"
                  >
                    <td className="py-1 px-1 text-left font-bold text-white">
                      {row.symbol}
                    </td>
                    <td className="py-1 px-1 text-right text-white/70">
                      {formatNumber(row.close)}
                    </td>
                    <td className="py-1 px-1 text-right">
                      {change !== null && !Number.isNaN(change) ? (
                        <span
                          className={
                            change >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                          }
                        >
                          {change >= 0 ? '+' : ''}
                          {formatNumber(change, 2)}%
                        </span>
                      ) : (
                        <span className="text-white/30">—</span>
                      )}
                    </td>
                    <td className="py-1 px-1 text-right text-white/70">
                      {formatNumber(rsi)}
                    </td>
                    <td className="py-1 px-1 text-right text-white/70">
                      {formatNumber(atr)}
                    </td>
                    <td className="py-1 px-1 text-left text-white/50">
                      {row.sector ?? '—'}
                    </td>
                    <td className="py-1 px-1 text-right">
                      {bbSq ? (
                        <span className="bg-yellow-600 text-black px-1 rounded text-[9px] font-bold">
                          SQ
                        </span>
                      ) : (
                        <span className="text-white/20">—</span>
                      )}
                    </td>
                    <td className="py-1 px-1 text-right text-white/70">
                      {formatNumber(row.momentum_score)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

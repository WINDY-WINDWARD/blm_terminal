'use client';

import React, {
  useState,
  useCallback,
  useRef,
  useEffect,
  KeyboardEvent,
} from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeSymbolAtom, activeExchangeAtom } from '@/store/terminalStore';
import {
  getSuggestions,
  applySuggestion,
  validateTql,
  getFieldInfo,
  type TqlSuggestion,
} from '@/lib/screenerTql';

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
type SortColumn =
  | 'symbol'
  | 'close'
  | 'change_today'
  | 'rsi'
  | 'atr_percent'
  | 'sector'
  | 'momentum_score';

// ─── Constants ───────────────────────────────────────────────────────────────

const INTERVAL_TABS: { key: IntervalTab; label: string }[] = [
  { key: '1d', label: 'Daily' },
  { key: '1h', label: '1h' },
  { key: 'W', label: 'Weekly' },
  { key: 'M', label: 'Monthly' },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
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

function compareValues(a: unknown, b: unknown, direction: SortDirection): number {
  const aNull = a === null || a === undefined || (typeof a === 'number' && Number.isNaN(a));
  const bNull = b === null || b === undefined || (typeof b === 'number' && Number.isNaN(b));
  if (aNull && bNull) return 0;
  if (aNull) return 1;
  if (bNull) return -1;
  if (typeof a === 'number' && typeof b === 'number') {
    return direction === 'asc' ? a - b : b - a;
  }
  if (typeof a === 'string' && typeof b === 'string') {
    return direction === 'asc' ? a.localeCompare(b) : b.localeCompare(a);
  }
  return 0;
}

// ─── TQL Input with autocomplete ─────────────────────────────────────────────

interface TqlInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  sectors: string[];
  isLoading: boolean;
  error?: string | null;
}

function TqlInput({ value, onChange, onSubmit, sectors, isLoading, error }: TqlInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [suggestions, setSuggestions] = useState<TqlSuggestion[]>([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [fieldHint, setFieldHint] = useState<string | null>(null);
  const validationError = validateTql(value);

  const updateSuggestions = useCallback(
    (text: string, cursor: number) => {
      const s = getSuggestions(text, cursor, sectors);
      setSuggestions(s);
      setSelectedIdx(0);
      setDropdownOpen(s.length > 0);
      // Update field hint bar
      const info = getFieldInfo(text, cursor);
      setFieldHint(info ? `${info.name}: ${info.hint}` : null);
    },
    [sectors]
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    onChange(v);
    updateSuggestions(v, e.target.selectionStart ?? v.length);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (dropdownOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1));
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIdx((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === 'Tab' || e.key === 'Enter') {
        if (e.key === 'Tab' || dropdownOpen) {
          e.preventDefault();
          const s = suggestions[selectedIdx];
          if (s) {
            const cursor = inputRef.current?.selectionStart ?? value.length;
            const { text, cursor: newCursor } = applySuggestion(value, cursor, s);
            onChange(text);
            setDropdownOpen(false);
            // restore cursor after React re-render
            requestAnimationFrame(() => {
              if (inputRef.current) {
                inputRef.current.setSelectionRange(newCursor, newCursor);
                updateSuggestions(text, newCursor);
              }
            });
            return;
          }
        }
        if (e.key === 'Enter') {
          setDropdownOpen(false);
          if (!validationError) onSubmit();
          return;
        }
      }
      if (e.key === 'Escape') {
        setDropdownOpen(false);
        return;
      }
    } else {
      if (e.key === 'Enter' && !validationError) {
        onSubmit();
      }
    }
  };

  const handleFocus = () => {
    const cursor = inputRef.current?.selectionStart ?? value.length;
    updateSuggestions(value, cursor);
  };

  const handleBlur = () => {
    // slight delay so click on suggestion registers
    setTimeout(() => setDropdownOpen(false), 150);
  };

  const applySuggestionClick = (s: TqlSuggestion) => {
    const cursor = inputRef.current?.selectionStart ?? value.length;
    const { text, cursor: newCursor } = applySuggestion(value, cursor, s);
    onChange(text);
    setDropdownOpen(false);
    requestAnimationFrame(() => {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.setSelectionRange(newCursor, newCursor);
        updateSuggestions(text, newCursor);
      }
    });
  };

  const kindColor: Record<TqlSuggestion['kind'], string> = {
    field:    'text-blue-400',
    operator: 'text-terminal-amber',
    value:    'text-terminal-green',
    keyword:  'text-white/60',
  };

  return (
    <div className="relative w-full">
      <div className="flex items-center gap-1.5">
        <div className="relative flex-1">
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onFocus={handleFocus}
            onBlur={handleBlur}
            spellCheck={false}
            autoComplete="off"
            placeholder='RSI > 60 AND Sector = "Banks"'
            className={`w-full bg-black/40 border rounded px-2 py-1.5 text-[11px] text-white font-mono outline-none transition-colors ${
              error || validationError
                ? 'border-terminal-red/60 focus:border-terminal-red'
                : 'border-white/15 focus:border-blue-500/70'
            }`}
          />
          {(error || validationError) && (
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[9px] text-terminal-red/80">
              {error ?? validationError}
            </span>
          )}
        </div>
        <button
          onClick={() => { if (!validationError) onSubmit(); }}
          disabled={isLoading || !!validationError}
          className="text-[10px] px-2 py-1.5 rounded border border-white/15 hover:bg-white/5 transition-colors disabled:opacity-40 shrink-0"
        >
          {isLoading ? '…' : 'Run'}
        </button>
      </div>

      {/* Dropdown */}
      {dropdownOpen && suggestions.length > 0 && (
        <ul className="absolute left-0 right-0 top-full mt-0.5 z-50 bg-[#0e0e0e] border border-white/15 rounded shadow-xl max-h-48 overflow-y-auto">
          {suggestions.map((s, i) => (
            <li
              key={`${s.label}-${i}`}
              onMouseDown={(e) => { e.preventDefault(); applySuggestionClick(s); }}
              className={`flex items-center justify-between px-2 py-1 cursor-pointer text-[11px] font-mono transition-colors ${
                i === selectedIdx ? 'bg-white/10' : 'hover:bg-white/5'
              }`}
            >
              <span className={kindColor[s.kind]}>{s.label}</span>
              {s.detail && (
                <span className="text-white/30 text-[10px] ml-2 truncate">{s.detail}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Field hint bar — shown when operator or value context is active */}
      {fieldHint && (
        <div className="mt-1 px-2 py-0.5 text-[9px] text-white/40 leading-snug border-l-2 border-blue-500/30 pl-2 bg-blue-500/5 rounded-r">
          {fieldHint}
        </div>
      )}
    </div>
  );
}

// ─── Main Widget ─────────────────────────────────────────────────────────────

export function ScreenerWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

  const [activeInterval, setActiveInterval] = useState<IntervalTab>('1d');
  const [tqlInput, setTqlInput] = useState('');
  const [submittedTql, setSubmittedTql] = useState('');
  const [tqlError, setTqlError] = useState<string | null>(null);

  const [sortColumn, setSortColumn] = useState<SortColumn>('symbol');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  // Fetch sectors once for autocomplete
  const { data: sectorsData } = useQuery<{ sectors: string[] }>({
    queryKey: ['screener-sectors'],
    queryFn: async () => {
      const res = await fetch('/api/py/ticker/screener/sectors');
      if (!res.ok) return { sectors: [] };
      return (await res.json()) as { sectors: string[] };
    },
    staleTime: 5 * 60_000,
  });
  const sectors = sectorsData?.sectors ?? [];

  // Build query string for screener API
  const buildParams = useCallback((): string => {
    const params = new URLSearchParams();
    if (submittedTql.trim()) {
      params.set('tql', submittedTql.trim());
      params.set('default_interval', activeInterval);
    }
    params.set('sort_by', sortColumn);
    params.set('order', sortDirection);
    params.set('limit', '100');
    return params.toString();
  }, [submittedTql, activeInterval, sortColumn, sortDirection]);

  const { data, isLoading, isError, error, refetch } = useQuery<ScreenerResponse>({
    queryKey: ['screener-tql', submittedTql, activeInterval, sortColumn, sortDirection],
    queryFn: async () => {
      const qs = buildParams();
      const res = await fetch(`/api/py/ticker/screener?${qs}`);
      if (!res.ok) {
        const json = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(json.detail ?? `HTTP ${res.status}`);
      }
      return (await res.json()) as ScreenerResponse;
    },
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: false,
  });

  // Surface API errors back to the TQL input
  useEffect(() => {
    if (isError && error instanceof Error) {
      setTqlError(error.message);
    } else {
      setTqlError(null);
    }
  }, [isError, error]);

  const handleSubmit = useCallback(() => {
    setTqlError(null);
    setSubmittedTql(tqlInput);
  }, [tqlInput]);

  const handleClear = useCallback(() => {
    setTqlInput('');
    setSubmittedTql('');
    setTqlError(null);
  }, []);

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

  const getSortIndicator = (column: SortColumn) =>
    sortColumn !== column ? '' : sortDirection === 'asc' ? ' ▲' : ' ▼';

  const results = data?.results ?? [];

  const columns: { key: SortColumn; label: string; align: 'left' | 'right' }[] = [
    { key: 'symbol',         label: 'Symbol',   align: 'left' },
    { key: 'close',          label: 'LTP',      align: 'right' },
    { key: 'change_today',   label: 'Change %', align: 'right' },
    { key: 'rsi',            label: 'RSI',      align: 'right' },
    { key: 'atr_percent',    label: 'ATR %',    align: 'right' },
    { key: 'sector',         label: 'Sector',   align: 'left' },
    { key: 'momentum_score', label: 'Mom.',     align: 'right' },
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
          <span className="text-white/20 text-[9px]">TQL</span>
          {isLoading && (
            <span className="text-white/30 text-[10px] animate-pulse">loading…</span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {submittedTql && (
            <button
              onClick={handleClear}
              className="text-[10px] px-2 py-0.5 rounded border border-white/10 hover:bg-white/5 transition-colors text-white/50"
            >
              Clear
            </button>
          )}
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

      {/* TQL Query Bar */}
      <div className="shrink-0 border-b border-white/10 px-2 py-1.5">
        <TqlInput
          value={tqlInput}
          onChange={setTqlInput}
          onSubmit={handleSubmit}
          sectors={sectors}
          isLoading={isLoading}
          error={tqlError}
        />
        <div className="mt-1 text-[9px] text-white/20 flex gap-3">
          <span>Tab/↑↓ to navigate, Enter or Run to execute</span>
          {submittedTql && (
            <span className="text-white/30 truncate">
              active: <span className="text-terminal-amber/60">{submittedTql}</span>
            </span>
          )}
        </div>
      </div>

      {/* Stats bar */}
      <div className="shrink-0 px-2 py-0.5 text-[10px] text-white/30 border-b border-white/10 flex justify-between">
        <span>
          {data ? `${data.returned} / ${data.count} results` : '—'}
        </span>
        <span className="text-white/20 text-[9px]">
          {data?.filters_applied?.length
            ? data.filters_applied.join(', ')
            : 'no filters — showing all'}
        </span>
      </div>

      {/* Results table */}
      <div className="flex-1 overflow-auto">
        {results.length === 0 ? (
          <div className="h-full flex items-center justify-center text-white/30 text-[10px]">
            {isLoading
              ? 'Loading…'
              : submittedTql
              ? 'No results match your query.'
              : 'Enter a TQL query above and press Run.'}
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
                const rsi   = getIndicatorValue(row, activeInterval, 'rsi_14');
                const atr   = getIndicatorValue(row, activeInterval, 'atr_percent');
                const bbSq  = getIndicatorBool(row, activeInterval, 'bb_squeeze');
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
                        <span className={change >= 0 ? 'text-terminal-green' : 'text-terminal-red'}>
                          {change >= 0 ? '+' : ''}{formatNumber(change, 2)}%
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
                      {bbSq ? (
                        <span className="bg-yellow-600 text-black px-1 rounded text-[9px] font-bold mr-1">SQ</span>
                      ) : null}
                      {row.sector ?? '—'}
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

'use client';

import React, {
  useState,
  useCallback,
  useRef,
  useEffect,
  useMemo,
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
  extractFieldsFromTql,
  TQL_FIELDS,
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
  fair_value?: number | null;
  data_points?: number;
  momentum_score?: number | null;
  pos_52w?: Record<string, number | boolean | null>;
}

interface ScreenerResponse {
  count: number;
  returned: number;
  filters_applied: string[];
  results: ScreenerResult[];
}

type IntervalTab = '1d' | '1h' | 'W' | 'M';
type SortDirection = 'asc' | 'desc';

// ─── Column system ────────────────────────────────────────────────────────────

interface ColDef {
  key: string;
  label: string;
  align: 'left' | 'right';
  minW?: number;           // px
  getValue: (row: ScreenerResult, interval: IntervalTab) => number | string | boolean | null | undefined;
  format?: (v: number | string | boolean | null | undefined) => React.ReactNode;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const INTERVAL_TABS: { key: IntervalTab; label: string }[] = [
  { key: '1d', label: 'Daily' },
  { key: '1h', label: '1h' },
  { key: 'W',  label: 'Weekly' },
  { key: 'M',  label: 'Monthly' },
];

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function getIv(row: ScreenerResult, interval: IntervalTab, key: string): number | null {
  const iv = row.indicators_by_interval?.[interval];
  if (!iv) return null;
  const v = iv[key];
  return typeof v === 'number' && !Number.isNaN(v) ? v : null;
}

function changeCell(v: number | string | boolean | null | undefined): React.ReactNode {
  if (v === null || v === undefined || typeof v !== 'number') return <span className="text-white/30">—</span>;
  return (
    <span className={v >= 0 ? 'text-terminal-green' : 'text-terminal-red'}>
      {v >= 0 ? '+' : ''}{fmt(v)}%
    </span>
  );
}

function numCell(digits = 2) {
  return (v: number | string | boolean | null | undefined): React.ReactNode => {
    if (v === null || v === undefined || typeof v !== 'number') return <span className="text-white/30">—</span>;
    return <span className="text-white/70">{fmt(v, digits)}</span>;
  };
}

function returnCell(v: number | string | boolean | null | undefined): React.ReactNode {
  return changeCell(v);
}

function boolCell(trueLabel = 'YES', falseLabel = '—') {
  return (v: number | string | boolean | null | undefined): React.ReactNode =>
    v ? (
      <span className="bg-yellow-600 text-black px-1 rounded text-[9px] font-bold">{trueLabel}</span>
    ) : (
      <span className="text-white/20">{falseLabel}</span>
    );
}

// ─── Fixed columns (always shown) ────────────────────────────────────────────

const FIXED_COLS: ColDef[] = [
  {
    key: 'symbol',
    label: 'Symbol',
    align: 'left',
    minW: 72,
    getValue: (r) => r.symbol,
    format: (v) => <span className="font-bold text-white">{String(v)}</span>,
  },
  {
    key: 'close',
    label: 'LTP',
    align: 'right',
    minW: 60,
    getValue: (r) => r.close,
    format: numCell(2),
  },
  {
    key: 'change_today',
    label: 'Chg %',
    align: 'right',
    minW: 60,
    getValue: (r) => r.change_today,
    format: changeCell,
  },
  {
    key: 'fair_value',
    label: 'MS FV',
    align: 'right',
    minW: 60,
    getValue: (r) => r.fair_value ?? null,
    format: numCell(2),
  },
];

// ─── Dynamic column catalogue (one entry per TQL field that can be a column) ──

const DYNAMIC_COL_MAP: Record<string, Omit<ColDef, 'key'>> = {
  RSI:          { label: 'RSI',       align: 'right', minW: 50,  getValue: (r, iv) => getIv(r, iv, 'rsi_14'),          format: numCell(1) },
  ATR:          { label: 'ATR %',     align: 'right', minW: 52,  getValue: (r, iv) => getIv(r, iv, 'atr_percent'),      format: numCell(2) },
  MACD:         { label: 'MACD',      align: 'right', minW: 60,  getValue: (r, iv) => getIv(r, iv, 'macd'),             format: numCell(2) },
  MACDSignal:   { label: 'MACD Sig',  align: 'right', minW: 64,  getValue: (r, iv) => getIv(r, iv, 'macd_signal'),      format: numCell(2) },
  MACDHist:     { label: 'MACD H',    align: 'right', minW: 60,  getValue: (r, iv) => getIv(r, iv, 'macd_histogram'),   format: numCell(2) },
  BBWidth:      { label: 'BB Wid',    align: 'right', minW: 56,  getValue: (r, iv) => getIv(r, iv, 'bb_width'),         format: numCell(2) },
  BBSqueeze:    { label: 'Squeeze',   align: 'right', minW: 56,  getValue: (r, iv) => { const v = r.indicators_by_interval?.[iv]?.['bb_squeeze']; return v !== undefined && v !== null ? Boolean(v) : null; }, format: boolCell('SQ') },
  HV20:         { label: 'HV20',      align: 'right', minW: 50,  getValue: (r, iv) => getIv(r, iv, 'hv_20'),            format: numCell(1) },
  HV60:         { label: 'HV60',      align: 'right', minW: 50,  getValue: (r, iv) => getIv(r, iv, 'hv_60'),            format: numCell(1) },
  Sharpe60:     { label: 'Sharpe60',  align: 'right', minW: 60,  getValue: (r, iv) => getIv(r, iv, 'sharpe_60'),        format: numCell(2) },
  Sharpe126:    { label: 'Sharpe126', align: 'right', minW: 64,  getValue: (r, iv) => getIv(r, iv, 'sharpe_126'),       format: numCell(2) },
  Volume:       { label: 'Vol Ratio', align: 'right', minW: 60,  getValue: (r) => r.volume_ratio ?? null,               format: numCell(2) },
  Return1w:     { label: '1W %',      align: 'right', minW: 52,  getValue: (r) => r.returns?.['1w'] ?? null,            format: returnCell },
  Return1m:     { label: '1M %',      align: 'right', minW: 52,  getValue: (r) => r.returns?.['1m'] ?? null,            format: returnCell },
  Return3m:     { label: '3M %',      align: 'right', minW: 52,  getValue: (r) => r.returns?.['3m'] ?? null,            format: returnCell },
  Return6m:     { label: '6M %',      align: 'right', minW: 52,  getValue: (r) => r.returns?.['6m'] ?? null,            format: returnCell },
  Return1y:     { label: '1Y %',      align: 'right', minW: 52,  getValue: (r) => r.returns?.['1y'] ?? null,            format: returnCell },
  From52wHigh:  { label: '52H %',     align: 'right', minW: 52,  getValue: (r) => (r.pos_52w?.['pct_from_52w_high'] as number | null) ?? null, format: numCell(1) },
  From52wLow:   { label: '52L %',     align: 'right', minW: 52,  getValue: (r) => (r.pos_52w?.['pct_from_52w_low'] as number | null) ?? null,  format: numCell(1) },
  PE:           { label: 'PE',        align: 'right', minW: 48,  getValue: (r) => r.pe ?? null,                         format: numCell(1) },
  MomentumScore:{ label: 'Mom.',      align: 'right', minW: 48,  getValue: (r) => r.momentum_score ?? null,             format: numCell(1) },
  Sector:       { label: 'Sector',    align: 'left',  minW: 80,  getValue: (r) => r.sector ?? null,                     format: (v) => <span className="text-white/50">{v ? String(v) : '—'}</span> },
  Industry:     { label: 'Industry',  align: 'left',  minW: 90,  getValue: (r) => r.industry ?? null,                   format: (v) => <span className="text-white/40 truncate">{v ? String(v) : '—'}</span> },
  DataPoints:   { label: 'Pts',       align: 'right', minW: 40,  getValue: (r) => r.data_points ?? null,                format: numCell(0) },
};

// ─── CSV export ───────────────────────────────────────────────────────────────

function exportCsv(results: ScreenerResult[], cols: ColDef[], interval: IntervalTab) {
  const header = cols.map((c) => c.label).join(',');
  const rows = results.map((row) =>
    cols
      .map((c) => {
        const v = c.getValue(row, interval);
        if (v === null || v === undefined) return '';
        if (typeof v === 'string') return `"${v.replace(/"/g, '""')}"`;
        return String(v);
      })
      .join(',')
  );
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `screener_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
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
      if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1)); return; }
      if (e.key === 'ArrowUp')   { e.preventDefault(); setSelectedIdx((i) => Math.max(i - 1, 0)); return; }
      if (e.key === 'Escape')    { setDropdownOpen(false); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && suggestions[selectedIdx])) {
        e.preventDefault();
        const s = suggestions[selectedIdx];
        if (s) {
          const cursor = inputRef.current?.selectionStart ?? value.length;
          const { text, cursor: nc } = applySuggestion(value, cursor, s);
          onChange(text);
          setDropdownOpen(false);
          requestAnimationFrame(() => {
            if (inputRef.current) {
              inputRef.current.setSelectionRange(nc, nc);
              updateSuggestions(text, nc);
            }
          });
        }
        return;
      }
    }
    if (e.key === 'Enter' && !validationError) {
      setDropdownOpen(false);
      onSubmit();
    }
  };

  const handleFocus = () => updateSuggestions(value, inputRef.current?.selectionStart ?? value.length);
  const handleBlur  = () => setTimeout(() => setDropdownOpen(false), 150);

  const applySuggestionClick = (s: TqlSuggestion) => {
    const cursor = inputRef.current?.selectionStart ?? value.length;
    const { text, cursor: nc } = applySuggestion(value, cursor, s);
    onChange(text);
    setDropdownOpen(false);
    requestAnimationFrame(() => {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.setSelectionRange(nc, nc);
        updateSuggestions(text, nc);
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

      {/* Field hint bar */}
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

  // Sort state — key is ColDef.key string
  const [sortKey, setSortKey] = useState<string>('symbol');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');

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

  // Derive dynamic columns from the submitted TQL
  const dynamicCols = useMemo<ColDef[]>(() => {
    const fields = extractFieldsFromTql(submittedTql);
    return fields
      .filter((f) => f in DYNAMIC_COL_MAP)
      .map((f) => ({ key: f, ...DYNAMIC_COL_MAP[f] }));
  }, [submittedTql]);

  // All visible columns = fixed + dynamic (dedup by key)
  const allCols = useMemo<ColDef[]>(() => {
    const dynKeys = new Set(dynamicCols.map((c) => c.key));
    // Remove from fixed any that somehow duplicate (shouldn't happen)
    const fixed = FIXED_COLS.filter((c) => !dynKeys.has(c.key));
    return [...fixed, ...dynamicCols];
  }, [dynamicCols]);

  // Build query params for the screener API
  const buildParams = useCallback((): string => {
    const params = new URLSearchParams();
    if (submittedTql.trim()) {
      params.set('tql', submittedTql.trim());
      params.set('default_interval', activeInterval);
    }
    // Backend sort is best-effort — client will re-sort anyway
    params.set('sort_by', 'symbol');
    params.set('order', 'asc');
    params.set('limit', '200');
    return params.toString();
  }, [submittedTql, activeInterval]);

  const { data, isLoading, isError, error, refetch } = useQuery<ScreenerResponse>({
    queryKey: ['screener-tql', submittedTql, activeInterval],
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

  useEffect(() => {
    if (isError && error instanceof Error) setTqlError(error.message);
    else setTqlError(null);
  }, [isError, error]);

  // Client-side sort
  const sortedResults = useMemo(() => {
    const rows = data?.results ?? [];
    if (!sortKey) return rows;
    const col = allCols.find((c) => c.key === sortKey);
    if (!col) return rows;
    return [...rows].sort((a, b) => {
      const av = col.getValue(a, activeInterval);
      const bv = col.getValue(b, activeInterval);
      const an = av === null || av === undefined;
      const bn = bv === null || bv === undefined;
      if (an && bn) return 0;
      if (an) return 1;
      if (bn) return -1;
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortDir === 'asc' ? av - bv : bv - av;
      }
      const as = String(av); const bs = String(bv);
      return sortDir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as);
    });
  }, [data, sortKey, sortDir, allCols, activeInterval]);

  const handleSubmit = useCallback(() => {
    setTqlError(null);
    setSubmittedTql(tqlInput);
    setSortKey('symbol');
    setSortDir('asc');
  }, [tqlInput]);

  const handleClear = useCallback(() => {
    setTqlInput('');
    setSubmittedTql('');
    setTqlError(null);
  }, []);

  const handleHeaderClick = useCallback((key: string) => {
    setSortKey((prev) => {
      if (prev === key) return prev;
      setSortDir('asc');
      return key;
    });
    if (sortKey === key) setSortDir((d) => d === 'asc' ? 'desc' : 'asc');
  }, [sortKey]);

  const handleRowClick = useCallback((symbol: string) => {
    setActiveSymbol(symbol);
    setActiveExchange('NSE');
  }, [setActiveSymbol, setActiveExchange]);

  const sortIndicator = (key: string) =>
    sortKey !== key ? '' : sortDir === 'asc' ? ' ▲' : ' ▼';

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
          {isLoading && <span className="text-white/30 text-[10px] animate-pulse">loading…</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {sortedResults.length > 0 && (
            <button
              onClick={() => exportCsv(sortedResults, allCols, activeInterval)}
              className="text-[10px] px-2 py-0.5 rounded border border-white/10 hover:bg-white/5 transition-colors text-white/60"
            >
              CSV
            </button>
          )}
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
          <span>Tab/↑↓ to navigate · Enter or Run to execute</span>
          {submittedTql && (
            <span className="text-white/30 truncate">
              active: <span className="text-terminal-amber/60">{submittedTql}</span>
            </span>
          )}
        </div>
      </div>

      {/* Stats bar */}
      <div className="shrink-0 px-2 py-0.5 text-[10px] text-white/30 border-b border-white/10 flex justify-between items-center">
        <span>{data ? `${data.returned} / ${data.count} results` : '—'}</span>
        {dynamicCols.length > 0 && (
          <span className="text-[9px] text-white/20">
            columns: {dynamicCols.map((c) => c.label).join(', ')}
          </span>
        )}
      </div>

      {/* Results table — horizontal scroll */}
      <div className="flex-1 overflow-auto">
        {sortedResults.length === 0 ? (
          <div className="h-full flex items-center justify-center text-white/30 text-[10px]">
            {isLoading
              ? 'Loading…'
              : submittedTql
              ? 'No results match your query.'
              : 'Enter a TQL query above and press Run.'}
          </div>
        ) : (
          <div className="overflow-x-auto h-full">
            <table className="text-[10px] border-collapse" style={{ minWidth: 'max-content' }}>
              <thead className="sticky top-0 bg-terminal-bg z-10">
                <tr className="border-b border-white/10">
                  {allCols.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => handleHeaderClick(col.key)}
                      style={{ minWidth: col.minW ?? 48 }}
                      className={`py-1 px-2 cursor-pointer select-none hover:text-white transition-colors whitespace-nowrap ${
                        col.align === 'left' ? 'text-left' : 'text-right'
                      } text-white/50`}
                    >
                      {col.label}
                      <span className="text-terminal-amber">{sortIndicator(col.key)}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedResults.map((row) => (
                  <tr
                    key={row.symbol}
                    onClick={() => handleRowClick(row.symbol)}
                    className="border-b border-white/5 hover:bg-white/5 cursor-pointer transition-colors"
                  >
                    {allCols.map((col) => {
                      const v = col.getValue(row, activeInterval);
                      return (
                        <td
                          key={col.key}
                          className={`py-1 px-2 whitespace-nowrap ${col.align === 'left' ? 'text-left' : 'text-right'}`}
                        >
                          {col.format ? col.format(v) : (
                            <span className="text-white/70">{v !== null && v !== undefined ? String(v) : '—'}</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

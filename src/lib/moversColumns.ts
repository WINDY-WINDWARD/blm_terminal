import type { ChangeRanges } from './nseTypes';

export const DEFAULT_MOVERS_COLUMN_ORDER = [
  'ticker',
  'ltp',
  'chg',
  'momentum',
  'velocity',
  'vol',
  'trnvr',
  'radar',
  'open',
  'high',
  'low',
  'ca',
  '2y',
  '3y',
  '5y',
  '52wh',
  '52wl',
] as const;

export type MoverColumnKey = (typeof DEFAULT_MOVERS_COLUMN_ORDER)[number];
export type MoverView = 'matrix' | 'gainers' | 'losers';
export type SortDirection = 'asc' | 'desc';

export interface MoverSortRow {
  symbol: string;
  close: string;
  pChange: number;
  open?: string;
  high?: string;
  low?: string;
  vol?: number;
  turnover?: number;
  caDate?: string;
}

export interface MoverQuoteData {
  yearHigh?: number;
  yearLow?: number;
}

export const MOVER_COLUMN_LABELS: Record<MoverColumnKey, string> = {
  ticker: 'Ticker & Bias',
  ltp: 'LTP (₹)',
  chg: 'Day %',
  momentum: '5-Period Momentum Alignment (1W / 1M / 3M / 6M / 1Y)',
  velocity: 'Velocity Score',
  vol: 'Volume',
  trnvr: 'Turnover',
  radar: 'Radar Status',
  open: 'Open',
  high: 'High',
  low: 'Low',
  ca: 'CA',
  '2y': '2Y%',
  '3y': '3Y%',
  '5y': '5Y%',
  '52wh': '52W High',
  '52wl': '52W Low',
};

const ALWAYS_VISIBLE = new Set<MoverColumnKey>(['ticker', 'ltp', 'chg']);
const MATRIX_ONLY = new Set<MoverColumnKey>(['momentum', 'velocity', 'radar']);
const OPTIONAL = new Set<MoverColumnKey>([
  'vol',
  'trnvr',
  'open',
  'high',
  'low',
  'ca',
  '2y',
  '3y',
  '5y',
  '52wh',
  '52wl',
]);

const KNOWN_COLUMNS = new Set<string>(DEFAULT_MOVERS_COLUMN_ORDER);

export function getVisibleMoverColumns(
  order: readonly string[],
  view: MoverView,
  optionalVisible: readonly string[],
): MoverColumnKey[] {
  const visibleOptional = new Set(optionalVisible);
  const normalized: string[] = [];

  for (const key of [...order, ...DEFAULT_MOVERS_COLUMN_ORDER]) {
    if (KNOWN_COLUMNS.has(key) && !normalized.includes(key)) normalized.push(key);
  }

  return normalized.filter((key): key is MoverColumnKey => {
    const column = key as MoverColumnKey;
    if (ALWAYS_VISIBLE.has(column)) return true;
    if (MATRIX_ONLY.has(column)) return view === 'matrix';
    if (OPTIONAL.has(column)) return visibleOptional.has(column);
    return false;
  });
}

export function getMoverColumnDefaultDirection(key: MoverColumnKey): SortDirection {
  return key === 'ticker' || key === 'ca' ? 'asc' : 'desc';
}

export function computeMoverAlignment(ranges: ChangeRanges | null, pChange: number) {
  if (!ranges) {
    return {
      bullCount: 0,
      velocity: 50,
      label: 'AWAITING RANGES',
      badgeClass: 'text-zinc-400 bg-zinc-800/40 border-zinc-700',
    };
  }

  const validVals = [
    ranges.oneWeekPercent,
    ranges.oneMonthPercent,
    ranges.threeMonthPercent,
    ranges.sixMonthPercent,
    ranges.oneYearPercent,
  ].filter((value): value is number => value != null && !Number.isNaN(value));

  if (validVals.length === 0) {
    return {
      bullCount: 0,
      velocity: 50,
      label: 'NO HISTORICAL DATA',
      badgeClass: 'text-zinc-400 bg-zinc-800/40 border-zinc-700',
    };
  }

  const bullCount = validVals.filter((value) => value >= 0).length;
  const baseVelocity = Math.min(
    99,
    Math.max(12, Math.round(50 + pChange * 3 + (bullCount - validVals.length / 2) * 8)),
  );

  if (bullCount >= Math.ceil(validVals.length * 0.8)) {
    return {
      bullCount,
      velocity: Math.max(70, baseVelocity),
      label: `▲ ACCELERATING (${bullCount}/${validVals.length})`,
      badgeClass: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    };
  }
  if (bullCount >= Math.ceil(validVals.length * 0.4)) {
    return {
      bullCount,
      velocity: baseVelocity,
      label: `◈ CONSOLIDATING (${bullCount}/${validVals.length})`,
      badgeClass: 'text-terminal-amber bg-terminal-amber/10 border-terminal-amber/30',
    };
  }
  return {
    bullCount,
    velocity: Math.min(35, baseVelocity),
    label: `▼ BEARISH DRIFT (${bullCount}/${validVals.length})`,
    badgeClass: 'text-rose-400 bg-rose-500/10 border-rose-500/30',
  };
}

function toFiniteNumber(value: string | number | null | undefined): number | null {
  if (value == null || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function getMomentumScore(ranges: ChangeRanges | null): { count: number; average: number } | null {
  if (!ranges) return null;
  const values = [
    ranges.oneWeekPercent,
    ranges.oneMonthPercent,
    ranges.threeMonthPercent,
    ranges.sixMonthPercent,
    ranges.oneYearPercent,
  ].filter((value): value is number => value != null && !Number.isNaN(value));
  if (values.length === 0) return null;
  return {
    count: values.filter((value) => value >= 0).length,
    average: values.reduce((sum, value) => sum + value, 0) / values.length,
  };
}

function getRadarSeverity(ranges: ChangeRanges | null, pChange: number): number | null {
  if (!ranges) return null;
  const alignment = computeMoverAlignment(ranges, pChange);
  if (alignment.label.startsWith('▲')) return 2;
  if (alignment.label.startsWith('◈')) return 1;
  if (alignment.label.startsWith('▼')) return 0;
  return null;
}

function directSortValue(
  row: MoverSortRow,
  key: MoverColumnKey,
  ranges: ChangeRanges | null,
  quote: MoverQuoteData | null,
): number | string | null {
  switch (key) {
    case 'ticker':
      return row.symbol;
    case 'ltp':
      return toFiniteNumber(row.close);
    case 'chg':
      return row.pChange;
    case 'vol':
      return row.vol ?? null;
    case 'trnvr':
      return row.turnover ?? null;
    case 'open':
      return toFiniteNumber(row.open);
    case 'high':
      return toFiniteNumber(row.high);
    case 'low':
      return toFiniteNumber(row.low);
    case 'ca':
      return row.caDate ?? null;
    case '2y':
      return ranges?.twoYearPercent ?? null;
    case '3y':
      return ranges?.threeYearPercent ?? null;
    case '5y':
      return ranges?.fiveYearPercent ?? null;
    case '52wh':
      return quote?.yearHigh ?? null;
    case '52wl':
      return quote?.yearLow ?? null;
    default:
      return null;
  }
}

function compareDirectValues(a: number | string, b: number | string, direction: SortDirection): number {
  if (typeof a === 'number' && typeof b === 'number') {
    return direction === 'asc' ? a - b : b - a;
  }
  const compared = String(a).localeCompare(String(b));
  return direction === 'asc' ? compared : -compared;
}

function compareNullable(
  a: number | string | null,
  b: number | string | null,
  direction: SortDirection,
): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return compareDirectValues(a, b, direction);
}

export function compareMoverRows(
  a: MoverSortRow,
  b: MoverSortRow,
  key: MoverColumnKey,
  direction: SortDirection,
  rangesBySymbol: Record<string, ChangeRanges | null | undefined>,
  quotesBySymbol: Record<string, MoverQuoteData | null | undefined>,
): number {
  const aRanges = rangesBySymbol[a.symbol] ?? null;
  const bRanges = rangesBySymbol[b.symbol] ?? null;
  let result = 0;

  if (key === 'momentum') {
    const aScore = getMomentumScore(aRanges);
    const bScore = getMomentumScore(bRanges);
    if (!aScore && !bScore) result = 0;
    else if (!aScore) result = 1;
    else if (!bScore) result = -1;
    else {
      const countDiff = direction === 'asc' ? aScore.count - bScore.count : bScore.count - aScore.count;
      result = countDiff || compareDirectValues(aScore.average, bScore.average, direction);
    }
  } else if (key === 'velocity') {
    const aVelocity = aRanges ? computeMoverAlignment(aRanges, a.pChange).velocity : null;
    const bVelocity = bRanges ? computeMoverAlignment(bRanges, b.pChange).velocity : null;
    result = compareNullable(aVelocity, bVelocity, direction);
  } else if (key === 'radar') {
    const aSeverity = getRadarSeverity(aRanges, a.pChange);
    const bSeverity = getRadarSeverity(bRanges, b.pChange);
    result = compareNullable(aSeverity, bSeverity, direction);
  } else {
    result = compareNullable(
      directSortValue(a, key, aRanges, quotesBySymbol[a.symbol] ?? null),
      directSortValue(b, key, bRanges, quotesBySymbol[b.symbol] ?? null),
      direction,
    );
  }

  return result || a.symbol.localeCompare(b.symbol);
}

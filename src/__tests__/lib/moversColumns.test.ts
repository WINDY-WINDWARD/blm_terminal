import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MOVERS_COLUMN_ORDER,
  compareMoverRows,
  getVisibleMoverColumns,
  type MoverQuoteData,
  type MoverSortRow,
} from '@/lib/moversColumns';
import type { ChangeRanges } from '@/lib/nseTypes';

const row = (symbol: string, close: string, pChange: number, extra: Partial<MoverSortRow> = {}): MoverSortRow => ({
  symbol,
  close,
  pChange,
  ...extra,
});

const ranges = (overrides: Partial<ChangeRanges> = {}): ChangeRanges => ({
  oneDayPercent: 1,
  oneWeekPercent: 1,
  oneMonthPercent: 1,
  threeMonthPercent: 1,
  sixMonthPercent: 1,
  oneYearPercent: 1,
  twoYearPercent: 1,
  threeYearPercent: 1,
  fiveYearPercent: 1,
  ...overrides,
});

const rangesMap = (value: Record<string, ChangeRanges | null>) => value;
const quotesMap = (value: Record<string, MoverQuoteData | null>) => value;

describe('getVisibleMoverColumns', () => {
  it('filters matrix-only columns from gainers and losers views', () => {
    const optional = ['vol', '52wh'];
    expect(getVisibleMoverColumns(DEFAULT_MOVERS_COLUMN_ORDER, 'gainers', optional)).toEqual([
      'ticker',
      'ltp',
      'chg',
      'vol',
      '52wh',
    ]);
    expect(getVisibleMoverColumns(DEFAULT_MOVERS_COLUMN_ORDER, 'losers', optional)).toEqual([
      'ticker',
      'ltp',
      'chg',
      'vol',
      '52wh',
    ]);
  });

  it('keeps matrix columns in the shared order', () => {
    expect(getVisibleMoverColumns(DEFAULT_MOVERS_COLUMN_ORDER, 'matrix', ['vol'])).toEqual([
      'ticker',
      'ltp',
      'chg',
      'momentum',
      'velocity',
      'vol',
      'radar',
    ]);
  });

  it('honours a saved order and appends missing known columns', () => {
    expect(getVisibleMoverColumns(['chg', 'ticker', 'vol', 'unknown'], 'gainers', ['vol'])).toEqual([
      'chg',
      'ticker',
      'vol',
      'ltp',
    ]);
  });
});

describe('compareMoverRows', () => {
  it('sorts ticker alphabetically and numeric columns numerically', () => {
    const a = row('ZETA', '100.00', 2);
    const b = row('ALPHA', '90.00', 5);
    expect(compareMoverRows(a, b, 'ticker', 'asc', {}, {})).toBeGreaterThan(0);
    expect(compareMoverRows(a, b, 'ltp', 'desc', {}, {})).toBeLessThan(0);
    expect(compareMoverRows(a, b, 'chg', 'desc', {}, {})).toBeGreaterThan(0);
  });

  it('sorts momentum by positive-period count then average return', () => {
    const a = row('A', '100', 0);
    const b = row('B', '100', 0);
    const map = rangesMap({
      A: ranges({ oneWeekPercent: 5, oneMonthPercent: 4, threeMonthPercent: -1, sixMonthPercent: -1, oneYearPercent: -1 }),
      B: ranges({ oneWeekPercent: 2, oneMonthPercent: 1, threeMonthPercent: 0, sixMonthPercent: -1, oneYearPercent: -1 }),
    });
    expect(compareMoverRows(a, b, 'momentum', 'desc', map, {})).toBeGreaterThan(0);
  });

  it('sorts velocity and radar severity from computed ranges', () => {
    const a = row('A', '100', 8);
    const b = row('B', '100', -8);
    const map = rangesMap({
      A: ranges({ oneWeekPercent: 8, oneMonthPercent: 8, threeMonthPercent: 8, sixMonthPercent: 8, oneYearPercent: 8 }),
      B: ranges({ oneWeekPercent: -8, oneMonthPercent: -8, threeMonthPercent: -8, sixMonthPercent: -8, oneYearPercent: -8 }),
    });
    expect(compareMoverRows(a, b, 'velocity', 'desc', map, {})).toBeLessThan(0);
    expect(compareMoverRows(a, b, 'radar', 'desc', map, {})).toBeLessThan(0);
  });

  it('sorts quote-backed 52 week columns', () => {
    const a = row('A', '100', 0);
    const b = row('B', '100', 0);
    const quotes = quotesMap({ A: { yearHigh: 200 }, B: { yearHigh: 150 } });
    expect(compareMoverRows(a, b, '52wh', 'desc', {}, quotes)).toBeLessThan(0);
  });

  it('places missing derived values last in either direction', () => {
    const a = row('A', '100', 0);
    const b = row('B', '100', 0);
    const map = rangesMap({ A: null, B: ranges() });
    expect(compareMoverRows(a, b, 'velocity', 'asc', map, {})).toBeGreaterThan(0);
    expect(compareMoverRows(b, a, 'velocity', 'asc', map, {})).toBeLessThan(0);
  });

  it('uses symbol as a stable tie-breaker', () => {
    const a = row('A', '100', 0);
    const b = row('B', '100', 0);
    const map = rangesMap({ A: ranges(), B: ranges() });
    expect(compareMoverRows(a, b, 'velocity', 'desc', map, {})).toBeLessThan(0);
  });
});

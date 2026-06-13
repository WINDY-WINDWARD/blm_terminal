// Shared types, constants, and helpers for NSE change-ranges and symbol-data.
//
// Used by:
//   - src/lib/nseFetch.ts          (browser transport, debounce + client cache)
//   - src/app/api/nse/change-ranges/route.ts
//   - src/app/api/nse/symbol-data/route.ts

export interface ChangeRanges {
  oneDayPercent: number | null;
  oneWeekPercent: number | null;
  oneMonthPercent: number | null;
  threeMonthPercent: number | null;
  sixMonthPercent: number | null;
  oneYearPercent: number | null;
  twoYearPercent: number | null;
  threeYearPercent: number | null;
  fiveYearPercent: number | null;
}

export interface SymbolDataExtract {
  ltp: number;
  pChange: number;
  yearHigh?: number;
  yearLow?: number;
}

// Raw NSE shape returned from the backend for symbol-data
export interface RawNseSymbolData {
  equityResponse?: Array<{
    orderBook?: { lastPrice?: number };
    tradeInfo?: { lastPrice?: number };
    metaData?: { pChange?: number };
    priceInfo?: { yearHigh?: number; yearLow?: number };
  }>;
}

export function extractSymbolData(raw: RawNseSymbolData | null): SymbolDataExtract | null {
  if (!raw) return null;
  const equity = raw.equityResponse?.[0];
  if (!equity) return null;
  const ltp = equity.orderBook?.lastPrice ?? equity.tradeInfo?.lastPrice ?? 0;
  if (!ltp) return null;
  return {
    ltp,
    pChange: equity.metaData?.pChange ?? 0,
    yearHigh: equity.priceInfo?.yearHigh,
    yearLow: equity.priceInfo?.yearLow,
  };
}

// NSE field rename map: our output key → NSE row key
// Mirrors backend/app/services/nse_client_async.py NSE_FIELD_MAP_CHANGE_RANGES
export const NSE_FIELD_MAP_CHANGE_RANGES: Record<keyof ChangeRanges, string> = {
  oneDayPercent: '',
  oneWeekPercent: 'one_week_chng_per',
  oneMonthPercent: 'one_month_chng_per',
  threeMonthPercent: 'three_month_chng_per',
  sixMonthPercent: 'six_month_chng_per',
  oneYearPercent: 'one_year_chng_per',
  twoYearPercent: 'two_year_chng_per',
  threeYearPercent: 'three_year_chng_per',
  fiveYearPercent: 'five_year_chng_per',
};

export const CHANGE_RANGES_TTL_SECONDS = 300;
export const SYMBOL_DATA_TTL_SECONDS = 60;

export const NSE_MAX_SYMBOLS_PER_REQUEST = 50;

export const NSE_BASE_URL = 'https://www.nseindia.com';

export const NSE_HEADERS: HeadersInit = {
  'User-Agent':
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  Accept: 'application/json, text/html, */*',
  'Accept-Language': 'en-US,en;q=0.9',
  Referer: 'https://www.nseindia.com/',
  Origin: 'https://www.nseindia.com',
};

export function cleanNaN<T>(value: T): T {
  if (typeof value === 'number' && (!Number.isFinite(value) || Number.isNaN(value))) {
    return null as T;
  }
  return value;
}

export function parseChangeRangesRow(row: Record<string, unknown> | undefined): ChangeRanges {
  const out: ChangeRanges = {
    oneDayPercent: null,
    oneWeekPercent: null,
    oneMonthPercent: null,
    threeMonthPercent: null,
    sixMonthPercent: null,
    oneYearPercent: null,
    twoYearPercent: null,
    threeYearPercent: null,
    fiveYearPercent: null,
  };
  if (!row) return out;
  for (const outKey of Object.keys(NSE_FIELD_MAP_CHANGE_RANGES) as (keyof ChangeRanges)[]) {
    const nseKey = NSE_FIELD_MAP_CHANGE_RANGES[outKey];
    if (!nseKey) continue;
    const raw = row[nseKey];
    if (raw === null || raw === undefined) {
      out[outKey] = null;
    } else {
      const num = Number(raw);
      out[outKey] = Number.isFinite(num) ? num : null;
    }
  }
  return out;
}

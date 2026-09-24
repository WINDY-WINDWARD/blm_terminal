/**
 * BLM Script Lab v1 — fundamentals context for scripts with needs_fundamentals.
 * Quarterly step-filled across bar times; ratios as constants.
 * Safe Mode (no data consent) → { state: 'needs-consent' }, script doesn't run.
 */
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { advancedScrapingConsentAtom } from '@/store/terminalStore';
import type { ScriptFundamentals, ScriptQuarterlyRow, ScriptRatios } from './types';

export type FundamentalsState =
  | { state: 'idle' }
  | { state: 'needs-consent' }
  | { state: 'loading' }
  | { state: 'error'; message: string }
  | { state: 'ready'; data: ScriptFundamentals };

const MONTH_Q: Record<string, string> = {
  Mar: 'Q1', Jun: 'Q2', Sep: 'Q3', Dec: 'Q4',
};

function toNum(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v !== 'string') return null;
  const cleaned = v.replace(/,/g, '').replace(/[^0-9.\-]/g, '');
  if (cleaned === '' || cleaned === '-' || cleaned === '.') return null;
  const n = parseFloat(cleaned);
  return Number.isFinite(n) ? n : null;
}

async function fetchJson(url: string): Promise<unknown> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<unknown>;
}

/** Normalize the /screener/quarterly payload into ascending quarterly rows. */
export function normalizeQuarterly(payload: unknown): ScriptQuarterlyRow[] {
  const root = payload as { quarterly_results?: Record<string, Record<string, Record<string, unknown>>> };
  const years = root?.quarterly_results;
  if (!years || typeof years !== 'object') return [];
  const rows: ScriptQuarterlyRow[] = [];
  for (const [year, months] of Object.entries(years)) {
    if (!months || typeof months !== 'object') continue;
    for (const [mon, cells] of Object.entries(months)) {
      const q = MONTH_Q[mon];
      if (!q || !cells || typeof cells !== 'object') continue; // skips "Mar TTM" etc.
      rows.push({
        period: `${year}${q}`,
        sales: toNum(cells['Sales']),
        opProfit: toNum(cells['Operating Profit'] ?? cells['OPM']),
        netProfit: toNum(cells['Net Profit']),
        eps: toNum(cells['EPS in Rs'] ?? cells['EPS']),
      });
    }
  }
  rows.sort((a, b) => (a.period < b.period ? -1 : 1));
  return rows;
}

export function normalizeRatios(payload: unknown): ScriptRatios {
  const root = payload as { ratios?: Record<string, unknown> };
  const r = root?.ratios ?? {};
  return {
    pe: toNum(r['pe']),
    roe: toNum(r['roe']),
    roce: toNum(r['roce']),
    marketCapCr: toNum(r['market_cap']),
  };
}

interface UseFundamentalsArgs {
  symbol: string;
  needed: boolean;
}

/** Fetch + normalize fundamentals when at least one enabled script needs them. */
export function useScriptFundamentals({ symbol, needed }: UseFundamentalsArgs): FundamentalsState {
  const consent = useAtomValue(advancedScrapingConsentAtom);

  const quarterlyQuery = useQuery({
    queryKey: ['script-fundamentals', 'quarterly', symbol],
    queryFn: () => fetchJson(`/api/py/screener/quarterly/${encodeURIComponent(symbol)}`),
    enabled: needed && consent === true && symbol.length > 0,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
  const companyQuery = useQuery({
    queryKey: ['script-fundamentals', 'company', symbol],
    queryFn: () => fetchJson(`/api/py/screener/company/${encodeURIComponent(symbol)}?consolidated=true`),
    enabled: needed && consent === true && symbol.length > 0,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });

  if (!needed) return { state: 'idle' };
  if (consent !== true) return { state: 'needs-consent' };
  if (quarterlyQuery.isPending || companyQuery.isPending) return { state: 'loading' };
  if (quarterlyQuery.isError || companyQuery.isError) {
    return { state: 'error', message: 'fundamentals unavailable' };
  }
  if (!quarterlyQuery.data || !companyQuery.data) return { state: 'loading' };
  return {
    state: 'ready',
    data: {
      quarterly: normalizeQuarterly(quarterlyQuery.data),
      ratios: normalizeRatios(companyQuery.data),
    },
  };
}

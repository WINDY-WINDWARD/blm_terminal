'use client';

import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom } from '@/store/terminalStore';

// ─── Types ────────────────────────────────────────────────────────────────────

interface ScreenerRatios {
  market_cap?: string | null;
  price?: string | null;
  high_52w?: string | null;
  low_52w?: string | null;
  pe?: string | null;
  book_value?: string | null;
  dividend_yield?: string | null;
  roce?: string | null;
  roe?: string | null;
  face_value?: string | null;
  [key: string]: string | null | undefined;
}

interface ScreenerQuarter {
  period: string;
  sales: string | null;
  net_profit: string | null;
  eps: string | null;
}

interface CompanyFundamentals {
  symbol: string;
  name: string;
  screener_warehouse_id: string | null;
  ratios: ScreenerRatios;
  quarters: ScreenerQuarter[];
}

// ─── Constants ────────────────────────────────────────────────────────────────

/** Fixed ratios displayed first, in order. */
const CORE_RATIO_KEYS: { key: keyof ScreenerRatios; label: string }[] = [
  { key: 'market_cap',     label: 'Market Cap'    },
  { key: 'price',          label: 'Price'         },
  { key: 'pe',             label: 'P/E'           },
  { key: 'book_value',     label: 'Book Value'    },
  { key: 'roce',           label: 'ROCE'          },
  { key: 'roe',            label: 'ROE'           },
  { key: 'high_52w',       label: '52W High'      },
  { key: 'low_52w',        label: '52W Low'       },
  { key: 'dividend_yield', label: 'Div Yield'     },
  { key: 'face_value',     label: 'Face Value'    },
];

const CORE_KEYS_SET = new Set([
  ...CORE_RATIO_KEYS.map((r) => r.key),
  // Shown in Calculated Ratios section — exclude from "More"
  'piotroski_score',
]);

// ─── Peter Lynch Fair Value ───────────────────────────────────────────────────

/** Parse a numeric value from a screener string, stripping %, ₹, Cr, commas etc. */
function parseNum(val: string | null | undefined): number | null {
  if (!val) return null;
  const cleaned = val.replace(/[%₹,\s]/g, '').replace(/Cr\.?$/i, '').trim();
  const n = parseFloat(cleaned);
  return isNaN(n) ? null : n;
}

/**
 * Try several possible key names screener.in uses for 5-year EPS CAGR in
 * quick_ratios. The exact key depends on the company page version.
 */
const EPS_GROWTH_KEYS = [
  'eps_growth_5years',
  '5yr_eps_growth',
  '5_yr_eps_growth',
  'eps_5yr_growth',
  'earnings_growth_5years',
  'profit_growth_5years',
];

/**
 * Try several possible key names screener.in uses for TTM/annual EPS
 * in quick_ratios (the "More" section). These are the annualised EPS figures,
 * not the per-quarter EPS from the quarterly table.
 */
const EPS_KEYS = [
  'eps',
  'earning_per_share',
  'earnings_per_share',
  'eps_in_rs',
  'eps_(ttm)',
  'ttm_eps',
];

interface PeterLynchResult {
  fairValueRatio: number | null;
  fairValuePrice: number | null;
  epsGrowth: number | null;
  latestEps: number | null;
  divYield: number | null;
  pe: number | null;
  ratioMissingKey: string | null;
  priceMissingKey: string | null;
  epsKey: string | null;
}

function calcPeterLynch(ratios: ScreenerRatios): PeterLynchResult {
  const pe       = parseNum(ratios.pe);
  const divYield = parseNum(ratios.dividend_yield);

  // Find whichever EPS growth key exists in the ratios object
  let epsGrowth: number | null = null;
  for (const key of EPS_GROWTH_KEYS) {
    const val = parseNum(ratios[key]);
    if (val !== null) { epsGrowth = val; break; }
  }

  // Find the TTM/annual EPS from quick_ratios ("More" section)
  let latestEps: number | null = null;
  let epsKey: string | null = null;
  for (const key of EPS_KEYS) {
    const val = parseNum(ratios[key]);
    if (val !== null) { latestEps = val; epsKey = key; break; }
  }

  const ratioMissingKey =
    pe        === null ? 'P/E'           :
    epsGrowth === null ? 'EPS Growth 5Y' :
    null;

  const priceMissingKey =
    epsGrowth === null ? 'EPS Growth 5Y' :
    latestEps === null ? 'EPS'           :
    null;

  const fairValueRatio =
    pe !== null && epsGrowth !== null
      ? (epsGrowth + (divYield ?? 0)) / pe
      : null;

  const fairValuePrice =
    epsGrowth !== null && latestEps !== null
      ? epsGrowth * latestEps
      : null;

  return { fairValueRatio, fairValuePrice, epsGrowth, latestEps, divYield, pe, ratioMissingKey, priceMissingKey, epsKey };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatRatioLabel(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function RatioRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <tr className="border-b border-terminal-gray/40">
      <td className="py-[3px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
        {label}
      </td>
      <td className="py-[3px] text-right text-terminal-amber text-[10px] font-mono font-bold whitespace-nowrap">
        {value ?? <span className="text-terminal-gray/60 font-normal">—</span>}
      </td>
    </tr>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function FundamentalsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);

  const {
    data,
    isLoading,
    isError,
    error,
  } = useQuery<CompanyFundamentals>({
    queryKey: ['screener/company', symbol],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/screener/company/${encodeURIComponent(symbol)}?consolidated=true`,
      );

      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const json = (await res.json()) as { detail?: string };
          if (json.detail) detail = json.detail;
        } catch {
          // ignore JSON parse errors
        }
        const err = new Error(detail);
        (err as Error & { status: number }).status = res.status;
        throw err;
      }

      return res.json() as Promise<CompanyFundamentals>;
    },
    staleTime: 15 * 60 * 1000,   // 15 min — matches backend TTL
    refetchOnWindowFocus: false,
    retry: false,                 // screener.in auth errors shouldn't be retried
    enabled: !!symbol,
  });

  // ── Loading ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-terminal-gray gap-1">
        <span className="text-terminal-amber/60 animate-pulse">LOADING FUNDAMENTALS...</span>
        <span className="text-white text-[10px]">{symbol}</span>
      </div>
    );
  }

  // ── Error ──────────────────────────────────────────────────────────────────

  if (isError || !data) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    const status = (error as Error & { status?: number })?.status;

    const is503 = status === 503;
    const is404 = status === 404;

    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2 px-4 text-center">
        {is503 ? (
          <>
            <span className="text-terminal-red font-bold uppercase">Session Unavailable</span>
            <span className="text-white text-[10px] leading-relaxed max-w-xs">
              screener.in session not found. Log in at{' '}
              <span className="text-terminal-amber">screener.in</span> in Chrome, then restart
              the backend.
            </span>
          </>
        ) : is404 ? (
          <>
            <span className="text-terminal-red font-bold uppercase">Symbol Not Found</span>
            <span className="text-white text-[10px]">
              {symbol} was not found on screener.in
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

  // ── Data ───────────────────────────────────────────────────────────────────

  const { name, ratios, quarters } = data;

  // Extra quick_ratios: all keys not in the core set
  const extraRatios = Object.entries(ratios).filter(
    ([k]) => !CORE_KEYS_SET.has(k as keyof ScreenerRatios),
  );

  const lynch = calcPeterLynch(ratios);

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase truncate">
          {name || symbol}
        </span>
        <span className="text-white text-[10px] flex-shrink-0">{symbol}</span>
        <span className="ml-auto text-[9px] text-white/60 flex-shrink-0 uppercase tracking-widest">
          Consolidated
        </span>
      </div>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden min-h-0">

        {/* ── Left: Ratios ─────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto border-r border-terminal-gray px-2 py-1 min-w-0">
          <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">
            Key Ratios
          </div>
          <table className="w-full border-collapse">
            <tbody>
              {CORE_RATIO_KEYS.map(({ key, label }) => (
                <RatioRow key={key} label={label} value={ratios[key]} />
              ))}

              {/* Extra quick_ratios */}
              {extraRatios.length > 0 && (
                <>
                  <tr>
                    <td
                      colSpan={2}
                      className="pt-2 pb-1 text-[9px] text-white/50 uppercase tracking-widest border-t border-terminal-gray/30"
                    >
                      More
                    </td>
                  </tr>
                  {extraRatios.map(([key, val]) => (
                    <RatioRow key={key} label={formatRatioLabel(key)} value={val} />
                  ))}
                </>
              )}
            </tbody>
          </table>
        </div>

        {/* ── Right: Quarterly Results ──────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-2 py-1 min-w-0">
          <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">
            Quarterly Results
          </div>

          {quarters.length === 0 ? (
            <span className="text-white text-[10px]">No quarterly data</span>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-[9px] text-white/60 uppercase">
                  <th className="text-left pb-1 font-normal">Period</th>
                  <th className="text-right pb-1 font-normal">Sales</th>
                  <th className="text-right pb-1 font-normal">Net Profit</th>
                  <th className="text-right pb-1 font-normal">EPS</th>
                </tr>
              </thead>
              <tbody>
                {quarters.map((q) => (
                  <tr
                    key={q.period}
                    className="border-b border-terminal-gray/40"
                  >
                    <td className="py-[3px] pr-2 text-white text-[10px] whitespace-nowrap">
                      {q.period}
                    </td>
                    <td className="py-[3px] text-right text-terminal-amber text-[10px] font-bold whitespace-nowrap">
                      {q.sales ?? <span className="text-terminal-gray/60 font-normal">—</span>}
                    </td>
                    <td className="py-[3px] text-right text-[10px] font-bold whitespace-nowrap">
                      {q.net_profit != null ? (
                        <span
                          className={
                            parseFloat(q.net_profit.replace(/,/g, '')) >= 0
                              ? 'text-terminal-green'
                              : 'text-terminal-red'
                          }
                        >
                          {q.net_profit}
                        </span>
                      ) : (
                        <span className="text-terminal-gray/60 font-normal">—</span>
                      )}
                    </td>
                    <td className="py-[3px] text-right text-[10px] font-bold whitespace-nowrap">
                      {q.eps != null ? (
                        <span
                          className={
                            parseFloat(q.eps.replace(/,/g, '')) >= 0
                              ? 'text-terminal-amber'
                              : 'text-terminal-red'
                          }
                        >
                          {q.eps}
                        </span>
                      ) : (
                        <span className="text-terminal-gray/60 font-normal">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* ── Calculated Ratios ──────────────────────────────────────── */}
          <div className="text-[9px] text-white/60 uppercase tracking-widest mt-3 mb-1 border-t border-terminal-gray/40 pt-2">
            Calculated Ratios
          </div>
          <table className="w-full border-collapse">
            <tbody>
              {/* Row 0: Piotroski Score */}
              {(() => {
                const raw = ratios.piotroski_score;
                const score = parseNum(raw);
                const color =
                  score === null ? 'text-white/40' :
                  score >= 7    ? 'text-terminal-green' :
                  score >= 4    ? 'text-terminal-amber' :
                                  'text-terminal-red';
                return (
                  <tr className="border-b border-terminal-gray/40">
                    <td className="py-[3px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                      Piotroski Score
                    </td>
                    <td className="py-[3px] text-right text-[10px] font-mono font-bold whitespace-nowrap">
                      {score !== null ? (
                        <span className={color}>{score.toFixed(0)} / 9</span>
                      ) : (
                        <span className="text-white/40 font-normal text-[9px]">N/A</span>
                      )}
                    </td>
                  </tr>
                );
              })()}

              {/* Row 1: Peter Lynch FV Ratio */}
              <tr className="border-b border-terminal-gray/40">
                <td className="py-[3px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                  Peter Lynch FV Ratio
                </td>
                <td className="py-[3px] text-right text-[10px] font-mono font-bold whitespace-nowrap">
                  {lynch.fairValueRatio !== null ? (
                    <span className="text-terminal-amber">
                      {lynch.fairValueRatio.toFixed(2)}
                    </span>
                  ) : (
                    <span
                      className="text-white/40 font-normal text-[9px] cursor-help"
                      title={`N/A — missing: ${lynch.ratioMissingKey}. Formula: (EPS Growth 5Y% + Div Yield%) / P/E`}
                    >
                      N/A {lynch.ratioMissingKey ? `(no ${lynch.ratioMissingKey})` : ''}
                    </span>
                  )}
                </td>
              </tr>
              <tr className="border-b border-terminal-gray/40">
                <td
                  colSpan={2}
                  className="pb-1 text-[9px] text-white/40 font-mono"
                >
                  = ({lynch.epsGrowth ?? '?'}% growth + {lynch.divYield ?? '0'}% yield) / {lynch.pe ?? '?'} PE
                </td>
              </tr>

              {/* Row 2: Peter Lynch FV Price */}
              <tr className="border-b border-terminal-gray/40">
                <td className="py-[3px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                  Peter Lynch FV
                </td>
                <td className="py-[3px] text-right text-[10px] font-mono font-bold whitespace-nowrap">
                  {lynch.fairValuePrice !== null ? (
                    <span className="text-terminal-amber">
                      ₹{lynch.fairValuePrice.toFixed(2)}
                    </span>
                  ) : (
                    <span
                      className="text-white/40 font-normal text-[9px] cursor-help"
                      title={`N/A — missing: ${lynch.priceMissingKey}. Formula: EPS Growth 5Y% × Latest EPS`}
                    >
                      N/A {lynch.priceMissingKey ? `(no ${lynch.priceMissingKey})` : ''}
                    </span>
                  )}
                </td>
              </tr>
              <tr>
                <td
                  colSpan={2}
                  className="pb-1 text-[9px] text-white/40 font-mono"
                >
                  = {lynch.epsGrowth ?? '?'}% growth × ₹{lynch.latestEps ?? '?'} EPS{lynch.epsKey ? ` [${lynch.epsKey}]` : ''}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

      </div>
    </div>
  );
}

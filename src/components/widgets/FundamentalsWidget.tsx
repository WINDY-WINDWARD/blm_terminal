'use client';

import React, { useState } from 'react';
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

interface DcfAssumptions {
  base_fcf_cr: number | null;
  stage1_growth_pct: number;
  stage2_growth_pct: number;
  terminal_growth_pct: number;
  wacc_pct: number;
  projection_years: number;
}

interface ValuationResult {
  symbol: string;
  cmp: number | null;
  currency: string;
  graham_number: number | null;
  graham_upside_pct: number | null;
  dcf_value: number | null;
  dcf_upside_pct: number | null;
  dcf_assumptions: DcfAssumptions | null;
  ddm_value: number | null;
  ddm_upside_pct: number | null;
  ev_ebitda_value: number | null;
  ev_ebitda_upside_pct: number | null;
  peg_value: number | null;
  peg_upside_pct: number | null;
  fetched_at: string;
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
  'piotroski_score',
]);

// ─── Peter Lynch Fair Value ───────────────────────────────────────────────────

function parseNum(val: string | null | undefined): number | null {
  if (!val) return null;
  const cleaned = val.replace(/[%₹,\s]/g, '').replace(/Cr\.?$/i, '').trim();
  const n = parseFloat(cleaned);
  return isNaN(n) ? null : n;
}

const EPS_GROWTH_KEYS = [
  'eps_growth_5years',
  '5yr_eps_growth',
  '5_yr_eps_growth',
  'eps_5yr_growth',
  'earnings_growth_5years',
  'profit_growth_5years',
];

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

  let epsGrowth: number | null = null;
  for (const key of EPS_GROWTH_KEYS) {
    const val = parseNum(ratios[key]);
    if (val !== null) { epsGrowth = val; break; }
  }

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
        {value ?? <span className="text-white/60 font-normal">—</span>}
      </td>
    </tr>
  );
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1 border-b border-terminal-gray/30 pb-1 sticky top-0 bg-terminal-bg z-10">
      {label}
    </div>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function FundamentalsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const [wacc, setWacc] = useState(0.12);
  const [terminalGrowth, setTerminalGrowth] = useState(0.05);

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
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: !!symbol,
  });

  const { data: msFairValue } = useQuery<number | null>({
    queryKey: ['morningstar/fairvalue', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/morningstar/fairvalue/${encodeURIComponent(symbol)}`);
      if (!res.ok) return null;
      const data = await res.json();
      const fv = data?.fairValue;
      return typeof fv === 'number' ? fv : typeof fv === 'string' ? parseFloat(fv) : null;
    },
    staleTime: 300_000,
    enabled: !!symbol,
  });

  const {
    data: valuationData,
    isLoading: valuationLoading,
    refetch: refetchValuation,
  } = useQuery<ValuationResult>({
    queryKey: ['valuation', symbol, wacc, terminalGrowth],
    queryFn: async () => {
      const res = await fetch(`/api/py/valuation/${encodeURIComponent(symbol)}?wacc=${wacc}&terminal_growth=${terminalGrowth}`);
      if (!res.ok) throw new Error('Valuation fetch failed');
      return res.json();
    },
    enabled: !!symbol,
    staleTime: 1000 * 60 * 30,
  });

  // ── Loading ────────────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-white gap-1">
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

  const extraRatios = Object.entries(ratios).filter(
    ([k]) => !CORE_KEYS_SET.has(k as keyof ScreenerRatios),
  );

  const lynch = calcPeterLynch(ratios);

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">

      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex-shrink-0 border-b border-terminal-gray">
        <div className="px-3 py-1 flex items-baseline gap-2 min-w-0">
          <span className="text-terminal-amber font-bold text-[11px] uppercase truncate">
            {name || symbol}
          </span>
          <span className="text-white text-[10px] flex-shrink-0">{symbol}</span>
          <span className="ml-auto text-[9px] text-white/60 flex-shrink-0 uppercase tracking-widest">
            Consolidated
          </span>
        </div>
      </div>

      {/* ── Scrollable body: all sections ─────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto min-h-0">

        {/* ── Ratios ──────────────────────────────────────────────────────── */}
        <div className="px-2 py-1">
          <SectionHeader label="Key Ratios" />
          <div className="flex gap-2">
            <div className="flex-1 min-w-0">
              <table className="w-full border-collapse">
                <tbody>
                  {CORE_RATIO_KEYS.map(({ key, label }) => (
                    <RatioRow key={key} label={label} value={ratios[key]} />
                  ))}
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

            <div className="flex-1 min-w-0">
              <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">
                Calculated Ratios
              </div>
              <table className="w-full border-collapse">
                <tbody>
                  {/* Piotroski Score */}
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

                  {/* Peter Lynch FV Ratio */}
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

                  {/* Peter Lynch FV Price */}
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

                  {/* Morningstar Fair Value */}
                  <tr className="border-b border-terminal-gray/40">
                    <td className="py-[3px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                      MS Fair Value
                    </td>
                    <td className="py-[3px] text-right text-[10px] font-mono font-bold whitespace-nowrap">
                      {msFairValue != null ? (
                        <span className="text-terminal-amber">₹{msFairValue.toFixed(2)}</span>
                      ) : (
                        <span className="text-white/40 font-normal">—</span>
                      )}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* ── Quarterly Results ────────────────────────────────────────────── */}
        <div className="px-2 py-1 border-t border-terminal-gray/30">
          <SectionHeader label="Quarterly Results" />
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
                      {q.sales ?? <span className="text-white/60 font-normal">—</span>}
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
                        <span className="text-white/60 font-normal">—</span>
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
                        <span className="text-white/60 font-normal">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Valuation ────────────────────────────────────────────────────── */}
        <div className="px-2 py-1 border-t border-terminal-gray/30">
          <SectionHeader label="Valuation Models" />
          {/* Controls */}
          <div className="flex items-center gap-2 text-[10px] text-white/40 mb-1">
            <span>WACC</span>
            <select
              value={wacc}
              onChange={(e) => setWacc(parseFloat(e.target.value))}
              className="bg-white/5 border border-white/10 rounded px-1 py-0.5 text-white/70 text-[10px]"
            >
              {[0.10, 0.11, 0.12, 0.13, 0.14, 0.15].map((v) => (
                <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>
              ))}
            </select>
            <span>Terminal g</span>
            <select
              value={terminalGrowth}
              onChange={(e) => setTerminalGrowth(parseFloat(e.target.value))}
              className="bg-white/5 border border-white/10 rounded px-1 py-0.5 text-white/70 text-[10px]"
            >
              {[0.03, 0.04, 0.05, 0.06, 0.07].map((v) => (
                <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>
              ))}
            </select>
            <button
              onClick={() => refetchValuation()}
              className="ml-auto text-[9px] px-1.5 py-0.5 border border-white/10 rounded hover:bg-white/5 text-white/50 hover:text-white/80 transition-colors"
            >
              Refresh
            </button>
          </div>

          {valuationLoading ? (
            <div className="text-white/30 text-[11px]">Loading valuation models...</div>
          ) : valuationData ? (
            <>
              <div className="text-[10px] text-white/30">CMP: ₹{valuationData.cmp?.toLocaleString('en-IN')}</div>
              <table className="w-full text-[11px]">
                <thead>
                  <tr className="text-white/30 text-left">
                    <th className="pb-1">Model</th>
                    <th className="pb-1 text-right">Fair Value</th>
                    <th className="pb-1 text-right">vs CMP</th>
                    <th className="pb-1 text-right">Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: 'Graham Number', value: valuationData.graham_number, upside: valuationData.graham_upside_pct },
                    { label: 'DCF (10Y)', value: valuationData.dcf_value, upside: valuationData.dcf_upside_pct },
                    { label: 'DDM', value: valuationData.ddm_value, upside: valuationData.ddm_upside_pct },
                    { label: 'EV/EBITDA (12x)', value: valuationData.ev_ebitda_value, upside: valuationData.ev_ebitda_upside_pct },
                    { label: 'PEG Fair Value', value: valuationData.peg_value, upside: valuationData.peg_upside_pct },
                  ].map((row) => {
                    const signal = row.upside === null ? null : row.upside > 15 ? 'UNDERVALUED' : row.upside < -15 ? 'OVERVALUED' : 'FAIR';
                    const signalColor = signal === 'UNDERVALUED' ? 'text-green-400' : signal === 'OVERVALUED' ? 'text-red-400' : 'text-yellow-400';
                    return (
                      <tr key={row.label} className="border-t border-white/5">
                        <td className="py-1 text-white/60">{row.label}</td>
                        <td className="py-1 text-right text-white/80">
                          {row.value !== null ? `₹${row.value.toLocaleString('en-IN')}` : '—'}
                        </td>
                        <td className={'py-1 text-right ' + (row.upside !== null ? (row.upside > 0 ? 'text-green-400' : 'text-red-400') : 'text-white/30')}>
                          {row.upside !== null ? `${row.upside > 0 ? '+' : ''}${row.upside.toFixed(1)}%` : '—'}
                        </td>
                        <td className={'py-1 text-right font-medium ' + signalColor}>
                          {signal ?? '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              {valuationData.dcf_assumptions && (
                <div className="text-[9px] text-white/25 mt-1 border-t border-white/5 pt-1">
                  DCF: Stage1 {valuationData.dcf_assumptions.stage1_growth_pct}% →
                  Stage2 {valuationData.dcf_assumptions.stage2_growth_pct}% →
                  Terminal {valuationData.dcf_assumptions.terminal_growth_pct}% |
                  WACC {valuationData.dcf_assumptions.wacc_pct}%
                  {valuationData.dcf_assumptions.base_fcf_cr !== null &&
                    ` | Base FCF ₹${valuationData.dcf_assumptions.base_fcf_cr.toFixed(0)}Cr`}
                </div>
              )}
            </>
          ) : (
            <div className="text-white/30 text-[11px]">No valuation data available</div>
          )}
        </div>

      </div>
    </div>
  );
}

'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchTradingViewFundamentals, type TradingViewFundamentals } from '@/lib/tradingview';
import { fetchNseMarketRatios, fetchIinvestAll, type NseMarketRatios, type IinvestAllResponse } from '@/lib/iinvest';
import { ShareholdingTable, type ScreenerCompanyData } from './ShareholdingTable';
import { IinvestGenericTable, type IinvestColumn } from './IinvestGenericTable';
import { TradingViewPanel } from '../TradingViewPanel';

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

interface CompanyFundamentals extends ScreenerCompanyData {
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

const CORE_RATIO_KEYS: { key: keyof ScreenerRatios; label: string }[] = [
  { key: 'market_cap',     label: 'Market Cap'    },
  { key: 'price',          label: 'Current Price' },
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

// ─── Peter Lynch Helpers ──────────────────────────────────────────────────────

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
  upsidePct: number | null;
  epsGrowth: number | null;
  growthSource: string;
  latestEps: number | null;
  divYield: number | null;
  pe: number | null;
  cmp: number | null;
  epsKey: string | null;
}

function calcPeterLynch(
  ratios: ScreenerRatios,
  quarters: ScreenerQuarter[],
  tvData?: TradingViewFundamentals | null,
  valuationData?: ValuationResult | null,
  nseRatios?: NseMarketRatios | null,
  customGrowth?: number | null
): PeterLynchResult {
  const cmp      = parseNum(ratios.price) ?? valuationData?.cmp ?? null;
  const pe       = tvData?.price_earnings_ttm ?? parseNum(ratios.pe) ?? nseRatios?.symbol_pe ?? null;
  const divYield = tvData?.dividends_yield ?? parseNum(ratios.dividend_yield) ?? 0;

  let epsGrowth: number | null = null;
  let growthSource = 'Auto';

  if (customGrowth !== null && customGrowth !== undefined) {
    epsGrowth = customGrowth;
    growthSource = 'Custom';
  } else {
    for (const key of [...EPS_GROWTH_KEYS, 'profit_growth', 'sales_growth']) {
      const val = parseNum(ratios[key]);
      if (val !== null && val > 0) {
        epsGrowth = val;
        growthSource = 'Screener';
        break;
      }
    }
    if (epsGrowth === null && valuationData?.dcf_assumptions?.stage1_growth_pct != null) {
      epsGrowth = valuationData.dcf_assumptions.stage1_growth_pct;
      growthSource = 'DCF Stage 1';
    }
    if (epsGrowth === null && quarters.length >= 2) {
      const newestEps = parseNum(quarters[0]?.eps);
      const oldestEps = parseNum(quarters[quarters.length - 1]?.eps);
      if (newestEps !== null && oldestEps !== null && oldestEps > 0 && newestEps > oldestEps) {
        const rawPct = ((newestEps - oldestEps) / oldestEps) * 100;
        epsGrowth = Math.min(35, Math.max(5, rawPct));
        growthSource = 'Qtr Trend';
      }
    }
    if (epsGrowth === null) {
      epsGrowth = 15.0;
      growthSource = 'Std 15%';
    }
  }

  let latestEps: number | null = tvData?.earnings_per_share_basic_ttm ?? null;
  let epsKey: string | null = latestEps !== null ? 'TV TTM' : null;

  if (latestEps === null) {
    for (const key of EPS_KEYS) {
      const val = parseNum(ratios[key]);
      if (val !== null) { latestEps = val; epsKey = 'Screener'; break; }
    }
  }
  if (latestEps === null && quarters.length >= 4) {
    const qEps = quarters.slice(0, 4).map((q) => parseNum(q.eps));
    if (qEps.every((v): v is number => v !== null)) {
      latestEps = qEps.reduce((acc, v) => acc + v, 0);
      epsKey = '4Q TTM';
    }
  }
  if (latestEps === null && cmp !== null && pe !== null && pe > 0) {
    latestEps = cmp / pe;
    epsKey = 'Implied';
  }

  const fairValueRatio =
    pe !== null && pe > 0 && epsGrowth !== null
      ? (epsGrowth + (divYield ?? 0)) / pe
      : null;

  const fairValuePrice =
    epsGrowth !== null && latestEps !== null
      ? epsGrowth * latestEps
      : null;

  const upsidePct =
    fairValuePrice !== null && cmp !== null && cmp > 0
      ? ((fairValuePrice - cmp) / cmp) * 100
      : null;

  return { fairValueRatio, fairValuePrice, upsidePct, epsGrowth, growthSource, latestEps, divYield, pe, cmp, epsKey };
}

function formatRatioLabel(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

// ─── Bento UI Component ───────────────────────────────────────────────────────

function BentoCard({
  children,
  className = '',
  title,
  badge,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
  badge?: React.ReactNode;
}) {
  return (
    <div
      className={`bg-[#09090b] border border-[#27272a] rounded p-3 flex flex-col justify-between transition-colors duration-200 hover:bg-zinc-900/80 ${className}`}
    >
      {(title || badge) && (
        <div className="flex items-center justify-between mb-2">
          {title && (
            <span className="text-[10px] uppercase font-mono tracking-wider text-zinc-400 font-semibold">
              {title}
            </span>
          )}
          {badge}
        </div>
      )}
      {children}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function FundamentalsTab({ symbol }: { symbol: string }) {
  const [wacc, setWacc] = useState(0.12);
  const [terminalGrowth, setTerminalGrowth] = useState(0.04);
  const [showMoreRatios, setShowMoreRatios] = useState(false);
  const [customLynchGrowth, setCustomLynchGrowth] = useState<number | null>(null);

  // 1. Screener company data
  const {
    data,
    isLoading,
    isError,
    error,
  } = useQuery<CompanyFundamentals>({
    queryKey: ['screener/company', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/screener/company/${encodeURIComponent(symbol)}?consolidated=true`);
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
      return res.json() as Promise<CompanyFundamentals>;
    },
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
    enabled: !!symbol,
  });

  // 2. Morningstar Fair Value
  const { data: msFairValue } = useQuery<number | null>({
    queryKey: ['morningstar/fairvalue', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/morningstar/fairvalue/${encodeURIComponent(symbol)}`);
      if (!res.ok) return null;
      const json = await res.json();
      const fv = json?.fairValue;
      return typeof fv === 'number' ? fv : typeof fv === 'string' ? parseFloat(fv) : null;
    },
    staleTime: 300_000,
    enabled: !!symbol,
  });

  // 3. Intrinsic Valuation Models
  const {
    data: valuationData,
    isLoading: valuationLoading,
    refetch: refetchValuation,
  } = useQuery<ValuationResult>({
    queryKey: ['valuation', symbol, wacc, terminalGrowth],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/valuation/${encodeURIComponent(symbol)}?wacc=${wacc}&terminal_growth=${terminalGrowth}`
      );
      if (!res.ok) throw new Error('Valuation fetch failed');
      return res.json();
    },
    enabled: !!symbol,
    staleTime: 1000 * 60 * 30,
  });

  // 4. TradingView Fundamentals
  const { data: tradingViewData } = useQuery({
    queryKey: ['tradingview', symbol],
    queryFn: () => fetchTradingViewFundamentals(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  // 5. Market Sectors & NSE Ratios for Industry Context
  const { data: nseRatios } = useQuery<NseMarketRatios | null>({
    queryKey: ['stockuniverse-ratios', symbol],
    queryFn: () => fetchNseMarketRatios(symbol).catch(() => null),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
  });
  const companySector = data?.ratios?.sector || nseRatios?.industry || null;
  const { data: sectors } = useQuery<Array<{ name: string; pe?: number | null; advance: number; decline: number }>>({
    queryKey: ['market/categories-context'],
    queryFn: async () => {
      const [secRes, indRes] = await Promise.all([
        fetch('/api/py/markets/sectors'),
        fetch('/api/py/markets/industries'),
      ]);
      const sec = secRes.ok ? await secRes.json() : [];
      const ind = indRes.ok ? await indRes.json() : [];
      return [...(Array.isArray(sec) ? sec : []), ...(Array.isArray(ind) ? ind : [])];
    },
    staleTime: 5 * 60 * 1000,
  });
  const sectorMatch = sectors?.find((s) => s.name?.toLowerCase() === companySector?.toLowerCase()) || null;
  const resolvedSectorPe = sectorMatch?.pe ?? nseRatios?.sector_pe ?? null;

  // 6. Shareholding & Pledged Shares (via iinvest aggregator)
  const { data: iinvestAllData, isLoading: isIinvestLoading } = useQuery<IinvestAllResponse>({
    queryKey: ['iinvest/all', symbol],
    queryFn: () => fetchIinvestAll(symbol).catch(() => ({} as IinvestAllResponse)),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const shareholderData = iinvestAllData?.key_shareholders;
  const pledgedData = iinvestAllData?.pledged_shares;
  const pledgedCount = Array.isArray(pledgedData?.response?.data)
    ? pledgedData.response.data.length
    : 0;

  // ── Loading State ───────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-white gap-2 bg-black">
        <div className="w-6 h-6 border-2 border-terminal-amber border-t-transparent rounded-full animate-spin"></div>
        <span className="text-terminal-amber/80 tracking-widest text-[11px] animate-pulse">
          INITIALIZING BENTO MATRIX...
        </span>
        <span className="text-zinc-400 text-xs">{symbol}</span>
      </div>
    );
  }

  // ── Error Fallback ──────────────────────────────────────────────────────────
  if (isError || !data) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    const status = (error as Error & { status?: number })?.status;

    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-3 p-6 text-center bg-black">
        <div className="p-4 border border-[#27272a] bg-[#09090b] rounded max-w-md w-full">
          <div className="text-terminal-red font-bold uppercase text-sm mb-1">
            {status === 503 ? 'Screener Session Unavailable' : status === 404 ? 'Symbol Not Found' : 'Fetch Failed'}
          </div>
          <div className="text-zinc-300 text-xs leading-relaxed mb-3">
            {status === 503 ? (
              <>
                Screener data is currently unreachable. You can still inspect official filings, NSE ratios, and corporate actions in the new{' '}
                <span className="text-terminal-amber font-semibold">Corporate</span> tab above.
              </>
            ) : (
              `${symbol}: ${errMsg}`
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Data Destructuring ──────────────────────────────────────────────────────
  const { name, ratios, quarters } = data;

  const extraRatios = Object.entries(ratios).filter(
    ([k]) => !CORE_KEYS_SET.has(k as keyof ScreenerRatios) && ratios[k] != null
  );

  const lynch = calcPeterLynch(ratios, quarters, tradingViewData, valuationData, nseRatios, customLynchGrowth);

  // Piotroski score parse
  const piotroskiScore = parseNum(ratios.piotroski_score);
  const piotroskiColor =
    piotroskiScore !== null
      ? piotroskiScore >= 7
        ? 'text-terminal-green'
        : piotroskiScore >= 4
        ? 'text-terminal-amber'
        : 'text-terminal-red'
      : 'text-zinc-300';

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-black">
      {/* Header Bar */}
      <div className="flex-shrink-0 border-b border-[#27272a] bg-[#09090b] px-3 py-1.5 flex items-center justify-between">
        <div className="flex items-center gap-2 truncate">
          <span className="text-terminal-amber font-bold text-sm tracking-wide truncate">
            {name || symbol}
          </span>
          <span className="text-zinc-300 text-xs font-semibold">{symbol}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-[10px] text-zinc-400 uppercase tracking-widest border border-zinc-800 rounded px-1.5 py-0.5">
            Bento Matrix
          </span>
          <span className="text-[10px] text-zinc-400 uppercase tracking-widest">
            Consolidated
          </span>
        </div>
      </div>

      {/* Bento Grid Body */}
      <div className="flex-1 overflow-y-auto p-2.5">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-2.5 max-w-full">

          {/* ── Row 2-4: Core Financial Metrics (Bento Cards) ──────────────── */}

          {/* Market Cap (Double Width) */}
          <BentoCard
            title="Market Capitalization"
            className="col-span-1 md:col-span-2 lg:col-span-2"
          >
            <div>
              <div className="text-lg font-bold text-terminal-amber tracking-tight">
                {ratios.market_cap ? (ratios.market_cap.includes('₹') ? ratios.market_cap : `₹${ratios.market_cap}`) : '—'}
              </div>
              <div className="text-[10px] text-zinc-300 mt-0.5 uppercase tracking-wider">
                Full Float Capitalization
              </div>
            </div>
          </BentoCard>

          {/* Current Price */}
          <BentoCard
            title="Current Price"
            className="col-span-1"
          >
            <div>
              <div className="text-lg font-bold text-white tracking-tight">
                {ratios.price ? (ratios.price.includes('₹') ? ratios.price : `₹${ratios.price}`) : '—'}
              </div>
              <div className="text-[10px] text-zinc-300 mt-0.5 uppercase tracking-wider">
                Consolidated CMP
              </div>
            </div>
          </BentoCard>

          {/* P/E Ratio */}
          <BentoCard title="P/E Ratio" className="col-span-1">
            <div className="text-base font-bold text-white">
              {ratios.pe ?? '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">Price to Earnings</div>
          </BentoCard>

          {/* Book Value */}
          <BentoCard title="Book Value" className="col-span-1">
            <div className="text-base font-bold text-white">
              {ratios.book_value ? (ratios.book_value.includes('₹') ? ratios.book_value : `₹${ratios.book_value}`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">Per Share Value</div>
          </BentoCard>

          {/* ROCE */}
          <BentoCard title="ROCE" className="col-span-1">
            <div className="text-base font-bold text-terminal-green">
              {ratios.roce ? (ratios.roce.includes('%') ? ratios.roce : `${ratios.roce}%`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">Return on Cap. Emp.</div>
          </BentoCard>

          {/* ROE */}
          <BentoCard title="ROE" className="col-span-1">
            <div className="text-base font-bold text-terminal-green">
              {ratios.roe ? (ratios.roe.includes('%') ? ratios.roe : `${ratios.roe}%`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">Return on Equity</div>
          </BentoCard>

          {/* 52W High */}
          <BentoCard title="52W High" className="col-span-1">
            <div className="text-base font-bold text-emerald-400">
              {ratios.high_52w ? (ratios.high_52w.includes('₹') ? ratios.high_52w : `₹${ratios.high_52w}`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">1-Year Peak</div>
          </BentoCard>

          {/* 52W Low */}
          <BentoCard title="52W Low" className="col-span-1">
            <div className="text-base font-bold text-rose-400">
              {ratios.low_52w ? (ratios.low_52w.includes('₹') ? ratios.low_52w : `₹${ratios.low_52w}`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">1-Year Trough</div>
          </BentoCard>

          {/* Dividend Yield */}
          <BentoCard title="Dividend Yield" className="col-span-1">
            <div className="text-base font-bold text-white">
              {ratios.dividend_yield ? (ratios.dividend_yield.includes('%') ? ratios.dividend_yield : `${ratios.dividend_yield}%`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">Annual Payout Rate</div>
          </BentoCard>

          {/* Face Value */}
          <BentoCard title="Face Value" className="col-span-1">
            <div className="text-base font-bold text-white">
              {ratios.face_value ? (ratios.face_value.includes('₹') ? ratios.face_value : `₹${ratios.face_value}`) : '—'}
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">Par Value</div>
          </BentoCard>

          {/* Piotroski Score */}
          <BentoCard
            title="Piotroski Score"
            className="col-span-1"
            badge={
              <span className={`text-[10px] font-bold ${piotroskiColor}`}>
                {piotroskiScore !== null ? (piotroskiScore >= 7 ? 'STRONG' : piotroskiScore >= 4 ? 'MODERATE' : 'WEAK') : '—'}
              </span>
            }
          >
            <div
              className="flex items-baseline gap-1.5 cursor-help"
              title="Piotroski F-Score (0-9): Audited accounting test across Profitability, Leverage, Liquidity, and Operating Efficiency"
            >
              <span className={`text-base font-bold ${piotroskiColor}`}>
                {piotroskiScore !== null ? piotroskiScore.toFixed(0) : '—'}
              </span>
              <span className="text-zinc-400 text-xs font-semibold">/ 9</span>
            </div>
            <div className="text-[10px] text-zinc-300 mt-0.5">
              Accounting Health
            </div>
          </BentoCard>

          {/* ── Additional Screener Ratios (Collapsible Card) ─────────────── */}
          {extraRatios.length > 0 && (
            <BentoCard
              title="Extended Screener Metrics"
              className="col-span-1 md:col-span-2 lg:col-span-4"
              badge={
                <button
                  onClick={() => setShowMoreRatios(!showMoreRatios)}
                  className="text-[10px] text-terminal-amber hover:underline uppercase"
                >
                  {showMoreRatios ? 'Hide Metrics ▲' : `Show ${extraRatios.length} Metrics ▼`}
                </button>
              }
            >
              {showMoreRatios ? (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2 pt-2 border-t border-[#27272a] mt-1">
                  {extraRatios.map(([key, val]) => (
                    <div key={key} className="bg-black/40 border border-[#27272a]/40 rounded p-2">
                      <div className="text-[9px] text-zinc-400 uppercase truncate" title={formatRatioLabel(key)}>
                        {formatRatioLabel(key)}
                      </div>
                      <div className="text-xs font-semibold text-white mt-0.5 truncate">
                        {val || '—'}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[11px] text-zinc-400">
                  {extraRatios.length} additional fundamental balance sheet and cash flow metrics available.
                </div>
              )}
            </BentoCard>
          )}

          {/* ── Row 5-6: Advanced Valuation Models ────────────────────────── */}

          {/* Peter Lynch Fair Value (col-span-2) */}
          <BentoCard
            title="Peter Lynch Valuation"
            className="col-span-1 md:col-span-2 lg:col-span-2"
            badge={
              lynch.fairValueRatio !== null ? (
                <span
                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                    lynch.fairValueRatio >= 1.5
                      ? 'bg-terminal-green/10 text-terminal-green border-terminal-green/30'
                      : lynch.fairValueRatio >= 1.0
                      ? 'bg-terminal-amber/10 text-terminal-amber border-terminal-amber/30'
                      : 'bg-terminal-red/10 text-terminal-red border-terminal-red/30'
                  }`}
                >
                  {lynch.fairValueRatio >= 1.5
                    ? 'UNDERVALUED'
                    : lynch.fairValueRatio >= 1.0
                    ? 'FAIR VALUE'
                    : 'OVERVALUED'}
                </span>
              ) : null
            }
          >
            <div className="space-y-2.5">
              {/* Growth Assumption Selector */}
              <div className="flex items-center justify-between gap-2 bg-black/50 p-2 rounded border border-[#27272a]/60">
                <div>
                  <div className="text-[9px] text-zinc-400 uppercase">Growth Rate</div>
                  <div className="text-[11px] font-semibold text-white">
                    {lynch.epsGrowth !== null ? `${lynch.epsGrowth.toFixed(1)}%` : '—'}{' '}
                    <span className="text-[9px] text-terminal-amber/80 uppercase">[{lynch.growthSource}]</span>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  {[null, 10, 15, 20, 25].map((preset) => {
                    const isActive = customLynchGrowth === preset;
                    return (
                      <button
                        key={preset === null ? 'auto' : preset}
                        onClick={() => setCustomLynchGrowth(preset)}
                        className={`px-1.5 py-0.5 rounded text-[10px] font-mono border transition-colors ${
                          isActive
                            ? 'bg-terminal-amber text-black border-terminal-amber font-bold'
                            : 'bg-[#09090b] text-zinc-300 border-[#27272a] hover:border-zinc-600 hover:text-white'
                        }`}
                      >
                        {preset === null ? 'AUTO' : `${preset}%`}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Primary KPIs: Fair Value Ratio & Target Fair Value */}
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-black/40 border border-[#27272a]/50 rounded p-2.5">
                  <div className="text-[10px] text-zinc-400 uppercase">Lynch Ratio (PEG Inv.)</div>
                  <div className="flex items-baseline gap-1.5 mt-0.5">
                    <span
                      className={`text-lg font-bold ${
                        lynch.fairValueRatio !== null
                          ? lynch.fairValueRatio >= 1.5
                            ? 'text-terminal-green'
                            : lynch.fairValueRatio >= 1.0
                            ? 'text-terminal-amber'
                            : 'text-terminal-red'
                          : 'text-zinc-300'
                      }`}
                    >
                      {lynch.fairValueRatio !== null ? `${lynch.fairValueRatio.toFixed(2)}x` : '—'}
                    </span>
                    <span className="text-[10px] text-zinc-400">/ 1.0x par</span>
                  </div>
                </div>

                <div className="bg-black/40 border border-[#27272a]/50 rounded p-2.5 text-right">
                  <div className="text-[10px] text-zinc-400 uppercase">Target Fair Value</div>
                  <div className="flex items-baseline justify-end gap-1.5 mt-0.5">
                    <span className="text-lg font-bold text-white">
                      {lynch.fairValuePrice !== null
                        ? `₹${lynch.fairValuePrice.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
                        : '—'}
                    </span>
                    {lynch.upsidePct !== null && (
                      <span
                        className={`text-[11px] font-bold ${
                          lynch.upsidePct >= 0 ? 'text-terminal-green' : 'text-terminal-red'
                        }`}
                      >
                        {lynch.upsidePct >= 0 ? '+' : ''}
                        {lynch.upsidePct.toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* 4-Metric Input Breakdown Grid */}
              <div className="grid grid-cols-4 gap-1.5 text-center bg-black/30 p-2 rounded border border-[#27272a]/40">
                <div>
                  <div className="text-[9px] text-zinc-400 uppercase">EPS Growth</div>
                  <div className="text-xs font-bold text-terminal-amber mt-0.5">
                    {lynch.epsGrowth !== null ? `${lynch.epsGrowth.toFixed(1)}%` : '—'}
                  </div>
                </div>
                <div className="border-l border-[#27272a]/50">
                  <div className="text-[9px] text-zinc-400 uppercase">Div Yield</div>
                  <div className="text-xs font-bold text-white mt-0.5">
                    {lynch.divYield !== null ? `${lynch.divYield.toFixed(2)}%` : '0.00%'}
                  </div>
                </div>
                <div className="border-l border-[#27272a]/50">
                  <div className="text-[9px] text-zinc-400 uppercase">P/E Ratio</div>
                  <div className="text-xs font-bold text-white mt-0.5">
                    {lynch.pe !== null ? `${lynch.pe.toFixed(2)}x` : '—'}
                  </div>
                </div>
                <div className="border-l border-[#27272a]/50">
                  <div className="text-[9px] text-zinc-400 uppercase">
                    EPS {lynch.epsKey ? `(${lynch.epsKey})` : ''}
                  </div>
                  <div className="text-xs font-bold text-white mt-0.5">
                    {lynch.latestEps !== null ? `₹${lynch.latestEps.toFixed(2)}` : '—'}
                  </div>
                </div>
              </div>

              {/* Morningstar Benchmark Footer */}
              <div className="flex items-center justify-between pt-1 border-t border-[#27272a]/40">
                <span className="text-[10px] text-zinc-400 uppercase">Morningstar Fair Value</span>
                {msFairValue != null ? (
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-terminal-amber">
                      ₹{msFairValue.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </span>
                    {lynch.cmp !== null && lynch.cmp > 0 && (
                      <span
                        className={`text-[10px] font-bold ${
                          msFairValue >= lynch.cmp ? 'text-terminal-green' : 'text-terminal-red'
                        }`}
                      >
                        {msFairValue >= lynch.cmp ? '+' : ''}
                        {(((msFairValue - lynch.cmp) / lynch.cmp) * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                ) : (
                  <span className="text-xs text-zinc-400">—</span>
                )}
              </div>
            </div>
          </BentoCard>

          {/* Intrinsic Valuation Matrix (col-span-2) */}
          <BentoCard
            title="Intrinsic Valuation Matrix"
            className="col-span-1 md:col-span-2 lg:col-span-2"
            badge={
              valuationData?.cmp != null && (
                <span className="text-[10px] text-zinc-300 font-semibold">
                  CMP: ₹{valuationData.cmp.toLocaleString('en-IN')}
                </span>
              )
            }
          >
            <div className="space-y-2">
              {/* Controls */}
              <div className="grid grid-cols-2 gap-2 bg-black/50 p-2 rounded border border-[#27272a]/60">
                <div>
                  <div className="text-[9px] text-zinc-400 uppercase mb-0.5">WACC</div>
                  <select
                    value={wacc}
                    onChange={(e) => setWacc(parseFloat(e.target.value))}
                    className="w-full bg-[#09090b] border border-[#27272a] rounded px-1.5 py-0.5 text-white text-[11px] outline-none"
                  >
                    {[0.10, 0.11, 0.12, 0.13, 0.14, 0.15].map((v) => (
                      <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>
                    ))}
                  </select>
                </div>
                <div>
                  <div className="text-[9px] text-zinc-400 uppercase mb-0.5">Terminal Growth</div>
                  <div className="flex items-center gap-1">
                    <select
                      value={terminalGrowth}
                      onChange={(e) => setTerminalGrowth(parseFloat(e.target.value))}
                      className="w-full bg-[#09090b] border border-[#27272a] rounded px-1.5 py-0.5 text-white text-[11px] outline-none"
                    >
                      {[0.03, 0.04, 0.05, 0.06, 0.07].map((v) => (
                        <option key={v} value={v}>{(v * 100).toFixed(0)}%</option>
                      ))}
                    </select>
                    <button
                      onClick={() => refetchValuation()}
                      className="px-1.5 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10px] rounded border border-zinc-700 transition-colors"
                      title="Recalculate models"
                    >
                      ↺
                    </button>
                  </div>
                </div>
              </div>

              {/* Models Table */}
              {valuationLoading ? (
                <div className="text-zinc-400 text-xs py-2 text-center animate-pulse">
                  CALCULATING INTRINSIC MODELS...
                </div>
              ) : valuationData ? (
                (() => {
                  const validModels = [
                    { label: 'Graham Number', value: valuationData.graham_number, upside: valuationData.graham_upside_pct },
                    { label: 'DCF (10Y)', value: valuationData.dcf_value, upside: valuationData.dcf_upside_pct },
                    { label: 'DDM', value: valuationData.ddm_value, upside: valuationData.ddm_upside_pct },
                    { label: 'EV/EBITDA', value: valuationData.ev_ebitda_value, upside: valuationData.ev_ebitda_upside_pct },
                    { label: 'PEG Fair Value', value: valuationData.peg_value, upside: valuationData.peg_upside_pct },
                  ].filter((row) => row.value !== null);

                  if (validModels.length === 0) {
                    return <div className="text-zinc-400 text-xs py-2">No valuation models available</div>;
                  }

                  return (
                    <table className="w-full border-collapse font-mono text-[11px]">
                      <thead>
                        <tr className="border-b border-[#27272a] text-zinc-400 text-[9px] uppercase">
                          <th className="text-left pb-1 font-normal">Model</th>
                          <th className="text-right pb-1 font-normal">Target</th>
                          <th className="text-right pb-1 font-normal">Upside</th>
                        </tr>
                      </thead>
                      <tbody>
                        {validModels.map((row) => (
                          <tr key={row.label} className="border-b border-[#27272a]/30">
                            <td className="py-1 text-zinc-200 whitespace-nowrap">{row.label}</td>
                            <td className="py-1 text-right text-white font-semibold whitespace-nowrap">
                              ₹{row.value !== null ? row.value.toLocaleString('en-IN') : '—'}
                            </td>
                            <td
                              className={
                                'py-1 text-right font-bold whitespace-nowrap ' +
                                (row.upside !== null
                                  ? row.upside > 0
                                    ? 'text-terminal-green'
                                    : 'text-terminal-red'
                                  : 'text-zinc-400')
                              }
                            >
                              {row.upside !== null ? `${row.upside > 0 ? '+' : ''}${row.upside.toFixed(1)}%` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  );
                })()
              ) : (
                <div className="text-zinc-400 text-xs py-2">Valuation data unavailable</div>
              )}

              {valuationData?.dcf_assumptions && (
                <div className="text-[10px] text-zinc-400 pt-1 border-t border-[#27272a]/40">
                  DCF: Stage1 {valuationData.dcf_assumptions.stage1_growth_pct}% → Stage2 {valuationData.dcf_assumptions.stage2_growth_pct}% → Term {valuationData.dcf_assumptions.terminal_growth_pct}%
                </div>
              )}
            </div>
          </BentoCard>

          {/* ── TradingView Panel (Full Width if available) ───────────────── */}
          {tradingViewData && (
            <BentoCard title="TradingView Quantitative Fundamentals" className="col-span-1 md:col-span-2 lg:col-span-4 overflow-x-auto">
              <TradingViewPanel data={tradingViewData} />
            </BentoCard>
          )}

          {/* ── Row 1: Industry Context Snippet (Full Width) ──────────────── */}
          {companySector && (
            <BentoCard
              title="Industry Context"
              className="col-span-1 md:col-span-2 lg:col-span-4"
              badge={
                sectorMatch && (
                  <span className="text-[10px] text-zinc-300">
                    Advance/Decline: {(sectorMatch.advance / (sectorMatch.decline || 1)).toFixed(2)}
                  </span>
                )
              }
            >
              <div className="flex flex-wrap items-center justify-between gap-4 pt-1">
                <div>
                  <div className="text-[10px] text-zinc-400 uppercase">Assigned Sector / Industry</div>
                  <div className="text-sm font-bold text-terminal-amber">{companySector}</div>
                </div>
                <div>
                  <div className="text-[10px] text-zinc-400 uppercase">Sector P/E</div>
                  <div className="text-sm font-bold text-white">
                    {resolvedSectorPe != null ? resolvedSectorPe.toFixed(2) : '—'}
                  </div>
                </div>
                {sectorMatch && (
                  <div>
                    <div className="text-[10px] text-zinc-400 uppercase">Sector Breadth</div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-xs text-terminal-green font-bold">▲ {sectorMatch.advance}</span>
                      <span className="text-zinc-300">/</span>
                      <span className="text-xs text-terminal-red font-bold">▼ {sectorMatch.decline}</span>
                    </div>
                  </div>
                )}
              </div>
            </BentoCard>
          )}

          {/* ── Row 7: Quarterly Financial Performance (Full Width) ──────── */}
          <BentoCard
            title="Quarterly Performance Trend"
            className="col-span-1 md:col-span-2 lg:col-span-4"
          >
            {quarters.length === 0 ? (
              <div className="text-zinc-400 text-xs py-2">No quarterly records available.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse font-mono text-xs">
                  <thead>
                    <tr className="border-b border-[#27272a] text-zinc-400 text-[10px] uppercase">
                      <th className="text-left pb-1.5 font-normal">Period</th>
                      <th className="text-right pb-1.5 font-normal">Sales</th>
                      <th className="text-right pb-1.5 font-normal">Net Profit</th>
                      <th className="text-right pb-1.5 font-normal">EPS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quarters.map((q) => (
                      <tr key={q.period} className="border-b border-[#27272a]/40 hover:bg-white/[0.02]">
                        <td className="py-1.5 pr-2 text-zinc-200 font-semibold whitespace-nowrap">
                          {q.period}
                        </td>
                        <td className="py-1.5 text-right text-terminal-amber font-semibold whitespace-nowrap">
                          {q.sales ?? '—'}
                        </td>
                        <td className="py-1.5 text-right font-semibold whitespace-nowrap">
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
                            '—'
                          )}
                        </td>
                        <td className="py-1.5 text-right font-semibold whitespace-nowrap">
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
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </BentoCard>


          {/* ── Shareholding Pattern (Full Width) ──────────────────────────── */}
          <BentoCard
            title="Shareholding Pattern"
            className="col-span-1 md:col-span-2 lg:col-span-4"
            badge={
              <span className="text-[10px] text-zinc-300 uppercase">
                Promoter · FII · DII · Public
              </span>
            }
          >
            {isIinvestLoading ? (
              <div className="py-6 flex items-center justify-center font-mono text-xs text-terminal-amber animate-pulse">
                LOADING SHAREHOLDING PATTERN...
              </div>
            ) : shareholderData?.response?.data ? (
              <div className="overflow-x-auto">
                <ShareholdingTable data={shareholderData.response.data} screenerData={data} />
              </div>
            ) : (
              <div className="text-zinc-300 text-xs py-2">
                No shareholding pattern on record.
              </div>
            )}
          </BentoCard>

          {/* ── Pledged Shares (Full Width) ────────────────────────────────── */}
          <BentoCard
            title="Pledged Shares"
            className="col-span-1 md:col-span-2 lg:col-span-4"
            badge={
              <span className="text-[10px] text-zinc-300 uppercase">
                {pledgedCount} {pledgedCount === 1 ? 'Record' : 'Records'}
              </span>
            }
          >
            {isIinvestLoading ? (
              <div className="py-6 flex items-center justify-center font-mono text-xs text-terminal-amber animate-pulse">
                LOADING PLEDGED SHARES...
              </div>
            ) : (
              <div className="overflow-x-auto">
                <IinvestGenericTable
                  data={pledgedData?.response?.data ?? []}
                  columns={(pledgedData?.response?.columns ?? []) as IinvestColumn[]}
                  emptyMsg={
                    symbol
                      ? `${symbol} has no pledged shares on record.`
                      : 'No pledged shares on record.'
                  }
                />
              </div>
            )}
          </BentoCard>

        </div>
      </div>
    </div>
  );
}

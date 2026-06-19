'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom } from '@/store/terminalStore';
import {
  fetchIinvestHealth,
  fetchIinvestAnnouncements,
  fetchIinvestBoardMeetings,
  fetchIinvestCorporateActions,
  fetchIinvestLegalCases,
  fetchIinvestCapitalHistory,
  IinvestHealth,
  IinvestAnnouncementRow,
} from '@/lib/iinvest';

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

// ─── Collapsible iinvest section ──────────────────────────────────────────────

interface IinvestSectionProps {
  label: string;
  defaultOpen?: boolean;
  count?: number | null;
  error?: string | null;
  children: React.ReactNode;
}

function IinvestSection({
  label,
  defaultOpen = false,
  count,
  error,
  children,
}: IinvestSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <details
      open={isOpen}
      onToggle={(e) => setIsOpen((e.target as HTMLDetailsElement).open)}
      className="border-b border-terminal-gray/30"
    >
      <summary className="px-2 py-1 cursor-pointer list-none flex items-baseline gap-2 hover:bg-terminal-gray/20">
        <span className="text-white text-[10px] font-mono">
          {isOpen ? '▾' : '▸'}
        </span>
        <span className="text-[10px] text-white/80 font-mono uppercase tracking-wide">
          {label}
        </span>
        {count != null && count > 0 && (
          <span className="text-[9px] text-terminal-amber font-mono">
            ({count})
          </span>
        )}
        {error && (
          <span className="text-[9px] text-terminal-red font-mono ml-auto">
            unavailable
          </span>
        )}
      </summary>
      <div className="px-2 py-1">
        {error ? (
          <div className="text-white/50 text-[10px] font-mono py-1">
            {error}
          </div>
        ) : (
          children
        )}
      </div>
    </details>
  );
}

// ─── iinvest Enrichment Panel (13 collapsible sections) ──────────────────────

interface IinvestEnrichmentPanelProps {
  symbol: string;
  iinvestAvailable: boolean;
  announcements?: IinvestAnnouncementRow[];
  boardMeetings?: unknown[];
  corporateActions?: unknown[];
  legalCases?: unknown[];
  capitalHistory?: unknown[];
  nseRatios?: {
    symbol_pe: number | null;
    sector_pe: number | null;
    high_52w: number | null;
    low_52w: number | null;
  } | null;
}

function IinvestEnrichmentPanel(props: IinvestEnrichmentPanelProps) {
  return (
    <div className="border-t border-terminal-gray/40">
      <div className="px-2 py-1 bg-terminal-gray/20 text-[9px] text-terminal-amber uppercase tracking-widest font-mono">
        iinvest enrichment (8)
      </div>

      <IinvestSection
        label="NSE Market Ratios (screener required for full set)"
        defaultOpen={!props.iinvestAvailable}
      >
        {props.nseRatios ? (
          <div className="text-[9px] text-white/60 mb-1 font-mono">
            4 of 10 core ratios (NSE GetQuoteApi, no screener session needed)
          </div>
        ) : null}
        <table className="w-full border-collapse">
          <tbody>
            <tr className="border-b border-terminal-gray/40">
              <td className="py-[2px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                P/E
              </td>
              <td className="py-[2px] text-right text-terminal-amber text-[10px] font-mono font-bold whitespace-nowrap">
                {props.nseRatios?.symbol_pe != null
                  ? props.nseRatios.symbol_pe.toFixed(2)
                  : <span className="text-white/60 font-normal">—</span>}
              </td>
            </tr>
            <tr className="border-b border-terminal-gray/40">
              <td className="py-[2px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                Sector P/E
              </td>
              <td className="py-[2px] text-right text-terminal-amber text-[10px] font-mono font-bold whitespace-nowrap">
                {props.nseRatios?.sector_pe != null
                  ? props.nseRatios.sector_pe.toFixed(2)
                  : <span className="text-white/60 font-normal">—</span>}
              </td>
            </tr>
            <tr className="border-b border-terminal-gray/40">
              <td className="py-[2px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                52W High
              </td>
              <td className="py-[2px] text-right text-terminal-amber text-[10px] font-mono font-bold whitespace-nowrap">
                {props.nseRatios?.high_52w != null
                  ? `₹${props.nseRatios.high_52w.toFixed(2)}`
                  : <span className="text-white/60 font-normal">—</span>}
              </td>
            </tr>
            <tr className="border-b border-terminal-gray/40">
              <td className="py-[2px] pr-3 text-white text-[10px] font-mono whitespace-nowrap">
                52W Low
              </td>
              <td className="py-[2px] text-right text-terminal-amber text-[10px] font-mono font-bold whitespace-nowrap">
                {props.nseRatios?.low_52w != null
                  ? `₹${props.nseRatios.low_52w.toFixed(2)}`
                  : <span className="text-white/60 font-normal">—</span>}
              </td>
            </tr>
          </tbody>
        </table>
      </IinvestSection>

      <IinvestSection
        label="Corporate Actions (Dividend)"
        count={props.corporateActions?.length}
      >
        <FormattedRowList rows={props.corporateActions} type="corporateActions" />
      </IinvestSection>

      <IinvestSection label="Board Meetings" count={props.boardMeetings?.length}>
        <FormattedRowList rows={props.boardMeetings} type="boardMeetings" />
      </IinvestSection>

      <IinvestSection label="Announcements" count={props.announcements?.length}>
        {props.announcements && props.announcements.length > 0 ? (
          <table className="w-full border-collapse">
            <tbody>
              {props.announcements.slice(0, 10).map((a, i) => {
                const dateStr = typeof a.f_156 === 'string' ? a.f_156.substring(0, 10) : typeof a.xEx_Date === 'string' ? a.xEx_Date.substring(0, 10) : '—';
                const text = a.f_158 || a.xPurpose || '—';
                const link = typeof a.f_159 === 'string' ? a.f_159 : undefined;
                return (
                  <tr key={i} className="border-b border-terminal-gray/40">
                    <td className="py-[2px] pr-2 text-white text-[10px] font-mono whitespace-nowrap">
                      {dateStr}
                    </td>
                    <td className="py-[2px] text-white/80 text-[10px] font-mono">
                      {link ? (
                        <a href={link} target="_blank" rel="noopener noreferrer" className="hover:text-blue-400 hover:underline">
                          {text}
                        </a>
                      ) : (
                        text
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="text-white/50 text-[10px] font-mono py-1">No data</div>
        )}
      </IinvestSection>

      <IinvestSection label="Legal Cases" count={props.legalCases?.length}>
        <FormattedRowList rows={props.legalCases} type="legalCases" />
      </IinvestSection>

      <IinvestSection label="Capital History" count={props.capitalHistory?.length}>
        <FormattedRowList rows={props.capitalHistory} type="capitalHistory" />
      </IinvestSection>
    </div>
  );
}

function FormattedRowList({ rows, type }: { rows?: unknown[], type: 'corporateActions' | 'boardMeetings' | 'capitalHistory' | 'legalCases' }) {
  if (!rows || rows.length === 0) {
    return <div className="text-white/50 text-[10px] font-mono py-1">No data</div>;
  }

  return (
    <table className="w-full border-collapse">
      <tbody>
        {rows.slice(0, 10).map((r, i) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const row = r as Record<string, any>;
          if (type === 'corporateActions') {
            const dateStr = row.f_81 || row.xEx_Date;
            const date = dateStr && typeof dateStr === 'string' ? dateStr.substring(0, 10) : '—';
            return (
              <tr key={i} className="border-b border-terminal-gray/40">
                <td className="py-[2px] pr-2 text-white text-[10px] font-mono whitespace-nowrap">{date}</td>
                <td className="py-[2px] text-white/80 text-[10px] font-mono">{row.f_79 || '—'}</td>
              </tr>
            );
          }
          if (type === 'boardMeetings') {
            const dateStr = row.f_43 || row.xMeeting_Date;
            const date = dateStr && typeof dateStr === 'string' ? dateStr.substring(0, 10) : '—';
            const link = typeof row.f_44 === 'string' ? row.f_44 : undefined;
            const text = row.f_41 || '—';
            return (
              <tr key={i} className="border-b border-terminal-gray/40">
                <td className="py-[2px] pr-2 text-white text-[10px] font-mono whitespace-nowrap">{date}</td>
                <td className="py-[2px] text-white/80 text-[10px] font-mono">
                  {link ? (
                    <a href={link} target="_blank" rel="noopener noreferrer" className="hover:text-blue-400 hover:underline">
                      {text}
                    </a>
                  ) : (
                    text
                  )}
                </td>
              </tr>
            );
          }
          if (type === 'capitalHistory') {
            return (
              <tr key={i} className="border-b border-terminal-gray/40">
                <td className="py-[2px] pr-2 text-white text-[10px] font-mono whitespace-nowrap">{row.f_139 || '—'}</td>
                <td className="py-[2px] pr-2 text-white/80 text-[10px] font-mono">{row.f_140 || '—'}</td>
                <td className="py-[2px] text-white/80 text-[10px] font-mono text-right">{row.f_141 || '—'}</td>
              </tr>
            );
          }
          if (type === 'legalCases') {
            const dateStr = typeof row.f_165 === 'string' ? row.f_165.substring(0, 10) : '—';
            let title = typeof row.f_163 === 'string' ? row.f_163 : '';
            // Remove html tags from title
            title = title.replace(/<[^>]*>?/gm, '');
            const source = typeof row.f_164 === 'string' ? row.f_164 : '';
            
            return (
              <tr key={i} className="border-b border-terminal-gray/40 flex flex-col py-1">
                <td className="text-white/80 text-[10px] font-mono whitespace-normal">{title || '—'}</td>
                <td className="text-white/40 text-[9px] font-mono">{dateStr} • {source}</td>
              </tr>
            );
          }
          return null;
        })}
      </tbody>
    </table>
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

  // iinvest: 13 collapsible enrichment sections. iinvest is the automatic
  // fallback when screener.in is unavailable (HTTP 503). Each section uses
  // useQuery with `enabled: isOpen` for lazy fetch on first expand.
  const { data: iinvestHealth } = useQuery<IinvestHealth>({
    queryKey: ['iinvest', 'health'],
    queryFn: () => fetchIinvestHealth(),
    staleTime: 60_000,
    retry: false,
  });
  const iinvestAvailable = iinvestHealth?.healthy === true;

  // NSE market ratios: 4 of screener's 10 core ratios that come directly from
  // NSE's GetQuoteApi (no screener.in session required). Shown as a fallback
  // when screener returns 503/404 — gives the user *something* instead of
  // a wall of "session unavailable". iinvest also has these ratios but only
  // in the HTML overview page (which the iinvest server only populates for
  // authenticated browser sessions, not the guest-JWT data APIs).
  const { data: nseRatios } = useQuery<{
    symbol_pe: number | null;
    sector_pe: number | null;
    high_52w: number | null;
    low_52w: number | null;
  }>({
    queryKey: ['nse', 'ratios', symbol],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/stockuniverse/${encodeURIComponent(symbol)}/ratios`,
      );
      if (!res.ok) return null;
      return res.json();
    },
    enabled: !!symbol,
    staleTime: 15 * 60 * 1000,
    retry: false,
  });

  const {
    data: announcements,
  } = useQuery<{ response: { data?: IinvestAnnouncementRow[] } }>({
    queryKey: ['iinvest', 'announcements', symbol],
    queryFn: () => fetchIinvestAnnouncements(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 15 * 60 * 1000,
    retry: false,
  });

  const {
    data: boardMeetings,
  } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'board-meetings', symbol],
    queryFn: () => fetchIinvestBoardMeetings(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  const {
    data: corporateActions,
  } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'corporate-actions', symbol, 'Dividend'],
    queryFn: () => fetchIinvestCorporateActions(symbol, 'Dividend'),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  const {
    data: legalCases,
  } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'legal-cases', symbol],
    queryFn: () => fetchIinvestLegalCases(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
  });

  const {
    data: capitalHistory,
  } = useQuery<{ response: { data?: unknown[] } }>({
    queryKey: ['iinvest', 'capital-history', symbol],
    queryFn: () => fetchIinvestCapitalHistory(symbol),
    enabled: iinvestAvailable && !!symbol,
    staleTime: 30 * 60 * 1000,
    retry: false,
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

  // ── Error / Fallback rendering ──────────────────────────────────────────────
  // Screener 503 is the common case: ratios / quarters are not available, but
  // iinvest enrichment sections (corporate actions, announcements, etc.) still
  // work. We render the iinvest sections so the user has something to look at.
  if (isError || !data) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    const status = (error as Error & { status?: number })?.status;
    const is503 = status === 503;
    const is404 = status === 404;

    // If iinvest is available and the screener failure is recoverable, show
    // the iinvest enrichment sections so the widget isn't dead.
    if (iinvestAvailable && (is503 || is404)) {
      return (
        <div className="h-full w-full flex flex-col font-mono text-xs overflow-y-auto bg-terminal-bg">
          <IinvestEnrichmentPanel
            symbol={symbol}
            iinvestAvailable={iinvestAvailable}
            nseRatios={nseRatios}
            announcements={announcements?.response.data}
            boardMeetings={boardMeetings?.response.data}
            corporateActions={corporateActions?.response.data}
            legalCases={legalCases?.response.data}
            capitalHistory={capitalHistory?.response.data}
          />
        </div>
      );
    }

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
              {/* ── Valuation ────────────────────────────────────────────────────── */}
              <div className="mt-4 mb-2">
                <div className="text-[9px] text-white/60 uppercase tracking-widest mb-1">
                  Valuation Models
                </div>
                {/* Controls */}
                <div className="flex flex-col gap-1 text-[10px] text-white/40 mb-2">
                  <div className="flex items-center justify-between">
                    <span>Weighted Average Cost of Capital</span>
                    <select
                      value={wacc}
                      onChange={(e) => setWacc(parseFloat(e.target.value))}
                      className="bg-terminal-bg border border-white/10 rounded px-1 py-0.5 text-white/70 text-[10px] outline-none"
                    >
                      {[0.10, 0.11, 0.12, 0.13, 0.14, 0.15].map((v) => (
                        <option key={v} value={v} className="bg-terminal-bg text-white">{(v * 100).toFixed(0)}%</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Terminal Growth Rate</span>
                    <select
                      value={terminalGrowth}
                      onChange={(e) => setTerminalGrowth(parseFloat(e.target.value))}
                      className="bg-terminal-bg border border-white/10 rounded px-1 py-0.5 text-white/70 text-[10px] outline-none"
                    >
                      {[0.03, 0.04, 0.05, 0.06, 0.07].map((v) => (
                        <option key={v} value={v} className="bg-terminal-bg text-white">{(v * 100).toFixed(0)}%</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex justify-end">
                    <button
                      onClick={() => refetchValuation()}
                      className="text-[9px] px-1.5 py-0.5 border border-white/10 rounded hover:bg-white/5 text-white/50 hover:text-white/80 transition-colors"
                    >
                      Refresh
                    </button>
                  </div>
                </div>
                {valuationLoading ? (
                  <div className="text-white/30 text-[11px] font-mono">Loading valuation models...</div>
                ) : valuationData ? (
                  <>
                    <div className="text-[10px] text-white/30 font-mono mb-1">CMP: ₹{valuationData.cmp?.toLocaleString('en-IN')}</div>
                    <table className="w-full text-[10px] border-collapse font-mono">
                      <thead>
                        <tr className="text-white/30 text-left border-b border-terminal-gray/40">
                          <th className="pb-1 font-normal">Model</th>
                          <th className="pb-1 text-right font-normal">Fair Value</th>
                          <th className="pb-1 text-right font-normal">vs CMP</th>
                          <th className="pb-1 text-right font-normal">Signal</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          { label: 'Graham Number', value: valuationData.graham_number, upside: valuationData.graham_upside_pct },
                          { label: 'DCF (10Y)', value: valuationData.dcf_value, upside: valuationData.dcf_upside_pct },
                          { label: 'DDM', value: valuationData.ddm_value, upside: valuationData.ddm_upside_pct },
                          { label: 'EV/EBITDA', value: valuationData.ev_ebitda_value, upside: valuationData.ev_ebitda_upside_pct },
                          { label: 'PEG Fair Value', value: valuationData.peg_value, upside: valuationData.peg_upside_pct },
                        ].map((row) => {
                          const signal = row.upside === null ? null : row.upside > 15 ? 'UNDERVALUED' : row.upside < -15 ? 'OVERVALUED' : 'FAIR';
                          const signalColor = signal === 'UNDERVALUED' ? 'text-terminal-green' : signal === 'OVERVALUED' ? 'text-terminal-red' : 'text-terminal-amber';
                          return (
                            <tr key={row.label} className="border-b border-terminal-gray/40">
                              <td className="py-[3px] pr-2 text-white/60 whitespace-nowrap">{row.label}</td>
                              <td className="py-[3px] text-right text-white/80 font-bold whitespace-nowrap">
                                {row.value !== null ? `₹${row.value.toLocaleString('en-IN')}` : '—'}
                              </td>
                              <td className={'py-[3px] text-right font-bold whitespace-nowrap ' + (row.upside !== null ? (row.upside > 0 ? 'text-terminal-green' : 'text-terminal-red') : 'text-white/30')}>
                                {row.upside !== null ? `${row.upside > 0 ? '+' : ''}${row.upside.toFixed(1)}%` : '—'}
                              </td>
                              <td className={'py-[3px] text-right font-bold whitespace-nowrap ' + signalColor}>
                                {signal ?? '—'}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {valuationData.dcf_assumptions && (
                      <div className="text-[9px] text-white/50 mt-1 pt-1 font-mono">
                        DCF: Stage1 {valuationData.dcf_assumptions.stage1_growth_pct}% →
                        Stage2 {valuationData.dcf_assumptions.stage2_growth_pct}% →
                        Term {valuationData.dcf_assumptions.terminal_growth_pct}% |
                        WACC {valuationData.dcf_assumptions.wacc_pct}%
                        {valuationData.dcf_assumptions.base_fcf_cr !== null &&
                          ` | Base FCF ₹${valuationData.dcf_assumptions.base_fcf_cr.toFixed(0)}Cr`}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="text-white/30 text-[11px] font-mono">No valuation data available</div>
                )}
              </div>
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

        {/* ── iinvest Enrichment (13 collapsible sections) ────────────── */}
        {iinvestAvailable && (
          <IinvestEnrichmentPanel
            symbol={symbol}
            iinvestAvailable={iinvestAvailable}
            announcements={announcements?.response.data}
            boardMeetings={boardMeetings?.response.data}
            corporateActions={corporateActions?.response.data}
            legalCases={legalCases?.response.data}
            capitalHistory={capitalHistory?.response.data}
            nseRatios={nseRatios}
          />
        )}

      </div>
    </div>
  );
}

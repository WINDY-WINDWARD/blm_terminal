'use client';

import React, { useState, useMemo, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSetAtom } from 'jotai';
import {
  chartSymbolOverridesAtom,
  companySymbolOverridesAtom,
  type ChartSymbolOverride,
  type CompanySymbolOverride,
} from '@/store/terminalStore';
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts';

type DealTab = 'bulk' | 'block' | 'short' | 'fii';

interface LargedealRow {
  date: string;
  symbol: string;
  name: string;
  clientName: string | null;
  buySell: 'BUY' | 'SELL' | null;
  qty: string;
  watp: string | number | null;
  remarks: string | null;
  /** Trade value in Rs Cr, added by the backend significance filter */
  trade_value_cr?: number | null;
}

interface LargedealSnapshot {
  as_on_date: string;
  BULK_DEALS_DATA: LargedealRow[];
  SHORT_DEALS_DATA: LargedealRow[];
  BLOCK_DEALS_DATA: LargedealRow[];
  BULK_DEALS?: string | number;
  SHORT_DEALS?: string | number;
  BLOCK_DEALS?: string | number;
}

interface FiiDiiRow {
  buyValue: number;
  sellValue: number;
  netValue: number;
  category: string;
  date: string;
}

function fmtNumber(raw: string | number | null): string {
  if (raw === null || raw === undefined) return '—';
  const n = typeof raw === 'number' ? raw : Number(String(raw).replace(/,/g, ''));
  if (!Number.isFinite(n)) return String(raw);
  return n.toLocaleString('en-IN');
}

export function LargedealsWidget() {
  const [activeTab, setActiveTab] = useState<DealTab>('bulk');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [minValueCr, setMinValueCr] = useState<number>(0);

  const setChartOverrides = useSetAtom(chartSymbolOverridesAtom);
  const setCompanyOverrides = useSetAtom(companySymbolOverridesAtom);

  const handleOpenChart = useCallback((e: React.MouseEvent, symbol: string) => {
    e.stopPropagation();
    const popoutKey = `popout_direct_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
    setChartOverrides((prev: Record<string, ChartSymbolOverride>) => ({
      ...prev,
      [popoutKey]: { symbol, exchange: 'NSE' },
    }));
    const query = new URLSearchParams({
      symbol,
      exchange: 'NSE',
      popoutPanelId: popoutKey,
    });
    window.open(
      `/widget/CHART?${query.toString()}`,
      `blm_widget_CHART_${popoutKey}`,
      'width=1100,height=720',
    );
  }, [setChartOverrides]);

  const handleOpenCompany = useCallback((e: React.MouseEvent, symbol: string) => {
    e.stopPropagation();
    const popoutKey = `popout_company_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
    setCompanyOverrides((prev: Record<string, CompanySymbolOverride>) => ({
      ...prev,
      [popoutKey]: { symbol },
    }));
    const query = new URLSearchParams({
      symbol,
      popoutPanelId: popoutKey,
    });
    window.open(
      `/widget/COMPANY?${query.toString()}`,
      `blm_widget_COMPANY_${popoutKey}`,
      'width=1200,height=800',
    );
  }, [setCompanyOverrides]);

  const { data, isLoading, isError, error, refetch } = useQuery<LargedealSnapshot>({
    queryKey: ['market/largedeal-snapshot'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/largedeal-snapshot');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<LargedealSnapshot>;
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  const { data: fiiData, isLoading: fiiLoading } = useQuery<{ data: FiiDiiRow[] }>({
    queryKey: ['market/fiidii'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/fiidii');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  const bulkDeals = useMemo(() => data?.BULK_DEALS_DATA ?? [], [data]);
  const blockDeals = useMemo(() => data?.BLOCK_DEALS_DATA ?? [], [data]);
  const shortDeals = useMemo(() => data?.SHORT_DEALS_DATA ?? [], [data]);
  const fiiRows = useMemo(() => fiiData?.data ?? [], [fiiData]);

  const activeRawRows = useMemo(() => {
    switch (activeTab) {
      case 'bulk':  return bulkDeals;
      case 'block': return blockDeals;
      case 'short': return shortDeals;
      default:      return [];
    }
  }, [activeTab, bulkDeals, blockDeals, shortDeals]);

  // Compute Bento KPI Metrics
  const kpis = useMemo(() => {
    let buyValueCr = 0;
    let sellValueCr = 0;
    let buyCount = 0;
    let sellCount = 0;

    for (const r of activeRawRows) {
      const val = r.trade_value_cr ?? 0;
      if (r.buySell === 'BUY') {
        buyValueCr += val;
        buyCount += 1;
      } else if (r.buySell === 'SELL') {
        sellValueCr += val;
        sellCount += 1;
      }
    }

    const totalTurnoverCr = buyValueCr + sellValueCr;
    const netFlowCr = buyValueCr - sellValueCr;
    const netBias =
      netFlowCr > 0
        ? `+₹${netFlowCr.toFixed(1)} Cr BUY ACCUMULATION`
        : netFlowCr < 0
        ? `-₹${Math.abs(netFlowCr).toFixed(1)} Cr DISTRIBUTION`
        : 'NEUTRAL BALANCE';
    const netColor = netFlowCr > 0 ? 'text-emerald-400' : netFlowCr < 0 ? 'text-rose-400' : 'text-zinc-400';

    return {
      totalTurnoverCr,
      buyValueCr,
      sellValueCr,
      buyCount,
      sellCount,
      netFlowCr,
      netBias,
      netColor,
      totalRows: activeRawRows.length,
    };
  }, [activeRawRows]);

  const filteredRows = useMemo(() => {
    let rows = activeRawRows;
    if (actionFilter !== 'ALL') {
      rows = rows.filter((r) => r.buySell === actionFilter);
    }
    if (minValueCr > 0) {
      rows = rows.filter((r) => (r.trade_value_cr ?? 0) >= minValueCr);
    }
    if (searchQuery.trim().length > 0) {
      const q = searchQuery.toLowerCase().trim();
      rows = rows.filter(
        (r) =>
          r.symbol.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q) ||
          (r.clientName && r.clientName.toLowerCase().includes(q)),
      );
    }
    return rows;
  }, [activeRawRows, actionFilter, minValueCr, searchQuery]);

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1 bg-[#09090b] text-amber-400">
        <span className="font-bold animate-pulse">LOADING INSTITUTIONAL DEALS MATRIX...</span>
      </div>
    );
  }

  if (isError) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2 px-4 text-center bg-[#09090b]">
        <span className="text-rose-400 font-bold uppercase">Fetch Failed</span>
        <span className="text-zinc-400 text-xs">{errMsg}</span>
        <button
          onClick={() => refetch()}
          className="px-3 py-1 rounded bg-amber-400 text-black font-bold text-xs hover:bg-amber-300 cursor-pointer"
        >
          Retry
        </button>
      </div>
    );
  }

  const asOnDate = data?.as_on_date ?? 'Latest Session';

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-[#09090b] text-white p-3 gap-3 overflow-hidden select-text">
      {/* ─── Top Header & Controls ─────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-[#27272a] shrink-0">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-amber-400/10 border border-amber-400/30 text-amber-400 font-bold text-xs">
            💼
          </span>
          <span className="text-amber-400 font-bold text-xs uppercase tracking-wider">
            INSTITUTIONAL DEALS &amp; FLOW RADAR
          </span>
          <span className="text-zinc-400 text-[11px] bg-zinc-800 px-2 py-0.5 rounded border border-[#27272a]">
            As on {asOnDate}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-[10px] text-zinc-400 font-mono">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>NSE/BSE Filings Live Feed</span>
        </div>
      </div>

      {/* ─── Bento Tabs & Filters Toolbar ───────────────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 shrink-0 bg-[#0c0c0f] border border-[#27272a] p-1.5 rounded-lg">
        <div data-widget-tour="largedeals-tabs" className="flex items-center gap-1" role="tablist">
          {(
            [
              { id: 'bulk', label: 'BULK DEALS', count: bulkDeals.length },
              { id: 'block', label: 'BLOCK DEALS', count: blockDeals.length },
              { id: 'short', label: 'SHORT DEALS', count: shortDeals.length },
              { id: 'fii', label: 'FII / DII RADAR', count: fiiRows.length },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={activeTab === t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all flex items-center gap-1.5 cursor-pointer ${
                activeTab === t.id
                  ? 'bg-amber-400 text-black font-extrabold shadow'
                  : 'bg-[#121216] text-zinc-400 border border-[#27272a] hover:text-white hover:bg-zinc-800'
              }`}
            >
              <span>{t.label}</span>
              {t.id !== 'fii' && (
                <span
                  className={`px-1.5 py-0.2 rounded text-[10px] tabular-nums ${
                    activeTab === t.id ? 'bg-black text-amber-400' : 'bg-zinc-800 text-zinc-400'
                  }`}
                >
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {activeTab !== 'fii' && (
          <div data-widget-tour="largedeals-filters" className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search symbol, client…"
              className="bg-[#121216] border border-[#27272a] hover:border-zinc-500 focus:border-amber-400 rounded px-2.5 py-1 text-xs text-white placeholder-zinc-500 outline-none w-44 font-mono transition-colors"
            />

            <div className="flex items-center bg-[#121216] border border-[#27272a] rounded overflow-hidden">
              {(['ALL', 'BUY', 'SELL'] as const).map((af) => (
                <button
                  key={af}
                  type="button"
                  onClick={() => setActionFilter(af)}
                  className={`px-2 py-1 text-[10px] font-mono font-bold transition-colors ${
                    actionFilter === af
                      ? 'bg-amber-400 text-black'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  {af}
                </button>
              ))}
            </div>

            <div className="flex items-center bg-[#121216] border border-[#27272a] rounded overflow-hidden">
              {[
                { label: 'ALL CR', val: 0 },
                { label: '≥ 5Cr', val: 5 },
                { label: '≥ 20Cr', val: 20 },
                { label: '≥ 50Cr', val: 50 },
              ].map((pill) => (
                <button
                  key={pill.val}
                  type="button"
                  onClick={() => setMinValueCr(pill.val)}
                  className={`px-1.5 py-1 text-[10px] font-mono font-bold transition-colors ${
                    minValueCr === pill.val
                      ? 'bg-amber-400 text-black'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  {pill.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ─── 4 Bento KPI Cards (Hidden on FII/DII tab) ─── */}
      {activeTab !== 'fii' && (
      <div data-widget-tour="largedeals-kpis" className="grid grid-cols-2 @4xl:grid-cols-4 gap-2.5 shrink-0">
        {/* Card 1: Total Turnover */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            TOTAL DEALS TURNOVER
          </div>
          <div className="text-base font-extrabold text-amber-400 tabular-nums">
            {kpis.totalTurnoverCr > 0 ? `₹${kpis.totalTurnoverCr.toFixed(1)} Cr` : '—'}
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            {kpis.totalRows} transactions in view
          </div>
        </div>

        {/* Card 2: Buy Flow */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            BUY FLOW (ACCUMULATION)
          </div>
          <div className="text-base font-extrabold text-emerald-400 tabular-nums flex items-center gap-1">
            <span>▲</span>
            <span>{kpis.buyValueCr > 0 ? `₹${kpis.buyValueCr.toFixed(1)} Cr` : `${kpis.buyCount} Buys`}</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            {kpis.buyCount} Institutional Buys
          </div>
        </div>

        {/* Card 3: Sell Flow */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            SELL FLOW (DISTRIBUTION)
          </div>
          <div className="text-base font-extrabold text-rose-400 tabular-nums flex items-center gap-1">
            <span>▼</span>
            <span>{kpis.sellValueCr > 0 ? `₹${kpis.sellValueCr.toFixed(1)} Cr` : `${kpis.sellCount} Sells`}</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            {kpis.sellCount} Institutional Sells
          </div>
        </div>

        {/* Card 4: Institutional Bias */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            INSTITUTIONAL BIAS
          </div>
          <div className={`text-xs font-extrabold tabular-nums ${kpis.netColor} truncate`}>
            {kpis.netBias}
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            Net Buy / Sell differential
          </div>
        </div>
      </div>
      )}

      {/* ─── Bento Content Area ─────────────────────────────────────────────── */}
      <div data-widget-tour="largedeals-table" className="flex-1 overflow-auto bg-[#0c0c0f] border border-[#27272a] rounded-lg min-h-0">
        {activeTab === 'fii' ? (
          /* FII / DII Radar View */
          fiiLoading ? (
            <div className="h-full w-full flex items-center justify-center font-mono text-xs text-amber-400 animate-pulse">
              LOADING FII / DII RADAR DATA...
            </div>
          ) : fiiRows.length === 0 ? (
            <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-zinc-500 gap-1 p-8 text-center">
              <span>No FII/DII data available for today.</span>
            </div>
          ) : (
            <div className="p-4 flex flex-col gap-4">
              <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-3">
                {fiiRows.map((r, idx) => {
                  const pieData = [
                    { name: 'Buy', value: Number(r.buyValue) || 0, color: '#10b981' },
                    { name: 'Sell', value: Number(r.sellValue) || 0, color: '#ef4444' },
                  ];
                  return (
                    <div
                      key={idx}
                      className="bg-[#121216] border border-[#27272a] rounded-lg p-3.5 flex flex-col items-center shadow"
                    >
                      <div className="font-bold text-white text-xs mb-1 uppercase tracking-wide">
                        {r.category}
                      </div>
                      <div className="text-[11px] text-zinc-400 mb-2 font-mono">
                        Net Flow:{' '}
                        <span className={`font-bold ${r.netValue >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {r.netValue >= 0 ? '+' : ''}₹{fmtNumber(r.netValue)} Cr
                        </span>
                      </div>
                      <div className="w-full h-40">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={pieData}
                              dataKey="value"
                              nameKey="name"
                              cx="50%"
                              cy="50%"
                              outerRadius={55}
                              innerRadius={35}
                            >
                              {pieData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={entry.color} />
                              ))}
                            </Pie>
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="flex items-center justify-around w-full mt-2 pt-2 border-t border-[#27272a] text-xs font-mono">
                        <span className="text-emerald-400 font-bold">Buy: ₹{fmtNumber(r.buyValue)} Cr</span>
                        <span className="text-rose-400 font-bold">Sell: ₹{fmtNumber(r.sellValue)} Cr</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )
        ) : filteredRows.length === 0 ? (
          <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-zinc-500 gap-1 p-8 text-center">
            <span className="text-2xl mb-1">💼</span>
            <span className="font-bold text-zinc-400 uppercase">NO DEALS MATCHING CRITERIA</span>
            <span className="text-[11px] text-zinc-600">
              No transactions found for the selected action and value filters.
            </span>
          </div>
        ) : (
          <table className="w-full text-left font-mono text-xs border-collapse">
            <thead className="sticky top-0 bg-[#121216] border-b border-[#27272a] z-10">
              <tr className="text-[10px] text-zinc-400 uppercase">
                <th className="py-2 px-3 font-semibold whitespace-nowrap">DATE</th>
                <th className="py-2 px-3 font-semibold whitespace-nowrap">SECURITY</th>
                <th className="py-2 px-3 font-semibold whitespace-nowrap">CLIENT / INSTITUTION</th>
                <th className="py-2 px-3 font-semibold whitespace-nowrap">ACTION</th>
                <th className="py-2 px-3 font-semibold text-right whitespace-nowrap">QUANTITY</th>
                <th className="py-2 px-3 font-semibold text-right whitespace-nowrap">WATP</th>
                <th className="py-2 px-3 font-semibold text-right whitespace-nowrap">VALUE (CR)</th>
                <th className="py-2 px-3 font-semibold text-right whitespace-nowrap">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#27272a]/60">
              {filteredRows.map((row, idx) => (
                <tr
                  key={`${row.date}-${row.symbol}-${row.clientName}-${idx}`}
                  className="hover:bg-zinc-900/60 transition-colors"
                >
                  <td className="py-2.5 px-3 text-zinc-400 tabular-nums whitespace-nowrap">
                    {row.date}
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-amber-400">{row.symbol}</span>
                      <span className="text-[10px] text-zinc-400 truncate max-w-[140px]" title={row.name}>
                        {row.name}
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 px-3 text-white font-medium">
                    <div className="max-w-xs truncate" title={row.clientName ?? '—'}>
                      {row.clientName ?? '—'}
                    </div>
                  </td>
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        row.buySell === 'BUY'
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                          : row.buySell === 'SELL'
                          ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                          : 'bg-zinc-800 text-zinc-400'
                      }`}
                    >
                      {row.buySell ?? '—'}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-right text-zinc-200 tabular-nums whitespace-nowrap">
                    {fmtNumber(row.qty)}
                  </td>
                  <td className="py-2.5 px-3 text-right text-zinc-300 tabular-nums whitespace-nowrap">
                    ₹{fmtNumber(row.watp)}
                  </td>
                  <td className="py-2.5 px-3 text-right whitespace-nowrap">
                    {row.trade_value_cr != null && row.trade_value_cr > 0 ? (
                      <span className="text-amber-400 font-bold tabular-nums">
                        ₹{row.trade_value_cr.toFixed(2)} Cr
                      </span>
                    ) : (
                      <span className="text-zinc-500 font-mono">—</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 text-right whitespace-nowrap">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={(e) => handleOpenChart(e, row.symbol)}
                        className="px-2 py-0.5 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700 hover:border-terminal-amber text-zinc-200 text-[10px] font-mono font-semibold transition-all inline-flex items-center gap-1 shadow-sm active:scale-95 cursor-pointer"
                        title={`Open chart for ${row.symbol}`}
                      >
                        <span>⚡</span>
                        <span>Chart</span>
                      </button>

                      <button
                        type="button"
                        onClick={(e) => handleOpenCompany(e, row.symbol)}
                        className="px-2 py-0.5 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700 hover:border-terminal-amber text-zinc-200 text-[10px] font-mono font-semibold transition-all inline-flex items-center gap-1 shadow-sm active:scale-95 cursor-pointer"
                        title={`Open company for ${row.symbol}`}
                      >
                        <span>🏢</span>
                        <span>Company</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

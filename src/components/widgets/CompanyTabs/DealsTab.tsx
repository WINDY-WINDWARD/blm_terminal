'use client';

import React, { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSetAtom } from 'jotai';
import {
  chartSymbolOverridesAtom,
  type ChartSymbolOverride,
} from '@/store/terminalStore';
import {
  fetchIinvestAll,
  type IinvestAllResponse,
  type IinvestInsiderRow,
} from '@/lib/iinvest';
import { IinvestGenericTable, type IinvestColumn } from './IinvestGenericTable';

// ─── Types ────────────────────────────────────────────────────────────────────

interface TradeRecord {
  period: string | null;
  person: string | null;
  category: string | null;
  quantity_raw: string | null;
  quantity: number | null;
  direction: 'up' | 'down' | null;
  avg_price_raw: string | null;
  avg_price: number | null;
  value_raw: string | null;
  value: number | null;
  value_in: string | null;
  small_quantity: boolean;
}

interface ScreenerTradesResponse {
  insider_trades: TradeRecord[];
  bulk_deals: TradeRecord[];
  block_deals: TradeRecord[];
}

type Tab = 'bulk' | 'block' | 'insider' | 'sast';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null, decimals = 0): string {
  if (n === null) return '—';
  return n.toLocaleString('en-IN', { maximumFractionDigits: decimals });
}

function DirectionBadge({ record }: { record: TradeRecord }) {
  if (record.direction === 'up') {
    const qty = record.quantity !== null ? fmt(record.quantity) : record.quantity_raw ?? '—';
    return (
      <span className="inline-flex items-center gap-1 text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 text-xs">
        <span>▲ BUY</span>
        <span className="tabular-nums font-mono">{qty}</span>
      </span>
    );
  }
  if (record.direction === 'down') {
    const qty = record.quantity !== null ? fmt(Math.abs(record.quantity)) : record.quantity_raw ?? '—';
    return (
      <span className="inline-flex items-center gap-1 text-rose-400 font-bold bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20 text-xs">
        <span>▼ SELL</span>
        <span className="tabular-nums font-mono">{qty}</span>
      </span>
    );
  }
  const raw = (record.quantity_raw ?? '—').toUpperCase();
  if (raw === 'B' || raw === 'BUY') {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 text-xs">
        <span>▲ BUY</span>
        {record.quantity !== null && <span className="tabular-nums font-mono">{fmt(record.quantity)}</span>}
      </span>
    );
  }
  if (raw === 'S' || raw === 'SALE' || raw === 'SELL') {
    return (
      <span className="inline-flex items-center gap-1 text-rose-400 font-bold bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20 text-xs">
        <span>▼ SELL</span>
        {record.quantity !== null && <span className="tabular-nums font-mono">{fmt(record.quantity)}</span>}
      </span>
    );
  }
  return <span className="text-zinc-400 text-xs">{record.quantity_raw ?? '—'}</span>;
}

function ValueBadge({ record }: { record: TradeRecord }) {
  if (record.value === null) return <span className="text-zinc-500 font-mono text-xs">—</span>;
  const suffix = record.value_in === 'lacs' ? ' L' : record.value_in === 'price' ? '₹' : '';
  return (
    <span className="text-amber-400 font-mono font-bold text-xs tabular-nums">
      {record.value_in === 'price' ? `${suffix}${fmt(record.value)}` : `${fmt(record.value)}${suffix}`}
    </span>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────


function mapIinvestInsiderToTradeRecords(rows: IinvestInsiderRow[]): TradeRecord[] {
  const toNum = (v: string | number | undefined): number | null => {
    if (v === undefined || v === null) return null;
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return rows.map((r) => {
    const type = String(r.f_12 || '').toUpperCase();
    const direction: 'up' | 'down' | null =
      type === 'B' || type === 'BUY' ? 'up'
      : type === 'S' || type === 'SELL' || type === 'SALE' ? 'down'
      : null;
    return {
      period: r.f_28 ?? null,
      person: r.f_4 ?? null,
      category: r.f_5 ?? null,
      quantity_raw: r.f_12 ?? null,
      quantity: toNum(r.f_10),
      direction,
      avg_price_raw: null,
      avg_price: null,
      value_raw: null,
      value: null,
      value_in: null,
      small_quantity: false,
    };
  });
}

function mapIinvestBlockToTradeRecords(rows: Array<Record<string, unknown>>): TradeRecord[] {
  const toNum = (v: unknown): number | null => {
    if (v === undefined || v === null) return null;
    const n = typeof v === 'number' ? v : Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return rows.map((r) => {
    const type = String(r.f_33 || '').toUpperCase();
    const direction: 'up' | 'down' | null =
      type === 'B' || type === 'BUY' ? 'up'
      : type === 'S' || type === 'SELL' || type === 'SALE' ? 'down'
      : null;
    return {
      period: (r.f_35 as string | undefined) ?? null,
      person: (r.f_32 as string | undefined) ?? null,
      category: null,
      quantity_raw: (r.f_33 as string | undefined) ?? null,
      quantity: toNum(r.f_34),
      direction,
      avg_price_raw: null,
      avg_price: toNum(r.f_36),
      value_raw: null,
      value: null,
      value_in: 'price',
      small_quantity: false,
    };
  });
}

export function DealsTab({ symbol }: { symbol: string }) {
  const [activeTab, setActiveTab] = useState<Tab>('bulk');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [actionFilter, setActionFilter] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const setChartOverrides = useSetAtom(chartSymbolOverridesAtom);

  const handleOpenChart = (e: React.MouseEvent) => {
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
  };

  const { data, isLoading: screenerLoading } = useQuery<ScreenerTradesResponse>({
    queryKey: ['screener/trades', symbol],
    queryFn: async () => {
      try {
        const res = await fetch(`/api/py/screener/trades/${encodeURIComponent(symbol)}`);
        if (!res.ok) return { insider_trades: [], bulk_deals: [], block_deals: [] };
        return res.json() as Promise<ScreenerTradesResponse>;
      } catch {
        return { insider_trades: [], bulk_deals: [], block_deals: [] };
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const { data: iinvestData, isLoading: iinvestLoading } = useQuery<IinvestAllResponse>({
    queryKey: ['iinvest/all', symbol],
    queryFn: () => fetchIinvestAll(symbol).catch(() => ({} as IinvestAllResponse)),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const isLoading = screenerLoading && iinvestLoading;

  const iinvestInsiderRows = useMemo(() => {
    const raw = iinvestData?.insider_trading?.response?.data;
    return raw ? mapIinvestInsiderToTradeRecords(raw) : [];
  }, [iinvestData]);

  const iinvestBulkRows = useMemo(() => {
    const raw = iinvestData?.bulk_deals?.response?.data;
    return raw ? mapIinvestBlockToTradeRecords(raw) : [];
  }, [iinvestData]);

  const iinvestBlockRows = useMemo(() => {
    const raw = iinvestData?.block_deals?.response?.data;
    return raw ? mapIinvestBlockToTradeRecords(raw) : [];
  }, [iinvestData]);

  const allBulk = useMemo(() => {
    const screener = data?.bulk_deals ?? [];
    return screener.length > 0 ? screener : iinvestBulkRows;
  }, [data, iinvestBulkRows]);

  const allBlock = useMemo(() => {
    const screener = data?.block_deals ?? [];
    return screener.length > 0 ? screener : iinvestBlockRows;
  }, [data, iinvestBlockRows]);

  const allInsider = useMemo(() => {
    const screener = data?.insider_trades ?? [];
    return screener.length > 0 ? screener : iinvestInsiderRows;
  }, [data, iinvestInsiderRows]);

  const allSast = useMemo(() => iinvestData?.sast?.response?.data ?? [], [iinvestData]);

  // Compute Bento KPI Metrics
  const kpis = useMemo(() => {
    const combined = [...allBulk, ...allBlock, ...allInsider];
    let buyCount = 0;
    let sellCount = 0;
    let totalValLacs = 0;

    for (const r of (combined as TradeRecord[])) {
      const isBuy = r.direction === 'up' || (r.quantity_raw && ['B', 'BUY'].includes(r.quantity_raw.toUpperCase()));
      const isSell = r.direction === 'down' || (r.quantity_raw && ['S', 'SELL', 'SALE'].includes(r.quantity_raw.toUpperCase()));
      if (isBuy) buyCount += 1;
      if (isSell) sellCount += 1;

      if (r.value !== null && Number.isFinite(r.value)) {
        if (r.value_in === 'lacs') {
          totalValLacs += r.value;
        } else {
          totalValLacs += r.value / 100000;
        }
      }
    }

    const netBias = buyCount > sellCount ? 'BUY ACCUMULATION' : sellCount > buyCount ? 'NET DISTRIBUTION' : 'NEUTRAL';
    const netColor = buyCount > sellCount ? 'text-emerald-400' : sellCount > buyCount ? 'text-rose-400' : 'text-zinc-400';

    return {
      totalRecords: combined.length,
      buyCount,
      sellCount,
      totalValLacs,
      netBias,
      netColor,
    };
  }, [allBulk, allBlock, allInsider]);

  const activeRawRows = useMemo(() => {
    switch (activeTab) {
      case 'bulk':    return allBulk;
      case 'block':   return allBlock;
      case 'insider': return allInsider;
      default:        return [];
    }
  }, [activeTab, allBulk, allBlock, allInsider]);

  const filteredRows = useMemo(() => {
    let rows = activeRawRows;
    if (actionFilter === 'BUY') {
      rows = rows.filter((r) => r.direction === 'up' || (r.quantity_raw && ['B', 'BUY'].includes(r.quantity_raw.toUpperCase())));
    } else if (actionFilter === 'SELL') {
      rows = rows.filter((r) => r.direction === 'down' || (r.quantity_raw && ['S', 'SELL', 'SALE'].includes(r.quantity_raw.toUpperCase())));
    }
    if (searchQuery.trim().length > 0) {
      const q = searchQuery.toLowerCase().trim();
      rows = rows.filter(
        (r) =>
          (r.person && r.person.toLowerCase().includes(q)) ||
          (r.category && r.category.toLowerCase().includes(q)) ||
          (r.period && r.period.toLowerCase().includes(q)),
      );
    }
    return rows;
  }, [activeRawRows, actionFilter, searchQuery]);

  const isAllLoading = isLoading || (activeTab === 'sast' && iinvestLoading);

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs bg-[#09090b] text-white p-3 gap-3 overflow-hidden select-text">
      {/* ─── Top Header & Independent Popout Button ─────────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-[#27272a] shrink-0">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-amber-400/10 border border-amber-400/30 text-amber-400 font-bold text-xs">
            💼
          </span>
          <span className="text-amber-400 font-bold text-xs uppercase tracking-wider">
            DEALS &amp; INSIDER MATRIX
          </span>
          <span className="text-white font-extrabold text-sm bg-zinc-800 px-2 py-0.5 rounded border border-[#27272a]">
            {symbol}
          </span>
        </div>

        <button
          type="button"
          onClick={handleOpenChart}
          className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700 hover:border-terminal-amber text-zinc-200 text-xs font-mono font-semibold transition-all inline-flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer"
          title={`Open independent chart for ${symbol}`}
        >
          <span>⚡</span>
          <span>Load Chart</span>
        </button>
      </div>

      {/* ─── 4 Bento KPI Cards ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 @4xl:grid-cols-4 gap-2.5 shrink-0">
        {/* Card 1: Recorded Turnover */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            RECORDED TURNOVER
          </div>
          <div className="text-base font-extrabold text-amber-400 tabular-nums">
            {kpis.totalValLacs > 100
              ? `₹${(kpis.totalValLacs / 100).toFixed(2)} Cr`
              : `₹${kpis.totalValLacs.toFixed(1)} L`}
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            {kpis.totalRecords} total transactions
          </div>
        </div>

        {/* Card 2: Buy Accumulation */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            BUY ACCUMULATION
          </div>
          <div className="text-base font-extrabold text-emerald-400 tabular-nums flex items-center gap-1">
            <span>▲</span>
            <span>{kpis.buyCount} Trades</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            Institutional &amp; Insider buys
          </div>
        </div>

        {/* Card 3: Sell Distribution */}
        <div className="bg-[#0c0c0f] border border-[#27272a] rounded-lg p-2.5 flex flex-col justify-between shadow">
          <div className="text-[10px] text-zinc-400 font-bold uppercase tracking-wider mb-1">
            SELL DISTRIBUTION
          </div>
          <div className="text-base font-extrabold text-rose-400 tabular-nums flex items-center gap-1">
            <span>▼</span>
            <span>{kpis.sellCount} Trades</span>
          </div>
          <div className="text-[10px] text-zinc-500 mt-0.5">
            Disposals &amp; Block exits
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
            Ratio: {kpis.buyCount}:{kpis.sellCount}
          </div>
        </div>
      </div>

      {/* ─── Bento Category Tab Bar & Filter Controls ───────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-2 shrink-0 bg-[#0c0c0f] border border-[#27272a] p-1.5 rounded-lg">
        <div className="flex items-center gap-1" role="tablist">
          {(
            [
              { id: 'bulk', label: 'BULK DEALS', count: allBulk.length },
              { id: 'block', label: 'BLOCK DEALS', count: allBlock.length },
              { id: 'insider', label: 'INSIDER TRADES', count: allInsider.length },
              { id: 'sast', label: 'SAST DISCLOSURES', count: allSast.length },
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
              <span
                className={`px-1.5 py-0.2 rounded text-[10px] tabular-nums ${
                  activeTab === t.id ? 'bg-black text-amber-400' : 'bg-zinc-800 text-zinc-400'
                }`}
              >
                {t.count}
              </span>
            </button>
          ))}
        </div>

        {activeTab !== 'sast' && (
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search person / entity…"
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
          </div>
        )}
      </div>

      {/* ─── Table Content Container ────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto bg-[#0c0c0f] border border-[#27272a] rounded-lg min-h-0">
        {isAllLoading ? (
          <div className="h-full w-full flex items-center justify-center font-mono text-xs text-amber-400 animate-pulse">
            LOADING {activeTab.toUpperCase()} RECORDS...
          </div>
        ) : false ? (
          <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-rose-400 gap-1 p-4 text-center">
            <span>Failed to load {activeTab} data</span>
            <span className="text-zinc-500 text-[10px]">'Failed to load transactions'</span>
          </div>
        ) : activeTab === 'sast' ? (
          <div className="p-2">
            <IinvestGenericTable
              data={iinvestData?.sast?.response?.data ?? []}
              columns={(iinvestData?.sast?.response?.columns ?? []) as IinvestColumn[]}
              emptyMsg="No SAST disclosures on record"
            />
          </div>
        ) : filteredRows.length === 0 ? (
          <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs text-zinc-500 gap-1 p-8 text-center">
            <span className="text-2xl mb-1">💼</span>
            <span className="font-bold text-zinc-400 uppercase">NO TRANSACTIONS RECORDED</span>
            <span className="text-[11px] text-zinc-600">
              No {activeTab} transactions matching the current filters for {symbol}.
            </span>
          </div>
        ) : (
          <table className="w-full text-left font-mono text-xs border-collapse">
            <thead className="sticky top-0 bg-[#121216] border-b border-[#27272a] z-10">
              <tr className="text-[10px] text-zinc-400 uppercase">
                <th className="py-2 px-3 font-semibold whitespace-nowrap">PERIOD / DATE</th>
                <th className="py-2 px-3 font-semibold whitespace-nowrap">PERSON / INSTITUTION</th>
                {activeTab === 'insider' && (
                  <th className="py-2 px-3 font-semibold whitespace-nowrap">CATEGORY</th>
                )}
                <th className="py-2 px-3 font-semibold whitespace-nowrap">ACTION &amp; QTY</th>
                <th className="py-2 px-3 font-semibold text-right whitespace-nowrap">AVG PRICE</th>
                <th className="py-2 px-3 font-semibold text-right whitespace-nowrap">VALUE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#27272a]/60">
              {filteredRows.map((row: TradeRecord, idx: number) => (
                <tr
                  key={`${row.period}-${row.person}-${idx}`}
                  className="hover:bg-zinc-900/60 transition-colors"
                >
                  <td className="py-2.5 px-3 text-zinc-300 tabular-nums whitespace-nowrap">
                    {row.period ?? '—'}
                  </td>
                  <td className="py-2.5 px-3 text-white font-medium">
                    <div className="max-w-xs truncate" title={row.person ?? '—'}>
                      {row.person ?? '—'}
                    </div>
                  </td>
                  {activeTab === 'insider' && (
                    <td className="py-2.5 px-3 text-zinc-400 text-[11px] whitespace-nowrap">
                      {row.category ?? '—'}
                    </td>
                  )}
                  <td className="py-2.5 px-3 whitespace-nowrap">
                    <DirectionBadge record={row} />
                  </td>
                  <td className="py-2.5 px-3 text-right text-zinc-200 tabular-nums whitespace-nowrap">
                    {row.avg_price !== null ? `₹${fmt(row.avg_price, 2)}` : row.avg_price_raw ?? '—'}
                  </td>
                  <td className="py-2.5 px-3 text-right whitespace-nowrap">
                    <ValueBadge record={row} />
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

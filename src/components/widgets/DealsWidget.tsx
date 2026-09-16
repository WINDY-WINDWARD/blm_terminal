'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, ResponsiveContainer, Legend } from 'recharts';
import { activeSymbolAtom } from '@/store/terminalStore';
import {
  fetchIinvestAll,
  type IinvestAllResponse,
  type IinvestInsiderRow,
  type IinvestResponse,
  type IinvestShareholderRow,
} from '@/lib/iinvest';

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

export interface ScreenerCompanyData {
  shareholding?: Array<{
    period: string;
    promoters: number | null;
    fiis: number | null;
    diis: number | null;
    public: number | null;
    government: number | null;
  }>;
}

type Tab = 'insider' | 'bulk' | 'block' | 'pledged' | 'shareholding' | 'sast';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n: number | null, decimals = 0): string {
  if (n === null) return '—';
  return n.toLocaleString('en-IN', { maximumFractionDigits: decimals });
}

function DirectionCell({ record }: { record: TradeRecord }) {
  // Insider trades have direction + quantity; deals have quantity_raw like "B"/"Sale"
  if (record.direction === 'up') {
    const qty = record.quantity !== null ? fmt(record.quantity) : record.quantity_raw ?? '—';
    return <span className="text-terminal-green font-bold">▲ {qty}</span>;
  }
  if (record.direction === 'down') {
    const qty = record.quantity !== null ? fmt(Math.abs(record.quantity)) : record.quantity_raw ?? '—';
    return <span className="text-terminal-red font-bold">▼ {qty}</span>;
  }
  // Bulk/block: quantity_raw holds "B" / "Sale" etc., quantity is null
  const raw = record.quantity_raw ?? '—';
  const upper = raw.toUpperCase();
  if (upper === 'B' || upper === 'BUY')
    return <span className="text-terminal-green font-bold">BUY</span>;
  if (upper === 'S' || upper === 'SALE' || upper === 'SELL')
    return <span className="text-terminal-red font-bold">SELL</span>;
  return <span className="text-white/60">{raw}</span>;
}

function ValueCell({ record }: { record: TradeRecord }) {
  if (record.value === null) return <span className="text-white/40">—</span>;
  const suffix = record.value_in === 'lacs' ? 'L' : record.value_in === 'price' ? '₹' : '';
  return (
    <span className="text-terminal-amber">
      {record.value_in === 'price' ? `${suffix}${fmt(record.value)}` : `${fmt(record.value)}${suffix}`}
    </span>
  );
}

interface SectionTableProps {
  rows: TradeRecord[];
  showCategory: boolean;
}

function SectionTable({ rows, showCategory }: SectionTableProps) {
  if (rows.length === 0) {
    return <div className="text-white/40 text-[10px] py-2 px-1">No records</div>;
  }

  return (
    <table className="w-full border-collapse text-[10px]">
      <thead className="sticky top-0 bg-terminal-bg z-10">
        <tr className="text-[9px] text-white/60 uppercase border-b border-terminal-gray/60">
          <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Period</th>
          <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Person</th>
          {showCategory && (
            <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Category</th>
          )}
          <th className="text-left pb-1 font-normal pr-2 whitespace-nowrap">Qty / Dir</th>
          <th className="text-right pb-1 font-normal pr-2 whitespace-nowrap">Avg Price</th>
          <th className="text-right pb-1 font-normal whitespace-nowrap">Value</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={`${row.period}-${row.person}-${i}`}
            className="border-b border-terminal-gray/30 hover:bg-zinc-900"
          >
            <td className="py-[3px] pr-2 text-white whitespace-nowrap">
              {row.period ?? '—'}
            </td>
            <td
              className="py-[3px] pr-2 text-white max-w-[120px] truncate"
              title={row.person ?? undefined}
            >
              {row.person ?? <span className="text-white/40">—</span>}
            </td>
            {showCategory && (
              <td
                className="py-[3px] pr-2 text-white/60 max-w-[100px] truncate text-[9px]"
                title={row.category ?? undefined}
              >
                {row.category || <span className="text-white/30">—</span>}
              </td>
            )}
            <td className="py-[3px] pr-2 whitespace-nowrap">
              <DirectionCell record={row} />
            </td>
            <td className="py-[3px] pr-2 text-right text-white whitespace-nowrap">
              {row.avg_price !== null ? fmt(row.avg_price) : (row.avg_price_raw ?? '—')}
            </td>
            <td className="py-[3px] text-right whitespace-nowrap">
              <ValueCell record={row} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ─── iinvest → TradeRecord mapper ────────────────────────────────────────────

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

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function DealsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const [activeTab, setActiveTab] = useState<Tab>('insider');

  const { data: allData, isLoading: isAllLoading } = useQuery<[ScreenerTradesResponse, IinvestAllResponse]>({
    queryKey: ['deals/all', symbol],
    queryFn: async () => {
      const fetchScreener = async (): Promise<ScreenerTradesResponse> => {
        const res = await fetch(`/api/py/screener/trades/${encodeURIComponent(symbol)}`);
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const json = (await res.json()) as { detail?: string };
            if (json.detail) detail = json.detail;
          } catch { /* ignore */ }
          const err = new Error(detail);
          (err as Error & { status: number }).status = res.status;
          throw err;
        }
        return res.json() as Promise<ScreenerTradesResponse>;
      };

      const [screenerRes, iinvestRes] = await Promise.all([
        fetchScreener().catch((err) => {
          return { insider_trades: [], bulk_deals: [], block_deals: [] } as ScreenerTradesResponse;
        }),
        fetchIinvestAll(symbol).catch((err) => {
          return {} as IinvestAllResponse;
        }),
      ]);
      return [screenerRes, iinvestRes];
    },
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: screenerCompany } = useQuery<ScreenerCompanyData>({
    queryKey: ['screener/company', symbol],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/screener/company/${encodeURIComponent(symbol)}?consolidated=true`,
      );
      if (!res.ok) throw new Error('Failed to fetch screener company');
      return res.json() as Promise<ScreenerCompanyData>;
    },
    staleTime: 15 * 60 * 1000,
    retry: false,
    enabled: !!symbol && activeTab === 'shareholding',
  });

  const [screenerTradesData, iinvestAllData] = allData ?? [
    { insider_trades: [], bulk_deals: [], block_deals: [] },
    {},
  ];

  const pledgedData = iinvestAllData?.pledged_shares;
  const shareholderData = iinvestAllData?.key_shareholders;
  const sastData = iinvestAllData?.sast;
  const iinvestInsider = iinvestAllData?.insider_trading;
  const iinvestBlockData = iinvestAllData?.block_deals;
  const iinvestBulkData = iinvestAllData?.bulk_deals;

  const iinvestBulkCount = iinvestBulkData?.response?.data?.length ?? 0;
  const iinvestBlockCount = iinvestBlockData?.response?.data?.length ?? 0;

  if (!symbol) {
    return (
      <div className="h-full w-full flex items-center justify-center font-mono text-xs text-white/40">
        No symbol selected
      </div>
    );
  }

  const screenerData: ScreenerTradesResponse = screenerTradesData ?? {
    insider_trades: [],
    bulk_deals: [],
    block_deals: [],
  };

  const iinvestInsiderRows = iinvestInsider?.response?.data
    ? mapIinvestInsiderToTradeRecords(iinvestInsider.response.data)
    : [];

  const insiderRows = screenerData.insider_trades.length > 0
    ? screenerData.insider_trades
    : iinvestInsiderRows;
    
  const iinvestBulkRawRows = iinvestBulkData?.response?.data ?? [];
  const iinvestBlockRawRows = iinvestBlockData?.response?.data ?? [];
  const iinvestBulkTradeRecords = mapIinvestBlockToTradeRecords(iinvestBulkRawRows);
  const iinvestBlockTradeRecords = mapIinvestBlockToTradeRecords(iinvestBlockRawRows);
  
  const useIinvestBulk = iinvestBulkCount > 0 && iinvestBulkCount >= screenerData.bulk_deals.length;
  const bulkRows = useIinvestBulk ? iinvestBulkTradeRecords : screenerData.bulk_deals;

  const useIinvestBlock = iinvestBlockCount > 0 && iinvestBlockCount >= screenerData.block_deals.length;
  const blockRows = useIinvestBlock ? iinvestBlockTradeRecords : screenerData.block_deals;

  const tabs: { id: Tab; label: string; count: number; description: string }[] = [
    { id: 'insider',      label: 'Insider',      count: insiderRows.length,            description: 'Buys/sells by directors, officers, promoters, and their relatives (SEBI Reg. 7(2))' },
    { id: 'bulk',         label: 'Bulk',         count: bulkRows.length,               description: 'Bulk deals — single transaction crossing 0.5% of a company’s paid-up capital' },
    { id: 'block',        label: 'Block',        count: blockRows.length,              description: 'Block deals — negotiated trade window 09:15–09:40 IST for 5%+ block size' },
    { id: 'pledged',      label: 'Pledged',      count: pledgedData?.response.data?.length ?? 0,      description: 'Promoter shares pledged as collateral with lenders (Reg. 31(2))' },
    { id: 'shareholding', label: 'Shareholding', count: shareholderData?.response.data?.length ?? 0, description: 'Quarterly shareholding pattern: Promoter / FII / DII / Public breakdown (~5y history)' },
    { id: 'sast',         label: 'SAST',         count: sastData?.response.data?.length ?? 0,         description: 'Substantial Acquisition of Shares & Takeovers (SEBI Reg. 29(2))' },
  ];

  const activeRows: TradeRecord[] =
    activeTab === 'insider' ? insiderRows :
    activeTab === 'bulk'    ? bulkRows    :
    activeTab === 'block'   ? blockRows   :
    [];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">

      {/* Header */}
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Deals, Insider &amp; Shareholding
        </span>
        <span className="text-white text-[10px] flex-shrink-0">{symbol}</span>
      </div>

      {/* Tabs */}
      <div className="flex-shrink-0 flex border-b border-terminal-gray/60 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors border-b-2 whitespace-nowrap ${
              activeTab === tab.id
                ? 'bg-terminal-amber text-black font-bold -mb-px'
                : 'text-white/50 hover:text-white hover:bg-zinc-900 border-transparent'
            }`}
            style={activeTab === tab.id ? { borderBottomColor: '#ffb900' } : undefined}
            title={tab.description}
          >
            {tab.label}
            <span className={`ml-1 text-[9px] ${activeTab === tab.id ? 'text-black/60' : 'text-white/30'}`}>
              ({tab.count})
            </span>
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {activeTab === 'insider' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING INSIDER TRADES...
          </div>
        ) : activeTab === 'bulk' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING BULK DEALS...
          </div>
        ) : activeTab === 'block' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING BLOCK DEALS...
          </div>
        ) : activeTab === 'shareholding' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING SHAREHOLDING PATTERN...
          </div>
        ) : activeTab === 'pledged' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING PLEDGED SHARES...
          </div>
        ) : activeTab === 'sast' && isAllLoading ? (
          <div className="h-full flex items-center justify-center font-mono text-xs text-terminal-amber/60 animate-pulse">
            LOADING SAST DISCLOSURES...
          </div>
        ) : activeTab === 'insider' || activeTab === 'bulk' || activeTab === 'block' ? (
          <SectionTable
            rows={activeRows}
            showCategory={activeTab === 'insider'}
          />
        ) : activeTab === 'shareholding' ? (
          shareholderData?.response?.data ? (
            <ShareholdingTable data={shareholderData.response.data} screenerData={screenerCompany} />
          ) : (
            <div className="h-full flex items-center justify-center font-mono text-xs text-white/40">
              No shareholding pattern on record
            </div>
          )
        ) : activeTab === 'pledged' ? (
          <IinvestGenericTable
            data={pledgedData?.response.data ?? []}
            columns={(pledgedData?.response.columns ?? []) as any}
            emptyMsg={
              symbol
                ? `${symbol} has no pledged shares on record.`
                : 'No pledged shares on record.'
            }
          />
        ) : activeTab === 'sast' ? (
          <IinvestGenericTable
            data={sastData?.response.data ?? []}
            columns={(sastData?.response.columns ?? []) as IinvestColumn[]}
            emptyMsg="No SAST disclosures on record"
          />
        ) : null}
      </div>
    </div>
  );
}

// ─── iinvest table helpers ───────────────────────────────────────────────────

// iinvest response shape for keyshareholders:
//   { response: { data: [
//     ["ID", "ParentID", ..., "Mar-26", "Dec-25", ...],   // array header row
//     { ID, ParentID, IsExpanded, Description, "Mar-26": {per, val}, ... },  // data row
//     ...
//   ]}}
// The first row is an array of column names. Subsequent rows are dicts where
// the quarter columns hold {per, val} objects (or null).

type ShareholdingCellValue = { per?: number; val?: number } | null | undefined;

function ShareholdingTable({ data, screenerData }: { data: unknown, screenerData?: ScreenerCompanyData }) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  if (!Array.isArray(data) || data.length === 0) {
    return <div className="text-white/40 text-[10px] py-2 px-1">No records</div>;
  }

  // Real iinvest shape (verified 2026-06-18, MAXHEALTH + TARACHAND):
  //   data[0] is the array HEADER: ['ID', 'ParentID', 'IsExpanded', 'Description', 'Mar-26', 'Dec-25', ...]
  //   data[1..] are PARALLEL ARRAYS of values. Format:
  //     [ID, ParentID, IsExpanded, Description, Mar-26, Dec-25, ...]
  //   Rows with IsExpanded=True + ParentID=null are TOP-LEVEL GROUPS
  //   (Promoter, Public, etc.). Their children have ParentID=this group's ID.
  //   Rows with IsExpanded=False are LEAF HOLDERS with {per, val} cells.
  const headerRow = data[0];
  if (!Array.isArray(headerRow)) {
    return <div className="text-white/40 text-[10px] py-2 px-1">No records</div>;
  }
  const headers = headerRow as string[];
  const descIdx = headers.indexOf('Description');
  const idIdx = headers.indexOf('ID');
  const isExpandedIdx = headers.indexOf('IsExpanded');
  if (descIdx < 0 || idIdx < 0 || isExpandedIdx < 0) {
    return <div className="text-white/40 text-[10px] py-2 px-1">Invalid shape</div>;
  }
  // Find quarter column indices like 'Mar-26', 'Dec-25', 'Sep-25' (in header order)
  const quarterIdxs = headers
    .map((h, i) => ({ h, i }))
    .filter(({ h }) => /^(Mar|Jun|Sep|Dec)-\d{2}$/.test(h))
    .slice(0, 4);
  const quarterLabels = quarterIdxs.map((q) => q.h);

  // Data rows are arrays parallel to the header.
  const dataRows = data.slice(1) as unknown[][];

  // Top-level groups: IsExpanded=True AND ParentID is null/None
  const groups = dataRows.filter(
    (r) => r[isExpandedIdx] === true && (r[idIdx + 1] === null || r[idIdx + 1] === undefined),
  );
  // Build a parent-ID → children map for non-group rows
  const childrenByParent: Record<string, unknown[][]> = {};
  for (const r of dataRows) {
    if (r[isExpandedIdx] === true) continue; // skip groups
    const parentId = r[idIdx + 1];
    if (parentId === null || parentId === undefined) continue;
    const key = String(parentId);
    if (!childrenByParent[key]) childrenByParent[key] = [];
    childrenByParent[key].push(r);
  }

  const toggleGroup = (id: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const latestQ = quarterIdxs[0];
  const prevQ = quarterIdxs[1];

  // Handle Pie Chart and QoQ using Screener Data
  let pieData: Array<{ name: string; value: number }> = [];
  let fiiQoQ: number | null = null;
  let diiQoQ: number | null = null;
  let latestPeriod = quarterLabels[0] ?? 'Latest';
  let prevPeriod = quarterLabels[1] ?? 'Previous';

  if (screenerData?.shareholding && screenerData.shareholding.length >= 2) {
    const sh = screenerData.shareholding;
    const latest = sh[sh.length - 1];
    const prev = sh[sh.length - 2];
    
    latestPeriod = latest.period;
    prevPeriod = prev.period;

    if (latest.promoters) pieData.push({ name: 'Promoters', value: latest.promoters });
    if (latest.fiis) pieData.push({ name: 'FIIs', value: latest.fiis });
    if (latest.diis) pieData.push({ name: 'DIIs', value: latest.diis });
    if (latest.public) pieData.push({ name: 'Public', value: latest.public });
    if (latest.government) pieData.push({ name: 'Govt', value: latest.government });
    
    pieData = pieData.sort((a, b) => b.value - a.value);

    if (latest.fiis !== null && prev.fiis !== null) fiiQoQ = latest.fiis - prev.fiis;
    if (latest.diis !== null && prev.diis !== null) diiQoQ = latest.diis - prev.diis;
  } else {
    // Fallback pie chart from iinvest data
    pieData = groups.map(group => {
      const groupId = String(group[idIdx]);
      const groupDesc = (group[descIdx] as string) ?? `Group ${groupId}`;
      
      const children = childrenByParent[groupId] ?? [];
      let perSumLatest = 0;
      for (const row of children) {
        if (latestQ) {
           const cell = row[latestQ.i] as ShareholdingCellValue;
           if (cell && cell.per != null) perSumLatest += cell.per;
        }
      }
      
      return {
         name: groupDesc.length > 20 ? groupDesc.substring(0, 20) + '...' : groupDesc,
         value: Number(perSumLatest.toFixed(2))
      };
    }).filter(d => d.value > 0).sort((a, b) => b.value - a.value);
  }

  const COLORS = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];

  return (
    <div className="flex flex-col h-full w-full">
      {pieData.length > 0 && (
        <div className="flex flex-row items-center justify-between p-2 mb-2 bg-zinc-900/50 rounded flex-shrink-0">
          <div className="flex flex-col items-center flex-1 h-[140px] min-w-0">
            <span className="text-white font-bold text-[10px] uppercase mb-1">Holdings ({latestPeriod})</span>
            <ResponsiveContainer width="100%" height="100%">
               <PieChart>
                  <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={25} outerRadius={45} stroke="none">
                     {pieData.map((e, i) => <Cell key={`cell-${i}`} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <RechartsTooltip 
                    contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46', fontSize: '10px' }}
                    itemStyle={{ color: '#fff' }}
                    formatter={(val: any) => [`${Number(val).toFixed(2)}%`, undefined]}
                  />
                  <Legend 
                    wrapperStyle={{ fontSize: '9px' }} 
                    layout="vertical" 
                    verticalAlign="middle" 
                    align="right"
                    formatter={(value, entry: any) => `${value} (${entry.payload.value.toFixed(2)}%)`}
                  />
               </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-col flex-1 items-center justify-center gap-2 min-w-0">
            <span className="text-white/60 text-[10px] uppercase font-bold text-center">QoQ Change ({prevPeriod} to {latestPeriod})</span>
            <div className="flex flex-col gap-1">
              {fiiQoQ !== null && (
                <div className="flex gap-2 items-center text-[11px]">
                    <span className="text-white/80 w-8">FII:</span>
                    {(fiiQoQ as number) > 0.005 ? <span className="text-terminal-green font-bold">▲ +{(fiiQoQ as number).toFixed(2)}%</span> : (fiiQoQ as number) < -0.005 ? <span className="text-terminal-red font-bold">▼ {(fiiQoQ as number).toFixed(2)}%</span> : <span className="text-white/50">0.00%</span>}
                </div>
              )}
              {diiQoQ !== null && (
                <div className="flex gap-2 items-center text-[11px]">
                    <span className="text-white/80 w-8">DII:</span>
                    {(diiQoQ as number) > 0.005 ? <span className="text-terminal-green font-bold">▲ +{(diiQoQ as number).toFixed(2)}%</span> : (diiQoQ as number) < -0.005 ? <span className="text-terminal-red font-bold">▼ {(diiQoQ as number).toFixed(2)}%</span> : <span className="text-white/50">0.00%</span>}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      <div className="flex-1 overflow-auto min-h-0">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 bg-terminal-bg z-10">
            <tr className="text-[9px] text-white/60 uppercase">
              <th className="text-left pb-1 font-normal">Description</th>
              {quarterLabels.map((q) => {
                return (
                  <th key={q} className="text-right pb-1 pr-2 font-normal whitespace-nowrap bg-terminal-bg">
                    <div className="leading-tight">
                      <div>{q}</div>
                      <div className="text-white/40 text-[8px]">% Holding | No of Shares</div>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => {
              const groupId = String(group[idIdx]);
              const groupDesc = (group[descIdx] as string) ?? `Group ${groupId}`;
              const isCollapsed = collapsedGroups.has(groupId);
              const children = childrenByParent[groupId] ?? [];
              return (
                <ShareholdingGroupFragment
                  key={groupId}
                  groupId={groupId}
                  groupDesc={groupDesc}
                  isCollapsed={isCollapsed}
                  onToggle={() => toggleGroup(groupId)}
                  descIdx={descIdx}
                  quarterIdxs={quarterIdxs}
                >
                  {children}
                </ShareholdingGroupFragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Fragment component for a single top-level group + its children.
// Split out so React's reconciliation doesn't tear down the children
// list when a sibling group's collapsed state changes.
interface ShareholdingGroupFragmentProps {
  groupId: string;
  groupDesc: string;
  isCollapsed: boolean;
  onToggle: () => void;
  descIdx: number;
  quarterIdxs: { h: string; i: number }[];
  children: unknown[][];
}

function ShareholdingGroupFragment({
  groupId,
  groupDesc,
  isCollapsed,
  onToggle,
  descIdx,
  quarterIdxs,
  children,
}: ShareholdingGroupFragmentProps) {
  // When the group is collapsed, show the SUM of children's % and shares per
  // quarter column. Pre-compute once so the JSX is straightforward.
  // When the group is expanded, filter out children where ALL quarter cells
  // are empty (per:null, val:null) — these are noise like "Blue Green
  // Biotech And Pharma Pvt Ltd" with no holdings data for that quarter.
  const aggregates: Record<number, { per: number; val: number }> = {};
  if (isCollapsed) {
    for (const { i: colIdx } of quarterIdxs) {
      let perSum = 0;
      let valSum = 0;
      let any = false;
      for (const row of children) {
        const cell = row[colIdx] as ShareholdingCellValue;
        if (cell && cell.per != null && cell.val != null) {
          perSum += cell.per;
          valSum += cell.val;
          any = true;
        }
      }
      if (any) aggregates[colIdx] = { per: perSum, val: valSum };
    }
  }

  // Filter children when expanded: only show rows with at least one
  // non-empty quarter cell. This drops rows like "Smallcap World Fund, Inc"
  // where per/val are null for every column.
  const visibleChildren = isCollapsed
    ? []
    : children.filter((row) =>
        quarterIdxs.some(({ i: colIdx }) => {
          const cell = row[colIdx] as ShareholdingCellValue;
          return cell && cell.per != null;
        }),
      );

  return (
    <>
      {/* Group header row (clickable) */}
      <tr
        className="border-b border-terminal-gray/60 bg-zinc-900/30 cursor-pointer hover:bg-zinc-800/40"
        onClick={onToggle}
        data-testid={`shareholding-group-${groupId}`}
      >
        <td className="py-[3px] pr-2 text-white text-[10px] font-mono whitespace-nowrap font-bold">
          <span className="text-white/50 mr-1">{isCollapsed ? '▸' : '▾'}</span>
          {groupDesc}
          {isCollapsed && (
            <span className="text-white/40 font-normal ml-2 text-[9px]">
              ({visibleChildren.length === children.length
                ? children.length
                : `${visibleChildren.length}/${children.length}`} holders)
            </span>
          )}
        </td>
        {quarterIdxs.map(({ h, i: colIdx }) => {
          const agg = aggregates[colIdx];
          return (
            <td
              key={h}
              className="py-[2px] pr-2 text-right text-[10px] font-mono whitespace-nowrap"
            >
              {agg ? (
                <div className="leading-tight">
                  <div className="text-terminal-amber font-bold">
                    {agg.per.toFixed(2)}
                  </div>
                  <div className="text-white/60 text-[9px]">
                    {agg.val.toLocaleString('en-IN')}
                  </div>
                </div>
              ) : (
                <span className="text-white/40">—</span>
              )}
            </td>
          );
        })}
      </tr>
      {/* Child rows (visible when expanded) — already filtered above */}
      {!isCollapsed && visibleChildren.map((row, i) => {
        const desc = (row[descIdx] as string | null) ?? `Row ${i + 1}`;
        return (
          <tr
            key={`${groupId}-${i}`}
            className="border-b border-terminal-gray/40"
            data-testid={`shareholding-row-${groupId}-${i}`}
          >
            <td className="py-[2px] pr-2 text-white/90 text-[10px] font-mono whitespace-nowrap pl-4">
              {desc}
            </td>
            {quarterIdxs.map(({ h, i: colIdx }) => {
              const cell = row[colIdx] as ShareholdingCellValue;
              if (cell === null || cell === undefined) {
                return (
                  <td
                    key={h}
                    className="py-[2px] pr-2 text-right text-white/40 text-[10px] font-mono"
                  >
                    —
                  </td>
                );
              }
              const per = cell.per;
              const val = cell.val;
              return (
                <td
                  key={h}
                  className="py-[2px] pr-2 text-right text-[10px] font-mono whitespace-nowrap"
                >
                  <div className="leading-tight">
                    {per != null ? (
                      <div className="text-terminal-amber font-bold">
                        {per.toFixed(2)}
                      </div>
                    ) : (
                      <div className="text-white/40">—</div>
                    )}
                    {val != null && (
                      <div className="text-white/40 text-[9px]">
                        {val.toLocaleString('en-IN')}
                      </div>
                    )}
                  </div>
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}

// iinvest columns metadata: { field: "f_162", displayName: "Date", dataType: "Date" }
// Builds a field → displayName map so we can render friendly headers.

interface IinvestColumn {
  field: string;
  displayName: string;
  dataType?: string;
  format?: string;
}

function formatCell(value: unknown, dataType: string | undefined, format: string | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  // String-typed: render as-is (dates come pre-formatted like "26-Sep-24")
  if (dataType === 'String' || dataType === 'Date' || format === 'd-mmm-yy' || format?.startsWith('d-')) {
    return String(value);
  }
  // Number-typed: add thousands separators
  if (dataType === 'Number' || typeof value === 'number') {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return String(value);
    return n.toLocaleString('en-IN');
  }
  return String(value);
}

function IinvestGenericTable({
  data,
  columns,
  emptyMsg,
}: {
  data: unknown;
  columns: IinvestColumn[];
  emptyMsg: string;
}) {
  if (!Array.isArray(data) || data.length === 0) {
    return <div className="text-white/40 text-[10px] py-2 px-1">{emptyMsg}</div>;
  }
  const rows = data as Array<Record<string, unknown>>;
  // Build field → column map, then drop the internal f_25008 (path slug)
  const colByField: Record<string, IinvestColumn> = {};
  for (const c of columns) colByField[c.field] = c;
  const visibleCols = columns.filter((c) => c.field !== 'f_25008');

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="text-[9px] text-white/60 uppercase">
          {visibleCols.map((c) => (
            <th key={c.field} className="text-left pb-1 pr-2 font-normal whitespace-nowrap">
              {c.displayName}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 50).map((row, i) => (
          <tr key={i} className="border-b border-terminal-gray/40">
            {visibleCols.map((c) => (
              <td
                key={c.field}
                className="py-[2px] pr-2 text-white text-[10px] font-mono whitespace-nowrap"
              >
                {formatCell(row[c.field], c.dataType, c.format)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

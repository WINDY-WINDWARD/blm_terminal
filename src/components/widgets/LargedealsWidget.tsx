'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, ResponsiveContainer, Legend } from 'recharts';

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

interface CompanyGroup {
  key: string;
  symbol: string;
  name: string;
  rows: LargedealRow[];
}

function fmtNumber(raw: string | number | null): string {
  if (raw === null) return '—';
  const n = typeof raw === 'number' ? raw : Number(raw.replace(/,/g, ''));
  if (!Number.isFinite(n)) return String(raw);
  return n.toLocaleString('en-IN');
}

function DealBadge({ kind, count, active }: { kind: DealTab; count: number; active?: boolean }) {
  const label =
    kind === 'bulk' ? 'Bulk Deals' : kind === 'block' ? 'Block Deals' : kind === 'fii' ? 'FII / DII' : 'Short Deals';
  
  if (kind === 'fii') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px]">
        <span>{label}</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1 text-[10px]">
      <span>{label}</span>
      <span className={`inline-flex items-center justify-center min-w-[18px] h-[14px] rounded-full text-[9px] px-1 ${
        active ? 'bg-black/30 text-black' : 'bg-terminal-gray text-white'
      }`}>
        {count}
      </span>
    </span>
  );
}

interface FiiDiiRow {
  buyValue: number;
  sellValue: number;
  netValue: number;
  category: string;
  date: string;
}

function FiiDiiChart({ data }: { data: FiiDiiRow[] }) {
  if (!data || data.length === 0) return <div className="p-4 text-white/50 text-center text-[10px]">No FII/DII data available.</div>;
  
  const fiiRow = data.find(r => r.category.includes('FII'));
  const diiRow = data.find(r => r.category.includes('DII'));
  const date = data[0]?.date || '';

  const renderPie = (row: FiiDiiRow | undefined, title: string) => {
    if (!row) return null;
    const pieData = [
      { name: 'Buy', value: Number(row.buyValue) || 0, color: '#10b981' }, // terminal-green
      { name: 'Sell', value: Number(row.sellValue) || 0, color: '#ef4444' }, // terminal-red
    ];
    return (
      <div className="flex flex-col items-center flex-1 min-w-0">
        <div className="text-white font-bold text-[11px] mb-2 uppercase">{title}</div>
        <div className="text-white/60 text-[9px] mb-2 text-center">Net: <span className={row.netValue >= 0 ? "text-terminal-green" : "text-terminal-red font-bold"}>₹{fmtNumber(row.netValue)} Cr</span></div>
        <div className="w-full h-[160px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                innerRadius={35}
                outerRadius={60}
                stroke="none"
              >
                {pieData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <RechartsTooltip 
                contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46', fontSize: '10px' }}
                itemStyle={{ color: '#fff' }}
                formatter={(val: any) => [`₹${Number(val).toLocaleString()} Cr`, undefined]}
              />
              <Legend wrapperStyle={{ fontSize: '10px' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4 p-2 h-full overflow-y-auto w-full">
      <div className="text-center text-white/60 text-[10px]">Market Activity for {date}</div>
      <div className="flex flex-row justify-around w-full mt-2">
        {renderPie(fiiRow, 'FII / FPI Activity')}
        {renderPie(diiRow, 'DII Activity')}
      </div>
    </div>
  );
}

interface CompanyAccordionProps {
  group: CompanyGroup;
  expanded: boolean;
  onToggle: () => void;
}

function CompanyAccordion({ group, expanded, onToggle }: CompanyAccordionProps) {
  return (
    <div className="border border-terminal-gray/50 rounded mb-1 overflow-hidden flex-shrink-0">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between px-2 py-1 bg-zinc-900 hover:bg-zinc-800 text-left"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-terminal-amber font-bold text-[11px] truncate">
            {group.name}
          </span>
          <span className="text-white/60 text-[10px] font-mono shrink-0">
            {group.symbol}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center min-w-[18px] h-[14px] rounded-full bg-terminal-gray text-[9px] text-white px-1">
            {group.rows.length}
          </span>
          <span className="text-white/50 text-[10px]">
            {expanded ? '▾' : '▸'}
          </span>
        </div>
      </button>
      {expanded && (
        <div className="bg-black/40 px-2 py-1">
          {group.rows.map((row, idx) => (
            <div
              key={`${row.date}-${row.clientName}-${idx}`}
              className="py-[3px] border-b border-terminal-gray/40 last:border-b-0 text-[10px]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-white/70 whitespace-nowrap">{row.date}</span>
                <span
                  className={`font-bold ${
                    row.buySell === 'BUY'
                      ? 'text-terminal-green'
                      : row.buySell === 'SELL'
                      ? 'text-terminal-red'
                      : 'text-white/50'
                  }`}
                >
                  {row.buySell ?? '—'}
                </span>
              </div>
              <div
                className="text-white truncate max-w-full"
                title={row.clientName ?? undefined}
              >
                {row.clientName ?? <span className="text-white/40">Unknown client</span>}
              </div>
              <div className="flex items-center justify-between gap-2 text-white/80">
                <span className="text-[10px]">
                  Qty:{' '}
                  <span className="font-mono">
                    {fmtNumber(row.qty)}
                  </span>
                </span>
                <span className="text-[10px]">
                  WATP:{' '}
                  <span className="font-mono">
                    ₹{fmtNumber(row.watp)}
                  </span>
                </span>
                {row.trade_value_cr != null && row.trade_value_cr > 0 && (
                  <span className="text-[10px] text-terminal-amber font-mono font-semibold">
                    ₹{row.trade_value_cr.toFixed(1)} Cr
                  </span>
                )}
              </div>
              {row.remarks && row.remarks !== '-' && (
                <div className="text-white/60 text-[9px] mt-[1px] truncate">
                  {row.remarks}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function LargedealsWidget() {
  const [activeTab, setActiveTab] = useState<DealTab>('bulk');
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());

  const { data, isLoading, isError, error } = useQuery<LargedealSnapshot>({
    queryKey: ['market/largedeal-snapshot'],
    queryFn: async () => {
      const res = await fetch('/api/py/market/largedeal-snapshot');
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
      return res.json() as Promise<LargedealSnapshot>;
    },
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const { data: fiiData, isLoading: fiiLoading, isError: fiiError } = useQuery<{data: FiiDiiRow[]}>({
    queryKey: ['market/fiidii'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/fiidii');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  const toggleKey = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">
          LOADING LARGE DEALS...
        </span>
      </div>
    );
  }

  if (isError || !data) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    const status = (error as Error & { status?: number })?.status;
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1 px-4 text-center">
        {status === 503 ? (
          <>
            <span className="text-terminal-red font-bold uppercase">Service Unavailable</span>
            <span className="text-white text-[10px]">
              NSE largedeal snapshot is currently unavailable. Please try again later.
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

  const bulkRows = data.BULK_DEALS_DATA ?? [];
  const blockRows = data.BLOCK_DEALS_DATA ?? [];
  const shortRows = data.SHORT_DEALS_DATA ?? [];

  const activeRows =
    activeTab === 'bulk' ? bulkRows : activeTab === 'block' ? blockRows : shortRows;

  const byKey = new Map<string, CompanyGroup>();
  for (const row of activeRows) {
    const symbol = row.symbol;
    const name = row.name;
    const key = `${symbol}::${name}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.rows.push(row);
    } else {
      byKey.set(key, { key, symbol, name, rows: [row] });
    }
  }
  const groups: CompanyGroup[] = Array.from(byKey.values()).sort((a, b) =>
    a.name.localeCompare(b.name),
  );


  const dealTabs: { id: DealTab; count?: number }[] = [
    { id: 'bulk', count: bulkRows.length },
    { id: 'block', count: blockRows.length },
    { id: 'short', count: shortRows.length },
    { id: 'fii' },
  ];

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          NSE Large Deals
        </span>
        <span className="text-white/60 text-[10px]">
          as of {data.as_on_date || '—'}
        </span>
      </div>

      <div className="flex-shrink-0 flex border-b border-terminal-gray/60">
        {dealTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors border-b-2 ${
              activeTab === tab.id
                ? 'bg-terminal-amber text-black font-bold -mb-px'
                : 'text-white/50 hover:text-white hover:bg-zinc-900 border-transparent'
            }`}
            style={activeTab === tab.id ? { borderBottomColor: '#ffb900' } : undefined}
          >
            <DealBadge kind={tab.id} count={tab.count ?? 0} active={activeTab === tab.id} />
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-2 py-1 min-h-0 flex flex-col">
        {activeTab === 'fii' ? (
          fiiLoading ? (
            <div className="flex items-center justify-center h-full w-full text-white/50">Loading FII/DII data...</div>
          ) : fiiError || !fiiData ? (
            <div className="flex items-center justify-center h-full w-full text-terminal-red">Failed to load FII/DII data</div>
          ) : (
            <FiiDiiChart data={fiiData.data} />
          )
        ) : groups.length === 0 ? (
          <div className="text-white/40 text-[10px] py-2 px-1">
            No records for this deal type.
          </div>
        ) : (
          groups.map((group) => (
            <CompanyAccordion
              key={group.key}
              group={group}
              expanded={expandedKeys.has(group.key)}
              onToggle={() => toggleKey(group.key)}
            />
          ))
        )}
      </div>
    </div>
  );
}


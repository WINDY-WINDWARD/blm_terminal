'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

type DealTab = 'bulk' | 'block' | 'short';

interface LargedealRow {
  date: string;
  symbol: string;
  name: string;
  clientName: string | null;
  buySell: 'BUY' | 'SELL' | null;
  qty: string;
  watp: string | number | null;
  remarks: string | null;
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

function DealBadge({ kind, count }: { kind: DealTab; count: number }) {
  const label =
    kind === 'bulk' ? 'Bulk Deals' : kind === 'block' ? 'Block Deals' : 'Short Deals';
  return (
    <span className="inline-flex items-center gap-1 text-[10px]">
      <span>{label}</span>
      <span className="inline-flex items-center justify-center min-w-[18px] h-[14px] rounded-full bg-terminal-gray text-[9px] text-white px-1">
        {count}
      </span>
    </span>
  );
}

interface CompanyAccordionProps {
  group: CompanyGroup;
  expanded: boolean;
  onToggle: () => void;
}

function CompanyAccordion({ group, expanded, onToggle }: CompanyAccordionProps) {
  return (
    <div className="border border-terminal-gray/50 rounded mb-1 overflow-hidden">
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

  const tabs: { id: DealTab; count: number }[] = [
    { id: 'bulk', count: bulkRows.length },
    { id: 'block', count: blockRows.length },
    { id: 'short', count: shortRows.length },
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
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors ${
              activeTab === tab.id
                ? 'bg-blue-900 text-white'
                : 'text-white/50 hover:text-white hover:bg-zinc-900'
            }`}
          >
            <DealBadge kind={tab.id} count={tab.count} />
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {groups.length === 0 ? (
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


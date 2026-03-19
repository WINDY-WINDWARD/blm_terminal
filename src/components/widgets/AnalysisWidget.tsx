'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

type Tab = 'sector' | 'industry';

interface Category {
  category_type: 'industry' | 'sector';
  slug: string;
  name: string;
  market_cap: number;
  pe: number;
  advance: number;
  decline: number;
  sentiment: string;
  earnings_yoy: number;
  last_updated: string;
}

interface Stock {
  id: number;
  symbol: string;
  company_name: string;
  exchange: string;
  curr_price: number;
  per_change: number;
  market_cap: number;
  ttm_pe: number;
  net_profit: number;
  net_profit_yoy: number;
  tech_trend: string;
}

function fmtCrore(value: number | null): string {
  if (value === null || value === undefined) return '—';
  if (value >= 100000) {
    return `${(value / 100000).toFixed(2)}L`;
  }
  return value.toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

function fmtPercent(value: number | null): string {
  if (value === null || value === undefined) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function getSentimentColor(sentiment: string): string {
  switch (sentiment) {
    case 'Bullish':
    case 'Very Bullish':
      return 'text-terminal-green';
    case 'Bearish':
    case 'Very Bearish':
      return 'text-terminal-red';
    default:
      return 'text-white/60';
  }
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '—';
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  } catch {
    return '—';
  }
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 ${
        active
          ? 'bg-terminal-amber text-black font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent'
      }`}
    >
      {label}
    </button>
  );
}

type SortKey = 'market_cap' | 'pe' | 'advance' | 'decline' | 'earnings_yoy' | 'sentiment' | 'name';
type SortDir = 'asc' | 'desc';

interface SortHeaderProps {
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
}

function SortHeader({ sortKey, sortDir, onSort }: SortHeaderProps) {
  const columns: { key: SortKey; label: string; width: string }[] = [
    { key: 'name', label: 'Name', width: 'flex-1 min-w-0' },
    { key: 'market_cap', label: 'MCap', width: 'w-20' },
    { key: 'pe', label: 'PE', width: 'w-10' },
    { key: 'advance', label: 'Advance', width: 'w-10' },
    { key: 'decline', label: 'Decline', width: 'w-10' },
    { key: 'earnings_yoy', label: 'Earn %', width: 'w-14' },
    { key: 'sentiment', label: 'Sentiment', width: 'w-16' },
  ];

  return (
    <div className="flex gap-3 px-2 py-1 bg-zinc-900/60 text-[9px] border-b border-terminal-gray/30 font-mono">
      <span className="flex-1 min-w-0" />
      {columns.slice(1).map((col) => (
        <button
          key={col.key}
          onClick={() => onSort(col.key)}
          className={`flex items-center gap-0.5 ${col.width} justify-end ${
            sortKey === col.key ? 'text-terminal-amber' : 'text-white/40 hover:text-white/60'
          }`}
        >
          {col.label}
          {sortKey === col.key && (
            <span>{sortDir === 'asc' ? '▴' : '▾'}</span>
          )}
        </button>
      ))}
      <span className="w-10 text-right text-white/40">Stks</span>
      <span className="w-12 text-right text-white/40">Updated</span>
      <span className="w-10" />
    </div>
  );
}

interface CategoryAccordionProps {
  category: Category;
  expanded: boolean;
  onToggle: () => void;
  stockCount: number;
}

function CategoryAccordion({ category, expanded, onToggle, stockCount }: CategoryAccordionProps) {
  return (
    <div className="border border-terminal-gray/50 rounded mb-1 overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between px-2 py-1.5 bg-zinc-900 hover:bg-zinc-800 text-left"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="text-terminal-amber font-bold text-[11px] truncate">
            {category.name}
          </span>
        </div>
        <div className="flex items-center gap-3 shrink-0 text-[9px] font-mono">
          <span className="text-white/50 w-20 text-right">
            ₹{fmtCrore(category.market_cap)}
          </span>
          <span className="text-white/60 w-10 text-right">
            {category.pe ? `${category.pe.toFixed(1)}x` : '—'}
          </span>
          <span className="text-terminal-green w-10 text-right">
            {category.advance || 0}▲
          </span>
          <span className="text-terminal-red w-10 text-right">
            {category.decline || 0}▼
          </span>
          <span className={`w-14 text-right ${
            category.earnings_yoy && category.earnings_yoy > 0 ? 'text-terminal-green' :
            category.earnings_yoy && category.earnings_yoy < 0 ? 'text-terminal-red' : 'text-white/50'
          }`}>
            {fmtPercent(category.earnings_yoy)}
          </span>
          <span className={`w-16 ${getSentimentColor(category.sentiment)}`}>
            {category.sentiment}
          </span>
          <span className="w-10 text-right text-white/50">
            {stockCount}
          </span>
          <span className="text-white/40 w-12 text-right">
            {formatRelativeTime(category.last_updated)}
          </span>
          <span className="text-white/50 text-[10px] w-4 text-right">
            {expanded ? '▾' : '▸'}
          </span>
        </div>
      </button>
      {expanded && (
        <StockList categorySlug={category.slug} categoryType={category.category_type} />
      )}
    </div>
  );
}

interface StockListProps {
  categorySlug: string;
  categoryType: 'industry' | 'sector';
}

function StockList({ categorySlug, categoryType }: StockListProps) {
  const endpoint = categoryType === 'industry' 
    ? `/api/py/markets/industries/${categorySlug}/stocks`
    : `/api/py/markets/sectors/${categorySlug}/stocks`;

  const { data: stocks, isLoading, isError } = useQuery<Stock[]>({
    queryKey: ['market/stocks', categoryType, categorySlug],
    queryFn: async () => {
      const res = await fetch(endpoint);
      if (!res.ok) {
        const detail = `Failed to fetch stocks`;
        throw new Error(detail);
      }
      return res.json() as Promise<Stock[]>;
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  if (isLoading) {
    return (
      <div className="bg-black/40 px-2 py-2">
        <div className="text-white/40 text-[10px] animate-pulse">Loading stocks...</div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="bg-black/40 px-2 py-2">
        <div className="text-terminal-red text-[10px]">Failed to load stocks</div>
      </div>
    );
  }

  if (!stocks || stocks.length === 0) {
    return (
      <div className="bg-black/40 px-2 py-2">
        <div className="text-white/40 text-[10px]">No stocks found</div>
      </div>
    );
  }

  return (
    <div className="bg-black/40 px-2 py-1 max-h-48 overflow-y-auto">
      <table className="w-full text-[9px]">
        <thead className="text-white/50 sticky top-0 bg-black/60">
          <tr>
            <th className="text-left py-1 font-normal">Company</th>
            <th className="text-right py-1 font-normal">Price</th>
            <th className="text-right py-1 font-normal">%Chg</th>
            <th className="text-right py-1 font-normal">MCap</th>
            <th className="text-right py-1 font-normal">PE</th>
            <th className="text-right py-1 font-normal">NP Yoy</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((stock) => (
            <tr key={stock.id} className="border-b border-terminal-gray/30 last:border-0">
              <td className="py-1 text-white/80 truncate max-w-[120px]" title={stock.company_name}>
                {stock.company_name}
              </td>
              <td className="text-right py-1 text-white/80 font-mono">
                ₹{stock.curr_price?.toFixed(2) || '—'}
              </td>
              <td className={`text-right py-1 font-mono ${
                stock.per_change && stock.per_change > 0 ? 'text-terminal-green' :
                stock.per_change && stock.per_change < 0 ? 'text-terminal-red' : 'text-white/50'
              }`}>
                {fmtPercent(stock.per_change)}
              </td>
              <td className="text-right py-1 text-white/60 font-mono">
                {fmtCrore(stock.market_cap)}
              </td>
              <td className="text-right py-1 text-white/60 font-mono">
                {stock.ttm_pe?.toFixed(2) || '—'}
              </td>
              <td className={`text-right py-1 font-mono ${
                stock.net_profit_yoy && stock.net_profit_yoy > 0 ? 'text-terminal-green' :
                stock.net_profit_yoy && stock.net_profit_yoy < 0 ? 'text-terminal-red' : 'text-white/50'
              }`}>
                {fmtPercent(stock.net_profit_yoy)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AnalysisWidget() {
  const [activeTab, setActiveTab] = useState<Tab>('sector');
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>('market_cap');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const { data: sectors = [], isLoading: sectorsLoading } = useQuery<Category[]>({
    queryKey: ['market/sectors'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/sectors');
      if (!res.ok) throw new Error('Failed to fetch sectors');
      return res.json() as Promise<Category[]>;
    },
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    enabled: activeTab === 'sector',
  });

  const { data: industries = [], isLoading: industriesLoading } = useQuery<Category[]>({
    queryKey: ['market/industries'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/industries');
      if (!res.ok) throw new Error('Failed to fetch industries');
      return res.json() as Promise<Category[]>;
    },
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    enabled: activeTab === 'industry',
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

  const isLoading = activeTab === 'sector' ? sectorsLoading : industriesLoading;
  const categories = activeTab === 'sector' ? sectors : industries;

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">
          LOADING ANALYSIS...
        </span>
      </div>
    );
  }

  const sortedCategories = [...categories].sort((a, b) => {
    const aVal = sortKey === 'name' ? (a.name || '') : (a[sortKey] ?? (sortKey === 'sentiment' ? '' : 0));
    const bVal = sortKey === 'name' ? (b.name || '') : (b[sortKey] ?? (sortKey === 'sentiment' ? '' : 0));

    if (sortKey === 'name' || sortKey === 'sentiment') {
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      return sortDir === 'asc' ? aStr.localeCompare(bStr) : bStr.localeCompare(aStr);
    }

    return sortDir === 'asc' ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number);
  });

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Market Analysis
        </span>
      </div>

      <div className="flex-shrink-0 flex border-b border-terminal-gray/60">
        <TabButton
          active={activeTab === 'sector'}
          onClick={() => {
            setActiveTab('sector');
            setExpandedKeys(new Set());
          }}
          label="Sector Analysis"
        />
        <TabButton
          active={activeTab === 'industry'}
          onClick={() => {
            setActiveTab('industry');
            setExpandedKeys(new Set());
          }}
          label="Industry Analysis"
        />
      </div>

      <SortHeader sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />

      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {categories.length === 0 ? (
          <div className="text-white/40 text-[10px] py-2 px-1">
            No {activeTab === 'sector' ? 'sectors' : 'industries'} available.
          </div>
        ) : (
          sortedCategories.map((category) => (
            <CategoryAccordion
              key={category.slug}
              category={category}
              expanded={expandedKeys.has(category.slug)}
              onToggle={() => toggleKey(category.slug)}
              stockCount={(category.advance || 0) + (category.decline || 0)}
            />
          ))
        )}
      </div>
    </div>
  );
}

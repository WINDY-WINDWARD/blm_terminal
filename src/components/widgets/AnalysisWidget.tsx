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
      className={`px-4 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors ${
        active
          ? 'bg-terminal-amber text-black font-bold'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900'
      }`}
    >
      {label}
    </button>
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
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-white/50 text-[9px] font-mono">
            MCap: ₹{fmtCrore(category.market_cap)}
          </span>
          <span className={`text-[9px] font-mono ${getSentimentColor(category.sentiment)}`}>
            {category.sentiment}
          </span>
          <span className="inline-flex items-center justify-center min-w-[20px] h-[16px] rounded-full bg-terminal-gray text-[9px] text-white px-1">
            {stockCount}
          </span>
          <span className="text-white/50 text-[10px]">
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

  const sortedCategories = [...categories].sort((a, b) => 
    (b.market_cap || 0) - (a.market_cap || 0)
  );

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

'use client';

import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { useAtom } from 'jotai';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';

type Tab = 'sector' | 'industry' | 'heatmap';

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

type SortKey = 'market_cap' | 'pe' | 'advance' | 'decline' | 'breadth' | 'earnings_yoy' | 'sentiment' | 'name';
type SortDir = 'asc' | 'desc';

function breadthOf(cat: Category): number {
  return (cat.advance || 0) - (cat.decline || 0);
}

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
    { key: 'breadth', label: 'Net A/D', width: 'w-12' },
    { key: 'earnings_yoy', label: 'Earn %', width: 'w-14' },
    { key: 'sentiment', label: 'Sentiment', width: 'w-16' },
  ];

  return (
    <div className="flex gap-3 px-2 py-1 bg-zinc-900/60 text-[9px] border-b border-terminal-gray/30 font-mono min-w-[600px]">
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
    <div className="border border-terminal-gray/50 rounded mb-1 overflow-hidden min-w-[600px]">
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
          <span className={`w-12 text-right font-mono ${
            breadthOf(category) > 0 ? 'text-terminal-green' :
            breadthOf(category) < 0 ? 'text-terminal-red' : 'text-white/50'
          }`}>
            {breadthOf(category) > 0 ? `+${breadthOf(category)}` : `${breadthOf(category)}`}
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
  maxHeightClass?: string;
}

function StockList({ categorySlug, categoryType, maxHeightClass = 'max-h-48' }: StockListProps) {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
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
    <div className={`bg-black/40 px-2 py-1 ${maxHeightClass} overflow-y-auto`}>
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
              <td className="py-1 text-white/80 max-w-[120px]" title={`${stock.company_name} — set as active symbol`}>
                <button
                  type="button"
                  onClick={() => {
                    setActiveSymbol(stock.symbol);
                    setActiveExchange(stock.exchange || 'NSE');
                  }}
                  className="truncate max-w-full text-left hover:text-terminal-amber hover:underline cursor-pointer"
                >
                  {stock.company_name}
                </button>
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

interface CategoryStocksModalProps {
  category: Category;
  onClose: () => void;
}

function CategoryStocksModal({ category, onClose }: CategoryStocksModalProps) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (typeof document === 'undefined') return null;
  return ReactDOM.createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded border border-[#2d3139] bg-[#121418] p-6 text-[#e1e4ea] shadow-2xl font-mono max-h-[90vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="rounded bg-[#1a1d23] border border-[#2d3139] p-3 flex items-center gap-3 mb-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-terminal-amber font-bold text-[13px] truncate">
                {category.name}
              </span>
              <span className="shrink-0 text-[9px] uppercase px-1.5 py-0.5 rounded border border-[#2d3139] text-white/50">
                {category.category_type}
              </span>
            </div>
            <div className="flex items-center gap-3 mt-1 text-[10px] text-white/60">
              <span>MCap ₹{fmtCrore(category.market_cap)} Cr</span>
              <span>
                <span className="text-terminal-green">{category.advance || 0}▲</span>
                {' / '}
                <span className="text-terminal-red">{category.decline || 0}▼</span>
              </span>
              <span>P/E {category.pe ? `${category.pe.toFixed(1)}x` : '—'}</span>
              <span className={getSentimentColor(category.sentiment)}>
                {category.sentiment || '—'}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded px-2.5 py-1 text-xs text-[#9ca3af] hover:text-white bg-[#1a1d23] hover:bg-[#252830] transition border border-[#2d3139]"
          >
            ✕
          </button>
        </div>
        <div className="overflow-y-auto min-h-0 rounded border border-[#2d3139]">
          <StockList
            categorySlug={category.slug}
            categoryType={category.category_type}
            maxHeightClass="max-h-[50vh]"
          />
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function AnalysisWidget() {
  const [activeTab, setActiveTab] = useState<Tab>('sector');
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [sortKey, setSortKey] = useState<SortKey>('breadth');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // Rebuild cadence mirrors the backend market_data scheduler (every 20 min
  // in live trading hours) so the widget picks up fresh aggregates on its own.
  const { data: sectors = [], isLoading: sectorsLoading } = useQuery<Category[]>({
    queryKey: ['market/sectors'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/sectors');
      if (!res.ok) throw new Error('Failed to fetch sectors');
      return res.json() as Promise<Category[]>;
    },
    staleTime: 10 * 60 * 1000,
    refetchInterval: 20 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const { data: industries = [], isLoading: industriesLoading } = useQuery<Category[]>({
    queryKey: ['market/industries'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/industries');
      if (!res.ok) throw new Error('Failed to fetch industries');
      return res.json() as Promise<Category[]>;
    },
    staleTime: 10 * 60 * 1000,
    refetchInterval: 20 * 60 * 1000,
    refetchOnWindowFocus: false,
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

  const [heatmapMetric, setHeatmapMetric] = useState<'breadth' | 'earnings' | 'sentiment'>('breadth');
  const [hoveredTile, setHoveredTile] = useState<{
    item: Category;
    rect: DOMRect;
  } | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<Category | null>(null);

  const isLoading = (activeTab === 'sector' || activeTab === 'heatmap') ? sectorsLoading : industriesLoading;
  const categories = activeTab === 'sector' ? sectors : industries;

  const heatmapCategories = [...sectors, ...industries].filter(
    (item, index, self) => index === self.findIndex((t) => t.slug === item.slug)
  );
  const totalMCap = heatmapCategories.reduce((acc, c) => acc + (c.market_cap || 0), 0) || 1;

  if (isLoading && categories.length === 0) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">
          LOADING ANALYSIS...
        </span>
      </div>
    );
  }

  const sortedCategories = [...categories].sort((a, b) => {    if (sortKey === 'breadth') {
      const diff = breadthOf(a) - breadthOf(b);
      return sortDir === 'asc' ? diff : -diff;
    }
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

  const getTileBg = (cat: Category) => {
    if (heatmapMetric === 'earnings') {
      const yoy = cat.earnings_yoy || 0;
      if (yoy > 20) return 'bg-emerald-600';
      if (yoy > 5) return 'bg-emerald-800/80';
      if (yoy < -20) return 'bg-rose-600';
      if (yoy < -5) return 'bg-rose-800/80';
      return 'bg-zinc-800';
    }
    if (heatmapMetric === 'sentiment') {
      if (cat.sentiment === 'Bullish' || cat.sentiment === 'Very Bullish') return 'bg-emerald-700';
      if (cat.sentiment === 'Bearish' || cat.sentiment === 'Very Bearish') return 'bg-rose-700';
      return 'bg-zinc-800';
    }
    // breadth default
    const adv = cat.advance || 0;
    const dec = cat.decline || 0;
    const tot = adv + dec || 1;
    const net = (adv - dec) / tot;
    if (net > 0.3) return 'bg-emerald-600 text-white';
    if (net > 0.1) return 'bg-emerald-800/70 text-emerald-200';
    if (net < -0.3) return 'bg-rose-600 text-white';
    if (net < -0.1) return 'bg-rose-800/70 text-rose-200';
    return 'bg-zinc-800 text-zinc-300';
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-baseline justify-between gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase">
          Market Analysis
        </span>
        {activeTab === 'heatmap' && (
          <div className="flex items-center gap-1.5 text-[10px]">
            <span className="text-white/40 uppercase">Color By:</span>
            <select
              value={heatmapMetric}
              onChange={(e) => setHeatmapMetric(e.target.value as any)}
              className="bg-zinc-900 border border-terminal-gray/60 text-terminal-amber text-[10px] px-1 py-0.5 rounded outline-none"
            >
              <option value="breadth">Advance / Decline</option>
              <option value="earnings">Earnings YoY</option>
              <option value="sentiment">Sentiment</option>
            </select>
          </div>
        )}
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
        <TabButton
          active={activeTab === 'heatmap'}
          onClick={() => {
            setActiveTab('heatmap');
            setExpandedKeys(new Set());
          }}
          label="Heatmap"
        />
      </div>

      {activeTab !== 'heatmap' && (
        <SortHeader sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
      )}

      <div className="flex-1 overflow-auto p-1 min-h-0">
        {activeTab === 'heatmap' ? (
          <div className="flex flex-wrap gap-1 p-1 bg-black/40 min-h-full content-start">
            {heatmapCategories.map((cat) => {
              const mCap = cat.market_cap || 0;
              // Log1p scaling clamped to 18% max, minimum width/height for readable tile
              const pct = Math.max(4, Math.min(18, (Math.log1p(mCap) / Math.log1p(totalMCap)) * 100));
              const adv = cat.advance || 0;
              const dec = cat.decline || 0;
              const tot = adv + dec || 1;
              const net = (adv - dec) / tot;

              return (
                <div
                  key={cat.slug}
                  onMouseEnter={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect();
                    setHoveredTile({ item: cat, rect });
                  }}
                  onMouseLeave={() => setHoveredTile(null)}
                  onClick={() => {
                    setHoveredTile(null);
                    setSelectedCategory(cat);
                  }}
                  className={`flex-1 min-w-[76px] min-h-[64px] border border-white/10 rounded-sm p-1 flex flex-col justify-between cursor-pointer transition-all hover:border-terminal-amber/80 ${getTileBg(
                    cat,
                  )}`}
                  style={{ flexBasis: `${pct.toFixed(1)}%` }}
                >
                  <div className="text-[10px] font-bold leading-tight line-clamp-2">
                    {cat.name}
                  </div>
                  <div className="flex flex-col text-[9px] opacity-80 mt-1">
                    <span className="font-mono">{fmtCrore(cat.market_cap)} Cr</span>
                    <span className="text-[8px]">
                      A:{cat.advance} D:{cat.decline} ({net > 0 ? '+' : ''}{(net * 100).toFixed(0)}%)
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : categories.length === 0 ? (
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

      {activeTab !== 'heatmap' && categories.length > 0 &&
        categories.every((c) => c.market_cap == null) && (
        <div className="flex-shrink-0 px-3 py-1 border-t border-terminal-gray/60 text-[10px] text-white/40">
          Market caps populate after the first full sync — trigger market_caps or fundamentals from Jobs.
        </div>
      )}

      {selectedCategory && (
        <CategoryStocksModal
          category={selectedCategory}
          onClose={() => setSelectedCategory(null)}
        />
      )}

      {hoveredTile && typeof document !== 'undefined' && ReactDOM.createPortal(
        <div
          className="fixed z-[99999] pointer-events-none"
          style={{
            left: Math.min(hoveredTile.rect.left, window.innerWidth - 220),
            top: hoveredTile.rect.top - 6,
            transform: 'translateY(-100%)',
          }}
        >
          <div className="bg-zinc-900 border border-terminal-amber/60 rounded shadow-2xl p-2 max-w-64 mb-1 text-[10px] font-mono text-white">
            <div className="text-terminal-amber font-bold border-b border-terminal-gray/40 pb-1 mb-1">
              {hoveredTile.item.name} ({hoveredTile.item.category_type})
            </div>
            <div className="flex justify-between py-0.5">
              <span className="text-white/50">Market Cap:</span>
              <span className="text-white font-bold">{fmtCrore(hoveredTile.item.market_cap)} Cr</span>
            </div>
            <div className="flex justify-between py-0.5">
              <span className="text-white/50">Advance / Decline:</span>
              <span>
                <span className="text-terminal-green">{hoveredTile.item.advance}</span> /{' '}
                <span className="text-terminal-red">{hoveredTile.item.decline}</span>
              </span>
            </div>
            <div className="flex justify-between py-0.5">
              <span className="text-white/50">P/E:</span>
              <span>{hoveredTile.item.pe ? hoveredTile.item.pe.toFixed(1) : '—'}</span>
            </div>
            <div className="flex justify-between py-0.5">
              <span className="text-white/50">Earnings YoY:</span>
              <span className={hoveredTile.item.earnings_yoy > 0 ? 'text-terminal-green' : hoveredTile.item.earnings_yoy < 0 ? 'text-terminal-red' : ''}>
                {fmtPercent(hoveredTile.item.earnings_yoy)}
              </span>
            </div>
            <div className="flex justify-between py-0.5">
              <span className="text-white/50">Sentiment:</span>
              <span className={getSentimentColor(hoveredTile.item.sentiment)}>{hoveredTile.item.sentiment || '—'}</span>
            </div>
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useAtom, useAtomValue } from 'jotai';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  activeSymbolAtom,
  newsWsConnectedAtom,
  liveNewsArticlesAtom,
  newsFiltersAtom,
} from '@/store/terminalStore';
import { newsSocketService } from '@/lib/newsSocket';
import type { NewsArticle } from '@/lib/newsSocket';

interface NewsPaginatedResponse {
  articles: NewsArticle[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

type Tab = 'global' | 'company';
const PAGE_LIMIT = 50;

const SOURCE_LABELS: Record<string, string> = {
  // Tier 1: Wire & Regulatory
  'ap-top': 'AP',
  'sec-press': 'SEC',
  'fed-press': 'Fed',
  'ecb-press': 'ECB',
  'boe-news': 'BoE',
  // Tier 1: Financial Media
  'bloomberg-mkts': 'Bloomberg',
  'wsj-markets': 'WSJ',
  'cnbc-finance': 'CNBC',
  // Tier 2: India
  'moneycontrol': 'MC',
  'et-markets': 'ET',
  'livemint': 'Mint',
  'hindu-biz': 'Hindu',
  // Tier 2: Global Markets
  'marketwatch': 'MW',
  'seekingalpha': 'SA',
  'investing-news': 'Investing',
  'benzinga': 'Benzinga',
  'bbc-business': 'BBC Biz',
  'nikkei-asia': 'Nikkei',
  'cna': 'CNA',
  'economist': 'Economist',
  'aljazeera': 'AJ',
  'foreignpolicy': 'FP',
  // Tier 2: Crypto
  'coindesk': 'CoinDesk',
  'cointelegraph': 'CT',
  'theblock': 'TheBlock',
  // Tier 2: Tech
  'techcrunch': 'TC',
  'finextra': 'Finextra',
  'theverge': 'Verge',
  'arstechnica': 'Ars',
  // Tier 3: Additional
  'bbc-world': 'BBC World',
  'calculated-risk': 'CalcRisk',
  'zero-hedge': 'ZH',
  'bellingcat': 'Bellingcat',
  'hackernews': 'HN',
  'abnormal-returns': 'AR',
  // MoneyControl scraped
  'moneycontrol_global': 'MC Global',
  'moneycontrol_company': 'MC Company',
};

const SENTIMENT_COLORS: Record<string, string> = {
  BULLISH: 'bg-green-500',
  BEARISH: 'bg-red-500',
  NEUTRAL: 'bg-gray-500',
};

const THREAT_BADGES: Record<string, { label: string; className: string }> = {
  low: { label: 'LOW', className: 'bg-green-900 text-green-400' },
  medium: { label: 'MED', className: 'bg-yellow-900 text-yellow-400' },
  high: { label: 'HIGH', className: 'bg-red-900 text-red-400' },
  critical: { label: 'CRIT', className: 'bg-red-900 text-red-400 font-bold' },
};

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-IN', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}

function SourceBadge({ sourceId }: { sourceId: string | null }) {
  const label = sourceId ? SOURCE_LABELS[sourceId] || sourceId : '?';
  return (
    <span className="text-[10px] text-terminal-amber/60 shrink-0 font-mono">
      {label}
    </span>
  );
}

function SentimentDot({ sentiment, score }: { sentiment: string | null; score: number | null }) {
  const color = sentiment ? SENTIMENT_COLORS[sentiment] || 'bg-gray-500' : 'bg-gray-500';
  const opacity = score !== null && score !== undefined ? Math.max(0.3, Math.min(1, score)) : 0.5;
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${color}`}
      style={{ opacity }}
      title={`${sentiment || 'unknown'} (${score?.toFixed(2) || '?'})`}
    />
  );
}

function ThreatBadge({ level }: { level: string | null }) {
  if (!level) return null;
  const badge = THREAT_BADGES[level.toLowerCase()];
  if (!badge) return null;
  return (
    <span className={`text-[8px] px-1 py-0.5 rounded font-bold ${badge.className}`}>
      {badge.label}
    </span>
  );
}

function CredibilityWarning({ credibility }: { credibility: string | null }) {
  if (!credibility || credibility === 'NONE') return null;
  return (
    <span className="text-[8px] text-yellow-500 ml-1" title={`Credibility: ${credibility}`}>
      ⚠
    </span>
  );
}

function ArticleRow({
  article,
  showSentiment = true,
}: {
  article: NewsArticle;
  showSentiment?: boolean;
}) {
  const title = article.title ?? 'Untitled';
  const date = formatDate(article.publish_date);
  const sourceId = article.source;
  const credibility = article.source_credibility;

  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      className="block border-b border-terminal-gray/40 hover:bg-zinc-900 py-2 px-1 cursor-pointer"
    >
      <div className="flex items-start gap-2">
        <span className="text-[10px] text-white/50 shrink-0 font-mono w-20">
          {date}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          <SourceBadge sourceId={sourceId} />
          {showSentiment && (
            <SentimentDot sentiment={article.sentiment} score={article.sentiment_score} />
          )}
        </div>
        <div className="flex items-center gap-1 flex-1 min-w-0">
          <span className="text-xs text-terminal-amber font-medium leading-tight truncate">
            {title}
          </span>
          <ThreatBadge level={article.threat_level} />
          <CredibilityWarning credibility={credibility} />
        </div>
      </div>
    </a>
  );
}

function SourceFilterChips({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (sources: string[]) => void;
}) {
  const allSources = Object.keys(SOURCE_LABELS);

  const toggle = (sourceId: string) => {
    if (selected.includes(sourceId)) {
      onChange(selected.filter((s) => s !== sourceId));
    } else {
      onChange([...selected, sourceId]);
    }
  };

  return (
    <div className="flex flex-wrap gap-1 px-1 py-1 border-b border-terminal-gray/30">
      {allSources.map((id) => (
        <button
          key={id}
          onClick={() => toggle(id)}
          className={`text-[9px] px-1.5 py-0.5 rounded border transition-colors ${
            selected.includes(id)
              ? 'bg-terminal-amber text-black border-terminal-amber font-bold'
              : 'text-white/50 border-terminal-gray/40 hover:text-terminal-amber hover:border-terminal-amber'
          }`}
        >
          {SOURCE_LABELS[id]}
        </button>
      ))}
      {selected.length > 0 && (
        <button
          onClick={() => onChange([])}
          className="text-[9px] px-1.5 py-0.5 text-white/40 hover:text-terminal-amber"
        >
          Clear
        </button>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
  live,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  live?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 flex items-center gap-1 ${
        active
          ? 'bg-terminal-amber text-black font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent'
      }`}
    >
      {label}
      {live && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
        </span>
      )}
    </button>
  );
}

export function NewsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const [wsConnected, setWsConnected] = useAtom(newsWsConnectedAtom);
  const [liveArticles, setLiveArticles] = useAtom(liveNewsArticlesAtom);
  const [filters, setFilters] = useAtom(newsFiltersAtom);

  const [activeTab, setActiveTab] = useState<Tab>('global');
  const [globalOffset, setGlobalOffset] = useState(0);
  const [companyOffset, setCompanyOffset] = useState(0);
  const queryClient = useQueryClient();

  useEffect(() => {
    newsSocketService.connect();

    const unsubConnection = newsSocketService.onConnectionChange((connected) => {
      setWsConnected(connected);
      if (connected) {
        newsSocketService.getRecent(50);
      }
    });

    const unsubNews = newsSocketService.onNews((article) => {
      setLiveArticles((prev) => {
        const exists = prev.some((a) => a.url === article.url);
        if (exists) return prev;
        const updated = [article, ...prev];
        return updated.slice(0, 100);
      });
    });

    return () => {
      unsubConnection();
      unsubNews();
    };
  }, [setLiveArticles, setWsConnected]);

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    if (tab === 'global') setGlobalOffset(0);
    if (tab === 'company') setCompanyOffset(0);
  };

  const handleRefresh = async () => {
    await queryClient.cancelQueries({ queryKey: ['news/company', symbol] });
    await fetch('/api/py/news/company', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol }),
    });
    setCompanyOffset(0);
    await queryClient.refetchQueries({ queryKey: ['news/company', symbol] });
  };

  const {
    data: globalData,
    isLoading: globalLoading,
    error: globalError,
  } = useQuery<NewsPaginatedResponse>({
    queryKey: ['news/all', { limit: PAGE_LIMIT, offset: globalOffset }],
    queryFn: async () => {
      const res = await fetch(`/api/py/news/all?limit=${PAGE_LIMIT}&offset=${globalOffset}`);
      if (!res.ok) throw new Error('Failed to fetch global news');
      return res.json() as Promise<NewsPaginatedResponse>;
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    enabled: activeTab === 'global',
  });

  const {
    data: companyData,
    isLoading: companyLoading,
    isFetching: companyFetching,
    error: companyError,
  } = useQuery<NewsPaginatedResponse>({
    queryKey: ['news/company', symbol, { limit: PAGE_LIMIT, offset: companyOffset }],
    queryFn: async () => {
      const res = await fetch(`/api/py/news/company/${encodeURIComponent(symbol)}?limit=${PAGE_LIMIT}&offset=${companyOffset}`);
      if (res.status === 404) {
        const postRes = await fetch('/api/py/news/company', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol }),
        });
        if (!postRes.ok) {
          throw new Error('Failed to fetch company news');
        }
        return postRes.json() as Promise<NewsPaginatedResponse>;
      }
      if (!res.ok) throw new Error('Failed to fetch company news');
      return res.json() as Promise<NewsPaginatedResponse>;
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    enabled: activeTab === 'company' && !!symbol,
    retry: false,
  });

  const isLoading = activeTab === 'global' ? globalLoading : companyLoading;
  const isRefreshing = activeTab === 'company' && companyFetching && !companyLoading;
  const error = activeTab === 'global' ? globalError : companyError;

  const currentData = activeTab === 'global' ? globalData : companyData;
  const dbArticles = currentData?.articles || [];
  const total = currentData?.total || 0;
  const currentOffset = activeTab === 'global' ? globalOffset : companyOffset;
  const setOffset = activeTab === 'global' ? setGlobalOffset : setCompanyOffset;
  const hasMore = currentData?.has_more || false;

  const filteredLiveArticles = useCallback(() => {
    return liveArticles.filter((a) => {
      if (filters.sources.length > 0 && !filters.sources.includes(a.source || '')) return false;
      if (filters.sentiment && a.sentiment !== filters.sentiment) return false;
      if (filters.threatLevel && a.threat_level !== filters.threatLevel) return false;
      return true;
    });
  }, [liveArticles, filters])();

  const handlePrevPage = () => {
    setOffset((prev: number) => Math.max(0, prev - PAGE_LIMIT));
  };

  const handleNextPage = () => {
    if (hasMore) {
      setOffset((prev: number) => prev + PAGE_LIMIT);
    }
  };

  const handleSourceFilterChange = (sources: string[]) => {
    setFilters((prev) => ({ ...prev, sources }));
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden">
      <div className="flex border-b border-terminal-gray shrink-0">
        <TabButton
          active={activeTab === 'global'}
          onClick={() => handleTabChange('global')}
          label="Global"
          live={wsConnected && activeTab === 'global'}
        />
        <TabButton
          active={activeTab === 'company'}
          onClick={() => handleTabChange('company')}
          label="Company"
        />
        {activeTab === 'company' && symbol && (
          <span className="ml-auto flex items-center gap-1 pr-1 py-1 text-[10px] text-terminal-amber">
            <span>{symbol}</span>
            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="p-0.5 hover:bg-zinc-700 rounded disabled:opacity-40 transition-opacity"
              title="Force refresh"
            >
              <svg
                viewBox="0 0 16 16"
                width="10"
                height="10"
                fill="currentColor"
                className={isRefreshing ? 'animate-spin' : ''}
              >
                <path d="M8 3a5 5 0 1 0 4.546 2.914.5.5 0 1 1 .908-.418A6 6 0 1 1 8 2v1z" />
                <path d="M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z" />
              </svg>
            </button>
          </span>
        )}
      </div>

      {activeTab === 'global' && (
        <SourceFilterChips
          selected={filters.sources}
          onChange={handleSourceFilterChange}
        />
      )}

      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="h-full w-full flex flex-col items-center justify-center gap-1">
            <span className="text-terminal-amber/60 animate-pulse text-[10px]">
              {activeTab === 'company' && !symbol
                ? 'SELECT A SYMBOL'
                : 'LOADING NEWS...'}
            </span>
            {activeTab === 'company' && symbol && (
              <span className="text-white/40 text-[10px]">{symbol}</span>
            )}
          </div>
        ) : error ? (
          <div className="h-full w-full flex flex-col items-center justify-center gap-1 px-4 text-center">
            <span className="text-terminal-red font-bold uppercase text-[10px]">
              Error
            </span>
            <span className="text-white/60 text-[10px]">
              {error instanceof Error ? error.message : 'Unknown error'}
            </span>
          </div>
        ) : !symbol && activeTab === 'company' ? (
          <div className="h-full w-full flex items-center justify-center">
            <span className="text-white/40 text-[10px]">
              Select a symbol to view company news
            </span>
          </div>
        ) : (
          <div className="flex flex-col h-full">
            {activeTab === 'global' && filteredLiveArticles.length > 0 && (
              <div className="border-b border-terminal-gray/40 pb-1">
                <div className="text-[9px] text-green-500 px-2 pt-1 flex items-center gap-1">
                  <span className="inline-flex h-1.5 w-1.5 rounded-full bg-green-500"></span>
                  LIVE
                </div>
                {filteredLiveArticles.slice(0, 5).map((article) => (
                  <ArticleRow key={article.url + '_live'} article={article} />
                ))}
              </div>
            )}
            <div className="flex-1 overflow-auto">
              {(activeTab === 'global' ? dbArticles : dbArticles).length === 0 ? (
                <div className="h-full w-full flex items-center justify-center">
                  <span className="text-white/40 text-[10px]">No articles found</span>
                </div>
              ) : (
                dbArticles.map((article, idx) => (
                  <ArticleRow key={article.url + idx} article={article} />
                ))
              )}
            </div>
            {total > 0 && (
              <div className="shrink-0 border-t border-terminal-gray/40 px-2 py-1.5 flex items-center justify-between text-[10px] text-white/60">
                <button
                  onClick={handlePrevPage}
                  disabled={currentOffset === 0}
                  className="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed rounded transition-colors"
                >
                  Prev
                </button>
                <span className="font-mono">
                  {currentOffset + 1}-{Math.min(currentOffset + PAGE_LIMIT, total)} of {total}
                </span>
                <button
                  onClick={handleNextPage}
                  disabled={!hasMore}
                  className="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed rounded transition-colors"
                >
                  Next
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
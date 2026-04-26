'use client';

import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { activeSymbolAtom } from '@/store/terminalStore';

interface NewsArticle {
  url: string;
  title: string | null;
  text: string | null;
  publish_date: string | null;
  fetched_at: string | null;
  company_symbol: string | null;
  source: string | null;
  top_image: string | null;
  authors: string | null;
}

interface NewsPaginatedResponse {
  articles: NewsArticle[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

type Tab = 'global' | 'company';

const PAGE_LIMIT = 50;

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

function ArticleRow({ article }: { article: NewsArticle }) {
  const title = article.title ?? 'Untitled';
  const date = formatDate(article.publish_date);
  const source = article.source === 'moneycontrol_global' ? 'MC Global' : 'MC Co.';

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
        <span className="text-[10px] text-terminal-amber/60 shrink-0 font-mono">
          {source}
        </span>
        <span className="text-xs text-terminal-amber font-medium leading-tight">
          {title}
        </span>
      </div>
    </a>
  );
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
      className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 ${
        active
          ? 'bg-terminal-amber text-black font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent'
      }`}
    >
      {label}
    </button>
  );
}

export function NewsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const [activeTab, setActiveTab] = useState<Tab>('global');
  const [globalOffset, setGlobalOffset] = useState(0);
  const [companyOffset, setCompanyOffset] = useState(0);
  const queryClient = useQueryClient();

  // Reset offsets when switching tabs or changing symbol
  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab);
    if (tab === 'global') setGlobalOffset(0);
    if (tab === 'company') setCompanyOffset(0);
  };

  // Reset company offset when symbol changes
  React.useEffect(() => {
    if (activeTab === 'company') {
      setCompanyOffset(0);
    }
  }, [symbol, activeTab]);

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
    queryKey: ['news/global', { limit: PAGE_LIMIT, offset: globalOffset }],
    queryFn: async () => {
      const res = await fetch(`/api/py/news/global?limit=${PAGE_LIMIT}&offset=${globalOffset}`);
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
  const articles = currentData?.articles || [];
  const total = currentData?.total || 0;
  const currentOffset = activeTab === 'global' ? globalOffset : companyOffset;
  const setOffset = activeTab === 'global' ? setGlobalOffset : setCompanyOffset;
  const hasMore = currentData?.has_more || false;

  const handlePrevPage = () => {
    setOffset((prev: number) => Math.max(0, prev - PAGE_LIMIT));
  };

  const handleNextPage = () => {
    if (hasMore) {
      setOffset((prev: number) => prev + PAGE_LIMIT);
    }
  };

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden">
      {/* Tab Bar */}
      <div className="flex border-b border-terminal-gray shrink-0">
        <TabButton
          active={activeTab === 'global'}
          onClick={() => handleTabChange('global')}
          label="Global"
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

      {/* Content */}
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
        ) : articles.length === 0 ? (
          <div className="h-full w-full flex items-center justify-center">
            <span className="text-white/40 text-[10px]">No articles found</span>
          </div>
        ) : (
          <div className="flex flex-col h-full">
            <div className="flex-1 overflow-auto">
              {articles.map((article, idx) => (
                <ArticleRow key={article.url + idx} article={article} />
              ))}
            </div>
            {/* Pagination Controls */}
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

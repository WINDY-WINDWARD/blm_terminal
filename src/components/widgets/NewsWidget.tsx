'use client';

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
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

type Tab = 'global' | 'company';

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
      className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors ${
        active
          ? 'bg-terminal-amber text-black font-bold'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900'
      }`}
    >
      {label}
    </button>
  );
}

export function NewsWidget() {
  const symbol = useAtomValue(activeSymbolAtom);
  const [activeTab, setActiveTab] = useState<Tab>('global');

  const {
    data: globalArticles = [],
    isLoading: globalLoading,
    error: globalError,
  } = useQuery<NewsArticle[]>({
    queryKey: ['news/global'],
    queryFn: async () => {
      const res = await fetch('/api/py/news/global');
      if (!res.ok) throw new Error('Failed to fetch global news');
      return res.json() as Promise<NewsArticle[]>;
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    enabled: activeTab === 'global',
  });

  const {
    data: companyArticles = [],
    isLoading: companyLoading,
    error: companyError,
  } = useQuery<NewsArticle[]>({
    queryKey: ['news/company', symbol],
    queryFn: async () => {
      const res = await fetch(`/api/py/news/company/${encodeURIComponent(symbol)}`);
      if (res.status === 404) {
        const postRes = await fetch('/api/py/news/company', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol }),
        });
        if (!postRes.ok) {
          throw new Error('Failed to fetch company news');
        }
        return postRes.json() as Promise<NewsArticle[]>;
      }
      if (!res.ok) throw new Error('Failed to fetch company news');
      return res.json() as Promise<NewsArticle[]>;
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
    enabled: activeTab === 'company' && !!symbol,
    retry: false,
  });

  const isLoading = activeTab === 'global' ? globalLoading : companyLoading;
  const error = activeTab === 'global' ? globalError : companyError;
  const articles = activeTab === 'global' ? globalArticles : companyArticles;

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden">
      {/* Tab Bar */}
      <div className="flex border-b border-terminal-gray shrink-0">
        <TabButton
          active={activeTab === 'global'}
          onClick={() => setActiveTab('global')}
          label="Global"
        />
        <TabButton
          active={activeTab === 'company'}
          onClick={() => setActiveTab('company')}
          label="Company"
        />
        {activeTab === 'company' && symbol && (
          <span className="ml-auto pr-2 py-1 text-[10px] text-terminal-amber">
            {symbol}
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
          <div className="flex flex-col">
            {articles.map((article, idx) => (
              <ArticleRow key={article.url + idx} article={article} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

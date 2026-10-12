'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAtom } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import {
  activeExchangeAtom,
  activeSymbolAtom,
  newsWsConnectedAtom,
  liveNewsArticlesAtom,
  newsFiltersAtom,
  advancedScrapingConsentAtom,
} from '@/store/terminalStore';
import { newsSocketService } from '@/lib/newsSocket';
import type { NewsArticle } from '@/lib/newsSocket';
import { isExternalClick, openLink } from '@/lib/openLink';

interface NewsPaginatedResponse {
  articles: NewsArticle[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  source_used?: 'iinvest' | 'moneycontrol' | 'merged' | null;
}

const PAGE_LIMIT = 50;
const ENTITY_CHIP_LIMIT = 3;

export const SOURCE_LABELS: Record<string, string> = {
  // Tier 1: Wire & Regulatory
  'ap-top': 'AP',
  'reuters': 'REUTERS',
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

export const SOURCE_FULL_NAMES: Record<string, string> = {
  'ap-top': 'Associated Press Top News',
  'reuters': 'Reuters Financial Wire',
  'sec-press': 'SEC Press Releases',
  'fed-press': 'Federal Reserve',
  'ecb-press': 'ECB Press',
  'boe-news': 'Bank of England',
  'bloomberg-mkts': 'Bloomberg Markets',
  'wsj-markets': 'WSJ Markets',
  'cnbc-finance': 'CNBC Finance',
  'moneycontrol': 'MoneyControl',
  'et-markets': 'Economic Times',
  'livemint': 'LiveMint',
  'hindu-biz': 'The Hindu Business',
  'marketwatch': 'MarketWatch',
  'seekingalpha': 'Seeking Alpha',
  'investing-news': 'Investing.com',
  'benzinga': 'Benzinga',
  'bbc-business': 'BBC Business',
  'nikkei-asia': 'Nikkei Asia',
  'cna': 'Channel News Asia',
  'economist': 'The Economist',
  'aljazeera': 'Al Jazeera',
  'foreignpolicy': 'Foreign Policy',
  'coindesk': 'CoinDesk',
  'cointelegraph': 'CoinTelegraph',
  'theblock': 'The Block',
  'techcrunch': 'TechCrunch',
  'finextra': 'Finextra',
  'theverge': 'The Verge',
  'arstechnica': 'Ars Technica',
  'bbc-world': 'BBC World',
  'calculated-risk': 'Calculated Risk',
  'zero-hedge': 'ZeroHedge',
  'bellingcat': 'Bellingcat',
  'hackernews': 'Hacker News',
  'abnormal-returns': 'Abnormal Returns',
  'moneycontrol_global': 'MoneyControl Global',
  'moneycontrol_company': 'MoneyControl Company',
};

const SENTIMENT_COLORS: Record<string, string> = {
  BULLISH: 'bg-emerald-400',
  BEARISH: 'bg-rose-400',
  NEUTRAL: 'bg-zinc-400',
};

const SENTIMENT_BADGE_STYLES: Record<string, string> = {
  BULLISH: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30',
  BEARISH: 'bg-rose-500/10 text-rose-400 border border-rose-500/30',
  NEUTRAL: 'bg-zinc-500/10 text-zinc-300 border border-zinc-500/30',
};

const THREAT_BADGES: Record<string, { label: string; className: string }> = {
  low: { label: 'LOW', className: 'bg-emerald-950 text-emerald-400 border border-emerald-500/30' },
  medium: { label: 'MED', className: 'bg-amber-950 text-amber-400 border border-amber-500/30' },
  high: { label: 'HIGH', className: 'bg-rose-950 text-rose-400 border border-rose-500/30' },
  critical: { label: 'CRIT', className: 'bg-rose-950 text-rose-400 border border-rose-500/40 font-bold' },
};

const PRIMARY_SOURCE_PILLS: Array<{ id: string; label: string }> = [
  { id: 'ap-top', label: 'AP' },
  { id: 'bloomberg-mkts', label: 'BLOOMBERG' },
  { id: 'moneycontrol', label: 'MC' },
  { id: 'reuters', label: 'REUTERS' },
  { id: 'et-markets', label: 'ET' },
  { id: 'wsj-markets', label: 'WSJ' },
  { id: 'cnbc-finance', label: 'CNBC' },
  { id: 'sec-press', label: 'SEC' },
  { id: 'livemint', label: 'MINT' },
];


function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    return d.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '—';
  }
}

function formatRelativeTimestamp(iso: string | null): string {
  if (!iso) return 'LIVE';
  try {
    const d = new Date(iso);
    const ts = d.getTime();
    if (Number.isNaN(ts)) return 'LIVE';
    const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDays = Math.floor(diffHr / 24);
    return `${diffDays}d ago`;
  } catch {
    return 'LIVE';
  }
}

function getSourceBadgePalette(sourceId: string | null): string {
  const id = (sourceId || '').toLowerCase();
  if (id.includes('bloomberg')) {
    return 'bg-amber-500/10 text-amber-400 border border-amber-500/25';
  }
  if (id.includes('reuters') || id.includes('cnbc') || id.includes('wsj')) {
    return 'bg-blue-500/10 text-blue-400 border border-blue-500/25';
  }
  if (id.includes('moneycontrol') || id.includes('et-markets') || id.includes('livemint')) {
    return 'bg-purple-500/10 text-purple-400 border border-purple-500/25';
  }
  if (id.includes('sec') || id.includes('fed') || id.includes('ecb') || id.includes('boe')) {
    return 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/25';
  }
  return 'bg-zinc-500/10 text-zinc-300 border border-zinc-500/25';
}

function SourceBadge({ sourceId }: { sourceId: string | null }) {
  const rawLabel = sourceId ? SOURCE_LABELS[sourceId] || sourceId : 'WIRE';
  const label = rawLabel.toUpperCase();
  return (
    <span
      className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold tracking-wider shrink-0 ${getSourceBadgePalette(
        sourceId
      )}`}
      title={sourceId ? SOURCE_FULL_NAMES[sourceId] || sourceId : 'News Wire'}
    >
      {label}
    </span>
  );
}

function formatPercent(value: number | null): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return `${Math.round(value * 100)}%`;
}

function formatThreatCategory(category: string | null): string | null {
  if (!category) return null;
  return category.replaceAll('_', ' ');
}

function normalizeTicker(value: string): string {
  return value.trim().toUpperCase().replace(/\s+/g, '');
}

function getEntityValues(article: NewsArticle, key: string): string[] {
  if (!article.entities || typeof article.entities !== 'object') return [];
  const raw = article.entities[key];
  if (!Array.isArray(raw)) return [];

  return raw
    .filter((value): value is string => typeof value === 'string')
    .map((value) => value.trim())
    .filter((value, index, all) => value.length > 0 && all.indexOf(value) === index);
}

function SentimentDot({
  sentiment,
  score,
  confidence,
}: {
  sentiment: string | null;
  score: number | null;
  confidence: number | null;
}) {
  const normalized = (sentiment || 'NEUTRAL').toUpperCase();
  const badgeStyle = SENTIMENT_BADGE_STYLES[normalized] || SENTIMENT_BADGE_STYLES.NEUTRAL;
  const dotColor = SENTIMENT_COLORS[normalized] || SENTIMENT_COLORS.NEUTRAL;
  const opacity = score !== null && score !== undefined ? Math.max(0.4, Math.min(1, score)) : 0.85;
  const confidenceLabel = formatPercent(confidence);

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold shrink-0 ${badgeStyle}`}
      title={`${normalized} (${score?.toFixed(2) || '?'})${
        confidenceLabel ? ` • confidence ${confidenceLabel}` : ''
      }`}
    >
      <span
        className={`inline-block w-1.5 h-1.5 rounded-full ${dotColor}`}
        style={{ opacity }}
      />
      <span>{normalized}</span>
      {confidenceLabel && (
        <span className="text-[10px] text-zinc-300 font-normal">{confidenceLabel}</span>
      )}
    </span>
  );
}

function ThreatBadge({ level, category }: { level: string | null; category: string | null }) {
  if (!level) return null;
  const badge = THREAT_BADGES[level.toLowerCase()];
  if (!badge) return null;
  const categoryLabel = formatThreatCategory(category);
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-bold ${badge.className}`}>
      {badge.label}
      {categoryLabel ? ` · ${categoryLabel}` : ''}
    </span>
  );
}

function CredibilityWarning({ credibility }: { credibility: string | null }) {
  if (!credibility || credibility === 'NONE') return null;
  return (
    <span className="text-[10px] text-amber-400 ml-1 font-mono" title={`Credibility: ${credibility}`}>
      ⚠
    </span>
  );
}

function MetaChip({
  label,
  className,
  title,
}: {
  label: string;
  className: string;
  title?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-mono leading-none ${className}`}
      title={title}
    >
      {label}
    </span>
  );
}

function EntityChips({
  label,
  values,
  className,
  onClick,
}: {
  label: string;
  values: string[];
  className: string;
  onClick?: (value: string) => void;
}) {
  if (values.length === 0) return null;

  const visible = values.slice(0, ENTITY_CHIP_LIMIT);
  const overflow = values.length - visible.length;

  return (
    <>
      {visible.map((value) => {
        const chipLabel = label === 'T' ? `$${value.replace(/^\$/, '')}` : `${label}:${value}`;

        if (!onClick) {
          return <MetaChip key={chipLabel} label={chipLabel} className={className} />;
        }

        return (
          <span
            key={chipLabel}
            role="button"
            tabIndex={0}
            onClick={(event) => {
              event.stopPropagation();
              event.preventDefault();
              onClick(value);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.stopPropagation();
                event.preventDefault();
                onClick(value);
              }
            }}
            className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-mono font-bold leading-none transition-colors hover:bg-terminal-amber hover:text-black cursor-pointer ${className}`}
            title={`Set active symbol to ${value}`}
          >
            {chipLabel}
          </span>
        );
      })}
      {overflow > 0 && (
        <MetaChip
          label={`+${overflow}`}
          className="border-[#27272a] text-zinc-300 bg-[#0c0c0f]"
          title={`${overflow} more ${label.toLowerCase()} entities`}
        />
      )}
    </>
  );
}

function ArticleRow({
  article,
  showSentiment = true,
  isLive = false,
  onTickerClick,
}: {
  article: NewsArticle;
  showSentiment?: boolean;
  isLive?: boolean;
  onTickerClick: (ticker: string) => void;
}) {
  const title = article.title ?? 'Untitled';
  const timeFormatted = formatDate(article.publish_date);
  const relativeTime = formatRelativeTimestamp(article.publish_date);
  const sourceId = article.source;
  const credibility = article.source_credibility;
  const companySymbol = article.company_symbol ? normalizeTicker(article.company_symbol) : null;
  const rawTickers = getEntityValues(article, 'tickers').map(normalizeTicker);
  const tickers =
    companySymbol && !rawTickers.includes(companySymbol)
      ? [companySymbol, ...rawTickers]
      : rawTickers;
  const organizations = getEntityValues(article, 'organizations');
  const people = getEntityValues(article, 'people');
  const countries = getEntityValues(article, 'countries');
  const impactNote = formatThreatCategory(article.threat_category);

  const handleOpenArticle = (event?: React.MouseEvent) => {
    // Ctrl+Click / Cmd+Click → system browser; plain click/Enter/Space →
    // in-app reader. Always preventDefault: a native anchor navigation would
    // otherwise escape to the system browser via the external-link policy.
    if (event && isExternalClick(event)) {
      event.preventDefault();
      openLink(article.url, 'external');
      return;
    }
    openLink(article.url, 'app');
  };

  return (
    <a
      href={article.url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        event.preventDefault();
        handleOpenArticle(event);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          handleOpenArticle();
        }
      }}
      className="block bg-[#121216] border border-[#27272a] hover:border-zinc-500 p-2.5 rounded transition-colors cursor-pointer focus:outline-none focus:border-terminal-amber"
    >
      <div className="flex items-center justify-between gap-2 text-[11px] font-mono text-zinc-300 mb-1.5 flex-wrap">
        <div className="flex items-center gap-1.5 flex-wrap">
          <SourceBadge sourceId={sourceId} />
          <span className="text-zinc-300 tabular-nums">{timeFormatted}</span>
          <span className="text-zinc-400 text-[10px]">({relativeTime})</span>
          {isLive && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              LIVE
            </span>
          )}
          <ThreatBadge level={article.threat_level} category={null} />
          <CredibilityWarning credibility={credibility} />
        </div>
        {showSentiment && (
          <SentimentDot
            sentiment={article.sentiment}
            score={article.sentiment_score}
            confidence={article.confidence}
          />
        )}
      </div>

      <div className="text-xs font-semibold text-white leading-snug font-sans">
        {title}
      </div>

      {(tickers.length > 0 ||
        organizations.length > 0 ||
        people.length > 0 ||
        countries.length > 0 ||
        impactNote) && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] font-mono text-zinc-300">
          <EntityChips
            label="T"
            values={tickers}
            className="border-terminal-amber/40 text-terminal-amber bg-terminal-amber/10"
            onClick={onTickerClick}
          />
          <EntityChips
            label="O"
            values={organizations}
            className="border-cyan-500/40 text-cyan-300 bg-cyan-500/10"
          />
          <EntityChips
            label="P"
            values={people}
            className="border-violet-500/40 text-violet-300 bg-violet-500/10"
          />
          <EntityChips
            label="C"
            values={countries}
            className="border-zinc-600 text-zinc-300 bg-zinc-800/60"
          />
          {impactNote && (
            <span className="text-zinc-300 font-mono text-[10px]">
              • Impact: {impactNote}
            </span>
          )}
        </div>
      )}
    </a>
  );
}

function matchesFilters(
  article: NewsArticle,
  filters: {
    excludedSources?: string[];
    sentiment: string | null;
    threatLevel: string | null;
    searchQuery?: string;
  }
): boolean {
  if ((filters.excludedSources || []).includes(article.source || '')) return false;
  if (filters.sentiment && article.sentiment !== filters.sentiment) return false;
  if (filters.threatLevel && article.threat_level !== filters.threatLevel) return false;
  const sq = filters.searchQuery || '';
  if (sq) {
    const q = sq.toLowerCase();
    const title = article.title?.toLowerCase() || '';
    const text = article.text?.toLowerCase() || '';
    const symbol = article.company_symbol?.toLowerCase() || '';
    const entities = JSON.stringify(article.entities || {}).toLowerCase();
    if (!title.includes(q) && !text.includes(q) && !symbol.includes(q) && !entities.includes(q)) {
      return false;
    }
  }
  return true;
}


function SourceFilterChips({
  excluded,
  onChange,
}: {
  excluded: string[];
  onChange: (excluded: string[]) => void;
}) {
  const [showAllSources, setShowAllSources] = useState(false);
  const allSources = Object.keys(SOURCE_LABELS);
  const isAllSelected = excluded.length === 0;

  const toggle = (sourceId: string) => {
    if (excluded.includes(sourceId)) {
      onChange(excluded.filter((s) => s !== sourceId));
    } else {
      onChange([...excluded, sourceId]);
    }
  };

  const selectSingleOrToggle = (sourceId: string) => {
    const onlyThisIncluded =
      excluded.length === allSources.length - 1 && !excluded.includes(sourceId);
    if (onlyThisIncluded) {
      onChange([]);
    } else if (isAllSelected) {
      onChange(allSources.filter((s) => s !== sourceId));
    } else {
      toggle(sourceId);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-400 mr-1">
          SOURCES:
        </span>
        <button
          type="button"
          onClick={() => onChange([])}
          className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded border transition-colors ${
            isAllSelected
              ? 'border-terminal-amber bg-terminal-amber/15 text-terminal-amber'
              : 'border-[#27272a] bg-[#121216] text-zinc-300 hover:text-white hover:border-zinc-500'
          }`}
        >
          ALL
        </button>

        {PRIMARY_SOURCE_PILLS.map(({ id, label }) => {
          const isIncluded = !excluded.includes(id);
          const isFocused = !isAllSelected && isIncluded;
          return (
            <button
              key={id}
              type="button"
              onClick={() => selectSingleOrToggle(id)}
              title={SOURCE_FULL_NAMES[id] || id}
              className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded border transition-colors ${
                isFocused
                  ? 'border-terminal-amber bg-terminal-amber text-black'
                  : isIncluded
                  ? 'border-[#27272a] bg-[#121216] text-zinc-200 hover:border-terminal-amber/60 hover:text-terminal-amber'
                  : 'border-[#27272a]/60 bg-[#09090b] text-zinc-400 opacity-60 hover:opacity-100'
              }`}
            >
              {label}
            </button>
          );
        })}

        <button
          type="button"
          onClick={() => setShowAllSources((prev) => !prev)}
          className="px-2 py-0.5 text-[10px] font-mono rounded border border-[#27272a] bg-[#121216] text-zinc-300 hover:text-terminal-amber hover:border-zinc-500 transition-colors ml-auto"
        >
          {showAllSources ? 'LESS FEEDS ▲' : `ALL ${allSources.length} FEEDS ▼`}
        </button>
      </div>

      {showAllSources && (
        <div className="flex flex-wrap gap-1 pt-1.5 border-t border-[#27272a]/60">
          {allSources.map((id) => {
            const active = !excluded.includes(id);
            return (
              <button
                key={id}
                type="button"
                onClick={() => toggle(id)}
                title={SOURCE_FULL_NAMES[id] || id}
                className={`text-[10px] font-mono px-1.5 py-0.5 rounded border transition-colors ${
                  active
                    ? 'bg-terminal-amber/15 text-terminal-amber border-terminal-amber/50 font-bold'
                    : 'bg-[#121216] text-zinc-400 border-[#27272a] hover:text-white'
                }`}
              >
                {SOURCE_LABELS[id]}
              </button>
            );
          })}
        </div>
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
      type="button"
      onClick={onClick}
      className={`px-2.5 py-1 text-[10px] font-mono font-bold uppercase tracking-wider rounded border transition-colors flex items-center gap-1.5 ${
        active
          ? 'border-terminal-amber bg-terminal-amber/10 text-terminal-amber'
          : 'border-[#27272a] bg-[#121216] text-zinc-300 hover:text-white'
      }`}
    >
      {label}
      {live && (
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_8px_#10b981]" />
      )}
    </button>
  );
}

export function NewsWidget() {
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);
  const [wsConnected, setWsConnected] = useAtom(newsWsConnectedAtom);
  const [liveArticles, setLiveArticles] = useAtom(liveNewsArticlesAtom);
  const [filters, setFilters] = useAtom(newsFiltersAtom);

  const [globalOffset, setGlobalOffset] = useState(0);
  const [localSearch, setLocalSearch] = useState(filters.searchQuery || '');
  const [scrapingConsent] = useAtom(advancedScrapingConsentAtom);
  const [showNudge, setShowNudge] = useState(false);

  useEffect(() => {
    if (scrapingConsent === false) {
      const showTimer = setTimeout(() => setShowNudge(true), 0);
      const hideTimer = setTimeout(() => {
        setShowNudge(false);
      }, 5000);
      return () => {
        clearTimeout(showTimer);
        clearTimeout(hideTimer);
      };
    }
  }, [scrapingConsent]);

  useEffect(() => {
    const t = setTimeout(() => {
      if ((filters.searchQuery || '') !== localSearch) {
        setFilters((prev) => ({ ...prev, searchQuery: localSearch }));
        setGlobalOffset(0);
      }
    }, 350);
    return () => clearTimeout(t);
  }, [localSearch, filters.searchQuery, setFilters]);

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

  const {
    data: globalData,
    isLoading,
    error,
  } = useQuery<NewsPaginatedResponse>({
    queryKey: ['news/all', { limit: PAGE_LIMIT, offset: globalOffset, filters }],
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(PAGE_LIMIT),
        offset: String(globalOffset),
      });
      const allSourceIds = Object.keys(SOURCE_LABELS);
      const excludedSources = filters.excludedSources || [];
      if (excludedSources.length > 0) {
        const included = allSourceIds.filter((s) => !excludedSources.includes(s));
        if (included.length > 0) {
          params.set('sources', included.join(','));
        } else {
          params.set('sources', 'NONE');
        }
      }
      if (filters.searchQuery) params.set('q', filters.searchQuery);
      if (filters.sentiment) params.set('sentiment', filters.sentiment);
      if (filters.threatLevel) params.set('threat_level', filters.threatLevel);

      let res = await fetch(`/api/py/news/all?${params.toString()}`);
      if (!res.ok) {
        res = await fetch(`/api/py/news/articles?${params.toString()}`);
      }
      if (!res.ok) throw new Error('Failed to fetch global news');
      return res.json() as Promise<NewsPaginatedResponse>;
    },
    staleTime: 5 * 60_000,
    refetchInterval: 5 * 60_000,
  });

  const dbArticles = useMemo(() => globalData?.articles || [], [globalData]);
  const currentOffset = globalOffset;
  const setOffset = setGlobalOffset;

  const filteredLiveArticles = useMemo(
    () => liveArticles.filter((a) => matchesFilters(a, filters)),
    [liveArticles, filters]
  );

  const wireArticles = useMemo<NewsArticle[]>(() => {
    const liveUrls = new Set(filteredLiveArticles.map((a) => a.url));
    const merged = [
      ...filteredLiveArticles,
      ...dbArticles.filter((a) => !liveUrls.has(a.url)),
    ];
    return merged;
  }, [filteredLiveArticles, dbArticles]);

  const liveUrlSet = useMemo(
    () => new Set(filteredLiveArticles.map((a) => a.url)),
    [filteredLiveArticles]
  );

  const totalCount = globalData?.total ?? wireArticles.length;
  const hasMore = globalData?.has_more || false;

  const handlePrevPage = () => {
    setOffset((prev: number) => Math.max(0, prev - PAGE_LIMIT));
  };

  const handleNextPage = () => {
    if (hasMore) {
      setOffset((prev: number) => prev + PAGE_LIMIT);
    }
  };

  const handleSourceFilterChange = (excludedSources: string[]) => {
    setFilters((prev) => ({ ...prev, excludedSources }));
    setGlobalOffset(0);
  };

  const handleSentimentFilterChange = (sentiment: string | null) => {
    setFilters((prev) => ({
      ...prev,
      sentiment: prev.sentiment === sentiment ? null : sentiment,
    }));
    setGlobalOffset(0);
  };

  const handleTickerClick = useCallback(
    async (ticker: string) => {
      const normalizedTicker = normalizeTicker(ticker.replace(/^\$/, ''));
      if (!normalizedTicker) return;

      setActiveSymbol(normalizedTicker);

      try {
        const res = await fetch(
          `/api/py/stockuniverse/search/${encodeURIComponent(normalizedTicker)}`
        );
        if (!res.ok) return;

        const data = await res.json();
        const results = Array.isArray(data?.results) ? data.results : [];
        const exactMatch = results.find(
          (item: { symbol?: string }) =>
            typeof item?.symbol === 'string' &&
            normalizeTicker(item.symbol) === normalizedTicker
        );
        const match = exactMatch ?? results[0];
        if (!match?.symbol) return;

        setActiveSymbol(match.symbol);
        setActiveExchange(match.exchange || 'NSE');
      } catch {
        // Ignore lookup failures so news browsing remains uninterrupted.
      }
    },
    [setActiveExchange, setActiveSymbol]
  );

  const handleExternalOrAppLink = useCallback(
    (url: string, event?: React.MouseEvent | React.KeyboardEvent) => {
      if (!url) return;
      if (event && 'ctrlKey' in event && isExternalClick(event)) {
        event.preventDefault();
        openLink(url, 'external');
        return;
      }
      openLink(url, 'app');
    },
    []
  );

  const activeSourceCount =
    Object.keys(SOURCE_LABELS).length - (filters.excludedSources?.length || 0);

  return (
    <div className="h-full w-full flex flex-col bg-[#09090b] text-zinc-100 font-mono text-xs overflow-hidden p-3 gap-3">
      {/* TOP TOOLBAR BENTO */}
      <div className="bg-[#0c0c0f] border border-[#27272a] rounded p-2.5 shrink-0 flex flex-col gap-2 shadow-md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span
              className={`w-2.5 h-2.5 rounded-full transition-all ${
                wsConnected
                  ? 'bg-emerald-400 animate-pulse shadow-[0_0_8px_#10b981]'
                  : 'bg-amber-400 shadow-[0_0_6px_#f59e0b]'
              }`}
              title={wsConnected ? 'Live WebSocket Connected' : 'REST Polling Mode'}
            />
            <span className="text-xs font-mono font-bold tracking-wider uppercase text-terminal-amber">
              NEWS & FILINGS RADAR HUB
            </span>
            <span className="text-zinc-600">|</span>
            <span className="text-xs text-zinc-300 font-mono tabular-nums">
              {activeSourceCount} FEEDS SYNCED • {wsConnected ? 'NSE/BSE LIVE' : 'SYNC READY'}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-2 flex-1 justify-end min-w-[260px]">
            <div className="flex items-center gap-1">
              {(['BULLISH', 'BEARISH', 'NEUTRAL'] as const).map((sent) => {
                const isActive = filters.sentiment === sent;
                const activeTone =
                  sent === 'BULLISH'
                    ? 'border-emerald-400 bg-emerald-500/15 text-emerald-400'
                    : sent === 'BEARISH'
                    ? 'border-rose-400 bg-rose-500/15 text-rose-400'
                    : 'border-zinc-400 bg-zinc-500/15 text-zinc-200';
                return (
                  <button
                    key={sent}
                    type="button"
                    onClick={() => handleSentimentFilterChange(sent)}
                    className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded border transition-colors ${
                      isActive
                        ? activeTone
                        : 'border-[#27272a] bg-[#121216] text-zinc-300 hover:text-white'
                    }`}
                  >
                    {sent}
                  </button>
                );
              })}
            </div>

            <div className="relative flex items-center min-w-[220px] sm:w-64">
              <input
                type="text"
                placeholder="Filter ticker or keyword (e.g. RELIANCE)..."
                className="w-full bg-[#121216] border border-[#27272a] rounded px-2.5 py-1 text-xs text-white placeholder:text-zinc-400 focus:outline-none focus:border-terminal-amber transition-colors font-mono"
                value={localSearch}
                onChange={(e) => setLocalSearch(e.target.value)}
              />
              {localSearch && (
                <button
                  type="button"
                  onClick={() => setLocalSearch('')}
                  className="absolute right-2 text-zinc-400 hover:text-white text-xs"
                  title="Clear search"
                >
                  ✕
                </button>
              )}
            </div>

            <TabButton
              active={true}
              onClick={() => undefined}
              label="MULTI-STREAM"
              live={wsConnected}
            />
          </div>
        </div>

        <SourceFilterChips
          excluded={filters.excludedSources || []}
          onChange={handleSourceFilterChange}
        />
      </div>

      {/* FULL PANEL LIVE WIRE FEED */}
      <div className="flex-1 overflow-y-auto pr-0.5">
        <div className="h-full bg-[#0c0c0f] border border-[#27272a] rounded p-3 flex flex-col justify-between transition-colors shadow-md">
            <div>
              <div className="flex items-center justify-between pb-2 mb-2.5 border-b border-[#27272a] flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-terminal-amber">
                    LIVE WIRE FLASH FEED
                  </span>
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      wsConnected ? 'bg-emerald-400 animate-ping' : 'bg-emerald-400'
                    }`}
                  />
                </div>
                <span className="text-[10px] font-mono text-zinc-300 bg-[#121216] px-2 py-0.5 rounded border border-[#27272a]">
                  AP • BLOOMBERG • MC • REUTERS
                </span>
              </div>

              {isLoading && wireArticles.length === 0 ? (
                <div className="h-[320px] flex items-center justify-center">
                  <span className="text-terminal-amber animate-pulse text-xs font-mono">
                    SYNCING WIRE FEEDS...
                  </span>
                </div>
              ) : error && wireArticles.length === 0 ? (
                <div className="h-[320px] flex flex-col items-center justify-center gap-1 px-4 text-center">
                  <span className="text-rose-400 font-bold uppercase text-xs">
                    WIRE STREAM ERROR
                  </span>
                  <span className="text-zinc-300 text-xs">
                    {error instanceof Error ? error.message : 'Unable to reach news service'}
                  </span>
                </div>
              ) : wireArticles.length === 0 ? (
                <div className="h-[320px] flex items-center justify-center">
                  <span className="text-zinc-300 text-xs font-mono">
                    No wire articles match current filters.
                  </span>
                </div>
              ) : (
                <div className="space-y-2.5 overflow-y-auto max-h-[calc(100vh-250px)] pr-1 font-sans">
                  {wireArticles.map((article, idx) => (
                    <ArticleRow
                      key={`${article.url}_${idx}`}
                      article={article}
                      isLive={liveUrlSet.has(article.url)}
                      onTickerClick={handleTickerClick}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Pagination Footer */}
            <div className="mt-2.5 pt-2 border-t border-[#27272a] flex items-center justify-between text-xs text-zinc-300 font-mono">
              <button
                type="button"
                onClick={handlePrevPage}
                disabled={currentOffset === 0}
                className="px-2.5 py-0.5 bg-[#121216] border border-[#27272a] hover:border-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed rounded transition-colors text-zinc-200"
              >
                Prev
              </button>
              <span className="font-mono tabular-nums text-[11px] text-zinc-300">
                {dbArticles.length > 0
                  ? `${currentOffset + 1}–${Math.min(
                      currentOffset + dbArticles.length,
                      totalCount
                    )} of ${totalCount}`
                  : `${wireArticles.length} active wire dispatches`}
              </span>
              <button
                type="button"
                onClick={handleNextPage}
                disabled={!hasMore}
                className="px-2.5 py-0.5 bg-[#121216] border border-[#27272a] hover:border-zinc-500 disabled:opacity-40 disabled:cursor-not-allowed rounded transition-colors text-zinc-200"
              >
                Next
              </button>
            </div>
          </div>
        </div>
    </div>
  );
}
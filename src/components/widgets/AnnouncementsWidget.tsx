'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { watchlistsAtom, Watchlist } from '@/store/terminalStore';

interface Announcement {
  title: string;
  link: string;
  description: string;
  subject: string;
  pubDate: string;
}

interface WatchlistItem {
  id: number;
  symbol: string;
}

const SUBJECT_TABS = ['ALL', 'CORP ACTION', 'BOARD', 'RESULTS', 'AGM/EGM'] as const;
type Tab = (typeof SUBJECT_TABS)[number];

const SUBJECT_MAP: Record<string, Tab> = {
  'acquisition': 'CORP ACTION',
  'preferential issue': 'CORP ACTION',
  'restructuring': 'CORP ACTION',
  'amalgamation': 'CORP ACTION',
  'merger': 'CORP ACTION',
  'amendment': 'CORP ACTION',
  'change in directors': 'BOARD',
  'change in directors/kmp': 'BOARD',
  'director': 'BOARD',
  'kmp': 'BOARD',
  'financial results': 'RESULTS',
  'results': 'RESULTS',
  'investor presentation': 'RESULTS',
  'quarterly results': 'RESULTS',
  'annual results': 'RESULTS',
  'shareholders meeting': 'AGM/EGM',
  'notice of shareholders meetings': 'AGM/EGM',
  'postal ballot': 'AGM/EGM',
  'egm': 'AGM/EGM',
  'agm': 'AGM/EGM',
};

function getTabForSubject(subject: string): Tab {
  const normalized = subject.toLowerCase();
  for (const [keyword, tab] of Object.entries(SUBJECT_MAP)) {
    if (normalized.includes(keyword)) return tab;
  }
  return 'ALL';
}

function getBadgeColor(subject: string): string {
  const normalized = subject.toLowerCase();
  if (normalized.includes('acquisition') || normalized.includes('restructuring')) {
    return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
  }
  if (normalized.includes('board') || normalized.includes('director') || normalized.includes('kmp')) {
    return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
  }
  if (normalized.includes('results') || normalized.includes('presentation') || normalized.includes('financial')) {
    return 'bg-green-500/20 text-green-400 border-green-500/30';
  }
  if (normalized.includes('shareholders') || normalized.includes('agm') || normalized.includes('egm') || normalized.includes('meeting')) {
    return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
  }
  return 'bg-terminal-amber/20 text-terminal-amber border-terminal-amber/30';
}

function formatTime(pubDate: string): string {
  const match = pubDate.match(/(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})/);
  if (!match) return pubDate.slice(0, 5);
  return `${match[4]}:${match[5]}`;
}

function normalizeCompanyName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
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
      className={`px-2 py-0.5 text-[10px] font-mono uppercase transition-colors ${
        active
          ? 'bg-terminal-amber text-black font-semibold'
          : 'text-white/50 hover:text-white hover:bg-zinc-800'
      }`}
    >
      {label}
    </button>
  );
}

function AnnouncementRow({
  announcement,
  isWatched,
}: {
  announcement: Announcement;
  isWatched: boolean;
}) {
  const handleClick = () => {
    if (!announcement.link) return;
    const isXml = announcement.link.toLowerCase().endsWith('.xml');
    if (isXml) {
      const viewerUrl = `/filing?url=${encodeURIComponent(announcement.link)}`;
      window.open(viewerUrl, '_blank');
    } else {
      window.open(announcement.link, '_blank');
    }
  };

  const badgeClass = getBadgeColor(announcement.subject);

  return (
    <div
      onClick={handleClick}
      className={`px-2 py-1.5 border-b border-terminal-gray/30 hover:bg-zinc-900 cursor-pointer transition-colors ${
        !announcement.link && 'cursor-default'
      }`}
    >
      <div className="flex items-start gap-2">
        <span className="text-[10px] text-white/40 font-mono w-10 shrink-0 pt-0.5">
          {formatTime(announcement.pubDate)}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span
              className={`text-xs font-mono font-semibold truncate ${
                isWatched ? 'text-white' : 'text-terminal-amber'
              }`}
            >
              {announcement.title.toUpperCase()}
            </span>
            {isWatched && (
              <span className="text-terminal-amber text-[10px] font-bold">★</span>
            )}
            <span
              className={`text-[9px] px-1 py-0.5 rounded border font-mono shrink-0 ${badgeClass}`}
            >
              {announcement.subject}
            </span>
          </div>
          <div className="text-[10px] text-white/50 font-mono mt-0.5 truncate flex items-center gap-1.5">
            <span className="truncate">{announcement.description}</span>
            {announcement.link?.toLowerCase().endsWith('.xml') && (
              <span className="shrink-0 text-[8px] px-1 py-0.5 rounded border border-blue-500/40 text-blue-400 bg-blue-500/10 font-mono">
                XML
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function AnnouncementsWidget() {
  const [activeTab, setActiveTab] = useState<Tab>('ALL');
  const [search, setSearch] = useState('');
  const watchlists = useAtomValue(watchlistsAtom);
  const queryClient = useQueryClient();

  const { data: watchlistSymbols } = useQuery({
    queryKey: ['watchlist-symbols'],
    queryFn: async () => {
      const symbols = new Set<string>();
      if (watchlists.length === 0) return symbols;

      const fetchPromises = watchlists.map(async (list: Watchlist) => {
        try {
          const res = await fetch(`/api/watchlist?watchlist_id=${list.id}`);
          const data = (await res.json()) as WatchlistItem[];
          data.forEach((item) => symbols.add(normalizeCompanyName(item.symbol)));
        } catch {
          // skip failed fetches
        }
      });

      await Promise.all(fetchPromises);
      return symbols;
    },
    enabled: watchlists.length > 0,
    staleTime: 60000,
  });

  const {
    data: announcementsData,
    isLoading,
    isError,
    dataUpdatedAt,
  } = useQuery<{ items: Announcement[]; lastBuild: string }>({
    queryKey: ['announcements'],
    queryFn: async () => {
      const res = await fetch('/api/announcements');
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Failed to fetch');
      }
      return res.json();
    },
    refetchInterval: 300000,
    staleTime: 290000,
  });

  const filteredItems = useMemo(() => {
    if (!announcementsData?.items) return [];
    const searchLower = search.toLowerCase().trim();
    return announcementsData.items.filter((item) => {
      if (activeTab !== 'ALL' && getTabForSubject(item.subject) !== activeTab) return false;
      if (searchLower) {
        const matchTitle = item.title.toLowerCase().includes(searchLower);
        const matchDesc = item.description.toLowerCase().includes(searchLower);
        const matchSubject = item.subject.toLowerCase().includes(searchLower);
        if (!matchTitle && !matchDesc && !matchSubject) return false;
      }
      return true;
    });
  }, [announcementsData, activeTab, search]);

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
      })
    : '--:--';

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['announcements'] });
  };

  const handleRetry = () => {
    queryClient.invalidateQueries({ queryKey: ['announcements'] });
  };

  return (
    <div className="h-full flex flex-col bg-terminal-bg font-mono">
      {/* Row 1: Tabs + Refresh */}
      <div className="flex items-center gap-1 px-2 py-1 border-b border-terminal-gray/30">
        {SUBJECT_TABS.map((tab) => (
          <TabButton
            key={tab}
            active={activeTab === tab}
            onClick={() => {
              setActiveTab(tab);
              setSearch('');
            }}
            label={tab}
          />
        ))}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[10px] text-white/40">
            {filteredItems.length} · {lastUpdated}
          </span>
          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="text-white/50 hover:text-terminal-amber transition-colors disabled:opacity-50"
          >
            <svg
              className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Row 2: Search bar (full width) */}
      <div className="px-2 py-1 border-b border-terminal-gray/30">
        <div className="relative flex items-center">
          <svg
            className="w-3 h-3 text-white/40 shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, description, subject..."
            className="flex-1 bg-transparent text-white/80 text-[10px] font-mono px-2 py-0.5 focus:outline-none placeholder:text-white/30"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="text-white/40 hover:text-white/80 shrink-0"
            >
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isError && (
          <div className="p-4 text-center">
            <p className="text-terminal-red text-xs mb-2">Failed to load announcements</p>
            <button
              onClick={handleRetry}
              className="text-terminal-amber text-xs hover:underline"
            >
              Retry
            </button>
          </div>
        )}

        {!isError && isLoading && filteredItems.length === 0 && (
          <div className="p-4 text-center text-white/40 text-xs">Loading...</div>
        )}

        {!isError && !isLoading && filteredItems.length === 0 && (
          <div className="p-4 text-center text-white/40 text-xs">
            No announcements
          </div>
        )}

        {!isError && filteredItems.length > 0 && (
          <div>
            {filteredItems.map((item, idx) => {
              const normalized = normalizeCompanyName(item.title);
              const isWatched =
                watchlistSymbols?.has(normalized) ||
                Array.from(watchlistSymbols || []).some(
                  (s) => normalized.includes(s) || s.includes(normalized)
                );
              return (
                <AnnouncementRow
                  key={`${item.pubDate}-${idx}`}
                  announcement={item}
                  isWatched={isWatched}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
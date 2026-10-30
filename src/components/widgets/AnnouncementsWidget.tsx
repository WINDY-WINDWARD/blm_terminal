'use client';

import React, { useState, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAtomValue } from 'jotai';
import { watchlistsAtom, Watchlist } from '@/store/terminalStore';
import type { EventCalendarItem } from '@/app/api/event-calendar/route';
import { isExternalClick, openLink } from '@/lib/openLink';

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

const SUBJECT_TABS = ['RESULTS', 'ALL', 'CORP ACTION', 'BOARD', 'AGM/EGM'] as const;
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

function getCalendarBadgeColor(purpose: string): string {
  const lower = purpose.toLowerCase();
  if (lower.includes('financial results') || lower.includes('results')) {
    return 'bg-green-500/20 text-green-400 border-green-500/30';
  }
  if (lower.includes('dividend')) {
    return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
  }
  return 'bg-terminal-amber/20 text-terminal-amber border-terminal-amber/30';
}

/** Returns true if the event calendar entry belongs in the RESULTS tab. */
function isResultsOrDividend(purpose: string): boolean {
  const lower = purpose.toLowerCase();
  return lower.includes('financial results') || lower.includes('dividend');
}

function formatTime(pubDate: string): string {
  const match = pubDate.match(/(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})/);
  if (!match) return pubDate.slice(0, 5);
  return `${match[4]}:${match[5]}`;
}

function normalizeCompanyName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '');
}

/**
 * Parse NSE date string "20-Apr-2026" into a Date object.
 * Returns null if parsing fails.
 */
function parseNseDate(dateStr: string): Date | null {
  const months: Record<string, number> = {
    Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
    Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
  };
  const m = dateStr.match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/);
  if (!m) return null;
  const month = months[m[2]];
  if (month === undefined) return null;
  return new Date(Number(m[3]), month, Number(m[1]));
}

function formatNseDate(dateStr: string): string {
  const d = parseNseDate(dateStr);
  if (!d) return dateStr;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function TabButton({
  active,
  onClick,
  label,
  tourId,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  tourId: string;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      data-widget-tour-click={`tab-${tourId}`}
      onClick={onClick}
      className={`px-3 py-1.5 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 flex items-center gap-1 ${
        active
          ? 'bg-terminal-amber text-black font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent'
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
  const openTarget = (event?: React.MouseEvent) => {
    if (!announcement.link) return;
    // Ctrl+Click / Cmd+Click → system browser (even for .xml: raw file).
    if (event && isExternalClick(event)) {
      event.preventDefault();
      openLink(announcement.link, 'external');
      return;
    }
    const isXml = announcement.link.toLowerCase().endsWith('.xml');
    if (isXml) {
      const viewerUrl = `/filing?url=${encodeURIComponent(announcement.link)}`;
      window.open(viewerUrl, '_blank');
    } else {
      openLink(announcement.link, 'app');
    }
  };

  const badgeClass = getBadgeColor(announcement.subject);

  const rowBody = (
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
  );

  if (!announcement.link) {
    return (
      <div
        className="px-2 py-1.5 border-b border-terminal-gray/30 hover:bg-zinc-900 cursor-default transition-colors"
      >
        {rowBody}
      </div>
    );
  }

  return (
    <a
      href={announcement.link}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        event.preventDefault();
        openTarget(event);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openTarget();
        }
      }}
      className="block px-2 py-1.5 border-b border-terminal-gray/30 hover:bg-zinc-900 cursor-pointer transition-colors"
    >
      {rowBody}
    </a>
  );
}

function EventCalendarRow({
  item,
  isWatched,
}: {
  item: EventCalendarItem;
  isWatched: boolean;
}) {
  const openTarget = (event?: React.MouseEvent) => {
    if (!item.attachment) return;
    if (event && isExternalClick(event)) {
      event.preventDefault();
      openLink(item.attachment, 'external');
      return;
    }
    const isXml = item.attachment.toLowerCase().endsWith('.xml');
    if (isXml) {
      window.open(`/filing?url=${encodeURIComponent(item.attachment)}`, '_blank');
    } else {
      openLink(item.attachment, 'app');
    }
  };

  const badgeClass = getCalendarBadgeColor(item.purpose);
  const purposeShort = item.purpose.length > 40 ? item.purpose.slice(0, 38) + '…' : item.purpose;

  const rowBody = (
      <div className="flex items-start gap-2">
        {/* Date badge */}
        <span className="text-[10px] text-white/40 font-mono w-16 shrink-0 pt-0.5">
          {formatNseDate(item.date)}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span
              className={`text-xs font-mono font-bold shrink-0 ${
                isWatched ? 'text-terminal-amber' : 'text-white/80'
              }`}
            >
              {item.symbol}
            </span>
            {isWatched && (
              <span className="text-terminal-amber text-[10px] font-bold">★</span>
            )}
            <span
              className={`text-[9px] px-1 py-0.5 rounded border font-mono shrink-0 ${badgeClass}`}
            >
              {purposeShort}
            </span>
            {item.source === 'sme' && (
              <span className="text-[8px] px-1 py-0.5 rounded border border-zinc-600 text-zinc-500 font-mono shrink-0">
                SME
              </span>
            )}
          </div>
          <div className="text-[10px] text-white/40 font-mono mt-0.5 truncate">
            {item.company}
          </div>
          {item.description && item.description !== item.purpose && (
            <div className="text-[9px] text-white/30 font-mono mt-0.5 line-clamp-2 leading-snug">
              {item.description}
            </div>
          )}
        </div>
      </div>
  );

  if (!item.attachment) {
    return (
      <div
        className={`px-2 py-1.5 border-b border-terminal-gray/30 transition-colors ${
          isWatched ? 'bg-zinc-900/60' : ''
        } cursor-default`}
      >
        {rowBody}
      </div>
    );
  }

  return (
    <a
      href={item.attachment}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        event.preventDefault();
        openTarget(event);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          openTarget();
        }
      }}
      className={`block px-2 py-1.5 border-b border-terminal-gray/30 transition-colors ${
        isWatched ? 'bg-zinc-900/60' : ''
      } hover:bg-zinc-900 cursor-pointer`}
    >
      {rowBody}
    </a>
  );
}

/** Section header divider used in the RESULTS tab. */
function SectionHeader({ label, count }: { label: string; count: number }) {
  return (
    <div className="px-2 py-1 flex items-center gap-2 bg-zinc-900/80 border-b border-terminal-gray/30 sticky top-0 z-10">
      <span className="text-[9px] font-mono font-bold text-white/50 uppercase tracking-widest">
        {label}
      </span>
      <span className="text-[9px] font-mono text-white/30">({count})</span>
    </div>
  );
}

export function AnnouncementsWidget() {
  const [activeTab, setActiveTab] = useState<Tab>('RESULTS');
  const [search, setSearch] = useState('');
  const watchlists = useAtomValue(watchlistsAtom);
  const queryClient = useQueryClient();

  // ------------------------------------------------------------------
  // Watchlist symbols — fetched once, used for highlighting
  // ------------------------------------------------------------------
  const { data: watchlistSymbols } = useQuery({
    queryKey: ['watchlist-symbols'],
    queryFn: async () => {
      const symbols = new Set<string>();
      if (watchlists.length === 0) return symbols;

      const fetchPromises = watchlists.map(async (list: Watchlist) => {
        try {
          const res = await fetch(`/api/watchlist?watchlist_id=${list.id}`);
          const data = (await res.json()) as WatchlistItem[];
          data.forEach((item) => symbols.add(item.symbol.toUpperCase()));
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

  // ------------------------------------------------------------------
  // RSS announcements feed
  // ------------------------------------------------------------------
  const {
    data: announcementsData,
    isLoading: announcementsLoading,
    isError: announcementsError,
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

  // ------------------------------------------------------------------
  // NSE event calendar (upcoming board meetings)
  // ------------------------------------------------------------------
  const {
    data: calendarData,
    isLoading: calendarLoading,
  } = useQuery<EventCalendarItem[]>({
    queryKey: ['event-calendar'],
    queryFn: async () => {
      const res = await fetch('/api/event-calendar');
      if (!res.ok) {
        const err = (await res.json()) as { error?: string };
        throw new Error(err.error || 'Failed to fetch event calendar');
      }
      return res.json();
    },
    refetchInterval: 900_000, // 15 min
    staleTime: 890_000,
  });

  const { data: pastResultsData } = useQuery<EventCalendarItem[]>({
    queryKey: ['event-calendar-past'],
    queryFn: async () => {
      const res = await fetch('/api/event-calendar/past');
      if (!res.ok) {
        const err = (await res.json()) as { error?: string };
        throw new Error(err.error || 'Failed to fetch past results');
      }
      return res.json();
    },
    refetchInterval: 900_000,
    staleTime: 890_000,
  });

  // ------------------------------------------------------------------
  // Filtered lists
  // ------------------------------------------------------------------
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

  /**
   * Event calendar items for the RESULTS tab: Financial Results + Dividend,
   * filtered by search if active.
   */
  const calendarResultsItems = useMemo(() => {
    if (!calendarData) return [];
    const searchLower = search.toLowerCase().trim();
    const filtered = calendarData.filter((item) => {
      if (!isResultsOrDividend(item.purpose)) return false;
      if (searchLower) {
        return (
          item.symbol.toLowerCase().includes(searchLower) ||
          item.company.toLowerCase().includes(searchLower) ||
          item.purpose.toLowerCase().includes(searchLower) ||
          item.description.toLowerCase().includes(searchLower)
        );
      }
      return true;
    });
    // Already sorted by date asc from backend; keep that order
    return filtered;
  }, [calendarData, search]);

  const pastResultsItems = useMemo(() => {
    if (!pastResultsData) return [];
    const searchLower = search.toLowerCase().trim();
    return pastResultsData.filter((item) => {
      const purpose = item.purpose.toLowerCase();
      if (!purpose.includes('financial results')) return false;
      if (searchLower) {
        return (
          item.symbol.toLowerCase().includes(searchLower) ||
          item.company.toLowerCase().includes(searchLower) ||
          item.purpose.toLowerCase().includes(searchLower) ||
          item.description.toLowerCase().includes(searchLower)
        );
      }
      return true;
    });
  }, [pastResultsData, search]);

  const isLoading = announcementsLoading;
  const isError = announcementsError;

  const lastUpdated = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
      })
    : '--:--';

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['announcements'] });
    queryClient.invalidateQueries({ queryKey: ['event-calendar'] });
  };

  const handleRetry = () => {
    queryClient.invalidateQueries({ queryKey: ['announcements'] });
  };

  // Count for tab header
  const totalResultsCount =
    activeTab === 'RESULTS'
      ? calendarResultsItems.length + pastResultsItems.length + filteredItems.length
      : filteredItems.length;

  return (
    <div className="h-full flex flex-col bg-terminal-bg font-mono">
      {/* Row 1: Tabs + Refresh */}
      <div data-widget-tour="annc-tabs" className="flex items-center border-b border-terminal-gray/30 shrink-0">
        {SUBJECT_TABS.map((tab) => (
          <TabButton
            key={tab}
            active={activeTab === tab}
            tourId={tab.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}
            onClick={() => {
              setActiveTab(tab);
              setSearch('');
            }}
            label={tab}
          />
        ))}
        <div className="ml-auto flex items-center gap-2 pr-2">
          <span className="text-[10px] text-white/40">
            {totalResultsCount} · {lastUpdated}
          </span>
          <button
            onClick={handleRefresh}
            disabled={isLoading || calendarLoading}
            className="text-white/50 hover:text-terminal-amber transition-colors disabled:opacity-50"
          >
            <svg
              className={`w-3 h-3 ${isLoading || calendarLoading ? 'animate-spin' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Row 2: Search bar (full width) */}
      <div data-widget-tour="annc-search" className="px-2 py-1 border-b border-terminal-gray/30">
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
              strokeWidth={1.5}
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
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      <div data-widget-tour="annc-filing-open" className="flex-1 overflow-y-auto">
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

        {/* ---------------------------------------------------------- */}
        {/* RESULTS tab: show upcoming event calendar + RSS announced   */}
        {/* ---------------------------------------------------------- */}
        {!isError && activeTab === 'RESULTS' && (
          <div data-widget-tour="annc-results-split">
            {/* UPCOMING RESULTS (event calendar) */}
            <SectionHeader label="Upcoming" count={calendarResultsItems.length} />
            {calendarLoading && calendarResultsItems.length === 0 && (
              <div className="px-2 py-2 text-center text-white/30 text-[10px]">
                Loading event calendar…
              </div>
            )}
            {!calendarLoading && calendarResultsItems.length === 0 && (
              <div className="px-2 py-2 text-center text-white/30 text-[10px]">
                No upcoming board meetings found
              </div>
            )}
            {calendarResultsItems.map((item, idx) => {
              const isWatched = watchlistSymbols?.has(item.symbol.toUpperCase()) ?? false;
              return (
                <EventCalendarRow
                  key={`cal-${item.symbol}-${item.date}-${idx}`}
                  item={item}
                  isWatched={isWatched}
                />
              );
            })}

            {/* ANNOUNCED (past results + RSS feed) */}
            <SectionHeader label="Announced" count={pastResultsItems.length + filteredItems.length} />
            {pastResultsItems.map((item, idx) => {
              const isWatched = watchlistSymbols?.has(item.symbol.toUpperCase()) ?? false;
              return (
                <EventCalendarRow
                  key={`past-${item.symbol}-${item.date}-${idx}`}
                  item={item}
                  isWatched={isWatched}
                />
              );
            })}
            {!isLoading && pastResultsItems.length === 0 && filteredItems.length === 0 && (
              <div className="px-2 py-2 text-center text-white/30 text-[10px]">
                No recent announcements
              </div>
            )}
            {filteredItems.map((item, idx) => {
              const normalizedTitle = normalizeCompanyName(item.title);
              const isWatched =
                watchlistSymbols
                  ? Array.from(watchlistSymbols).some((sym) => {
                      const normSym = normalizeCompanyName(sym);
                      return (
                        normalizedTitle.includes(normSym) || normSym.includes(normalizedTitle)
                      );
                    })
                  : false;
              return (
                <AnnouncementRow
                  key={`rss-${item.pubDate}-${idx}`}
                  announcement={item}
                  isWatched={isWatched}
                />
              );
            })}
          </div>
        )}

        {/* ---------------------------------------------------------- */}
        {/* ALL other tabs: existing RSS behaviour unchanged            */}
        {/* ---------------------------------------------------------- */}
        {!isError && activeTab !== 'RESULTS' && (
          <>
            {!isLoading && filteredItems.length === 0 && (
              <div className="p-4 text-center text-white/40 text-xs">
                No announcements
              </div>
            )}
            {filteredItems.length > 0 && (
              <div>
                {filteredItems.map((item, idx) => {
                  const normalizedTitle = normalizeCompanyName(item.title);
                  const isWatched =
                    watchlistSymbols
                      ? Array.from(watchlistSymbols).some((sym) => {
                          const normSym = normalizeCompanyName(sym);
                          return (
                            normalizedTitle.includes(normSym) ||
                            normSym.includes(normalizedTitle)
                          );
                        })
                      : false;
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
          </>
        )}
      </div>
    </div>
  );
}

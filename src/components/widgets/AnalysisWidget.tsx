'use client';

import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSetAtom } from 'jotai';
import {
  chartSymbolOverridesAtom,
  companySymbolOverridesAtom,
  type ChartSymbolOverride,
  type CompanySymbolOverride,
} from '@/store/terminalStore';

type Tab = 'summary' | 'sector' | 'industry' | 'heatmap';
type PeriodKey = '1d' | '1w' | '1m' | '6m';

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
  return_1d: number | null;
  return_1w: number | null;
  return_1m: number | null;
  return_6m: number | null;
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

interface WatchlistSummary {
  id: number;
  name: string;
  created_at?: string;
  item_count: number;
}

interface WatchlistItem {
  id: number;
  symbol: string;
  exchange?: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtCrore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (value >= 100000) {
    return `${(value / 100000).toFixed(2)}L Cr`;
  }
  return `${Math.round(value).toLocaleString('en-IN')} Cr`;
}

function fmtPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function signed(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value}`;
}

function toneClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'text-white/60';
  if (value > 0) return 'text-terminal-green';
  if (value < 0) return 'text-terminal-red';
  return 'text-white/60';
}


function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  } catch {
    return '—';
  }
}

function getPeriodReturn(c: Category, period: PeriodKey): number | null {
  if (period === '1d') return c.return_1d ?? null;
  if (period === '1w') return c.return_1w ?? null;
  if (period === '1m') return c.return_1m ?? null;
  if (period === '6m') return c.return_6m ?? null;
  return null;
}

// ─── useWidgetWidth Hook ─────────────────────────────────────────────────────

function useWidgetWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState<number>(800);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const cr = entry.contentRect;
        setWidth(cr.width);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);

  return {
    width,
    wide: width >= 860,
    mid: width >= 620,
  };
}

// ─── Watchlist Picker Modal ──────────────────────────────────────────────────

const WATCHLIST_NAME_REGEX = /^[A-Za-z0-9 _-]{1,32}$/;

interface WatchlistModalProps {
  symbol: string;
  companyName: string;
  onClose: () => void;
}

function WatchlistModal({ symbol, companyName, onClose }: WatchlistModalProps) {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // 1. Fetch user watchlists
  const {
    data: watchlists = [],
    isLoading: loadingLists,
    isError: listError,
  } = useQuery<WatchlistSummary[]>({
    queryKey: ['watchlists'],
    queryFn: async () => {
      const res = await fetch('/api/watchlists');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WatchlistSummary[]>;
    },
    staleTime: 30 * 1000,
  });

  // 2. Fetch membership items for each list
  const [memberships, setMemberships] = useState<Record<number, { inList: boolean; itemId?: number }>>({});
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [initialLoaded, setInitialLoaded] = useState(false);
  const seededRef = useRef(false);

  useEffect(() => {
    let active = true;
    if (watchlists.length === 0) return;

    Promise.all(
      watchlists.map(async (wl) => {
        try {
          const res = await fetch(`/api/watchlist?watchlist_id=${wl.id}`);
          if (!res.ok) return { id: wl.id, inList: false };
          const items = (await res.json()) as WatchlistItem[];
          const match = Array.isArray(items) ? items.find((it) => it.symbol === symbol) : undefined;
          return { id: wl.id, inList: Boolean(match), itemId: match?.id };
        } catch {
          return { id: wl.id, inList: false };
        }
      }),
    ).then((results) => {
      if (!active) return;
      const memMap: Record<number, { inList: boolean; itemId?: number }> = {};
      const sel = new Set<number>();
      for (const r of results) {
        memMap[r.id] = { inList: r.inList, itemId: r.itemId };
        if (r.inList) sel.add(r.id);
      }
      setMemberships(memMap);
      // Only seed the selection once. A refetch (e.g. after creating a list)
      // must not clobber toggles the user already made.
      if (!seededRef.current) {
        seededRef.current = true;
        setSelectedIds(sel);
      }
      setInitialLoaded(true);
    });

    return () => {
      active = false;
    };
  }, [watchlists, symbol]);

  // Handle escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Create new watchlist
  const createMutation = useMutation({
    mutationFn: async (name: string) => {
      const res = await fetch('/api/watchlists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const errData = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(errData.error || `Failed to create watchlist (${res.status})`);
      }
      return res.json() as Promise<WatchlistSummary>;
    },
    onSuccess: (newList) => {
      setNewName('');
      setCreateError(null);
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      if (newList?.id) {
        setMemberships((prev) => ({ ...prev, [newList.id]: { inList: false } }));
        setSelectedIds((prev) => new Set(prev).add(newList.id));
      }
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      setCreateError(msg);
    },
  });

  const handleValidateAndCreate = () => {
    const trimmed = newName.trim();
    if (!trimmed) {
      setCreateError('Name cannot be empty');
      return;
    }
    if (trimmed.length > 32) {
      setCreateError('Max 32 characters');
      return;
    }
    if (!WATCHLIST_NAME_REGEX.test(trimmed)) {
      setCreateError('Letters, numbers, spaces, _ and - only');
      return;
    }
    setCreateError(null);
    createMutation.mutate(trimmed);
  };

  // Save changes diff
  const [isSaving, setIsSaving] = useState(false);
  const handleSave = async () => {
    setIsSaving(true);
    setActionError(null);
    try {
      // 1. Add to newly checked lists
      for (const wl of watchlists) {
        const wasIn = Boolean(memberships[wl.id]?.inList);
        const isIn = selectedIds.has(wl.id);

        if (!wasIn && isIn) {
          const res = await fetch(`/api/watchlist?watchlist_id=${wl.id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, exchange: 'NSE' }),
          });
          if (!res.ok) {
            const err = (await res.json().catch(() => ({}))) as { error?: string };
            throw new Error(err.error || `Failed to add to ${wl.name}`);
          }
        } else if (wasIn && !isIn) {
          const itemId = memberships[wl.id]?.itemId;
          if (itemId !== undefined) {
            const res = await fetch(`/api/watchlist?id=${itemId}&watchlist_id=${wl.id}`, {
              method: 'DELETE',
            });
            if (!res.ok) {
              const err = (await res.json().catch(() => ({}))) as { error?: string };
              throw new Error(err.error || `Failed to remove from ${wl.name}`);
            }
          }
        }
      }

      await queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      setSaveStatus('Saved!');
      setIsSaving(false);
      setTimeout(() => {
        onClose();
      }, 900);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to save changes';
      setActionError(msg);
      setIsSaving(false);
    }
  };

  const isNameValid = WATCHLIST_NAME_REGEX.test(newName.trim());

  const hasChanges = useMemo(() => {
    if (!initialLoaded) return false;
    for (const wl of watchlists) {
      const wasIn = Boolean(memberships[wl.id]?.inList);
      if (wasIn !== selectedIds.has(wl.id)) return true;
    }
    return false;
  }, [watchlists, memberships, selectedIds, initialLoaded]);

  return (
    <div
      data-testid="analysis-watchlist-modal"
      role="dialog"
      aria-modal="true"
      aria-label={`Add ${symbol} to watchlist`}
      className="absolute inset-0 z-30 flex items-center justify-center p-3"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/80" />
      <div
        className="relative flex w-full max-w-[390px] flex-col border border-terminal-amber/50 bg-terminal-bg shadow-2xl font-mono"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-2 border-b border-terminal-gray px-2.5 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-terminal-amber">
              Add to watchlist
            </span>
            <span className="shrink-0 border border-terminal-gray px-1 py-[1px] text-[9px] font-bold tabular-nums text-white/75">
              {symbol}
            </span>
          </div>
          <button
            type="button"
            data-testid="analysis-watchlist-cancel"
            aria-label="Close watchlist modal"
            onClick={onClose}
            className="shrink-0 border border-terminal-gray px-2 py-0.5 text-[11px] text-white/60 hover:border-terminal-amber hover:text-terminal-amber transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Subhead */}
        <div className="flex items-baseline justify-between gap-2 px-2.5 pt-2 pb-1">
          <span className="truncate text-[9px] uppercase tracking-wider text-white/40">
            {companyName || symbol}
          </span>
          <span className="shrink-0 text-[9px] uppercase tracking-wider text-white/40 tabular-nums">
            {selectedIds.size} selected
          </span>
        </div>

        {/* Error surface */}
        {(actionError || listError) && (
          <div
            data-testid="analysis-watchlist-error"
            className="mx-2.5 mb-1 border border-terminal-red/50 bg-terminal-red/10 px-2 py-1 text-[10px] text-terminal-red"
          >
            {actionError || 'Failed to load watchlists'}
          </div>
        )}

        {/* Options list */}
        <div className="max-h-[236px] overflow-y-auto border-y border-terminal-gray/60">
          {loadingLists && !initialLoaded ? (
            <div className="px-3 py-4 text-center text-[10px] text-white/40">Loading watchlists...</div>
          ) : watchlists.length === 0 ? (
            <div className="px-3 py-4 text-center text-[10px] text-white/40">No watchlists yet. Create one below.</div>
          ) : (
            watchlists.map((wl) => {
              const on = selectedIds.has(wl.id);
              return (
                <button
                  key={wl.id}
                  type="button"
                  data-testid="analysis-watchlist-option"
                  data-watchlist-id={wl.id}
                  role="checkbox"
                  aria-checked={on}
                  aria-label={`${wl.name}${on ? ', selected' : ''}`}
                  disabled={!initialLoaded}
                  onClick={() => {
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      if (next.has(wl.id)) next.delete(wl.id);
                      else next.add(wl.id);
                      return next;
                    });
                  }}
                  className={`flex w-full items-center gap-2 border-b border-terminal-gray/30 px-2.5 py-[7px] text-left last:border-b-0 transition-colors disabled:cursor-wait ${
                    on ? 'bg-terminal-amber/10' : 'hover:bg-white/[0.04]'
                  } ${initialLoaded ? '' : 'opacity-50'}`}
                >
                  <span
                    className={`flex h-3 w-3 shrink-0 items-center justify-center border text-[9px] font-bold ${
                      on
                        ? 'border-terminal-amber bg-terminal-amber text-black'
                        : 'border-terminal-gray text-transparent'
                    }`}
                  >
                    ✓
                  </span>
                  <span className={`min-w-0 flex-1 truncate text-[11px] ${on ? 'text-white' : 'text-white/70'}`}>
                    {wl.name}
                  </span>
                  <span className="shrink-0 text-[9px] tabular-nums text-white/40">
                    {wl.item_count ?? 0}
                  </span>
                  {on ? (
                    <span className="shrink-0 text-[9px] uppercase tracking-wider text-terminal-amber font-bold">
                      in
                    </span>
                  ) : (
                    <span className="w-[14px] shrink-0" />
                  )}
                </button>
              );
            })
          )}
        </div>

        {/* New watchlist input */}
        <div className="flex flex-col gap-1 px-2.5 py-2">
          <div className="flex items-center gap-1.5">
            <input
              type="text"
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
                setCreateError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && isNameValid) {
                  handleValidateAndCreate();
                }
              }}
              placeholder="New watchlist name"
              maxLength={32}
              className="min-w-0 flex-1 border border-terminal-gray bg-black px-1.5 py-1 text-[10px] text-white placeholder:text-white/30 focus:border-terminal-amber focus:outline-none"
            />
            <button
              type="button"
              data-testid="analysis-watchlist-create"
              disabled={!isNameValid || createMutation.isPending}
              onClick={handleValidateAndCreate}
              className={`shrink-0 border px-2 py-1 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                isNameValid && !createMutation.isPending
                  ? 'border-terminal-gray text-white/70 hover:border-terminal-amber hover:text-terminal-amber'
                  : 'border-terminal-gray/40 text-white/20 cursor-not-allowed'
              }`}
            >
              + Create
            </button>
          </div>
          {createError && <span className="text-[9px] text-terminal-red">{createError}</span>}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 border-t border-terminal-gray px-2.5 py-2">
          <span className="text-[9px] text-white/35">
            {saveStatus ? (
              <span className="text-terminal-green font-bold">{saveStatus}</span>
            ) : (
              'toggles apply on save'
            )}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onClose}
              className="border border-terminal-gray px-2 py-1 text-[10px] uppercase tracking-wider text-white/60 hover:border-white/40 hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              data-testid="analysis-watchlist-save"
              disabled={isSaving || !hasChanges}
              onClick={handleSave}
              className="border border-terminal-amber bg-terminal-amber px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-black hover:bg-terminal-amber/85 transition-colors disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : selectedIds.size ? `Save · ${selectedIds.size}` : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Summary Tab ─────────────────────────────────────────────────────────────

interface SummaryPaneProps {
  sectors: Category[];
  onJumpToCategory: (slug: string) => void;
  wide: boolean;
  mid: boolean;
}

function SummaryPane({ sectors, onJumpToCategory, wide, mid }: SummaryPaneProps) {
  const [period, setPeriod] = useState<PeriodKey>('1d');

  // Breadth KPI
  const adv = sectors.reduce((acc, c) => acc + (c.advance || 0), 0);
  const dec = sectors.reduce((acc, c) => acc + (c.decline || 0), 0);
  const totalStocks = adv + dec;
  const netAdv = adv - dec;
  const advPct = totalStocks > 0 ? Math.round((adv / totalStocks) * 100) : 0;

  // Total MCap & P/E & Returns
  const totalMCap = sectors.reduce((acc, c) => acc + (c.market_cap || 0), 0);
  const avgPe = sectors.length > 0 ? sectors.reduce((acc, c) => acc + (c.pe || 0), 0) / sectors.length : 0;

  // Earnings YoY — median across sectors. A mean is dragged by a handful of
  // turnaround outliers (+1500%, -680%), so the headline reads as noise.
  const earningsValues = sectors
    .map((c) => c.earnings_yoy)
    .filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v))
    .sort((a, b) => a - b);
  const medianEarnings =
    earningsValues.length === 0
      ? 0
      : earningsValues.length % 2 === 1
        ? earningsValues[(earningsValues.length - 1) / 2]
        : (earningsValues[earningsValues.length / 2 - 1] + earningsValues[earningsValues.length / 2]) / 2;

  // Leading & lagging earnings categories (nulls excluded: an unknown is not a drag)
  const sortedByEarn = [...sectors]
    .filter((c) => c.earnings_yoy !== null && c.earnings_yoy !== undefined)
    .sort((a, b) => (b.earnings_yoy as number) - (a.earnings_yoy as number));
  const earnLeader = sortedByEarn[0];
  const earnDrag = sortedByEarn[sortedByEarn.length - 1];

  // Day change (cap-weighted)
  const dayChgWeighted = useMemo(() => {
    let sumWeight = 0;
    let sumCap = 0;
    for (const c of sectors) {
      const r = getPeriodReturn(c, '1d');
      const cap = c.market_cap || 0;
      if (r !== null && cap > 0) {
        sumWeight += r * cap;
        sumCap += cap;
      }
    }
    return sumCap > 0 ? sumWeight / sumCap : null;
  }, [sectors]);

  // Check which periods have ANY non-null data
  const availablePeriods = useMemo(() => {
    const checkPeriod = (pk: PeriodKey) => sectors.some((c) => getPeriodReturn(c, pk) !== null);
    return {
      '1d': checkPeriod('1d'),
      '1w': checkPeriod('1w'),
      '1m': checkPeriod('1m'),
      '6m': checkPeriod('6m'),
    };
  }, [sectors]);

  // Re-rank sectors by selected period
  const rankedByPeriod = useMemo(() => {
    return [...sectors].sort((a, b) => {
      const ra = getPeriodReturn(a, period);
      const rb = getPeriodReturn(b, period);
      if (ra === null && rb === null) return 0;
      if (ra === null) return 1;
      if (rb === null) return -1;
      return rb - ra;
    });
  }, [sectors, period]);

  const validRanked = useMemo(() => {
    return rankedByPeriod.filter((c) => getPeriodReturn(c, period) !== null);
  }, [rankedByPeriod, period]);

  const strongest = validRanked[0];
  const weakest = validRanked[validRanked.length - 1];

  const leaders = validRanked.slice(0, 6);
  const laggards = [...validRanked].slice(-6).reverse();

  const maxAbsReturn = useMemo(() => {
    let max = 0.1;
    for (const c of sectors) {
      const r = getPeriodReturn(c, period);
      if (r !== null && Math.abs(r) > max) max = Math.abs(r);
    }
    return max;
  }, [sectors, period]);

  // Map stays a glance view: the 12 largest sectors, ordered hot → cold
  const mapCats = useMemo(() => {
    const largest = [...sectors]
      .sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))
      .slice(0, 12);
    return largest.sort((a, b) => {
      const ra = getPeriodReturn(a, period);
      const rb = getPeriodReturn(b, period);
      if (ra === null && rb === null) return 0;
      if (ra === null) return 1;
      if (rb === null) return -1;
      return rb - ra;
    });
  }, [sectors, period]);

  return (
    <div
      data-testid="analysis-pane-summary"
      className="h-full overflow-y-auto p-2 font-mono text-xs flex flex-col gap-2"
    >
      {/* Bento band: 3 KPIs */}
      <div data-widget-tour="analysis-kpis" className={`grid gap-2 ${wide ? 'grid-cols-4' : 'grid-cols-2'}`}>
        {/* Breadth KPI hero */}
        <div
          data-testid="analysis-kpi-breadth"
          className="col-span-2 flex flex-col justify-between border border-terminal-gray bg-[#070707] p-2.5"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="whitespace-nowrap text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-amber">
              Market breadth
            </span>
            <span className="whitespace-nowrap text-[9px] tabular-nums text-white/45">
              {advPct}% advancing
            </span>
          </div>
          <div className="mt-2 flex items-end justify-between gap-2">
            <span
              className={`text-[28px] font-extrabold leading-none tabular-nums ${
                netAdv > 0 ? 'text-terminal-green' : netAdv < 0 ? 'text-terminal-red' : 'text-white/60'
              }`}
            >
              {signed(netAdv)}
            </span>
            <span className="whitespace-nowrap text-[10px] tabular-nums">
              <span className="text-terminal-green">{adv}▲</span>
              <span className="mx-1 text-white/25">/</span>
              <span className="text-terminal-red">{dec}▼</span>
            </span>
          </div>
          {/* Two segment bar */}
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-sm bg-white/5">
            <div className="flex h-full w-full">
              <span className="bg-terminal-green" style={{ flex: adv || 1 }} />
              <span className="bg-terminal-red" style={{ flex: dec || 1 }} />
            </div>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-2 text-[9px] text-white/40">
            <span className="truncate">
              {sectors.length} sectors · {totalStocks} stocks
            </span>
            <span className="whitespace-nowrap text-white/35">live aggregate</span>
          </div>
        </div>

        {/* Total MCap */}
        <div
          data-testid="analysis-kpi-mcap"
          className="flex flex-col justify-between border border-terminal-gray bg-[#070707] p-2.5"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="whitespace-nowrap text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-amber">
              Total MCap
            </span>
            <span className="text-[9px] uppercase tracking-wider text-white/35">NSE</span>
          </div>
          <div className="mt-2 whitespace-nowrap text-[21px] font-extrabold leading-none tabular-nums text-white">
            ₹{fmtCrore(totalMCap)}
          </div>
          <div className="mt-2 space-y-[3px] text-[9px]">
            <div className="flex items-center justify-between gap-2">
              <span className="text-white/40">avg P/E</span>
              <span className="tabular-nums text-white/80">{avgPe ? `${avgPe.toFixed(1)}x` : '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-white/40">today</span>
              <span className={`font-bold tabular-nums ${toneClass(dayChgWeighted)}`}>
                {fmtPercent(dayChgWeighted)}
              </span>
            </div>
          </div>
        </div>

        {/* Earnings YoY */}
        <div
          data-testid="analysis-kpi-earnings"
          className="flex flex-col justify-between border border-terminal-gray bg-[#070707] p-2.5"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="whitespace-nowrap text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-amber">
              Earnings YoY
            </span>
            <span className="text-[9px] uppercase tracking-wider text-white/35">median</span>
          </div>
          <div className={`mt-2 text-[21px] font-extrabold leading-none tabular-nums ${toneClass(medianEarnings)}`}>
            {fmtPercent(medianEarnings)}
          </div>
          <div className="mt-2 space-y-[3px] text-[9px]">
            <div className="flex items-center justify-between gap-2">
              <span className="shrink-0 text-white/40">leadership</span>
              <span className="truncate tabular-nums text-white/80">{earnLeader ? earnLeader.name : '—'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-white/40">growth</span>
              <span className="font-bold tabular-nums text-terminal-green">
                {earnLeader ? fmtPercent(earnLeader.earnings_yoy) : '—'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Period Selector row */}
      <div className="flex items-center justify-between border-b border-terminal-gray/60 pb-1">
        <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-white/45">
          Performance Horizon
        </span>
        <div className="flex items-center gap-1">
          {availablePeriods['1d'] && (
            <button
              type="button"
              data-testid="analysis-period-1d"
              aria-pressed={period === '1d'}
              onClick={() => setPeriod('1d')}
              className={`border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                period === '1d'
                  ? 'border-terminal-amber bg-terminal-amber text-black'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              1D
            </button>
          )}
          {availablePeriods['1w'] && (
            <button
              type="button"
              data-testid="analysis-period-1w"
              aria-pressed={period === '1w'}
              onClick={() => setPeriod('1w')}
              className={`border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                period === '1w'
                  ? 'border-terminal-amber bg-terminal-amber text-black'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              1W
            </button>
          )}
          {availablePeriods['1m'] && (
            <button
              type="button"
              data-testid="analysis-period-1m"
              aria-pressed={period === '1m'}
              onClick={() => setPeriod('1m')}
              className={`border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                period === '1m'
                  ? 'border-terminal-amber bg-terminal-amber text-black'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              1M
            </button>
          )}
          {availablePeriods['6m'] && (
            <button
              type="button"
              data-testid="analysis-period-6m"
              aria-pressed={period === '6m'}
              onClick={() => setPeriod('6m')}
              className={`border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider transition-colors ${
                period === '6m'
                  ? 'border-terminal-amber bg-terminal-amber text-black'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              6M
            </button>
          )}
        </div>
      </div>

      {/* Momentum Strip */}
      <div
        data-testid="analysis-momentum"
        className={`grid border border-terminal-gray bg-[#070707] ${
          mid ? 'grid-cols-3 divide-x divide-terminal-gray/60' : 'grid-cols-1 divide-y divide-terminal-gray/60'
        }`}
      >
        <div className="p-2">
          <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-amber">Strongest</div>
          <div className="mt-1 flex items-baseline justify-between gap-2">
            <span className="truncate text-[10px] text-white/85">{strongest ? strongest.name : '—'}</span>
            <span className="shrink-0 text-[10px] font-bold tabular-nums text-terminal-green">
              {strongest ? fmtPercent(getPeriodReturn(strongest, period)) : '—'}
            </span>
          </div>
        </div>
        <div className="p-2">
          <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-white/40">Weakest</div>
          <div className="mt-1 flex items-baseline justify-between gap-2">
            <span className="truncate text-[10px] text-white/85">{weakest ? weakest.name : '—'}</span>
            <span className="shrink-0 text-[10px] font-bold tabular-nums text-terminal-red">
              {weakest ? fmtPercent(getPeriodReturn(weakest, period)) : '—'}
            </span>
          </div>
        </div>
        <div className="p-2">
          <div className="text-[9px] font-bold uppercase tracking-[0.16em] text-white/40">Earnings drag</div>
          <div className="mt-1 flex items-baseline justify-between gap-2">
            <span className="truncate text-[10px] text-white/85">{earnDrag ? earnDrag.name : '—'}</span>
            <span className="shrink-0 text-[10px] font-bold tabular-nums text-terminal-red">
              {earnDrag ? fmtPercent(earnDrag.earnings_yoy) : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Movers: Leaders & Laggards */}
      <div className={`grid gap-2 ${mid ? 'grid-cols-2' : 'grid-cols-1'}`}>
        {/* Leaders */}
        <div data-testid="analysis-leaders" className="border border-terminal-gray bg-[#070707] p-2">
          <div className="mb-1 flex items-center justify-between border-b border-terminal-gray/60 pb-1">
            <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-green">
              Leading sectors
            </span>
            <span className="text-[9px] uppercase tracking-wider text-white/35">{period.toUpperCase()}</span>
          </div>
          {leaders.map((c, i) => {
            const ret = getPeriodReturn(c, period);
            const w = ret !== null ? Math.min(100, (Math.abs(ret) / maxAbsReturn) * 100) : 0;
            return (
              <button
                key={c.slug}
                type="button"
                onClick={() => onJumpToCategory(c.slug)}
                className="flex w-full items-center gap-2 border-b border-terminal-gray/25 py-[5px] text-left last:border-b-0 hover:bg-white/[0.03] transition-colors"
              >
                <span className="w-3 shrink-0 text-[9px] tabular-nums text-white/35">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-white/85">{c.name}</span>
                <span className="h-1.5 w-10 shrink-0 overflow-hidden rounded-sm bg-white/5">
                  <span
                    className={`block h-full ${ret !== null && ret >= 0 ? 'bg-terminal-green/70' : 'bg-terminal-red/70'}`}
                    style={{ width: `${w}%` }}
                  />
                </span>
                <span className={`w-12 shrink-0 text-right text-[11px] font-bold tabular-nums ${toneClass(ret)}`}>
                  {fmtPercent(ret)}
                </span>
              </button>
            );
          })}
        </div>

        {/* Laggards */}
        <div data-testid="analysis-laggards" className="border border-terminal-gray bg-[#070707] p-2">
          <div className="mb-1 flex items-center justify-between border-b border-terminal-gray/60 pb-1">
            <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-red">
              Lagging sectors
            </span>
            <span className="text-[9px] uppercase tracking-wider text-white/35">{period.toUpperCase()}</span>
          </div>
          {laggards.map((c, i) => {
            const ret = getPeriodReturn(c, period);
            const w = ret !== null ? Math.min(100, (Math.abs(ret) / maxAbsReturn) * 100) : 0;
            return (
              <button
                key={c.slug}
                type="button"
                onClick={() => onJumpToCategory(c.slug)}
                className="flex w-full items-center gap-2 border-b border-terminal-gray/25 py-[5px] text-left last:border-b-0 hover:bg-white/[0.03] transition-colors"
              >
                <span className="w-3 shrink-0 text-[9px] tabular-nums text-white/35">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-white/85">{c.name}</span>
                <span className="h-1.5 w-10 shrink-0 overflow-hidden rounded-sm bg-white/5">
                  <span
                    className={`block h-full ${ret !== null && ret >= 0 ? 'bg-terminal-green/70' : 'bg-terminal-red/70'}`}
                    style={{ width: `${w}%` }}
                  />
                </span>
                <span className={`w-12 shrink-0 text-right text-[11px] font-bold tabular-nums ${toneClass(ret)}`}>
                  {fmtPercent(ret)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Sector Map */}
      <div data-testid="analysis-sector-map" className="border border-terminal-gray bg-[#070707] p-2">
        <div className="mb-1.5 flex items-center justify-between border-b border-terminal-gray/60 pb-1">
          <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-terminal-amber">Sector map</span>
          <span className="text-[9px] uppercase tracking-wider text-white/35">
            {mapCats.length} of {sectors.length} · largest by mcap
          </span>
        </div>
        <div className={`grid gap-1 ${wide ? 'grid-cols-4' : mid ? 'grid-cols-3' : 'grid-cols-2'}`}>
          {mapCats.map((c) => {
            const ret = getPeriodReturn(c, period);
            const a = c.advance || 1;
            const d = c.decline || 1;
            return (
              <button
                key={c.slug}
                type="button"
                onClick={() => onJumpToCategory(c.slug)}
                className="flex min-w-0 flex-col gap-1 border border-terminal-gray/50 px-1.5 py-1 text-left hover:border-terminal-amber/70 hover:bg-terminal-amber/[0.06] transition-colors"
              >
                <span className="flex items-center justify-between gap-1.5">
                  <span className="truncate text-[10px] text-white/75">{c.name}</span>
                  <span className={`shrink-0 text-[10px] font-bold tabular-nums ${toneClass(ret)}`}>
                    {fmtPercent(ret)}
                  </span>
                </span>
                {/* 3px breadth strip */}
                <div className="flex h-[3px] w-full gap-px overflow-hidden rounded-sm bg-white/5">
                  <div className="bg-terminal-green/70" style={{ flex: a }} />
                  <div className="bg-terminal-red/70" style={{ flex: d }} />
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ─── Split Cockpit (Sectors / Industries) ───────────────────────────────────

interface SplitCockpitPaneProps {
  categoryType: 'sector' | 'industry';
  categories: Category[];
  selectedSlug: string | null;
  onSelectSlug: (slug: string) => void;
  wide: boolean;
  mid: boolean;
}

function SplitCockpitPane({
  categoryType,
  categories,
  selectedSlug,
  onSelectSlug,
  wide,
  mid,
}: SplitCockpitPaneProps) {
  const setChartOverrides = useSetAtom(chartSymbolOverridesAtom);
  const setCompanyOverrides = useSetAtom(companySymbolOverridesAtom);

  const [watchlistTarget, setWatchlistTarget] = useState<{ symbol: string; name: string } | null>(null);

  // Active category — the explicit pick, else the largest by market cap (an
  // alphabetical default lands on a two-stock sector and looks empty)
  const activeCategory =
    categories.find((c) => c.slug === selectedSlug) ||
    [...categories].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))[0] ||
    null;

  const handleOpenChart = useCallback(
    (e: React.MouseEvent, symbol: string) => {
      e.stopPropagation();
      const popoutKey = `popout_direct_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
      setChartOverrides((prev: Record<string, ChartSymbolOverride>) => ({
        ...prev,
        [popoutKey]: { symbol, exchange: 'NSE' },
      }));
      const query = new URLSearchParams({
        symbol,
        exchange: 'NSE',
        popoutPanelId: popoutKey,
      });
      window.open(
        `/widget/CHART?${query.toString()}`,
        `blm_widget_CHART_${popoutKey}`,
        'width=1100,height=720',
      );
    },
    [setChartOverrides],
  );

  const handleOpenCompany = useCallback(
    (e: React.MouseEvent, symbol: string) => {
      e.stopPropagation();
      const popoutKey = `popout_company_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
      setCompanyOverrides((prev: Record<string, CompanySymbolOverride>) => ({
        ...prev,
        [popoutKey]: { symbol },
      }));
      const query = new URLSearchParams({
        symbol,
        popoutPanelId: popoutKey,
      });
      window.open(
        `/widget/COMPANY?${query.toString()}`,
        `blm_widget_COMPANY_${popoutKey}`,
        'width=1200,height=800',
      );
    },
    [setCompanyOverrides],
  );

  // Fetch stocks for selected category
  const endpoint =
    activeCategory
      ? activeCategory.category_type === 'industry'
        ? `/api/py/markets/industries/${activeCategory.slug}/stocks`
        : `/api/py/markets/sectors/${activeCategory.slug}/stocks`
      : null;

  const { data: stocks = [], isLoading: stocksLoading } = useQuery<Stock[]>({
    queryKey: ['market/stocks', activeCategory?.category_type, activeCategory?.slug],
    queryFn: async () => {
      if (!endpoint) return [];
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error('Failed to fetch stocks');
      return res.json() as Promise<Stock[]>;
    },
    enabled: Boolean(endpoint),
    staleTime: 5 * 60 * 1000,
  });

  const paneTestId = categoryType === 'sector' ? 'analysis-pane-sectors' : 'analysis-pane-industries';

  if (!activeCategory) {
    return (
      <div data-testid={paneTestId} className="h-full flex items-center justify-center font-mono text-xs text-white/40">
        No {categoryType === 'sector' ? 'sectors' : 'industries'} available.
      </div>
    );
  }

  const adv = activeCategory.advance || 0;
  const dec = activeCategory.decline || 0;
  const totalStocks = adv + dec;
  const netAdv = adv - dec;
  const advPct = totalStocks > 0 ? Math.round((adv / totalStocks) * 100) : 0;
  const day1d = getPeriodReturn(activeCategory, '1d');

  const insight =
    netAdv > 3
      ? `Breadth firmly positive — ${adv} of ${totalStocks} constituents advancing.`
      : netAdv < -3
        ? `Distribution day — ${dec} of ${totalStocks} constituents declining.`
        : `Mixed tape — ${adv} advancing against ${dec} declining.`;

  const valuationSentence = `P/E ${activeCategory.pe ? activeCategory.pe.toFixed(1) : '—'}x against ${fmtPercent(
    activeCategory.earnings_yoy,
  )} earnings growth — ${
    activeCategory.earnings_yoy > 15
      ? 'growth still justifies the multiple'
      : activeCategory.earnings_yoy < 0
        ? 'multiple is unsupported by earnings'
        : 'fairly priced for the cycle'
  }.`;

  return (
    <div data-testid={paneTestId} className="flex h-full w-full font-mono text-xs overflow-hidden">
      {/* Left rail */}
      <div
        data-testid="analysis-rail"
        data-widget-tour="analysis-rail"
        className={`flex shrink-0 flex-col border-r border-terminal-gray ${
          wide ? 'w-[210px]' : mid ? 'w-[190px]' : 'w-[160px]'
        }`}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-terminal-gray px-2 py-1">
          <span className="text-[9px] font-bold uppercase tracking-wider text-terminal-amber">
            {categoryType === 'industry' ? 'Industries' : 'Sectors'}
          </span>
          <span className="text-[9px] tabular-nums text-white/50">{categories.length}</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          {categories.map((x) => {
            const on = x.slug === activeCategory.slug;
            const r1d = getPeriodReturn(x, '1d');
            const xa = x.advance || 1;
            const xd = x.decline || 1;
            return (
              <button
                key={x.slug}
                type="button"
                data-testid="analysis-rail-item"
                data-slug={x.slug}
                onClick={() => onSelectSlug(x.slug)}
                className={`flex w-full flex-col gap-1 border-b border-l-2 border-b-terminal-gray/30 px-2 py-1.5 text-left transition-colors ${
                  on
                    ? 'border-l-terminal-amber bg-terminal-amber/10'
                    : 'border-l-transparent hover:bg-white/[0.04]'
                }`}
              >
                <div className="flex items-baseline justify-between gap-1">
                  <span
                    className={`truncate text-[10px] ${
                      on ? 'font-bold text-terminal-amber' : 'text-white/80'
                    }`}
                  >
                    {x.name}
                  </span>
                  <span
                    className={`shrink-0 text-[9px] font-bold tabular-nums ${toneClass(r1d)}`}
                  >
                    {fmtPercent(r1d)}
                  </span>
                </div>
                {/* 3px breadth bar */}
                <div className="flex h-[3px] w-full gap-px overflow-hidden rounded-sm bg-white/5">
                  <div className="bg-terminal-green/70" style={{ flex: xa }} />
                  <div className="bg-terminal-red/70" style={{ flex: xd }} />
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Right detail cockpit */}
      <div data-widget-tour="analysis-cockpit" className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {/* Header */}
        <div className="flex shrink-0 items-start justify-between gap-2 border-b border-terminal-gray px-2.5 py-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-bold text-terminal-amber">
                {activeCategory.name}
              </span>
              <span
                className={`shrink-0 border px-1.5 py-[1px] text-[10px] font-bold uppercase tracking-wider rounded-sm ${
                  /Very Bullish/.test(activeCategory.sentiment)
                    ? 'border-terminal-green/60 bg-terminal-green/10 text-terminal-green'
                    : /Bullish/.test(activeCategory.sentiment)
                      ? 'border-terminal-green/30 bg-terminal-green/5 text-terminal-green/80'
                      : /Very Bearish/.test(activeCategory.sentiment)
                        ? 'border-terminal-red/60 bg-terminal-red/10 text-terminal-red'
                        : /Bearish/.test(activeCategory.sentiment)
                          ? 'border-terminal-red/30 bg-terminal-red/5 text-terminal-red/80'
                          : 'border-terminal-gray bg-white/5 text-white/60'
                }`}
              >
                {activeCategory.sentiment ? activeCategory.sentiment.replace('Very ', 'V.') : '—'}
              </span>
            </div>
            <div className="mt-1 text-[10px] tabular-nums text-white/60">
              {totalStocks} stocks · ₹{fmtCrore(activeCategory.market_cap)} · updated{' '}
              {formatRelativeTime(activeCategory.last_updated)}
            </div>
          </div>
          <div className="shrink-0 text-right">
            <div className={`text-lg font-bold tabular-nums ${toneClass(day1d)}`}>
              {fmtPercent(day1d)}
            </div>
            <div className="text-[9px] uppercase tracking-wider text-white/50">1D</div>
          </div>
        </div>

        {/* 6 stats cells */}
        <div
          data-testid="analysis-stats"
          data-widget-tour="analysis-stats"
          className={`grid shrink-0 divide-x divide-terminal-gray border-b border-terminal-gray ${
            mid ? 'grid-cols-6' : 'grid-cols-3'
          }`}
        >
          <div className="px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-white/50">MCap</div>
            <div className="text-[11px] font-bold tabular-nums text-white">
              ₹{fmtCrore(activeCategory.market_cap)}
            </div>
          </div>
          <div className="px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-white/50">P/E</div>
            <div className="text-[11px] font-bold tabular-nums text-white">
              {activeCategory.pe ? `${activeCategory.pe.toFixed(1)}x` : '—'}
            </div>
          </div>
          <div className="px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-white/50">Earn YoY</div>
            <div
              className={`text-[11px] font-bold tabular-nums ${toneClass(activeCategory.earnings_yoy)}`}
            >
              {fmtPercent(activeCategory.earnings_yoy)}
            </div>
          </div>
          <div className="px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-white/50">Adv</div>
            <div className="text-[11px] font-bold tabular-nums text-terminal-green">{adv}</div>
          </div>
          <div className="px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-white/50">Dec</div>
            <div className="text-[11px] font-bold tabular-nums text-terminal-red">{dec}</div>
          </div>
          <div className="px-2 py-1.5">
            <div className="text-[9px] uppercase tracking-wider text-white/50">Net</div>
            <div className={`text-[11px] font-bold tabular-nums ${toneClass(netAdv)}`}>
              {signed(netAdv)}
            </div>
          </div>
        </div>

        {/* Donut + generated insight */}
        <div className="flex shrink-0 items-center gap-3 border-b border-terminal-gray px-2.5 py-2">
          <div
            data-testid="analysis-donut"
            className="relative h-14 w-14 shrink-0 rounded-full"
            style={{
              background: `conic-gradient(#00ff00 0% ${advPct}%, #ff0000 ${advPct}% 100%)`,
            }}
          >
            <div className="absolute inset-[7px] rounded-full bg-black" />
            <div className="absolute inset-0 flex items-center justify-center text-[10px] font-bold tabular-nums text-white">
              {advPct}%
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-bold uppercase tracking-wider text-terminal-amber">Read</div>
            <div className="mt-0.5 text-[11px] leading-snug text-white/80">{insight}</div>
            <div className="mt-0.5 text-[10px] leading-snug text-white/50">{valuationSentence}</div>
          </div>
        </div>

        {/* Constituents subheader */}
        <div className="flex shrink-0 items-center justify-between border-b border-terminal-gray px-2.5 py-1">
          <span className="text-[9px] font-bold uppercase tracking-wider text-white/50">Constituents</span>
          <span className="text-[9px] uppercase tracking-wider text-white/35">row click opens company</span>
        </div>

        {/* Constituents table */}
        <div
          data-testid="analysis-constituents"
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {/* Table Header */}
          <div
            className={`sticky top-0 z-10 grid gap-2 border-b border-terminal-gray bg-black px-2.5 py-1 items-center ${
              mid
                ? 'grid-cols-[minmax(0,1fr)_68px_54px_auto]'
                : 'grid-cols-[minmax(0,1fr)_62px_52px_auto]'
            }`}
          >
            <span className="text-[9px] uppercase tracking-wider text-white/50">Company</span>
            <span className="text-right text-[9px] uppercase tracking-wider text-white/50">LTP</span>
            <span className="text-right text-[9px] uppercase tracking-wider text-white/50">1D</span>
            <span className="text-right text-[9px] uppercase tracking-wider text-white/50">Actions</span>
          </div>

          {stocksLoading ? (
            <div className="p-4 text-center text-[10px] text-white/40">Loading constituents...</div>
          ) : stocks.length === 0 ? (
            <div className="p-4 text-center text-[10px] text-white/40">No constituents available</div>
          ) : (
            stocks.map((s) => (
              <div
                key={s.id || s.symbol}
                data-testid="analysis-row"
                data-symbol={s.symbol}
                onClick={(e) => handleOpenCompany(e, s.symbol)}
                className={`grid gap-2 border-b border-terminal-gray/30 px-2.5 py-1.5 cursor-pointer hover:bg-terminal-amber/[0.06] transition-colors items-center ${
                  mid
                    ? 'grid-cols-[minmax(0,1fr)_68px_54px_auto]'
                    : 'grid-cols-[minmax(0,1fr)_62px_52px_auto]'
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate text-[11px] text-white/90">
                    {s.company_name || s.symbol}
                  </div>
                  <div className="text-[9px] tabular-nums text-white/50">
                    {s.symbol} · {s.ttm_pe ? `${s.ttm_pe.toFixed(1)}x` : '—'}
                  </div>
                </div>

                <span className="text-right text-[11px] tabular-nums text-white/80">
                  ₹{s.curr_price ? s.curr_price.toFixed(2) : '—'}
                </span>

                <span className={`text-right text-[11px] font-bold tabular-nums ${toneClass(s.per_change)}`}>
                  {fmtPercent(s.per_change)}
                </span>

                {/* Actions */}
                <div data-widget-tour="analysis-actions" className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    data-testid="analysis-act-chart"
                    aria-label={`Open chart for ${s.symbol}`}
                    onClick={(e) => handleOpenChart(e, s.symbol)}
                    className="inline-flex min-h-[22px] items-center gap-1 border border-terminal-gray bg-[#0a0a0a] px-1.5 py-0.5 text-[9px] font-bold leading-none text-white/75 rounded-sm hover:border-terminal-amber hover:text-terminal-amber hover:bg-terminal-amber/10 active:scale-95 transition-all"
                  >
                    <span aria-hidden="true">⚡</span>
                    {wide && <span>Chart</span>}
                  </button>

                  <button
                    type="button"
                    data-testid="analysis-act-company"
                    aria-label={`Open company page for ${s.symbol}`}
                    onClick={(e) => handleOpenCompany(e, s.symbol)}
                    className="inline-flex min-h-[22px] items-center gap-1 border border-terminal-gray bg-[#0a0a0a] px-1.5 py-0.5 text-[9px] font-bold leading-none text-white/75 rounded-sm hover:border-terminal-amber hover:text-terminal-amber hover:bg-terminal-amber/10 active:scale-95 transition-all"
                  >
                    <span aria-hidden="true">🏢</span>
                    {wide && <span>Company</span>}
                  </button>

                  <button
                    type="button"
                    data-testid="analysis-act-watch"
                    aria-label={`Add ${s.symbol} to watchlist`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setWatchlistTarget({ symbol: s.symbol, name: s.company_name || s.symbol });
                    }}
                    className="inline-flex min-h-[22px] items-center gap-1 border border-terminal-gray bg-[#0a0a0a] px-1.5 py-0.5 text-[9px] font-bold leading-none text-white/75 rounded-sm hover:border-terminal-amber hover:text-terminal-amber hover:bg-terminal-amber/10 active:scale-95 transition-all"
                  >
                    <span aria-hidden="true">★</span>
                    {wide && <span>Watch</span>}
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Watchlist Modal */}
      {watchlistTarget && (
        <WatchlistModal
          symbol={watchlistTarget.symbol}
          companyName={watchlistTarget.name}
          onClose={() => setWatchlistTarget(null)}
        />
      )}
    </div>
  );
}

// ─── Heatmap Types & Constants ───────────────────────────────────────────────

type HeatScope = 'sector' | 'industry' | 'all';
type HeatMetricKey = 'breadth' | 'earnings' | 'sentiment' | 'perf';
type HeatSortKey =
  | 'chg'
  | 'chg1w'
  | 'chg1m'
  | 'chg6m'
  | 'mcap'
  | 'net'
  | 'earn'
  | 'pe'
  | 'adv'
  | 'sent'
  | 'name';

interface HeatBucketStyle {
  bg: string;
  bd: string;
  fg: string;
  sw: string;
}

const HEAT_BUCKET_STYLE: HeatBucketStyle[] = [
  { bg: 'rgba(255,0,0,.30)', bd: 'rgba(255,0,0,.62)', fg: '#ffb8b8', sw: '#ff2b2b' },
  { bg: 'rgba(255,0,0,.15)', bd: 'rgba(255,0,0,.38)', fg: '#ffa8a8', sw: '#ff4d4d' },
  { bg: 'rgba(255,255,255,.05)', bd: 'rgba(70,70,70,1)', fg: '#cfcfcf', sw: '#4a4a4a' },
  { bg: 'rgba(0,255,0,.14)', bd: 'rgba(0,255,0,.34)', fg: '#b3ffb3', sw: '#67ff67' },
  { bg: 'rgba(0,255,0,.27)', bd: 'rgba(0,255,0,.58)', fg: '#8dff8d', sw: '#00ff00' },
];

const HEAT_SORT_LABELS: Record<HeatSortKey, string> = {
  chg: '1D %',
  chg1w: '1W %',
  chg1m: '1M %',
  chg6m: '6M %',
  mcap: 'Market cap',
  net: 'Net A/D',
  earn: 'Earn YoY',
  pe: 'P/E',
  adv: 'Advancers',
  sent: 'Sentiment',
  name: 'Name A–Z',
};

const HEAT_SORT_GROUPS: Array<{ label: string; keys: HeatSortKey[] }> = [
  { label: 'Performance', keys: ['chg', 'chg1w', 'chg1m', 'chg6m'] },
  { label: 'Structure', keys: ['mcap', 'net', 'earn', 'pe', 'adv', 'sent', 'name'] },
];

const PERIOD_SORT_KEYS = new Set<HeatSortKey>(['chg', 'chg1w', 'chg1m', 'chg6m']);

const PERF_BANDS: Record<string, [number, number]> = {
  chg: [2, 6],
  chg1w: [2, 5],
  chg1m: [2, 8],
  chg6m: [6, 20],
};

function getSentRank(sent: string | null | undefined): number {
  if (!sent) return 2;
  if (/Very Bullish/i.test(sent)) return 5;
  if (/Bullish/i.test(sent)) return 4;
  if (/Neutral/i.test(sent)) return 3;
  if (/Very Bearish/i.test(sent)) return 1;
  return 2;
}

function getNetAdv(c: Category): number {
  return (c.advance || 0) - (c.decline || 0);
}

function getNetRatio(c: Category): number {
  const tot = (c.advance || 0) + (c.decline || 0);
  if (tot === 0) return 0;
  return ((c.advance || 0) - (c.decline || 0)) / tot;
}

interface MetricDef {
  label: string;
  desc: string;
  tile: (c: Category) => string;
  sub: (c: Category) => string;
  score: (c: Category) => number | null;
  bucketOf: (c: Category) => number;
  keys: [string, string, string, string, string];
  ranges: [string, string, string, string, string];
  short: [string, string, string, string, string];
}

const STATIC_METRICS: Record<'breadth' | 'earnings' | 'sentiment', MetricDef> = {
  breadth: {
    label: 'Net A/D',
    desc: 'advance minus decline',
    tile: (c) => signed(getNetAdv(c)),
    sub: (c) => `${c.advance || 0}/${c.decline || 0}`,
    score: (c) => getNetAdv(c),
    bucketOf: (c) => {
      const v = getNetRatio(c);
      return v <= -0.5 ? 0 : v < -0.18 ? 1 : v > 0.5 ? 4 : v > 0.18 ? 3 : 2;
    },
    keys: ['Heavy selling', 'Selling', 'Balanced', 'Buying', 'Heavy buying'],
    ranges: ['net ≤ −50%', '−50% to −18%', '±18%', '+18% to +50%', 'net ≥ +50%'],
    short: ['≤−50%', '−50…−18%', '±18%', '+18…+50%', '≥+50%'],
  },
  earnings: {
    label: 'Earnings YoY',
    desc: 'profit growth, year on year',
    tile: (c) => fmtPercent(c.earnings_yoy),
    sub: () => 'YoY',
    score: (c) => c.earnings_yoy ?? null,
    bucketOf: (c) => {
      const v = c.earnings_yoy ?? 0;
      return v <= -20 ? 0 : v < -5 ? 1 : v > 20 ? 4 : v > 5 ? 3 : 2;
    },
    keys: ['Collapsing', 'Contracting', 'Flat', 'Growing', 'Surging'],
    ranges: ['≤ −20%', '−20% to −5%', '±5%', '+5% to +20%', '≥ +20%'],
    short: ['≤−20%', '−20…−5%', '±5%', '+5…+20%', '≥+20%'],
  },
  sentiment: {
    label: 'Sentiment',
    desc: 'aggregate sector call',
    tile: (c) => (c.sentiment ? c.sentiment.replace('Very ', 'V.') : '—'),
    sub: (c) => fmtPercent(c.return_1d),
    score: (c) => {
      const s = c.sentiment || '';
      return /Very Bullish/i.test(s) ? 4 : /Bullish/i.test(s) ? 3 : /Very Bearish/i.test(s) ? 0 : /Bearish/i.test(s) ? 1 : 2;
    },
    bucketOf: (c) => {
      const s = c.sentiment || '';
      return /Very Bullish/i.test(s) ? 4 : /Bullish/i.test(s) ? 3 : /Very Bearish/i.test(s) ? 0 : /Bearish/i.test(s) ? 1 : 2;
    },
    keys: ['Very bearish', 'Bearish', 'Neutral', 'Bullish', 'Very bullish'],
    ranges: ['bearish aggregate', 'bearish', 'no direction', 'bullish', 'bullish aggregate'],
    short: ['V.Bear', 'Bear', 'Neutral', 'Bull', 'V.Bull'],
  },
};

function getPerfMetric(key: HeatSortKey): MetricDef {
  const [lo, hi] = PERF_BANDS[key] || [3, 8];
  const b = (v: number | null | undefined) => {
    if (v === null || v === undefined) return 2;
    return v <= -hi ? 0 : v < -lo ? 1 : v > hi ? 4 : v > lo ? 3 : 2;
  };
  const getVal = (c: Category) =>
    key === 'chg'
      ? c.return_1d
      : key === 'chg1w'
        ? c.return_1w
        : key === 'chg1m'
          ? c.return_1m
          : c.return_6m;

  return {
    label: `${HEAT_SORT_LABELS[key]} return`,
    desc: 'period % change',
    tile: (c) => fmtPercent(getVal(c)),
    sub: (c) => `${c.advance || 0}/${c.decline || 0}`,
    score: (c) => getVal(c),
    bucketOf: (c) => b(getVal(c)),
    keys: ['Selling hard', 'Selling', 'Flat', 'Buying', 'Buying hard'],
    ranges: [`≤ −${hi}%`, `−${hi}% to −${lo}%`, `±${lo}%`, `+${lo}% to +${hi}%`, `≥ +${hi}%`],
    short: [`≤−${hi}%`, `−${hi}…−${lo}%`, `±${lo}%`, `+${lo}…+${hi}%`, `≥+${hi}%`],
  };
}

function sortTiles(pool: Category[], key: HeatSortKey, dir: 'asc' | 'desc'): Category[] {
  const val = (c: Category): number | string | null => {
    if (key === 'name') return c.name.toLowerCase();
    if (key === 'net') return getNetAdv(c);
    if (key === 'sent') return getSentRank(c.sentiment);
    if (key === 'mcap') return c.market_cap;
    if (key === 'adv') return c.advance;
    if (key === 'earn') return c.earnings_yoy;
    if (key === 'pe') return c.pe;
    if (key === 'chg') return c.return_1d;
    if (key === 'chg1w') return c.return_1w;
    if (key === 'chg1m') return c.return_1m;
    if (key === 'chg6m') return c.return_6m;
    return null;
  };
  const missing = (v: unknown): boolean =>
    v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v));

  return [...pool].sort((a, b) => {
    const av = val(a);
    const bv = val(b);
    if (missing(av) || missing(bv)) return missing(av) ? (missing(bv) ? 0 : 1) : -1;
    const r =
      typeof av === 'string'
        ? av.localeCompare(bv as string)
        : (av as number) - (bv as number);
    return dir === 'asc' ? r : -r;
  });
}

// ─── Heatmap Drawer Component ────────────────────────────────────────────────

interface HeatmapDrawerProps {
  category: Category;
  onClose: () => void;
  onOpenChart: (e: React.MouseEvent, symbol: string) => void;
  onOpenCompany: (e: React.MouseEvent, symbol: string) => void;
  onOpenWatchlist: (symbol: string, name: string) => void;
}

type DrawerSortKey = 'symbol' | 'ltp' | 'chg' | 'pe';

// One template per pane width, used verbatim by the sticky header and every
// row. Sharing the literal is what keeps each label over its own values.
// The actions column is fixed and slightly wider than its three buttons need,
// and the buttons are laid out with their own 3-column grid, so a long label
// can never spill back over the P/E column.
const DRAWER_ROW_COMPACT = 'grid grid-cols-[minmax(0,1fr)_58px_50px_44px_86px] gap-2 items-center';
const DRAWER_ROW_WIDE = 'grid grid-cols-[minmax(0,1fr)_66px_56px_50px_198px] gap-2 items-center';

const DRAWER_MIN_WIDTH = 300;
const DRAWER_DEFAULT_MAX = 430;
// Below this the action buttons lose their text labels and the pane switches
// to the compact column template. 580 is the width at which the wide template
// still leaves the symbol column enough room to read a company name.
const DRAWER_LABEL_WIDTH = 580;

function HeatmapDrawer({
  category,
  onClose,
  onOpenChart,
  onOpenCompany,
  onOpenWatchlist,
}: HeatmapDrawerProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Drag-resizable pane. null means "auto": 94% of the overlay capped at 430px,
  // so the drawer still behaves the old way until the user grabs the edge.
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const [paneWidth, setPaneWidth] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<DrawerSortKey | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const startResize = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const overlay = overlayRef.current;
    if (!overlay) return;
    event.preventDefault();
    event.stopPropagation();
    const bounds = overlay.getBoundingClientRect();
    const apply = (clientX: number) => {
      const next = bounds.right - clientX;
      setPaneWidth(Math.min(bounds.width, Math.max(DRAWER_MIN_WIDTH, next)));
    };
    apply(event.clientX);
    const onMove = (e: PointerEvent) => apply(e.clientX);
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }, []);

  const handleSort = (key: DrawerSortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    setSortDir(key === 'symbol' ? 'asc' : 'desc');
  };

  const sortIndicator = (key: DrawerSortKey) =>
    sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '';

  const endpoint =
    category.category_type === 'industry'
      ? `/api/py/markets/industries/${category.slug}/stocks`
      : `/api/py/markets/sectors/${category.slug}/stocks`;

  const { data: stocks = [], isLoading: stocksLoading } = useQuery<Stock[]>({
    queryKey: ['market/stocks', category.category_type, category.slug],
    queryFn: async () => {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error('Failed to fetch stocks');
      return res.json() as Promise<Stock[]>;
    },
    staleTime: 5 * 60 * 1000,
  });

  const netAdv = getNetAdv(category);

  // Same column set/order as the watchlist, so the header always labels the
  // cell underneath it.
  const sortedStocks = useMemo(() => {
    if (!sortKey) return stocks;
    const dir = sortDir === 'asc' ? 1 : -1;
    const valueOf = (s: Stock): string | number => {
      if (sortKey === 'symbol') return (s.company_name || s.symbol).toUpperCase();
      if (sortKey === 'ltp') return s.curr_price ?? 0;
      if (sortKey === 'chg') return s.per_change ?? 0;
      return s.ttm_pe ?? 0;
    };
    return [...stocks].sort((a, b) => {
      const va = valueOf(a);
      const vb = valueOf(b);
      if (typeof va === 'string' || typeof vb === 'string') {
        return String(va).localeCompare(String(vb)) * dir;
      }
      return (Number(va) - Number(vb)) * dir;
    });
  }, [stocks, sortKey, sortDir]);

  const narrowPane = (paneWidth ?? DRAWER_DEFAULT_MAX) < DRAWER_LABEL_WIDTH;
  const rowGrid = narrowPane ? DRAWER_ROW_COMPACT : DRAWER_ROW_WIDE;

  const headerCell = (key: DrawerSortKey, label: string, align: 'left' | 'right') => (
    <button
      type="button"
      onClick={() => handleSort(key)}
      aria-label={`Sort by ${label}`}
      className={`whitespace-nowrap text-[9px] uppercase tracking-wider transition-colors hover:text-terminal-amber ${
        align === 'right' ? 'text-right' : 'text-left'
      } ${sortKey === key ? 'text-terminal-amber' : 'text-white/60'}`}
    >
      {label}
      {sortIndicator(key)}
    </button>
  );

  return (
    <div
      data-testid="analysis-drawer"
      ref={overlayRef}
      className="absolute inset-0 z-40 flex justify-end bg-black/70 backdrop-blur-xs font-mono"
      onClick={onClose}
    >
      <div
        className={`relative flex h-full flex-col border-l border-terminal-amber/40 bg-terminal-bg shadow-2xl overflow-hidden ${
          paneWidth === null ? 'w-[94%] max-w-[430px]' : 'max-w-full'
        }`}
        style={paneWidth === null ? undefined : { width: `${paneWidth}px` }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Resize handle: drag the left edge, double-click to reset */}
        <div
          data-testid="analysis-drawer-resize"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize constituent pane"
          title="Drag to resize · double-click to reset"
          onPointerDown={startResize}
          onDoubleClick={() => setPaneWidth(null)}
          className="group absolute inset-y-0 left-0 z-20 w-1.5 cursor-col-resize touch-none"
        >
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-px bg-terminal-gray transition-colors group-hover:w-0.5 group-hover:bg-terminal-amber"
          />
        </div>
        {/* Header */}
        <div className="flex shrink-0 items-start justify-between gap-2 border-b border-terminal-gray p-2.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-bold text-terminal-amber">{category.name}</span>
              <span className="shrink-0 border border-terminal-gray px-1 text-[9px] uppercase tracking-wider text-white/60">
                {category.category_type}
              </span>
              <span
                className={`shrink-0 border px-1 text-[9px] font-bold uppercase tracking-wider ${
                  category.sentiment === 'Bullish' || category.sentiment === 'Very Bullish'
                    ? 'border-terminal-green/50 bg-terminal-green/10 text-terminal-green'
                    : category.sentiment === 'Bearish' || category.sentiment === 'Very Bearish'
                      ? 'border-terminal-red/50 bg-terminal-red/10 text-terminal-red'
                      : 'border-terminal-gray bg-white/5 text-white/60'
                }`}
              >
                {category.sentiment ? category.sentiment.replace('Very ', 'V.') : '—'}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[10px] tabular-nums text-white/60">
              <span className={`text-xs font-bold ${toneClass(category.return_1d)}`}>
                {fmtPercent(category.return_1d)}
              </span>
              <span>P/E {category.pe ? `${category.pe.toFixed(1)}x` : '—'}</span>
              <span className={toneClass(category.earnings_yoy)}>
                {fmtPercent(category.earnings_yoy)} YoY
              </span>
            </div>
          </div>
          <button
            type="button"
            data-testid="analysis-drawer-close"
            onClick={onClose}
            aria-label="Close drawer"
            className="shrink-0 border border-terminal-gray px-2 py-0.5 text-[11px] text-white/60 hover:border-terminal-amber hover:text-terminal-amber transition-colors"
          >
            ✕
          </button>
        </div>

        {/* 6 stats cells */}
        <div className="grid shrink-0 grid-cols-3 divide-x divide-terminal-gray border-b border-terminal-gray">
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">MCap</div>
            <div className="text-xs font-bold tabular-nums text-white">₹{fmtCrore(category.market_cap)}</div>
          </div>
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">P/E</div>
            <div className="text-xs font-bold tabular-nums text-white">
              {category.pe ? `${category.pe.toFixed(1)}x` : '—'}
            </div>
          </div>
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">Earn YoY</div>
            <div className={`text-xs font-bold tabular-nums ${toneClass(category.earnings_yoy)}`}>
              {fmtPercent(category.earnings_yoy)}
            </div>
          </div>
        </div>

        <div className="grid shrink-0 grid-cols-3 divide-x divide-terminal-gray border-b border-terminal-gray">
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">Adv</div>
            <div className="text-xs font-bold tabular-nums text-terminal-green">{category.advance || 0}</div>
          </div>
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">Dec</div>
            <div className="text-xs font-bold tabular-nums text-terminal-red">{category.decline || 0}</div>
          </div>
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">Net</div>
            <div className={`text-xs font-bold tabular-nums ${toneClass(netAdv)}`}>{signed(netAdv)}</div>
          </div>
        </div>

        {/* 1W / 1M / 6M Returns Strip */}
        <div className="grid shrink-0 grid-cols-3 divide-x divide-terminal-gray border-b border-terminal-gray">
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">1W return</div>
            <div className={`text-xs font-bold tabular-nums ${toneClass(category.return_1w)}`}>
              {fmtPercent(category.return_1w)}
            </div>
          </div>
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">1M return</div>
            <div className={`text-xs font-bold tabular-nums ${toneClass(category.return_1m)}`}>
              {fmtPercent(category.return_1m)}
            </div>
          </div>
          <div className="p-2">
            <div className="text-[9px] uppercase tracking-wider text-white/60">6M return</div>
            <div className={`text-xs font-bold tabular-nums ${toneClass(category.return_6m)}`}>
              {fmtPercent(category.return_6m)}
            </div>
          </div>
        </div>

        {/* Constituents Table */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div
            className={`sticky top-0 z-10 border-b border-terminal-gray bg-black px-2.5 py-1 ${rowGrid}`}
          >
            {headerCell('symbol', 'Symbol', 'left')}
            {headerCell('ltp', 'LTP', 'right')}
            {headerCell('chg', 'Chg%', 'right')}
            {headerCell('pe', 'P/E', 'right')}
            <span className="text-right text-[9px] uppercase tracking-wider text-white/60">Actions</span>
          </div>

          {stocksLoading ? (
            <div className="p-4 text-center text-[10px] text-white/40">Loading constituents...</div>
          ) : stocks.length === 0 ? (
            <div className="p-4 text-center text-[10px] text-white/40">No constituents available</div>
          ) : (
            sortedStocks.map((s) => (
              <div
                key={s.id || s.symbol}
                data-testid="analysis-row"
                data-symbol={s.symbol}
                onClick={(e) => onOpenCompany(e, s.symbol)}
                className={`border-b border-terminal-gray/30 px-2.5 py-1.5 cursor-pointer hover:bg-terminal-amber/[0.06] transition-colors ${rowGrid}`}
              >
                <div className="min-w-0">
                  <div className="truncate text-[11px] text-white/90">{s.company_name || s.symbol}</div>
                  <div className="text-[9px] tabular-nums text-white/50">{s.symbol}</div>
                </div>

                <span className="min-w-0 truncate text-right text-[11px] tabular-nums text-white/80">
                  ₹{s.curr_price ? s.curr_price.toFixed(2) : '—'}
                </span>

                <span
                  className={`min-w-0 truncate text-right text-[11px] font-bold tabular-nums ${toneClass(s.per_change)}`}
                >
                  {fmtPercent(s.per_change)}
                </span>

                <span className="min-w-0 truncate text-right text-[11px] tabular-nums text-white/60">
                  {s.ttm_pe ? `${s.ttm_pe.toFixed(1)}x` : '—'}
                </span>

                {/* Actions: a fixed 3-column grid inside the fixed-width cell, so
                    the buttons can never push back over the P/E column. */}
                <div className="grid w-full grid-cols-3 gap-1" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    data-testid="analysis-act-chart"
                    aria-label={`Open chart for ${s.symbol}`}
                    onClick={(e) => onOpenChart(e, s.symbol)}
                    className="inline-flex min-h-[22px] min-w-0 items-center justify-center gap-1 border border-terminal-gray bg-[#0a0a0a] px-1 py-0.5 text-[9px] font-bold leading-none text-white/75 rounded-sm hover:border-terminal-amber hover:text-terminal-amber hover:bg-terminal-amber/10 active:scale-95 transition-all"
                  >
                    <span aria-hidden="true">⚡</span>
                    {!narrowPane && <span className="truncate">Chart</span>}
                  </button>

                  <button
                    type="button"
                    data-testid="analysis-act-company"
                    aria-label={`Open company page for ${s.symbol}`}
                    onClick={(e) => onOpenCompany(e, s.symbol)}
                    className="inline-flex min-h-[22px] min-w-0 items-center justify-center gap-1 border border-terminal-gray bg-[#0a0a0a] px-1 py-0.5 text-[9px] font-bold leading-none text-white/75 rounded-sm hover:border-terminal-amber hover:text-terminal-amber hover:bg-terminal-amber/10 active:scale-95 transition-all"
                  >
                    <span aria-hidden="true">🏢</span>
                    {!narrowPane && <span className="truncate">Company</span>}
                  </button>

                  <button
                    type="button"
                    data-testid="analysis-act-watch"
                    aria-label={`Add ${s.symbol} to watchlist`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenWatchlist(s.symbol, s.company_name || s.symbol);
                    }}
                    className="inline-flex min-h-[22px] min-w-0 items-center justify-center gap-1 border border-terminal-gray bg-[#0a0a0a] px-1 py-0.5 text-[9px] font-bold leading-none text-white/75 rounded-sm hover:border-terminal-amber hover:text-terminal-amber hover:bg-terminal-amber/10 active:scale-95 transition-all"
                  >
                    <span aria-hidden="true">★</span>
                    {!narrowPane && <span className="truncate">Watch</span>}
                  </button>
                </div>
              </div>
            ))
          )}
          <div className="px-2.5 py-2 text-[9px] uppercase tracking-wider text-white/35">
            {sortedStocks.length} constituents
            {sortKey ? ` · sorted by ${sortKey}` : ' · largest first'}
            {' · click a header to sort'}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Heatmap Tab (Rewritten) ──────────────────────────────────────────────────

interface HeatmapPaneProps {
  sectors: Category[];
  industries: Category[];
  wide?: boolean;
  mid?: boolean;
}

function HeatmapPane({ sectors, industries, wide = true, mid = true }: HeatmapPaneProps) {
  const setChartOverrides = useSetAtom(chartSymbolOverridesAtom);
  const setCompanyOverrides = useSetAtom(companySymbolOverridesAtom);

  const [scope, setScope] = useState<HeatScope>('all');
  const [metricKey, setMetricKey] = useState<HeatMetricKey>('breadth');
  const [sortKey, setSortKey] = useState<HeatSortKey>('mcap');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [isolatedBucket, setIsolatedBucket] = useState<number | null>(null);
  const [hoveredBucket, setHoveredBucket] = useState<number | null>(null);
  const [drawerCategory, setDrawerCategory] = useState<Category | null>(null);
  const [watchlistTarget, setWatchlistTarget] = useState<{ symbol: string; name: string } | null>(null);

  // Tiles are percentage-based horizontally (column width) but pixel-based
  // vertically: the map is a flex child whose computed height is `auto`, so
  // `height: X%` on absolutely positioned tiles falls back to content height
  // and overlaps.
  const mapBoxRef = useRef<HTMLDivElement | null>(null);
  const [mapWidth, setMapWidth] = useState(680);
  useEffect(() => {
    const el = mapBoxRef.current;
    if (!el) return;
    const measure = () => {
      setMapWidth(Math.max(200, el.clientWidth - 12));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // A new scope / metric / ordering replaces the pool, so start reading at the
  // top of the map instead of wherever the scroll position happened to be.
  useEffect(() => {
    mapBoxRef.current?.scrollTo({ top: 0 });
  }, [scope, metricKey, sortKey, sortDir]);

  // Keyboard navigation: Escape closes drawer/modal
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (watchlistTarget) setWatchlistTarget(null);
        else if (drawerCategory) setDrawerCategory(null);
        else if (isolatedBucket !== null) setIsolatedBucket(null);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawerCategory, watchlistTarget, isolatedBucket]);

  // Handle Sort Change
  const handleSortChange = (newSort: HeatSortKey) => {
    setSortKey(newSort);
    if (PERIOD_SORT_KEYS.has(newSort) && metricKey !== 'perf') {
      setMetricKey('perf');
    }
  };

  const isPeriodSort = PERIOD_SORT_KEYS.has(sortKey);
  const period = isPeriodSort ? sortKey : null;

  // Active Metric
  const activeMetric = useMemo<MetricDef>(() => {
    if (metricKey === 'perf') {
      return getPerfMetric(period || 'chg1m');
    }
    return STATIC_METRICS[metricKey];
  }, [metricKey, period]);

  // Base Categories: de-duplicated by name when scope is all
  const baseCategories = useMemo<Category[]>(() => {
    const raw =
      scope === 'sector'
        ? sectors
        : scope === 'industry'
          ? industries
          : [...sectors, ...industries];
    // De-duplicate across scopes. NSE often publishes a sector and an industry
    // over the exact same constituents (e.g. "Personal Products" / "Personal
    // Care" with identical market cap and breadth), so identity is the metric
    // fingerprint, not the name. Name is the fallback when caps are missing.
    if (scope !== 'all') return raw;
    const seen = new Set<string>();
    return raw.filter((cat) => {
      const key =
        cat.market_cap != null
          ? `${cat.market_cap.toFixed(1)}|${cat.advance ?? ''}|${cat.decline ?? ''}`
          : cat.name.trim().toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [scope, sectors, industries]);

  // Sorted pool (drives leaderboards + tile selection)
  const pool = useMemo(() => {
    return sortTiles(baseCategories, sortKey, sortDir);
  }, [baseCategories, sortKey, sortDir]);

  // Uniform heat grid. Every tile is the same size, so tiles can carry a
  // summary (name, value, adv/dec) instead of the old market-cap-weighted
  // treemap whose tail shrank below legibility and had to be dropped. Rows
  // stack vertically inside the scroll container, so the whole pool stays
  // reachable.
  // Tiles are sized to hold a wrapped name: 132px wide keeps ~17 characters
  // per line at 11px, and 100px tall leaves room for three name lines plus the
  // value and breadth rows.
  const UNIFORM_TILE_MIN_W = 132;
  const UNIFORM_TILE_H = 100;
  const { tiles, cols } = useMemo(() => {
    const columns = Math.max(1, Math.floor(mapWidth / UNIFORM_TILE_MIN_W));
    return {
      cols: columns,
      tiles: pool.map((cat, i) => ({ cat, row: Math.floor(i / columns), col: i % columns })),
    };
  }, [pool, mapWidth]);
  const rowCount = Math.ceil(tiles.length / cols);
  const tileW = 100 / cols;

  // Bucket counts (whole scope, so the legend describes the market rather than
  // only the tiles that survived the readability filter)
  const counts = useMemo(() => {
    const c = [0, 0, 0, 0, 0];
    for (const item of baseCategories) {
      const b = activeMetric.bucketOf(item);
      if (b >= 0 && b < 5) c[b]++;
    }
    return c;
  }, [baseCategories, activeMetric]);

  // Leaders & Laggards
  const { leaders, laggards, maxAbs } = useMemo(() => {
    const rankOf = period
      ? (c: Category) =>
          period === 'chg'
            ? c.return_1d
            : period === 'chg1w'
              ? c.return_1w
              : period === 'chg1m'
                ? c.return_1m
                : c.return_6m
      : (c: Category) => activeMetric.score(c);

    const missing = (v: unknown): boolean =>
      v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v));

    const ranked = [...baseCategories].sort((a, b) => {
      const av = rankOf(a);
      const bv = rankOf(b);
      if (missing(av) || missing(bv)) return missing(av) ? (missing(bv) ? 0 : 1) : -1;
      return (bv as number) - (av as number);
    });

    // Nulls must never reach the leaderboards: a category with no score for the
    // selected horizon would otherwise surface as the "worst" with a dash.
    const valid = ranked.filter((c) => !missing(rankOf(c)));

    const l = valid.slice(0, 4);
    const lag = valid.slice(-4).reverse();
    const maxVal = Math.max(
      ...baseCategories.map((c) => {
        const v = rankOf(c);
        return missing(v) ? 0 : Math.abs(v as number);
      }),
      1,
    );

    return { leaders: l, laggards: lag, maxAbs: maxVal };
  }, [baseCategories, period, activeMetric]);

  // Popouts
  const handleOpenChart = useCallback(
    (e: React.MouseEvent, symbol: string) => {
      e.stopPropagation();
      const popoutKey = `popout_direct_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
      setChartOverrides((prev: Record<string, ChartSymbolOverride>) => ({
        ...prev,
        [popoutKey]: { symbol, exchange: 'NSE' },
      }));
      const query = new URLSearchParams({
        symbol,
        exchange: 'NSE',
        popoutPanelId: popoutKey,
      });
      window.open(
        `/widget/CHART?${query.toString()}`,
        `blm_widget_CHART_${popoutKey}`,
        'width=1100,height=720',
      );
    },
    [setChartOverrides],
  );

  const handleOpenCompany = useCallback(
    (e: React.MouseEvent, symbol: string) => {
      e.stopPropagation();
      const popoutKey = `popout_company_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
      setCompanyOverrides((prev: Record<string, CompanySymbolOverride>) => ({
        ...prev,
        [popoutKey]: { symbol },
      }));
      const query = new URLSearchParams({
        symbol,
        popoutPanelId: popoutKey,
      });
      window.open(
        `/widget/COMPANY?${query.toString()}`,
        `blm_widget_COMPANY_${popoutKey}`,
        'width=1200,height=800',
      );
    },
    [setCompanyOverrides],
  );

  const handleOpenWatchlist = useCallback((symbol: string, name: string) => {
    setWatchlistTarget({ symbol, name });
  }, []);

  return (
    <div
      data-testid="analysis-pane-heatmap"
      className="flex h-full flex-col font-mono text-xs overflow-hidden relative select-none"
    >
      <div className="h-full overflow-y-auto flex flex-col">
        {/* 1. Scope + count row */}
        <div
          data-widget-tour="analysis-heat-controls"
          className="flex h-8 shrink-0 items-center justify-between gap-2 border-b border-terminal-gray px-2"
        >
          <div className="flex items-center gap-3">
            <button
              type="button"
              data-testid="analysis-heat-scope-sector"
              onClick={() => {
                setScope('sector');
                setIsolatedBucket(null);
              }}
              className={`text-[10px] font-bold uppercase tracking-wider transition-colors ${
                scope === 'sector' ? 'text-terminal-amber' : 'text-white/50 hover:text-white'
              }`}
            >
              Sectors
            </button>
            <button
              type="button"
              data-testid="analysis-heat-scope-industry"
              onClick={() => {
                setScope('industry');
                setIsolatedBucket(null);
              }}
              className={`text-[10px] font-bold uppercase tracking-wider transition-colors ${
                scope === 'industry' ? 'text-terminal-amber' : 'text-white/50 hover:text-white'
              }`}
            >
              Industries
            </button>
            <button
              type="button"
              data-testid="analysis-heat-scope-all"
              onClick={() => {
                setScope('all');
                setIsolatedBucket(null);
              }}
              className={`text-[10px] font-bold uppercase tracking-wider transition-colors ${
                scope === 'all' ? 'text-terminal-amber' : 'text-white/50 hover:text-white'
              }`}
            >
              All
            </button>
          </div>
          <span className="text-[9px] tabular-nums text-white/45">
            {rowCount > 1
              ? `${tiles.length} tiles · ${cols} per row · scroll`
              : `${tiles.length} tiles`}
          </span>
        </div>

        {/* 2. Colour + sort row */}
        <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-terminal-gray px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] font-bold uppercase tracking-wider text-white/45">Color</span>
            <button
              type="button"
              data-testid="analysis-heat-metric-breadth"
              aria-pressed={metricKey === 'breadth'}
              onClick={() => {
                setMetricKey('breadth');
                setIsolatedBucket(null);
              }}
              className={`border px-1.5 py-[2px] text-[10px] font-bold uppercase tracking-wider rounded-sm transition-colors ${
                metricKey === 'breadth'
                  ? 'border-terminal-amber bg-terminal-amber/15 text-terminal-amber'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              A/D
            </button>
            <button
              type="button"
              data-testid="analysis-heat-metric-earnings"
              aria-pressed={metricKey === 'earnings'}
              onClick={() => {
                setMetricKey('earnings');
                setIsolatedBucket(null);
              }}
              className={`border px-1.5 py-[2px] text-[10px] font-bold uppercase tracking-wider rounded-sm transition-colors ${
                metricKey === 'earnings'
                  ? 'border-terminal-amber bg-terminal-amber/15 text-terminal-amber'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              Earn
            </button>
            <button
              type="button"
              data-testid="analysis-heat-metric-sentiment"
              aria-pressed={metricKey === 'sentiment'}
              onClick={() => {
                setMetricKey('sentiment');
                setIsolatedBucket(null);
              }}
              className={`border px-1.5 py-[2px] text-[10px] font-bold uppercase tracking-wider rounded-sm transition-colors ${
                metricKey === 'sentiment'
                  ? 'border-terminal-amber bg-terminal-amber/15 text-terminal-amber'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              Sent
            </button>
            <button
              type="button"
              data-testid="analysis-heat-metric-perf"
              aria-pressed={metricKey === 'perf'}
              onClick={() => {
                setMetricKey('perf');
                setIsolatedBucket(null);
              }}
              className={`border px-1.5 py-[2px] text-[10px] font-bold uppercase tracking-wider rounded-sm transition-colors ${
                metricKey === 'perf'
                  ? 'border-terminal-amber bg-terminal-amber/15 text-terminal-amber'
                  : 'border-terminal-gray text-white/60 hover:text-white'
              }`}
            >
              Perf
            </button>
          </div>

          <div className="ml-auto flex items-center gap-1.5">
            <span className="text-[9px] font-bold uppercase tracking-wider text-white/45">Sort</span>
            <select
              data-testid="analysis-heat-sort"
              value={sortKey}
              onChange={(e) => handleSortChange(e.target.value as HeatSortKey)}
              className="border border-terminal-gray bg-black px-1 py-[2px] text-[10px] text-terminal-amber focus:border-terminal-amber focus:outline-none"
            >
              {HEAT_SORT_GROUPS.map((g) => (
                <optgroup key={g.label} label={g.label}>
                  {g.keys.map((k) => (
                    <option key={k} value={k}>
                      {HEAT_SORT_LABELS[k]}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            <button
              type="button"
              data-testid="analysis-heat-dir"
              title="Toggle sort direction"
              onClick={() => setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))}
              className="border border-terminal-gray px-1.5 py-[1px] text-[10px] font-bold text-terminal-amber hover:border-terminal-amber transition-colors"
            >
              {sortDir === 'desc' ? '↓' : '↑'}
            </button>
          </div>
        </div>

        {/* 3. Legend band at the top of the map */}
        <div
          data-testid="analysis-heat-legend"
          data-widget-tour="analysis-heat-legend"
          className="shrink-0 border-y border-terminal-gray bg-[#060606] px-2 py-1.5"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[9px] font-bold uppercase tracking-wider text-terminal-amber">
              Legend · {activeMetric.label}
            </span>
            <span className="text-[9px] text-white/45">
              uniform tiles · colour = {activeMetric.desc}
              {period ? ` · value = ${HEAT_SORT_LABELS[period]}` : ''}
            </span>
          </div>

          <div className="mt-1 flex w-full overflow-hidden rounded-sm border border-terminal-gray/70">
            {HEAT_BUCKET_STYLE.map((s, i) => {
              const isIso = isolatedBucket === i;
              const hasIso = isolatedBucket !== null;
              return (
                <button
                  key={i}
                  type="button"
                  onClick={() => {
                    setIsolatedBucket((prev) => (prev === i ? null : i));
                  }}
                  onMouseEnter={() => setHoveredBucket(i)}
                  onMouseLeave={() => setHoveredBucket(null)}
                  title={`${activeMetric.keys[i]} — ${activeMetric.ranges[i]} (${counts[i]} of ${baseCategories.length})`}
                  style={{
                    backgroundColor: s.bg,
                    borderColor: s.bd,
                  }}
                  className={`relative flex min-w-0 flex-1 items-center justify-between gap-1 border-r last:border-r-0 px-1.5 py-[5px] text-left transition-all ${
                    isIso
                      ? 'shadow-[inset_0_0_0_1px_#ffb900]'
                      : hasIso
                        ? 'opacity-45 hover:opacity-100'
                        : 'hover:brightness-125'
                  }`}
                >
                  <span className="flex items-center gap-1 min-w-0 truncate">
                    <span
                      className="inline-block h-2 w-2 shrink-0 rounded-xs"
                      style={{ backgroundColor: s.sw }}
                    />
                    <span className="truncate text-[9px] font-bold tabular-nums" style={{ color: s.fg }}>
                      {activeMetric.short[i]}
                    </span>
                  </span>
                  <span
                    className={`shrink-0 text-[10px] font-bold tabular-nums ${
                      isIso ? 'text-terminal-amber' : 'text-white/80'
                    }`}
                  >
                    {counts[i]}
                  </span>
                </button>
              );
            })}
          </div>

          <div className="mt-1 flex items-center justify-between gap-2">
            <span className="text-[9px] text-white/45">
              {isolatedBucket !== null
                ? `Isolated · ${activeMetric.keys[isolatedBucket]} · ${counts[isolatedBucket]} of ${baseCategories.length}`
                : 'Click a band to isolate · click a tile for constituents'}
            </span>
            {isolatedBucket !== null && (
              <button
                type="button"
                onClick={() => setIsolatedBucket(null)}
                className="border border-terminal-amber/60 px-1.5 py-[1px] text-[9px] uppercase tracking-wider text-terminal-amber hover:bg-terminal-amber/10 transition-colors"
              >
                clear
              </button>
            )}
          </div>
        </div>

        {/* 4. Treemap */}
        <div
          ref={mapBoxRef}
          data-testid="analysis-heat-map"
          data-widget-tour="analysis-heatmap"
          className="relative min-h-[210px] flex-1 overflow-y-auto overflow-x-hidden p-1.5"
          style={{ minHeight: '210px' }}
        >
          <div className="relative w-full" style={{ height: `${Math.max(1, rowCount) * UNIFORM_TILE_H}px` }}>
            {tiles.map(({ cat: c, row, col }) => {
              const b = activeMetric.bucketOf(c);
              const s = HEAT_BUCKET_STYLE[b] || HEAT_BUCKET_STYLE[2];
              const leftPct = col * tileW;
              const topPx = row * UNIFORM_TILE_H;

              // Dim logic
              let dim = false;
              if (hoveredBucket !== null) {
                dim = b !== hoveredBucket;
              } else if (isolatedBucket !== null) {
                dim = b !== isolatedBucket;
              }

              const primary = period
                ? fmtPercent(
                    period === 'chg'
                      ? c.return_1d
                      : period === 'chg1w'
                        ? c.return_1w
                        : period === 'chg1m'
                          ? c.return_1m
                          : c.return_6m,
                  )
                : activeMetric.tile(c);

              const sub = period && metricKey !== 'perf' ? activeMetric.tile(c) : activeMetric.sub(c);

              const tooltip = `${c.name} · ₹${fmtCrore(c.market_cap)} · 1D ${fmtPercent(c.return_1d)} · 1W ${fmtPercent(
                c.return_1w,
              )} · 1M ${fmtPercent(c.return_1m)} · 6M ${fmtPercent(c.return_6m)} · MCap ₹${fmtCrore(
                c.market_cap,
              )} · ${activeMetric.label} ${activeMetric.tile(c)}`;

              return (
                <div
                  key={`${c.category_type}:${c.slug}`}
                  data-testid="analysis-heat-tile"
                  role="button"
                  tabIndex={0}
                  title={tooltip}
                  onClick={() => setDrawerCategory(c)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setDrawerCategory(c);
                    }
                  }}
                  className="group absolute flex flex-col gap-1 overflow-hidden border p-1.5 cursor-pointer transition-all hover:border-terminal-amber hover:z-10 select-none"
                  style={{
                    left: `calc(${leftPct.toFixed(3)}% + 1px)`,
                    top: `${(topPx + 1).toFixed(1)}px`,
                    width: `calc(${tileW.toFixed(3)}% - 2px)`,
                    height: `${UNIFORM_TILE_H - 2}px`,
                    backgroundColor: s.bg,
                    borderColor: s.bd,
                    color: s.fg,
                    opacity: dim ? 0.18 : 1,
                  }}
                >
                  {/* Summary: name, value, breadth — same size on every tile */}
                  <span className="w-full min-w-0 flex-1 break-words text-[11px] font-bold leading-snug line-clamp-3">
                    {c.name}
                  </span>
                  <div className="flex w-full min-w-0 items-baseline justify-between gap-1">
                    <span className="min-w-0 truncate text-[13px] font-bold leading-none tabular-nums">
                      {primary}
                    </span>
                    <span className="shrink-0 text-[9px] leading-none tabular-nums opacity-70">{sub}</span>
                  </div>
                  <div className="flex w-full min-w-0 items-center justify-between gap-1 text-[8px] leading-none tabular-nums opacity-70">
                    <span className="truncate">
                      {c.advance || 0}A {c.decline || 0}D
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      <span>₹{fmtCrore(c.market_cap)}</span>
                      <span className="uppercase tracking-wider opacity-80">
                        {c.category_type === 'sector' ? 'sec' : 'ind'}
                      </span>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 5. Leaderboards */}
        <div
          className={`grid shrink-0 grid-cols-1 gap-2 border-t border-terminal-gray p-2 ${
            wide ? 'grid-cols-2' : ''
          }`}
        >
          {/* Top Leaderboard */}
          <div
            data-testid="analysis-heat-top"
            className="rounded border border-terminal-green/25 bg-terminal-green/[0.04] p-2"
          >
            <div className="mb-1 flex items-center justify-between border-b border-terminal-green/20 pb-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-terminal-green">
                Top by {period ? HEAT_SORT_LABELS[period] : activeMetric.label}
              </span>
              <span className="text-[9px] uppercase text-white/45">
                {scope === 'industry' ? 'industry' : scope === 'sector' ? 'sector' : 'all'}
              </span>
            </div>
            {leaders.map((c, i) => {
              const b = activeMetric.bucketOf(c);
              const s = HEAT_BUCKET_STYLE[b] || HEAT_BUCKET_STYLE[2];
              const scoreVal = period
                ? period === 'chg'
                  ? c.return_1d
                  : period === 'chg1w'
                    ? c.return_1w
                    : period === 'chg1m'
                      ? c.return_1m
                      : c.return_6m
                : activeMetric.score(c);

              const barPct =
                scoreVal !== null && scoreVal !== undefined
                  ? Math.min(100, (Math.abs(scoreVal) / maxAbs) * 100)
                  : 0;
              const valText = period ? fmtPercent(scoreVal) : activeMetric.tile(c);

              return (
                <button
                  key={c.slug}
                  type="button"
                  onClick={() => setDrawerCategory(c)}
                  className="group flex w-full items-center gap-2 py-[3px] text-left hover:bg-white/[0.03] transition-colors"
                >
                  <span className="w-3 text-[9px] tabular-nums text-white/40">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-[11px] text-white/80 group-hover:text-terminal-amber">
                    {c.name}
                  </span>
                  <span
                    className={`h-1.5 w-14 shrink-0 overflow-hidden rounded-xs bg-white/5 ${
                      mid ? 'block' : 'hidden'
                    }`}
                  >
                    <span
                      className="block h-full transition-all"
                      style={{
                        width: `${barPct}%`,
                        backgroundColor: period
                          ? (scoreVal ?? 0) >= 0
                            ? '#00ff00'
                            : '#ff0000'
                          : s.sw,
                        opacity: 0.75,
                      }}
                    />
                  </span>
                  <span
                    className={`w-16 shrink-0 truncate text-right text-[11px] font-bold tabular-nums ${
                      period ? toneClass(scoreVal) : ''
                    }`}
                    style={period ? undefined : { color: s.fg }}
                    title={valText}
                  >
                    {valText}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Bottom Leaderboard */}
          <div
            data-testid="analysis-heat-bottom"
            className="rounded border border-terminal-red/25 bg-terminal-red/[0.04] p-2"
          >
            <div className="mb-1 flex items-center justify-between border-b border-terminal-red/20 pb-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-terminal-red">
                Bottom by {period ? HEAT_SORT_LABELS[period] : activeMetric.label}
              </span>
              <span className="text-[9px] uppercase text-white/45">
                {scope === 'industry' ? 'industry' : scope === 'sector' ? 'sector' : 'all'}
              </span>
            </div>
            {laggards.map((c, i) => {
              const b = activeMetric.bucketOf(c);
              const s = HEAT_BUCKET_STYLE[b] || HEAT_BUCKET_STYLE[2];
              const scoreVal = period
                ? period === 'chg'
                  ? c.return_1d
                  : period === 'chg1w'
                    ? c.return_1w
                    : period === 'chg1m'
                      ? c.return_1m
                      : c.return_6m
                : activeMetric.score(c);

              const barPct =
                scoreVal !== null && scoreVal !== undefined
                  ? Math.min(100, (Math.abs(scoreVal) / maxAbs) * 100)
                  : 0;
              const valText = period ? fmtPercent(scoreVal) : activeMetric.tile(c);

              return (
                <button
                  key={c.slug}
                  type="button"
                  onClick={() => setDrawerCategory(c)}
                  className="group flex w-full items-center gap-2 py-[3px] text-left hover:bg-white/[0.03] transition-colors"
                >
                  <span className="w-3 text-[9px] tabular-nums text-white/40">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-[11px] text-white/80 group-hover:text-terminal-amber">
                    {c.name}
                  </span>
                  <span
                    className={`h-1.5 w-14 shrink-0 overflow-hidden rounded-xs bg-white/5 ${
                      mid ? 'block' : 'hidden'
                    }`}
                  >
                    <span
                      className="block h-full transition-all"
                      style={{
                        width: `${barPct}%`,
                        backgroundColor: period
                          ? (scoreVal ?? 0) >= 0
                            ? '#00ff00'
                            : '#ff0000'
                          : s.sw,
                        opacity: 0.75,
                      }}
                    />
                  </span>
                  <span
                    className={`w-16 shrink-0 truncate text-right text-[11px] font-bold tabular-nums ${
                      period ? toneClass(scoreVal) : ''
                    }`}
                    style={period ? undefined : { color: s.fg }}
                    title={valText}
                  >
                    {valText}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* 6. Drawer */}
      {drawerCategory && (
        <HeatmapDrawer
          category={drawerCategory}
          onClose={() => setDrawerCategory(null)}
          onOpenChart={handleOpenChart}
          onOpenCompany={handleOpenCompany}
          onOpenWatchlist={handleOpenWatchlist}
        />
      )}

      {/* Watchlist Modal */}
      {watchlistTarget && (
        <WatchlistModal
          symbol={watchlistTarget.symbol}
          companyName={watchlistTarget.name}
          onClose={() => setWatchlistTarget(null)}
        />
      )}
    </div>
  );
}

// ─── Main AnalysisWidget Component ───────────────────────────────────────────

export function AnalysisWidget() {
  const rootRef = useRef<HTMLDivElement>(null);
  const { wide, mid } = useWidgetWidth(rootRef);

  const [activeTab, setActiveTab] = useState<Tab>('summary');
  const [selectedSectorSlug, setSelectedSectorSlug] = useState<string | null>(null);
  const [selectedIndustrySlug, setSelectedIndustrySlug] = useState<string | null>(null);

  // Time display
  const [currentTime, setCurrentTime] = useState('');
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setCurrentTime(
        now.toLocaleTimeString('en-IN', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: false,
          timeZone: 'Asia/Kolkata',
        }) + ' IST',
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 10000);
    return () => clearInterval(interval);
  }, []);

  // Backend queries: sectors and industries
  const {
    data: sectors = [],
    isLoading: sectorsLoading,
    isError: sectorsError,
  } = useQuery<Category[]>({
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

  const {
    data: industries = [],
    isLoading: industriesLoading,
    isError: industriesError,
  } = useQuery<Category[]>({
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

  // Derive active selection, else the largest category by market cap (an
  // alphabetical default lands on a two-stock sector and renders an empty pane)
  const biggestSlug = (list: Category[]) =>
    list.length === 0 ? null : [...list].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))[0].slug;
  const activeSectorSlug = selectedSectorSlug || biggestSlug(sectors);
  const activeIndustrySlug = selectedIndustrySlug || biggestSlug(industries);

  const isLoading =
    (activeTab === 'summary' || activeTab === 'sector')
      ? sectorsLoading && sectors.length === 0
      : activeTab === 'industry'
        ? industriesLoading && industries.length === 0
        : (sectorsLoading || industriesLoading) && sectors.length === 0 && industries.length === 0;

  const handleJumpToSector = (slug: string) => {
    setSelectedSectorSlug(slug);
    setActiveTab('sector');
  };

  return (
    <div
      ref={rootRef}
      data-testid="analysis-widget"
      className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg text-terminal-amber"
    >
      {/* Tabs Row */}
      <div
        role="tablist"
        aria-label="Analysis Tabs"
        data-widget-tour="analysis-tabs"
        className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-terminal-gray px-2"
      >
        <div className="flex items-center gap-3">
          <button
            type="button"
            role="tab"
            data-testid="analysis-tab-summary"
            data-widget-tour-click="tab-summary"
            aria-selected={activeTab === 'summary'}
            onClick={() => setActiveTab('summary')}
            className={`relative pb-[6px] pt-[6px] text-[11px] font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'summary'
                ? 'text-terminal-amber after:absolute after:inset-x-0 after:bottom-0 after:h-[2px] after:bg-terminal-amber'
                : 'text-white/50 hover:text-white'
            }`}
          >
            Summary
          </button>
          <button
            type="button"
            role="tab"
            data-testid="analysis-tab-sectors"
            data-widget-tour-click="tab-sectors"
            aria-selected={activeTab === 'sector'}
            onClick={() => setActiveTab('sector')}
            className={`relative pb-[6px] pt-[6px] text-[11px] font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'sector'
                ? 'text-terminal-amber after:absolute after:inset-x-0 after:bottom-0 after:h-[2px] after:bg-terminal-amber'
                : 'text-white/50 hover:text-white'
            }`}
          >
            Sectors
          </button>
          <button
            type="button"
            role="tab"
            data-testid="analysis-tab-industries"
            data-widget-tour-click="tab-industries"
            aria-selected={activeTab === 'industry'}
            onClick={() => setActiveTab('industry')}
            className={`relative pb-[6px] pt-[6px] text-[11px] font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'industry'
                ? 'text-terminal-amber after:absolute after:inset-x-0 after:bottom-0 after:h-[2px] after:bg-terminal-amber'
                : 'text-white/50 hover:text-white'
            }`}
          >
            Industries
          </button>
          <button
            type="button"
            role="tab"
            data-testid="analysis-tab-heatmap"
            data-widget-tour-click="tab-heatmap"
            aria-selected={activeTab === 'heatmap'}
            onClick={() => setActiveTab('heatmap')}
            className={`relative pb-[6px] pt-[6px] text-[11px] font-bold uppercase tracking-wider transition-colors ${
              activeTab === 'heatmap'
                ? 'text-terminal-amber after:absolute after:inset-x-0 after:bottom-0 after:h-[2px] after:bg-terminal-amber'
                : 'text-white/50 hover:text-white'
            }`}
          >
            Heatmap
          </button>
        </div>

        <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-white/40">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-terminal-green" />
          <span className="tabular-nums">{currentTime || 'LIVE'}</span>
        </div>
      </div>

      {/* Pane Content */}
      <div className="min-h-0 flex-1 overflow-hidden relative">
        {isLoading ? (
          <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
            <span className="text-terminal-amber/60 animate-pulse">LOADING ANALYSIS...</span>
          </div>
        ) : sectorsError && industriesError ? (
          <div className="h-full w-full flex items-center justify-center font-mono text-xs text-terminal-red">
            Failed to load market categories.
          </div>
        ) : activeTab === 'summary' ? (
          <SummaryPane
            sectors={sectors}
            onJumpToCategory={handleJumpToSector}
            wide={wide}
            mid={mid}
          />
        ) : activeTab === 'sector' ? (
          <SplitCockpitPane
            categoryType="sector"
            categories={sectors}
            selectedSlug={activeSectorSlug}
            onSelectSlug={setSelectedSectorSlug}
            wide={wide}
            mid={mid}
          />
        ) : activeTab === 'industry' ? (
          <SplitCockpitPane
            categoryType="industry"
            categories={industries}
            selectedSlug={activeIndustrySlug}
            onSelectSlug={setSelectedIndustrySlug}
            wide={wide}
            mid={mid}
          />
        ) : (
          <HeatmapPane sectors={sectors} industries={industries} wide={wide} mid={mid} />
        )}
      </div>
    </div>
  );
}

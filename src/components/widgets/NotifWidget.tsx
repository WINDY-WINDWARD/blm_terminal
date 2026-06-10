'use client';

import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useAtomValue, useAtom } from 'jotai';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactDOM from 'react-dom';
import {
  activeExchangeAtom,
  activeSymbolAtom,
  watchlistsAtom,
  activeWatchlistIdAtom,
  notifSubFiltersAtom,
  notifStreakMinDaysAtom,
  notifSymbolFilterAtom,
  type Watchlist,
  type SubFilterMap,
} from '@/store/terminalStore';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Notification {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
  trigger_type: string;
  message: string;
  triggered_at: string;
  triggered_date: string;
  is_read: boolean;
}

type NotifTab =
  | 'all'
  | 'breakout'
  | 'volume'
  | 'movers'
  | 'deals'
  | 'insider'
  | 'technical'
  | 'momentum'
  | 'volatility'
  | 'streaks'
  | 'results';

type ReadFilter = 'unread' | 'read' | 'all';

// ─── Constants ───────────────────────────────────────────────────────────────

const TAB_TRIGGERS: Record<NotifTab, string[]> = {
  all: [],
  breakout: ['52w_high_breakout', '52w_low_breakout', 'near_52w_high', 'near_52w_low', 'repeated_52w_high', 'repeated_52w_low', 'repeated_volume_breakout'],
  volume: ['volume_breakout'],
  movers: ['top_gainer', 'top_loser'],
  deals: ['bulk_deal', 'block_deal', 'short_deal'],
  insider: ['insider_buy', 'insider_sell'],
  technical: [
    // daily
    'rsi_oversold',
    'rsi_overbought',
    'macd_bullish_cross',
    'macd_bearish_cross',
    'bb_squeeze_alert',
    'bb_upper_break',
    'bb_lower_break',
    // 1h
    'rsi_oversold_1h',
    'rsi_overbought_1h',
    'macd_bullish_cross_1h',
    'macd_bearish_cross_1h',
    'bb_squeeze_alert_1h',
    'bb_upper_break_1h',
    'bb_lower_break_1h',
    'atr_expansion_1h',
    // weekly
    'rsi_oversold_W',
    'rsi_overbought_W',
    'macd_bullish_cross_W',
    'macd_bearish_cross_W',
    'bb_squeeze_alert_W',
    // monthly
    'rsi_oversold_M',
    'rsi_overbought_M',
    'macd_bullish_cross_M',
    'macd_bearish_cross_M',
    // multi-timeframe
    'mtf_bullish_alignment',
    'mtf_bearish_alignment',
  ],
  momentum: ['momentum_surge', 'return_1w_spike'],
  volatility: ['volatility_spike', 'atr_expansion'],
  streaks: ['streak_up_5d', 'streak_down_5d'],
  results: ['results_upcoming'],
};

/** All known trigger types across every tab */
const ALL_TRIGGER_TYPES: string[] = Array.from(
  new Set(Object.values(TAB_TRIGGERS).flat()),
);

/** Human-readable label for each trigger type (used in autocomplete) */
const TRIGGER_LABELS: Record<string, string> = {
  '52w_high_breakout': '52W HIGH BREAKOUT',
  '52w_low_breakout': '52W LOW BREAKOUT',
  near_52w_high: 'NEAR 52W HIGH',
  near_52w_low: 'NEAR 52W LOW',
  volume_breakout: 'VOLUME BREAKOUT',
  top_gainer: 'TOP GAINER',
  top_loser: 'TOP LOSER',
  bulk_deal: 'BULK DEAL',
  block_deal: 'BLOCK DEAL',
  short_deal: 'SHORT DEAL',
  insider_buy: 'INSIDER BUY',
  insider_sell: 'INSIDER SELL',
  rsi_oversold: 'RSI OVERSOLD',
  rsi_overbought: 'RSI OVERBOUGHT',
  macd_bullish_cross: 'MACD BULLISH CROSS',
  macd_bearish_cross: 'MACD BEARISH CROSS',
  bb_squeeze_alert: 'BB SQUEEZE',
  bb_upper_break: 'BB UPPER BREAK',
  bb_lower_break: 'BB LOWER BREAK',
  volatility_spike: 'VOLATILITY SPIKE',
  atr_expansion: 'ATR EXPANSION',
  momentum_surge: 'MOMENTUM SURGE',
  return_1w_spike: '1W RETURN SPIKE',
  streak_up_5d: 'STREAK UP',
  streak_down_5d: 'STREAK DOWN',
  results_upcoming: 'RESULTS UPCOMING',
  // 1h
  rsi_oversold_1h: 'RSI OVERSOLD [1H]',
  rsi_overbought_1h: 'RSI OVERBOUGHT [1H]',
  macd_bullish_cross_1h: 'MACD BULLISH [1H]',
  macd_bearish_cross_1h: 'MACD BEARISH [1H]',
  bb_squeeze_alert_1h: 'BB SQUEEZE [1H]',
  bb_upper_break_1h: 'BB UPPER BREAK [1H]',
  bb_lower_break_1h: 'BB LOWER BREAK [1H]',
  atr_expansion_1h: 'ATR EXPANSION [1H]',
  // weekly
  rsi_oversold_W: 'RSI OVERSOLD [W]',
  rsi_overbought_W: 'RSI OVERBOUGHT [W]',
  macd_bullish_cross_W: 'MACD BULLISH [W]',
  macd_bearish_cross_W: 'MACD BEARISH [W]',
  bb_squeeze_alert_W: 'BB SQUEEZE [W]',
  // monthly
  rsi_oversold_M: 'RSI OVERSOLD [M]',
  rsi_overbought_M: 'RSI OVERBOUGHT [M]',
  macd_bullish_cross_M: 'MACD BULLISH [M]',
  macd_bearish_cross_M: 'MACD BEARISH [M]',
  // multi-timeframe
  mtf_bullish_alignment: 'MTF BULLISH ALIGNMENT',
  mtf_bearish_alignment: 'MTF BEARISH ALIGNMENT',
  repeated_52w_high: 'REPEATED 52W HIGH',
  repeated_52w_low: 'REPEATED 52W LOW',
  repeated_volume_breakout: 'REPEATED VOL BREAKOUT',
};

const STREAK_TRIGGER_TYPES = new Set(['streak_up_5d', 'streak_down_5d']);
const STREAK_MIN = 5;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getBadgeColor(triggerType: string): string {
  if (triggerType.startsWith('52w_')) return 'bg-terminal-amber text-black';
  if (triggerType === 'volume_breakout') return 'bg-cyan-600 text-white';
  if (triggerType === 'top_gainer') return 'bg-terminal-green text-black';
  if (triggerType === 'top_loser') return 'bg-terminal-red text-white';
  if (triggerType === 'bulk_deal') return 'bg-orange-600 text-white';
  if (triggerType === 'block_deal') return 'bg-orange-700 text-white';
  if (triggerType === 'short_deal') return 'bg-orange-500 text-white';
  if (triggerType === 'insider_buy') return 'bg-purple-600 text-white';
  if (triggerType === 'insider_sell') return 'bg-purple-700 text-white';
  if (triggerType === 'rsi_oversold') return 'bg-blue-600 text-white';
  if (triggerType === 'rsi_overbought') return 'bg-rose-600 text-white';
  if (triggerType === 'macd_bullish_cross') return 'bg-emerald-600 text-white';
  if (triggerType === 'macd_bearish_cross') return 'bg-red-700 text-white';
  if (triggerType === 'bb_squeeze_alert') return 'bg-yellow-600 text-black';
  if (triggerType === 'bb_upper_break') return 'bg-green-600 text-white';
  if (triggerType === 'bb_lower_break') return 'bg-red-600 text-white';
  if (triggerType === 'volatility_spike') return 'bg-fuchsia-600 text-white';
  if (triggerType === 'atr_expansion') return 'bg-pink-600 text-white';
  if (triggerType === 'momentum_surge') return 'bg-sky-500 text-white';
  if (triggerType === 'return_1w_spike') return 'bg-teal-600 text-white';
  if (triggerType === 'streak_up_5d') return 'bg-lime-600 text-white';
  if (triggerType === 'streak_down_5d') return 'bg-red-800 text-white';
  if (triggerType === 'near_52w_high') return 'bg-amber-500 text-black';
  if (triggerType === 'near_52w_low') return 'bg-amber-700 text-white';
  if (triggerType === 'results_upcoming') return 'bg-emerald-700 text-white';
  // interval-suffixed technical triggers (slightly muted vs daily)
  if (triggerType.endsWith('_1h')) return 'bg-indigo-500 text-white';
  if (triggerType.endsWith('_W')) return 'bg-violet-600 text-white';
  if (triggerType.endsWith('_M')) return 'bg-fuchsia-700 text-white';
  if (triggerType.startsWith('mtf_')) return 'bg-cyan-600 text-white';
  if (triggerType.startsWith('repeated_')) return 'bg-purple-600 text-white';
  return 'bg-terminal-gray text-white';
}

function getBadgeLabel(triggerType: string): string {
  if (triggerType === '52w_high_breakout') return '52W HIGH';
  if (triggerType === '52w_low_breakout') return '52W LOW';
  if (triggerType === 'volume_breakout') return 'VOL';
  if (triggerType === 'top_gainer') return 'GAINER';
  if (triggerType === 'top_loser') return 'LOSER';
  if (triggerType === 'bulk_deal') return 'BULK';
  if (triggerType === 'block_deal') return 'BLOCK';
  if (triggerType === 'short_deal') return 'SHORT';
  if (triggerType === 'insider_buy') return 'INS BUY';
  if (triggerType === 'insider_sell') return 'INS SELL';
  if (triggerType === 'rsi_oversold') return 'RSI LOW';
  if (triggerType === 'rsi_overbought') return 'RSI HIGH';
  if (triggerType === 'macd_bullish_cross') return 'MACD +';
  if (triggerType === 'macd_bearish_cross') return 'MACD -';
  if (triggerType === 'bb_squeeze_alert') return 'BB SQZ';
  if (triggerType === 'bb_upper_break') return 'BB UP';
  if (triggerType === 'bb_lower_break') return 'BB DN';
  if (triggerType === 'volatility_spike') return 'VOL SPK';
  if (triggerType === 'atr_expansion') return 'ATR EXP';
  if (triggerType === 'momentum_surge') return 'MOM';
  if (triggerType === 'return_1w_spike') return '1W RET';
  if (triggerType === 'streak_up_5d') return 'STREAK+';
  if (triggerType === 'streak_down_5d') return 'STREAK-';
  if (triggerType === 'near_52w_high') return '~52W HI';
  if (triggerType === 'near_52w_low') return '~52W LO';
  if (triggerType === 'results_upcoming') return 'RESULTS';
  // interval-suffixed short labels
  if (triggerType === 'rsi_oversold_1h') return 'RSI LO[1H]';
  if (triggerType === 'rsi_overbought_1h') return 'RSI HI[1H]';
  if (triggerType === 'macd_bullish_cross_1h') return 'MACD+[1H]';
  if (triggerType === 'macd_bearish_cross_1h') return 'MACD-[1H]';
  if (triggerType === 'bb_squeeze_alert_1h') return 'BB SQZ[1H]';
  if (triggerType === 'bb_upper_break_1h') return 'BB UP[1H]';
  if (triggerType === 'bb_lower_break_1h') return 'BB DN[1H]';
  if (triggerType === 'atr_expansion_1h') return 'ATR EXP[1H]';
  if (triggerType === 'rsi_oversold_W') return 'RSI LO[W]';
  if (triggerType === 'rsi_overbought_W') return 'RSI HI[W]';
  if (triggerType === 'macd_bullish_cross_W') return 'MACD+[W]';
  if (triggerType === 'macd_bearish_cross_W') return 'MACD-[W]';
  if (triggerType === 'bb_squeeze_alert_W') return 'BB SQZ[W]';
  if (triggerType === 'rsi_oversold_M') return 'RSI LO[M]';
  if (triggerType === 'rsi_overbought_M') return 'RSI HI[M]';
  if (triggerType === 'macd_bullish_cross_M') return 'MACD+[M]';
  if (triggerType === 'macd_bearish_cross_M') return 'MACD-[M]';
  if (triggerType === 'mtf_bullish_alignment') return 'MTF BULL';
  if (triggerType === 'mtf_bearish_alignment') return 'MTF BEAR';
  if (triggerType === 'repeated_52w_high') return 'RPT 52H';
  if (triggerType === 'repeated_52w_low') return 'RPT 52L';
  if (triggerType === 'repeated_volume_breakout') return 'RPT VOL';
  return triggerType.toUpperCase();
}

function getTooltipDescription(triggerType: string): string {
  switch (triggerType) {
    case '52w_high_breakout':
      return 'Price broke above its 52-week high — strong bullish signal';
    case '52w_low_breakout':
      return 'Price broke below its 52-week low — strong bearish signal';
    case 'volume_breakout':
      return 'Volume surged 3x+ above 20-day average — unusual activity';
    case 'top_gainer':
      return 'Among top gainers in the watchlist today';
    case 'top_loser':
      return 'Among top losers in the watchlist today';
    case 'bulk_deal':
      return 'Large bulk deal detected on NSE — significant institutional activity';
    case 'block_deal':
      return 'Block deal detected on NSE — large block transaction';
    case 'short_deal':
      return 'Short deal detected on NSE — short selling activity';
    case 'insider_buy':
      return 'Promoter/institution bought shares — insider buying signal';
    case 'insider_sell':
      return 'Promoter/institution sold shares — insider selling signal';
    case 'rsi_oversold':
      return 'RSI(14) below 30 — oversold condition, potential bounce';
    case 'rsi_overbought':
      return 'RSI(14) above 70 — overbought condition, potential pullback';
    case 'macd_bullish_cross':
      return 'MACD line crossed above signal line — bullish momentum shift';
    case 'macd_bearish_cross':
      return 'MACD line crossed below signal line — bearish momentum shift';
    case 'bb_squeeze_alert':
      return 'Bollinger Bands squeezed — low volatility, potential breakout coming';
    case 'bb_upper_break':
      return 'Price closed above upper Bollinger Band — overbought signal';
    case 'bb_lower_break':
      return 'Price closed below lower Bollinger Band — oversold signal';
    case 'volatility_spike':
      return 'HV20 is 1.5x+ higher than HV60 — volatility spike detected';
    case 'atr_expansion':
      return 'Daily price range expanded significantly — volatility increasing, wider stop-loss needed';
    case 'momentum_surge':
      return 'Momentum score above 70 — strong bullish momentum';
    case 'return_1w_spike':
      return '1-week return above 10% — short-term momentum surge';
    case 'streak_up_5d':
      return '5+ consecutive up days — strong upward streak';
    case 'streak_down_5d':
      return '5+ consecutive down days — strong downward streak';
    case 'near_52w_high':
      return 'Within 3% of 52-week high — approaching resistance';
    case 'near_52w_low':
      return 'Within 3% of 52-week low — approaching support';
    case 'results_upcoming':
      return 'Board meeting scheduled to announce financial results — check for earnings surprise';
    // 1h
    case 'rsi_oversold_1h':
      return 'Hourly RSI(14) below 30 — short-term oversold bounce potential';
    case 'rsi_overbought_1h':
      return 'Hourly RSI(14) above 70 — short-term overbought pullback risk';
    case 'macd_bullish_cross_1h':
      return 'Hourly MACD crossed above signal — intraday bullish shift';
    case 'macd_bearish_cross_1h':
      return 'Hourly MACD crossed below signal — intraday bearish shift';
    case 'bb_squeeze_alert_1h':
      return 'Hourly Bollinger Bands squeezed — intraday breakout imminent';
    case 'bb_upper_break_1h':
      return 'Hourly price closed above upper BB — short-term overbought';
    case 'bb_lower_break_1h':
      return 'Hourly price closed below lower BB — short-term oversold';
    case 'atr_expansion_1h':
      return 'Hourly ATR% expanded — intraday volatility increasing';
    // weekly
    case 'rsi_oversold_W':
      return 'Weekly RSI(14) below 30 — deeper oversold, stronger signal';
    case 'rsi_overbought_W':
      return 'Weekly RSI(14) above 70 — deeper overbought, stronger signal';
    case 'macd_bullish_cross_W':
      return 'Weekly MACD bullish crossover — medium-term momentum shift';
    case 'macd_bearish_cross_W':
      return 'Weekly MACD bearish crossover — medium-term momentum shift';
    case 'bb_squeeze_alert_W':
      return 'Weekly Bollinger squeeze — medium-term breakout setup';
    // monthly
    case 'rsi_oversold_M':
      return 'Monthly RSI(14) below 30 — very long-term oversold';
    case 'rsi_overbought_M':
      return 'Monthly RSI(14) above 70 — very long-term overbought';
    case 'macd_bullish_cross_M':
      return 'Monthly MACD bullish crossover — long-term trend change';
    case 'macd_bearish_cross_M':
      return 'Monthly MACD bearish crossover — long-term trend change';
    // MTF
    case 'mtf_bullish_alignment':
      return 'Daily + Weekly + Monthly RSI all above 50 — strong multi-timeframe bullish consensus';
    case 'mtf_bearish_alignment':
      return 'Daily + Weekly + Monthly RSI all below 50 — strong multi-timeframe bearish consensus';
    case 'repeated_52w_high':
      return 'Stock appeared in 52W HIGH list multiple times in the last 10 calendar days — persistent bullish momentum';
      return 'Stock appeared in 52W LOW list multiple times in the last 10 calendar days — persistent bearish pressure';
      return 'Stock appeared in volume gainers list multiple times in the last 10 calendar days — sustained unusual activity';
    default:
      return triggerType;
  }
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const mon = months[d.getMonth()];
  const dd = d.getDate().toString().padStart(2, '0');
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  return `${mon} ${dd}, ${hh}:${mm}`;
}

/** Parse streak day count from a notification message. Returns null if not parseable. */
export function parseStreakDays(message: string): number | null {
  // Matches: "RELIANCE up 7 consecutive days" or "TCS down 5 days"
  const match = message.match(/(?:up|down)\s+(\d+)\s+(?:consecutive\s+)?days?/i);
  return match ? parseInt(match[1], 10) : null;
}

// ─── SubFilterBar Component ───────────────────────────────────────────────────

interface SubFilterBarProps {
  activeTab: NotifTab;
  subFilters: SubFilterMap;
  onSubFiltersChange: (updated: SubFilterMap) => void;
  streakMinDays: number;
  onStreakMinDaysChange: (days: number) => void;
}

function SubFilterBar({
  activeTab,
  subFilters,
  onSubFiltersChange,
  streakMinDays,
  onStreakMinDaysChange,
}: SubFilterBarProps) {
  const [inputValue, setInputValue] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedForTab = subFilters[activeTab] ?? [];

  // Candidates: trigger types valid for this tab (or all if "all" tab), minus already selected
  const candidatePool = activeTab === 'all' ? ALL_TRIGGER_TYPES : TAB_TRIGGERS[activeTab];
  const candidates = candidatePool.filter(
    (t) =>
      !selectedForTab.includes(t) &&
      (inputValue === '' ||
        (TRIGGER_LABELS[t] ?? t.toUpperCase()).includes(inputValue.toUpperCase()) ||
        t.toUpperCase().includes(inputValue.toUpperCase())),
  );

  const addFilter = useCallback(
    (triggerType: string) => {
      if (selectedForTab.includes(triggerType)) return;
      onSubFiltersChange({ ...subFilters, [activeTab]: [...selectedForTab, triggerType] });
      setInputValue('');
      setShowDropdown(false);
      inputRef.current?.focus();
    },
    [activeTab, selectedForTab, subFilters, onSubFiltersChange],
  );

  const removeFilter = useCallback(
    (triggerType: string) => {
      onSubFiltersChange({
        ...subFilters,
        [activeTab]: selectedForTab.filter((t) => t !== triggerType),
      });
    },
    [activeTab, selectedForTab, subFilters, onSubFiltersChange],
  );

  const clearAll = useCallback(() => {
    onSubFiltersChange({ ...subFilters, [activeTab]: [] });
  }, [activeTab, subFilters, onSubFiltersChange]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && candidates.length > 0) {
      addFilter(candidates[0]);
    } else if (e.key === 'Escape') {
      setShowDropdown(false);
      setInputValue('');
    }
  };

  // Determine whether to show the streak stepper:
  // - active tab is streaks, OR
  // - any selected sub-filter in this tab is a streak type
  const showStreakStepper =
    activeTab === 'streaks' ||
    selectedForTab.some((t) => STREAK_TRIGGER_TYPES.has(t));

  return (
    <div className="flex-shrink-0 px-2 py-1 border-b border-terminal-gray/40 bg-zinc-950 flex flex-wrap items-center gap-1 min-h-[28px]">
      {/* Active filter bubbles */}
      {selectedForTab.map((triggerType) => (
        <span
          key={triggerType}
          className={`inline-flex items-center gap-1 text-[9px] font-bold px-1.5 py-px rounded ${getBadgeColor(triggerType)}`}
        >
          {getBadgeLabel(triggerType)}
          <button
            onClick={() => removeFilter(triggerType)}
            className="opacity-70 hover:opacity-100 leading-none"
            title={`Remove ${TRIGGER_LABELS[triggerType] ?? triggerType}`}
          >
            ×
          </button>
        </span>
      ))}

      {/* Autocomplete input */}
      <div className="relative">
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value);
            setShowDropdown(true);
          }}
          onFocus={() => setShowDropdown(true)}
          onBlur={() => setTimeout(() => setShowDropdown(false), 150)}
          onKeyDown={handleKeyDown}
          placeholder="+ filter..."
          className="bg-transparent text-white/60 text-[9px] border border-transparent focus:border-terminal-gray/60 outline-none px-1 py-px w-16 focus:w-28 transition-all placeholder:text-white/30"
        />
        {showDropdown && candidates.length > 0 && (
          <div className="absolute top-full left-0 mt-0.5 w-48 bg-zinc-800 border border-terminal-gray/60 rounded shadow-xl z-50 max-h-40 overflow-auto">
            {candidates.map((t) => (
              <button
                key={t}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus on input through the click
                  addFilter(t);
                }}
                className="w-full text-left px-2 py-1 text-[9px] text-white/80 hover:bg-zinc-700 hover:text-terminal-amber flex items-center gap-1.5"
              >
                <span className={`text-[8px] font-bold px-1 py-px rounded ${getBadgeColor(t)}`}>
                  {getBadgeLabel(t)}
                </span>
                <span className="truncate">{TRIGGER_LABELS[t] ?? t}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Clear all bubbles */}
      {selectedForTab.length > 0 && (
        <button
          onClick={clearAll}
          className="text-[9px] text-white/30 hover:text-terminal-red transition-colors ml-0.5"
          title="Clear all filters"
        >
          CLEAR
        </button>
      )}

      {/* Streak day stepper — shown when streaks are in scope */}
      {showStreakStepper && (
        <div className="ml-auto flex items-center gap-1 shrink-0">
          <span className="text-white/40 text-[9px]">≥</span>
          <button
            onClick={() => onStreakMinDaysChange(Math.max(STREAK_MIN, streakMinDays - 1))}
            className="text-white/50 hover:text-white text-[10px] w-4 text-center leading-none"
            title="Decrease minimum streak days"
          >
            −
          </button>
          <span className="text-terminal-amber text-[9px] font-bold w-5 text-center tabular-nums">
            {streakMinDays}
          </span>
          <button
            onClick={() => onStreakMinDaysChange(streakMinDays + 1)}
            className="text-white/50 hover:text-white text-[10px] w-4 text-center leading-none"
            title="Increase minimum streak days"
          >
            +
          </button>
          <span className="text-white/30 text-[9px]">days</span>
        </div>
      )}
    </div>
  );
}

// ─── Main Widget ──────────────────────────────────────────────────────────────

export function NotifWidget() {
  const queryClient = useQueryClient();
  const watchlists = useAtomValue(watchlistsAtom);
  const activeWatchlistId = useAtomValue(activeWatchlistIdAtom);
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<number>(
    watchlists.length > 0 ? watchlists[0].id : 1,
  );
  const [activeTab, setActiveTab] = useState<NotifTab>('all');
  const [selectedDate, setSelectedDate] = useState<string>('today');
  const [readFilter, setReadFilter] = useState<ReadFilter>('unread');
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

  const [subFilters, setSubFilters] = useAtom(notifSubFiltersAtom);
  const [streakMinDays, setStreakMinDays] = useAtom(notifStreakMinDaysAtom);
  const [symbolFilter, setSymbolFilter] = useAtom(notifSymbolFilterAtom);

  // When a symbol filter is applied from WatchWidget, sync the watchlist
  // selection so the query targets the same watchlist the badge was counted from.
  useEffect(() => {
    if (symbolFilter !== null) {
      setSelectedWatchlistId(activeWatchlistId);
    }
  }, [symbolFilter, activeWatchlistId]);

  const [hoveredNotif, setHoveredNotif] = useState<{ id: number; rect: DOMRect } | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery<Notification[]>({
    queryKey: ['notifications', selectedWatchlistId, readFilter],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/notifications?watchlist_id=${selectedWatchlistId}&days=14&read_filter=${readFilter}`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  const dismissMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/py/notifications/${id}?watchlist_id=${selectedWatchlistId}`, {
        method: 'DELETE',
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const clearAllMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(
        `/api/py/notifications?all=true&watchlist_id=${selectedWatchlistId}`,
        { method: 'DELETE' },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const handleRowClick = (n: Notification) => {
    setActiveSymbol(n.symbol);
    setActiveExchange(n.exchange);
  };

  const handleDismiss = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    dismissMutation.mutate(id);
  };

  const activeSubFilters = subFilters[activeTab] ?? [];

  const todayStr = useMemo(() => {
    // triggered_date is stored as an IST (UTC+5:30) date string.
    // Using toISOString() would give the UTC date, which is up to 5.5 hours
    // behind IST — during IST evening/night, today's notifications would be
    // invisible under the "Today" filter. Compute the date in IST instead.
    const now = new Date();
    const istOffset = 5.5 * 60; // IST is UTC+5:30
    const istMs = now.getTime() + (istOffset - now.getTimezoneOffset()) * 60_000;
    return new Date(istMs).toISOString().slice(0, 10);
  }, []);

  const dateOptions = useMemo(() => {
    const dates = new Set((data ?? []).map((n) => n.triggered_date));
    const sorted = Array.from(dates).sort().reverse();
    const labels: Record<string, string> = {};
    for (const d of sorted) {
      if (d === todayStr) {
        labels[d] = 'Today';
      } else {
        const date = new Date(d + 'T00:00:00');
        const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        labels[d] = `${months[date.getMonth()]} ${date.getDate()}`;
      }
    }
    return [
      { label: 'Today', value: 'today' },
      ...sorted.filter((d) => d !== todayStr).map((d) => ({ label: labels[d], value: d })),
    ];
  }, [data, todayStr]);

  const targetDate = selectedDate === 'today' ? todayStr : selectedDate;

  const filteredNotifications = (data ?? []).filter((n) => {
    // Symbol filter set by WatchWidget alert-count click
    if (symbolFilter && n.symbol !== symbolFilter) return false;
    // Coarse tab filter
    if (activeTab !== 'all' && !TAB_TRIGGERS[activeTab].includes(n.trigger_type)) return false;
    // Sub-filter bubbles (OR — match any selected type)
    if (activeSubFilters.length > 0 && !activeSubFilters.includes(n.trigger_type)) return false;
    // Streak numeric filter: applies whenever a streak trigger is shown
    if (STREAK_TRIGGER_TYPES.has(n.trigger_type) && streakMinDays > STREAK_MIN) {
      const days = parseStreakDays(n.message);
      if (days === null || days < streakMinDays) return false;
    }
    // Date filter
    if (n.triggered_date !== targetDate) return false;
    return true;
  });

  const selectedWatchlist = watchlists.find((wl) => wl.id === selectedWatchlistId);

  const tabs: { id: NotifTab; label: string }[] = [
    { id: 'all', label: 'ALL' },
    { id: 'breakout', label: '52W' },
    { id: 'volume', label: 'VOLUME' },
    { id: 'movers', label: 'MOVERS' },
    { id: 'deals', label: 'DEALS' },
    { id: 'insider', label: 'INSIDER' },
    { id: 'technical', label: 'TECHNICAL' },
    { id: 'momentum', label: 'MOMENTUM' },
    { id: 'volatility', label: 'VOLATILITY' },
    { id: 'streaks', label: 'STREAKS' },
    { id: 'results', label: 'RESULTS' },
  ];

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">LOADING NOTIFICATIONS...</span>
      </div>
    );
  }

  if (isError) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2 px-4 text-center">
        <span className="text-terminal-red font-bold uppercase">Fetch Failed</span>
        <span className="text-white text-[10px] max-w-xs">{errMsg}</span>
        <button
          onClick={() => refetch()}
          className="text-terminal-amber text-[10px] underline hover:text-white"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-terminal-bg">
      {/* Header bar */}
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-center gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase shrink-0">NOTIF</span>
        <select
          value={selectedWatchlistId}
          onChange={(e) => setSelectedWatchlistId(Number(e.target.value))}
          className="bg-terminal-bg text-terminal-amber text-[10px] border border-terminal-gray px-1 py-px max-w-[120px] truncate"
        >
          {watchlists.map((wl: Watchlist) => (
            <option key={wl.id} value={wl.id}>
              {wl.name}
            </option>
          ))}
        </select>
        <select
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="bg-terminal-bg text-white text-[10px] border border-terminal-gray px-1 py-px max-w-[110px]"
        >
          {dateOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <select
          value={readFilter}
          onChange={(e) => setReadFilter(e.target.value as ReadFilter)}
          className="bg-terminal-bg text-white text-[10px] border border-terminal-gray px-1 py-px"
        >
          <option value="unread">UNREAD</option>
          <option value="read">READ</option>
          <option value="all">ALL</option>
        </select>
        <span className="text-white/60 text-[10px] shrink-0">({filteredNotifications.length})</span>
        {(data ?? []).length > 0 && readFilter === 'unread' && (
          <button
            onClick={() => clearAllMutation.mutate()}
            className="ml-auto text-[9px] text-white/50 hover:text-terminal-red transition-colors shrink-0"
          >
            CLEAR ALL
          </button>
        )}
      </div>

      {/* Category tab strip */}
      <div className="flex-shrink-0 flex border-b border-terminal-gray/60 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-2 py-1 text-[10px] font-mono uppercase tracking-wide border-r border-terminal-gray/40 transition-colors border-b-2 whitespace-nowrap ${
              activeTab === tab.id
                ? 'bg-terminal-amber text-black font-bold -mb-px'
                : 'text-white/50 hover:text-white hover:bg-zinc-900 border-transparent'
            }`}
            style={activeTab === tab.id ? { borderBottomColor: '#ffb900' } : undefined}
          >
            {tab.label}
            {/* Dot indicator when this tab has active sub-filters */}
            {(subFilters[tab.id] ?? []).length > 0 && activeTab !== tab.id && (
              <span className="ml-1 inline-block w-1 h-1 rounded-full bg-terminal-amber align-middle" />
            )}
          </button>
        ))}
      </div>

      {/* Sub-filter bubble bar */}
      <SubFilterBar
        activeTab={activeTab}
        subFilters={subFilters}
        onSubFiltersChange={setSubFilters}
        streakMinDays={streakMinDays}
        onStreakMinDaysChange={(d) => setStreakMinDays(Math.max(STREAK_MIN, d))}
      />

      {/* Symbol filter banner — set when WatchWidget alert-count badge is clicked */}
      {symbolFilter && (
        <div className="flex-shrink-0 flex items-center gap-2 px-3 py-0.5 bg-blue-950 border-b border-blue-700/50">
          <span className="text-blue-400 text-[10px] font-bold uppercase shrink-0">SYMBOL:</span>
          <span className="text-terminal-amber text-[10px] font-bold">{symbolFilter}</span>
          <button
            onClick={() => setSymbolFilter(null)}
            className="ml-auto text-white/40 hover:text-white text-[11px] leading-none"
            title="Clear symbol filter"
          >
            ×
          </button>
        </div>
      )}

      {/* Notification list */}
      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {filteredNotifications.length === 0 ? (
          <div className="text-white/40 text-[10px] py-4 text-center">
            No alerts for {selectedWatchlist?.name ?? `watchlist ${selectedWatchlistId}`}.
          </div>
        ) : (
          <div className="flex flex-col gap-px">
            {filteredNotifications.map((n) => (
              <div
                key={n.id}
                onClick={() => handleRowClick(n)}
                onMouseEnter={(e) =>
                  setHoveredNotif({ id: n.id, rect: e.currentTarget.getBoundingClientRect() })
                }
                onMouseLeave={() => setHoveredNotif(null)}
                className="relative flex items-center gap-2 px-2 py-[4px] bg-zinc-900 hover:bg-zinc-800 cursor-pointer group border border-terminal-gray/20 rounded-sm"
              >
                <span
                  className={`shrink-0 text-[8px] font-bold px-1 py-px rounded ${getBadgeColor(n.trigger_type)}`}
                >
                  {getBadgeLabel(n.trigger_type)}
                </span>
                <span className="font-bold text-terminal-amber text-[11px] shrink-0">
                  {n.symbol}
                </span>
                <span
                  className="text-white/80 text-[10px] truncate flex-1 min-w-0"
                  title={n.message}
                >
                  {n.message}
                </span>
                <span className="text-white/40 text-[9px] shrink-0">
                  {formatDateTime(n.triggered_at)}
                </span>
                <button
                  onClick={(e) => handleDismiss(e, n.id)}
                  className="shrink-0 text-white/30 hover:text-terminal-red text-[11px] w-4 text-center opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Dismiss"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Hover tooltip portal */}
      {hoveredNotif &&
        typeof document !== 'undefined' &&
        ReactDOM.createPortal(
          <div
            className="fixed z-[99999] pointer-events-none"
            style={{
              left: hoveredNotif.rect.left,
              top: hoveredNotif.rect.top - 4,
              transform: 'translateY(-100%)',
            }}
          >
            <div className="bg-zinc-800 border border-terminal-amber/60 rounded-md shadow-2xl p-3 max-w-80 mb-1">
              <div className="text-terminal-amber text-[10px] font-bold mb-1">
                {getBadgeLabel(
                  filteredNotifications.find((n) => n.id === hoveredNotif.id)?.trigger_type ?? '',
                )}
              </div>
              <div className="text-white/80 text-[9px] mb-1 leading-snug">
                {getTooltipDescription(
                  filteredNotifications.find((n) => n.id === hoveredNotif.id)?.trigger_type ?? '',
                )}
              </div>
              <div className="text-white/50 text-[8px] truncate">
                {filteredNotifications.find((n) => n.id === hoveredNotif.id)?.message}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

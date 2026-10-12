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

type NotifViewMode = 'stream' | 'heatmap';

type TriggerSeverity = 'CRITICAL' | 'HIGH' | 'NORMAL';

// ─── Constants ───────────────────────────────────────────────────────────────

const TAB_TRIGGERS: Record<NotifTab, string[]> = {
  all: [],
  breakout: [
    '52w_high_breakout',
    '52w_low_breakout',
    'near_52w_high',
    'near_52w_low',
    'repeated_52w_high',
    'repeated_52w_low',
    'repeated_volume_breakout',
  ],
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
const STREAK_PRESET_DAYS = [2, 4, 6, 8, 12] as const;

const SESSION_SLOTS = [
  { id: '09-10', label: '09-10', startHour: 9, endHour: 10 },
  { id: '10-11', label: '10-11', startHour: 10, endHour: 11 },
  { id: '11-12', label: '11-12', startHour: 11, endHour: 12 },
  { id: '12-13', label: '12-13', startHour: 12, endHour: 13 },
  { id: '13-14', label: '13-14', startHour: 13, endHour: 14 },
  { id: '14-15', label: '14-15', startHour: 14, endHour: 15 },
  { id: '15-30', label: '15-30', startHour: 15, endHour: 24 },
] as const;

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

function getBentoBadgeStyle(triggerType: string): string {
  if (
    triggerType === '52w_high_breakout' ||
    triggerType === 'top_gainer' ||
    triggerType === 'macd_bullish_cross' ||
    triggerType === 'bb_upper_break' ||
    triggerType === 'streak_up_5d' ||
    triggerType === 'mtf_bullish_alignment' ||
    triggerType === 'repeated_52w_high' ||
    triggerType === 'insider_buy'
  ) {
    return 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30';
  }
  if (
    triggerType === '52w_low_breakout' ||
    triggerType === 'top_loser' ||
    triggerType === 'rsi_overbought' ||
    triggerType === 'rsi_overbought_1h' ||
    triggerType === 'rsi_overbought_W' ||
    triggerType === 'rsi_overbought_M' ||
    triggerType === 'macd_bearish_cross' ||
    triggerType === 'bb_lower_break' ||
    triggerType === 'streak_down_5d' ||
    triggerType === 'mtf_bearish_alignment' ||
    triggerType === 'repeated_52w_low' ||
    triggerType === 'insider_sell' ||
    triggerType === 'short_deal'
  ) {
    return 'bg-rose-500/10 text-rose-400 border border-rose-500/30';
  }
  if (
    triggerType === 'volume_breakout' ||
    triggerType === 'repeated_volume_breakout' ||
    triggerType === 'momentum_surge' ||
    triggerType === 'return_1w_spike'
  ) {
    return 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/30';
  }
  return 'bg-amber-400/10 text-amber-400 border border-amber-400/30';
}

function getTriggerSeverity(triggerType: string): TriggerSeverity {
  if (
    triggerType === '52w_high_breakout' ||
    triggerType === '52w_low_breakout' ||
    triggerType === 'block_deal' ||
    triggerType === 'bulk_deal' ||
    triggerType === 'streak_up_5d' ||
    triggerType === 'streak_down_5d' ||
    triggerType === 'mtf_bullish_alignment' ||
    triggerType === 'mtf_bearish_alignment'
  ) {
    return 'CRITICAL';
  }
  if (
    triggerType === 'volume_breakout' ||
    triggerType === 'repeated_volume_breakout' ||
    triggerType === 'rsi_overbought' ||
    triggerType === 'rsi_oversold' ||
    triggerType === 'rsi_overbought_1h' ||
    triggerType === 'rsi_oversold_1h' ||
    triggerType === 'volatility_spike' ||
    triggerType === 'atr_expansion' ||
    triggerType === 'momentum_surge' ||
    triggerType === 'insider_buy' ||
    triggerType === 'insider_sell'
  ) {
    return 'HIGH';
  }
  return 'NORMAL';
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
    case 'repeated_52w_low':
      return 'Stock appeared in 52W LOW list multiple times in the last 10 calendar days — persistent bearish pressure';
    case 'repeated_volume_breakout':
      return 'Stock appeared in volume gainers list multiple times in the last 10 calendar days — sustained unusual activity';
    default:
      return triggerType;
  }
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
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

function extractIndicatorParameter(n: Notification): {
  paramLabel: string;
  paramValue: string;
  timeframe: string;
  categoryLabel: string;
} {
  const t = n.trigger_type;
  const msg = n.message || '';

  let timeframe = '1D · DAILY';
  if (t.endsWith('_1h')) timeframe = '1H · INTRADAY';
  else if (t.endsWith('_W')) timeframe = '1W · WEEKLY';
  else if (t.endsWith('_M')) timeframe = '1M · MONTHLY';
  else if (t.startsWith('mtf_')) timeframe = '1D/1W/1M · MTF';

  const rsiMatch = msg.match(/RSI(?:\(14\))?[\s:=]*(\d+(?:\.\d+)?)/i);
  if (rsiMatch || t.startsWith('rsi_')) {
    const val = rsiMatch ? rsiMatch[1] : t.includes('overbought') ? '> 70.0' : '< 30.0';
    const tfShort = t.endsWith('_1h') ? '1h' : t.endsWith('_W') ? '1W' : t.endsWith('_M') ? '1M' : '15m/1D';
    return {
      paramLabel: 'RSI PARAMETER',
      paramValue: `RSI ${val} on ${tfShort}`,
      timeframe,
      categoryLabel: 'TECHNICAL · OSCILLATOR',
    };
  }

  const volMatch = msg.match(/(\d+(?:\.\d+)?x)/i);
  if (volMatch || t.includes('volume')) {
    return {
      paramLabel: 'VOLUME RATIO',
      paramValue: volMatch ? `${volMatch[1]} vs 20D SMA` : '3.0x+ Surge vs 20D SMA',
      timeframe,
      categoryLabel: 'VOLUME · FLOW',
    };
  }

  const streakDays = parseStreakDays(msg);
  if (streakDays !== null || STREAK_TRIGGER_TYPES.has(t)) {
    const days = streakDays ?? 5;
    const dir = t === 'streak_down_5d' || /down/i.test(msg) ? 'Down' : 'Up';
    return {
      paramLabel: 'STREAK RUN',
      paramValue: `${days}D Consecutive ${dir}`,
      timeframe: `${days}D · STREAK`,
      categoryLabel: 'STREAKS · MOMENTUM',
    };
  }

  const pctMatch = msg.match(/([+-]?\d+(?:\.\d+)?%)/);
  if (t.startsWith('52w_') || t.startsWith('near_52w_') || t.startsWith('repeated_52w_')) {
    return {
      paramLabel: '52W EXTREMUM',
      paramValue: pctMatch ? `Breakout (${pctMatch[1]})` : (TRIGGER_LABELS[t] ?? '52W Level'),
      timeframe,
      categoryLabel: 'BREAKOUT · STRUCTURE',
    };
  }

  return {
    paramLabel: 'SIGNAL PARAMETER',
    paramValue: pctMatch ? `${getBadgeLabel(t)} (${pctMatch[1]})` : (TRIGGER_LABELS[t] ?? getBadgeLabel(t)),
    timeframe,
    categoryLabel: 'SCANNER · TRIGGER',
  };
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

  const showStreakStepper =
    activeTab === 'streaks' ||
    selectedForTab.some((t) => STREAK_TRIGGER_TYPES.has(t));

  return (
    <div className="flex-shrink-0 px-3 py-1.5 border-b border-[#27272a] bg-[#0c0c0f] flex flex-wrap items-center gap-1.5 min-h-[32px]">
      <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-400 mr-1">
        SUB-FILTERS:
      </span>
      {selectedForTab.map((triggerType) => (
        <span
          key={triggerType}
          className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded ${getBadgeColor(triggerType)}`}
        >
          {getBadgeLabel(triggerType)}
          <button
            onClick={() => removeFilter(triggerType)}
            className="opacity-80 hover:opacity-100 leading-none"
            title={`Remove ${TRIGGER_LABELS[triggerType] ?? triggerType}`}
          >
            ×
          </button>
        </span>
      ))}

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
          placeholder="+ Add trigger filter..."
          className="bg-[#121216] text-zinc-200 text-xs border border-[#27272a] focus:border-amber-400 rounded outline-none px-2 py-0.5 w-36 focus:w-48 transition-[width,border-color] placeholder:text-zinc-400"
        />
        {showDropdown && candidates.length > 0 && (
          <div className="absolute top-full left-0 mt-1 w-56 bg-[#121216] border border-[#27272a] rounded shadow-2xl z-50 max-h-48 overflow-auto">
            {candidates.map((t) => (
              <button
                key={t}
                onMouseDown={(e) => {
                  e.preventDefault();
                  addFilter(t);
                }}
                className="w-full text-left px-2.5 py-1.5 text-xs text-zinc-200 hover:bg-zinc-800 hover:text-amber-400 flex items-center gap-2"
              >
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${getBadgeColor(t)}`}>
                  {getBadgeLabel(t)}
                </span>
                <span className="truncate">{TRIGGER_LABELS[t] ?? t}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedForTab.length > 0 && (
        <button
          onClick={clearAll}
          className="text-[10px] font-bold text-zinc-400 hover:text-rose-400 transition-colors ml-1"
          title="Clear all filters"
        >
          CLEAR
        </button>
      )}

      {showStreakStepper && (
        <div className="ml-auto flex items-center gap-1.5 shrink-0 bg-[#121216] px-2 py-0.5 rounded border border-[#27272a]">
          <span className="text-zinc-300 text-[10px] font-bold">STREAK ≥</span>
          <button
            onClick={() => onStreakMinDaysChange(Math.max(2, streakMinDays - 1))}
            className="text-zinc-300 hover:text-white text-xs w-4 text-center leading-none font-bold"
            title="Decrease minimum streak days"
          >
            −
          </button>
          <span className="text-amber-400 text-xs font-bold w-5 text-center tabular-nums">
            {streakMinDays}
          </span>
          <button
            onClick={() => onStreakMinDaysChange(streakMinDays + 1)}
            className="text-zinc-300 hover:text-white text-xs w-4 text-center leading-none font-bold"
            title="Increase minimum streak days"
          >
            +
          </button>
          <span className="text-zinc-300 text-[10px]">days</span>
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
  const [activeView, setActiveView] = useState<NotifViewMode>('stream');
  const [activeTab, setActiveTab] = useState<NotifTab>('all');
  const [selectedDate, setSelectedDate] = useState<string>('today');
  const [readFilter, setReadFilter] = useState<ReadFilter>('unread');
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

  const [subFilters, setSubFilters] = useAtom(notifSubFiltersAtom);
  const [streakMinDays, setStreakMinDays] = useAtom(notifStreakMinDaysAtom);
  const [symbolFilter, setSymbolFilter] = useAtom(notifSymbolFilterAtom);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [streamPaused, setStreamPaused] = useState<boolean>(false);
  const [compactStream, setCompactStream] = useState<boolean>(false);
  const [expandedCards, setExpandedCards] = useState<Record<number, boolean>>({});
  const [exchangeFilter, setExchangeFilter] = useState<string>('ALL');
  const [heatmapInspector, setHeatmapInspector] = useState<string>(
    'Hover over any matrix cell above to inspect session trigger breakdown.',
  );

  useEffect(() => {
    if (symbolFilter !== null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
    refetchInterval: streamPaused ? false : 30_000,
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

  const markReadMutation = useMutation({
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

  const clearAllMutation = markReadMutation;

  const handleRowClick = (n: Notification) => {
    setActiveSymbol(n.symbol);
    setActiveExchange(n.exchange || 'NSE');
  };

  const handleDismiss = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    dismissMutation.mutate(id);
  };

  const toggleCardDetails = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    setExpandedCards((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const activeSubFilters = subFilters[activeTab] ?? [];

  const todayStr = useMemo(() => {
    const now = new Date();
    const istOffset = 5.5 * 60;
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

  const dateScopedNotifications = useMemo(() => {
    const all = data ?? [];
    return all.filter((n) => n.triggered_date === targetDate);
  }, [data, targetDate]);

  const unreadCount = useMemo(() => {
    return (data ?? []).filter((n) => !n.is_read).length;
  }, [data]);

  const categoryCounts = useMemo(() => {
    const counts: Record<NotifTab, number> = {
      all: 0,
      breakout: 0,
      volume: 0,
      movers: 0,
      deals: 0,
      insider: 0,
      technical: 0,
      momentum: 0,
      volatility: 0,
      streaks: 0,
      results: 0,
    };
    for (const n of dateScopedNotifications) {
      if (symbolFilter && n.symbol !== symbolFilter) continue;
      counts.all += 1;
      (Object.keys(TAB_TRIGGERS) as NotifTab[]).forEach((tabKey) => {
        if (tabKey !== 'all' && TAB_TRIGGERS[tabKey].includes(n.trigger_type)) {
          counts[tabKey] += 1;
        }
      });
    }
    return counts;
  }, [dateScopedNotifications, symbolFilter]);

  const filteredNotifications = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return (data ?? []).filter((n) => {
      if (symbolFilter && n.symbol !== symbolFilter) return false;
      if (activeTab !== 'all' && !TAB_TRIGGERS[activeTab].includes(n.trigger_type)) return false;
      if (activeSubFilters.length > 0 && !activeSubFilters.includes(n.trigger_type)) return false;
      if (STREAK_TRIGGER_TYPES.has(n.trigger_type)) {
        const days = parseStreakDays(n.message);
        if (streakMinDays > STREAK_MIN && (days === null || days < streakMinDays)) return false;
        if (days !== null && days < streakMinDays) return false;
      }
      if (n.triggered_date !== targetDate) return false;
      if (exchangeFilter !== 'ALL' && (n.exchange || 'NSE').toUpperCase() !== exchangeFilter) {
        return false;
      }
      if (q) {
        const label = (TRIGGER_LABELS[n.trigger_type] ?? n.trigger_type).toLowerCase();
        const hay = `${n.symbol} ${n.exchange} ${label} ${n.message}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [
    data,
    symbolFilter,
    activeTab,
    activeSubFilters,
    streakMinDays,
    targetDate,
    exchangeFilter,
    searchQuery,
  ]);
  const streakRadarNotifications = useMemo(() => {
    const all = data ?? [];
    return all.filter((n) => {
      const isStreak =
        STREAK_TRIGGER_TYPES.has(n.trigger_type) ||
        n.trigger_type === 'repeated_52w_high' ||
        n.trigger_type === 'repeated_52w_low' ||
        parseStreakDays(n.message) !== null;
      if (!isStreak) return false;
      const days = parseStreakDays(n.message);
      if (days !== null && days < streakMinDays) return false;
      return true;
    });
  }, [data, streakMinDays]);

  const heatmapMatrix = useMemo(() => {
    const rows: {
      id: NotifTab;
      label: string;
      triggers: string[];
    }[] = [
      { id: 'breakout', label: 'BREAKOUT (52W)', triggers: TAB_TRIGGERS.breakout },
      { id: 'technical', label: 'TECHNICAL / RSI', triggers: TAB_TRIGGERS.technical },
      { id: 'volume', label: 'VOLUME & SURGE', triggers: [...TAB_TRIGGERS.volume, ...TAB_TRIGGERS.movers] },
      { id: 'deals', label: 'DEALS & INSIDER', triggers: [...TAB_TRIGGERS.deals, ...TAB_TRIGGERS.insider] },
      { id: 'momentum', label: 'MOMENTUM & VOL', triggers: [...TAB_TRIGGERS.momentum, ...TAB_TRIGGERS.volatility] },
      { id: 'streaks', label: 'STREAKS & FLOW', triggers: TAB_TRIGGERS.streaks },
    ];

    const pool = dateScopedNotifications.length > 0 ? dateScopedNotifications : (data ?? []);

    let peakCount = 0;
    let peakSummary = 'N/A';
    let hotRowLabel = 'BREAKOUT (52W)';
    let hotRowMax = -1;

    const matrix = rows.map((row) => {
      let rowTotal = 0;
      const cells = SESSION_SLOTS.map((slot) => {
        const matches = pool.filter((n) => {
          if (!row.triggers.includes(n.trigger_type)) return false;
          const d = new Date(n.triggered_at);
          if (Number.isNaN(d.getTime())) return false;
          const hr = d.getHours();
          return hr >= slot.startHour && hr < slot.endHour;
        });
        const count = matches.length;
        rowTotal += count;
        if (count > peakCount) {
          peakCount = count;
          peakSummary = `${slot.label} ${row.label.split(' ')[0]} (${count} Signals)`;
        }
        const sampleSymbols = Array.from(new Set(matches.slice(0, 4).map((m) => m.symbol))).join(', ');
        const detail =
          count > 0
            ? `${count} Triggers: ${sampleSymbols}${matches.length > 4 ? '...' : ''}`
            : '0 Triggers in this session hour';
        return {
          slotId: slot.id,
          slotLabel: slot.label,
          count,
          detail,
        };
      });

      if (rowTotal > hotRowMax) {
        hotRowMax = rowTotal;
        hotRowLabel = `${row.label} (${rowTotal} Signals)`;
      }

      return {
        ...row,
        rowTotal,
        cells,
      };
    });

    return {
      rows: matrix,
      peakSummary: peakCount > 0 ? peakSummary : 'Awaiting Session Burst',
      hotRowLabel,
    };
  }, [dateScopedNotifications, data]);

  const selectedWatchlist = watchlists.find((wl) => wl.id === selectedWatchlistId);

  const categoryPills: {
    id: NotifTab;
    label: string;
    icon: string;
    accentText: string;
  }[] = [
    { id: 'all', label: 'All Signals', icon: '◈', accentText: 'text-amber-400' },
    { id: 'breakout', label: 'Breakout', icon: '⚡', accentText: 'text-amber-400' },
    { id: 'volume', label: 'Volume', icon: '🌊', accentText: 'text-cyan-400' },
    { id: 'movers', label: 'Movers', icon: '🚀', accentText: 'text-emerald-400' },
    { id: 'deals', label: 'Deals', icon: '🏛', accentText: 'text-amber-300' },
    { id: 'insider', label: 'Insider', icon: '🛡', accentText: 'text-purple-400' },
    { id: 'technical', label: 'Technical', icon: '📐', accentText: 'text-purple-300' },
    { id: 'momentum', label: 'Momentum', icon: '📈', accentText: 'text-sky-400' },
    { id: 'volatility', label: 'Volatility', icon: '⚡', accentText: 'text-rose-400' },
    { id: 'streaks', label: 'Streaks', icon: '🔥', accentText: 'text-emerald-400' },
    { id: 'results', label: 'Results', icon: '📅', accentText: 'text-teal-300' },
  ];

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1 bg-[#09090b]">
        <span className="text-amber-400 font-bold animate-pulse">LOADING NOTIFICATIONS &amp; SIGNAL MATRIX...</span>
      </div>
    );
  }

  if (isError) {
    const errMsg = error instanceof Error ? error.message : 'Unknown error';
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-2 px-4 text-center bg-[#09090b]">
        <span className="text-rose-400 font-bold uppercase">Fetch Failed</span>
        <span className="text-zinc-200 text-xs max-w-xs">{errMsg}</span>
        <button
          onClick={() => refetch()}
          className="px-3 py-1 rounded bg-amber-400 text-black font-bold text-xs hover:bg-amber-300"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col font-mono text-xs overflow-hidden bg-[#09090b] text-white">
      {/* ─── Top View Switcher Toolbar ────────────────────────────────────────── */}
      <div className="flex-shrink-0 px-3 py-2 border-b border-[#27272a] bg-[#09090b] flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-amber-400/10 border border-amber-400/30 text-amber-400 font-black text-xs">
              ◈
            </span>
            <span className="text-amber-400 font-bold text-xs uppercase tracking-wider">
              ALERTS &amp; SCANNER HUB
            </span>
          </div>

          <select
            value={selectedWatchlistId}
            onChange={(e) => setSelectedWatchlistId(Number(e.target.value))}
            className="bg-[#121216] text-amber-400 font-bold text-xs border border-[#27272a] hover:border-zinc-500 rounded px-2 py-1 max-w-[140px] truncate outline-none"
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
            className="bg-[#121216] text-zinc-200 text-xs border border-[#27272a] hover:border-zinc-500 rounded px-2 py-1 max-w-[120px] outline-none"
          >
            {dateOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center bg-[#121216] p-1 rounded-md border border-[#27272a] gap-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeView === 'stream'}
            onClick={() => setActiveView('stream')}
            className={`px-3 py-1 rounded text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
              activeView === 'stream'
                ? 'bg-amber-400 text-black shadow'
                : 'text-zinc-300 hover:text-white hover:bg-zinc-800/60'
            }`}
          >
            <span>⚡</span>
            <span>[LIVE SPLIT STREAM]</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={activeView === 'heatmap'}
            onClick={() => setActiveView('heatmap')}
            className={`px-3 py-1 rounded text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
              activeView === 'heatmap'
                ? 'bg-amber-400 text-black shadow'
                : 'text-zinc-300 hover:text-white hover:bg-zinc-800/60'
            }`}
          >
            <span>📊</span>
            <span>[SIGNAL HEATMAP &amp; RADAR]</span>
          </button>
        </div>
      </div>

      <SubFilterBar
        activeTab={activeTab}
        subFilters={subFilters}
        onSubFiltersChange={setSubFilters}
        streakMinDays={streakMinDays}
        onStreakMinDaysChange={(d) => setStreakMinDays(Math.max(2, d))}
      />

      {symbolFilter && (
        <div className="flex-shrink-0 flex items-center gap-2 px-3 py-1 bg-blue-950/90 border-b border-blue-700/60">
          <span className="text-blue-300 text-xs font-bold uppercase shrink-0">SYMBOL FILTER:</span>
          <span className="text-amber-400 text-xs font-bold">{symbolFilter}</span>
          <button
            onClick={() => setSymbolFilter(null)}
            className="ml-auto text-zinc-300 hover:text-white text-xs font-bold px-1.5 py-0.5 rounded bg-blue-900/40 hover:bg-blue-800/60 leading-none"
            title="Clear symbol filter"
          >
            × CLEAR
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-3 min-h-0">
        {activeView === 'stream' ? (
          <div id="alerts-concept-2" className="grid grid-cols-1 md:grid-cols-4 lg:grid-cols-4 gap-3 max-w-full">
            {/* LEFT FILTER COLUMN (col-span-1 md:col-span-1 lg:col-span-1) */}
            <div className="col-span-1 md:col-span-1 lg:col-span-1 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-3.5 flex flex-col gap-3.5 shadow-xl transition-colors">
              <div className="pb-2.5 border-b border-[#27272a]">
                <div className="flex items-center justify-between">
                  <span className="text-amber-400 font-bold text-xs uppercase tracking-wider font-mono">
                    FILTER &amp; SEVERITY MATRIX
                  </span>
                  <span className="text-[10px] font-mono text-zinc-300 bg-[#121216] px-1.5 py-0.5 rounded border border-[#27272a]">
                    V2 ENGINE
                  </span>
                </div>
                <div className="text-[11px] text-zinc-300 mt-1 font-mono">
                  Dynamic multi-facet query filtering
                </div>
              </div>

              {/* Unread Count Badge & Mark All Read Action */}
              <div className="flex flex-col gap-2 pb-2.5 border-b border-[#27272a]">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-400 font-mono font-bold text-xs">
                    <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                    <span className="tabular-nums">{unreadCount} Unread</span>
                  </div>

                  <button
                    type="button"
                    onClick={() => clearAllMutation.mutate()}
                    disabled={markReadMutation.isPending || unreadCount === 0}
                    className="px-2.5 py-1 rounded bg-amber-400 hover:bg-amber-300 disabled:opacity-40 disabled:pointer-events-none text-black font-bold text-xs font-mono transition-all shadow flex items-center gap-1"
                  >
                    <span>✓</span>
                    <span>Mark All Read</span>
                  </button>
                </div>

                <div>
                  <div className="text-[10px] font-bold text-zinc-300 uppercase tracking-wider mb-1">
                    READ STATUS FILTER
                  </div>
                  <div className="grid grid-cols-3 gap-1">
                    {(['unread', 'read', 'all'] as ReadFilter[]).map((rf) => (
                      <button
                        key={rf}
                        type="button"
                        onClick={() => setReadFilter(rf)}
                        className={`py-1 rounded text-center text-xs font-mono font-bold uppercase transition-all border ${
                          readFilter === rf
                            ? 'bg-amber-400 text-black border-amber-400 shadow'
                            : 'bg-[#121216] text-zinc-200 hover:text-white border-[#27272a] hover:border-zinc-500'
                        }`}
                      >
                        {rf}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Category Filter Pills with Live Counters */}
              <div>
                <div className="text-[11px] font-bold text-white uppercase font-mono tracking-wider mb-2 flex items-center justify-between">
                  <span>TRIGGER CATEGORIES</span>
                  <span className="text-[10px] text-zinc-300 font-bold tabular-nums">
                    {categoryCounts.all} TOTAL
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  {categoryPills.map((cat) => {
                    const isActive = activeTab === cat.id;
                    const count = categoryCounts[cat.id] ?? 0;
                    const hasSubFilters = (subFilters[cat.id] ?? []).length > 0;
                    return (
                      <button
                        key={cat.id}
                        type="button"
                        onClick={() => setActiveTab(cat.id)}
                        className={`w-full p-2 rounded text-xs font-mono flex items-center justify-between transition-all border ${
                          isActive
                            ? 'bg-amber-400 text-black border-amber-400 font-bold shadow'
                            : 'bg-[#121216] text-zinc-200 hover:text-white border-[#27272a] hover:border-zinc-500 font-semibold'
                        }`}
                      >
                        <span className="flex items-center gap-1.5 truncate">
                          <span className={isActive ? 'text-black font-bold' : `${cat.accentText} font-bold`}>
                            {cat.icon}
                          </span>
                          <span className="truncate">{cat.label}</span>
                          {hasSubFilters && !isActive && (
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                          )}
                        </span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded font-bold tabular-nums ${
                            isActive
                              ? 'bg-black/20 text-black'
                              : 'bg-zinc-800 text-amber-400'
                          }`}
                        >
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Streak Min Days Selector (2, 4, 6, 8, 12 days) bound to notifStreakMinDaysAtom */}
              <div className="pt-2.5 border-t border-[#27272a]">
                <div className="text-[11px] font-bold text-white uppercase font-mono tracking-wider mb-1.5 flex items-center justify-between">
                  <span>STREAK MIN DAYS</span>
                  <span className="text-amber-400 font-bold text-[10px] tabular-nums">
                    ≥ {streakMinDays} DAYS
                  </span>
                </div>
                <div className="grid grid-cols-5 gap-1">
                  {STREAK_PRESET_DAYS.map((days) => {
                    const isSelected = streakMinDays === days;
                    return (
                      <button
                        key={days}
                        type="button"
                        onClick={() => setStreakMinDays(days)}
                        className={`py-1 rounded text-center text-xs font-mono font-bold transition-all border ${
                          isSelected
                            ? 'bg-amber-400 text-black border-amber-400 shadow'
                            : 'bg-[#121216] text-zinc-200 hover:text-white border-[#27272a] hover:border-zinc-500'
                        }`}
                      >
                        {days}d
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-zinc-300 mt-1.5 font-mono leading-snug">
                  Filters consecutive day directional closes or volume escalation.
                </p>
              </div>
            </div>

            {/* RIGHT LIVE STREAM BENTO (col-span-1 md:col-span-3 lg:col-span-3) */}
            <div className="col-span-1 md:col-span-3 lg:col-span-3 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-3.5 flex flex-col shadow-xl transition-colors">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-[#27272a] mb-3">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2.5 h-2.5 rounded-full ${
                        streamPaused ? 'bg-amber-400' : 'bg-emerald-400 animate-pulse'
                      }`}
                    />
                    <span className="font-bold text-white text-xs tracking-wider uppercase font-mono">
                      LIVE TRIGGER FEED
                    </span>
                  </div>
                  <span className="text-xs font-mono text-zinc-300 bg-[#121216] px-2 py-0.5 rounded border border-[#27272a] tabular-nums">
                    Showing {filteredNotifications.length} of {dateScopedNotifications.length} Signals ({activeTab.toUpperCase()})
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <div className="relative">
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Filter ticker / trigger / RSI..."
                      className="bg-[#121216] border border-[#27272a] rounded px-2.5 py-1 text-xs text-white placeholder-zinc-400 font-mono focus:border-amber-400 focus:outline-none w-52"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="absolute right-2 top-1 text-zinc-300 hover:text-white text-xs"
                      >
                        ×
                      </button>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => setStreamPaused((p) => !p)}
                    className={`px-2.5 py-1 rounded font-mono text-xs transition-colors flex items-center gap-1 border ${
                      streamPaused
                        ? 'bg-amber-400 text-black border-amber-400 font-bold'
                        : 'bg-[#121216] border-[#27272a] hover:border-zinc-500 text-zinc-200'
                    }`}
                  >
                    <span>{streamPaused ? '▶' : '⏸'}</span>
                    <span>{streamPaused ? 'Resume' : 'Pause'}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setCompactStream((c) => !c)}
                    className={`px-2.5 py-1 rounded font-mono text-xs transition-colors border ${
                      compactStream
                        ? 'bg-amber-400/15 border-amber-400/50 text-amber-400 font-bold'
                        : 'bg-[#121216] border-[#27272a] hover:border-zinc-500 text-zinc-200'
                    }`}
                  >
                    Compact
                  </button>
                </div>
              </div>

              {filteredNotifications.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 px-4 text-center bg-[#121216] border border-[#27272a] rounded-md">
                  <span className="text-amber-400 font-bold text-sm mb-1">
                    NO SIGNALS MATCH CURRENT MATRIX FILTERS
                  </span>
                  <span className="text-zinc-300 text-xs max-w-md">
                    No alerts found for {selectedWatchlist?.name ?? `Watchlist #${selectedWatchlistId}`} under the active filter criteria. Try switching to ALL SIGNALS or adjusting the date/read filter.
                  </span>
                </div>
              ) : (
                <div className={`flex flex-col ${compactStream ? 'gap-1.5' : 'gap-2.5'} overflow-y-auto pr-1`}>
                  {filteredNotifications.map((n) => {
                    const severity = getTriggerSeverity(n.trigger_type);
                    const indicator = extractIndicatorParameter(n);
                    const isExpanded = Boolean(expandedCards[n.id]);

                    return (
                      <div
                        key={n.id}
                        onClick={() => handleRowClick(n)}
                        onMouseEnter={(e) =>
                          setHoveredNotif({ id: n.id, rect: e.currentTarget.getBoundingClientRect() })
                        }
                        onMouseLeave={() => setHoveredNotif(null)}
                        className="p-3 bg-[#121216] border border-[#27272a] hover:border-zinc-500 rounded-md transition-all cursor-pointer"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-sm font-bold text-amber-400 tracking-wide">
                              {n.symbol}
                            </span>
                            <span className="text-[10px] text-zinc-300 font-mono bg-zinc-800 px-1.5 py-0.5 rounded border border-[#27272a]">
                              {n.exchange || 'NSE'} · EQ
                            </span>
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${getBentoBadgeStyle(
                                n.trigger_type,
                              )}`}
                            >
                              {TRIGGER_LABELS[n.trigger_type] ?? getBadgeLabel(n.trigger_type)}
                            </span>
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                                severity === 'CRITICAL'
                                  ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                                  : severity === 'HIGH'
                                  ? 'bg-amber-400/10 text-amber-400 border border-amber-400/20'
                                  : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              }`}
                            >
                              {severity}
                            </span>
                          </div>

                          <div className="flex items-center gap-2">
                            <span className="text-xs text-zinc-300 font-mono tabular-nums">
                              {formatDateTime(n.triggered_at)}
                            </span>
                            <button
                              type="button"
                              onClick={(e) => handleDismiss(e, n.id)}
                              className="text-zinc-300 hover:text-rose-400 text-xs px-1.5 py-0.5 rounded hover:bg-rose-500/10 transition-colors"
                              title="Dismiss trigger"
                            >
                              ✕
                            </button>
                          </div>
                        </div>

                        {!compactStream && (
                          <div className="grid grid-cols-1 sm:grid-cols-4 gap-2 bg-[#09090b] p-2 rounded border border-[#27272a]/80 text-xs font-mono mb-2.5">
                            <div>
                              <span className="text-zinc-400 text-[10px] block uppercase">
                                {indicator.paramLabel}
                              </span>
                              <span className="text-amber-400 font-bold tabular-nums">
                                {indicator.paramValue}
                              </span>
                            </div>
                            <div>
                              <span className="text-zinc-400 text-[10px] block uppercase">
                                TIMEFRAME
                              </span>
                              <span className="text-white font-bold tabular-nums">
                                {indicator.timeframe}
                              </span>
                            </div>
                            <div className="sm:col-span-2">
                              <span className="text-zinc-400 text-[10px] block uppercase">
                                SIGNAL PAYLOAD
                              </span>
                              <span className="text-zinc-100 font-medium block truncate" title={n.message}>
                                {n.message}
                              </span>
                            </div>
                          </div>
                        )}

                        {compactStream && (
                          <div className="text-zinc-200 text-xs mb-2 truncate" title={n.message}>
                            {n.message}
                          </div>
                        )}

                        {isExpanded && (
                          <div
                            onClick={(e) => e.stopPropagation()}
                            className="mb-2.5 p-2.5 bg-[#09090b] border border-[#27272a] rounded text-xs font-mono leading-relaxed"
                          >
                            <div className="text-amber-400 font-bold mb-1">
                              {'// SCANNER ENGINE PARAMETER SNAPSHOT'}
                            </div>
                            <div className="text-zinc-200">
                              Signal Definition:{' '}
                              <span className="text-white font-semibold">
                                {getTooltipDescription(n.trigger_type)}
                              </span>
                            </div>
                            <div className="text-zinc-300 mt-1">
                              Raw Trigger Message: <span className="text-amber-400">{n.message}</span>
                            </div>
                            <div className="text-zinc-300 mt-1">
                              Trigger Key: <code className="text-white bg-[#121216] px-1 rounded">{n.trigger_type}</code> | Parameter: <span className="text-emerald-400">{indicator.paramValue}</span> | Date: {n.triggered_date}
                            </div>
                          </div>
                        )}

                        <div className="flex items-center justify-between gap-2 pt-2 border-t border-[#27272a]/60">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRowClick(n);
                              }}
                              className="px-2.5 py-1 rounded bg-amber-400 hover:bg-amber-300 text-black font-bold text-xs font-mono transition-all flex items-center gap-1 shadow-sm"
                            >
                              <span>⚡</span>
                              <span>LOAD CHART</span>
                            </button>

                            <button
                              type="button"
                              onClick={(e) => toggleCardDetails(e, n.id)}
                              className="px-2 py-1 rounded bg-[#18181f] hover:bg-zinc-700 text-zinc-200 border border-[#27272a] text-xs font-mono transition-colors"
                            >
                              {isExpanded ? '▴ Hide Details' : '▾ Show Details'}
                            </button>
                          </div>

                          <div className="text-[10px] text-zinc-300 font-mono">
                            Engine: <span className="text-zinc-100">NotifScanner_v2.6</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* =====================================================================
           * VIEW 2 — SIGNAL HEATMAP & STREAK RADAR (#alerts-concept-3)
           * ===================================================================== */
          <div id="alerts-concept-3" className="grid grid-cols-1 md:grid-cols-4 lg:grid-cols-4 gap-3 max-w-full">
            {/* 1. SIGNAL FREQUENCY HEATMAP (col-span-1 md:col-span-2 lg:col-span-2) */}
            <div className="col-span-1 md:col-span-2 lg:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-3.5 flex flex-col justify-between shadow-xl transition-colors">
              <div>
                <div className="flex items-center justify-between mb-3 pb-2 border-b border-[#27272a]">
                  <div className="flex items-center gap-2">
                    <span className="text-amber-400 font-bold text-sm">📊</span>
                    <span className="font-bold text-white text-xs tracking-wider uppercase font-mono">
                      SIGNAL FREQUENCY HEATMAP
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-zinc-300 bg-[#121216] px-2 py-0.5 rounded border border-[#27272a]">
                    HOURLY SESSION DENSITY
                  </div>
                </div>

                <p className="text-xs text-zinc-300 mb-2.5 font-mono leading-relaxed">
                  Hourly density breakdown of notifications across market trading sessions. Hover over cells to inspect trigger distribution.
                </p>

                {/* Heatmap Matrix Table */}
                <div className="overflow-x-auto">
                  <table className="w-full text-center font-mono text-xs border-collapse">
                    <thead>
                      <tr className="text-[10px] text-zinc-300 uppercase border-b border-[#27272a]">
                        <th className="text-left py-1.5 px-2">CATEGORY</th>
                        {SESSION_SLOTS.map((slot) => (
                          <th key={slot.id} className="py-1 px-1">
                            {slot.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#27272a]/40 text-xs">
                      {heatmapMatrix.rows.map((row) => (
                        <tr key={row.id}>
                          <td className="text-left py-1.5 px-2 font-bold text-white whitespace-nowrap">
                            {row.label}
                          </td>
                          {row.cells.map((cell) => {
                            const cellStyle =
                              cell.count >= 6
                                ? 'bg-amber-400 text-black font-extrabold shadow'
                                : cell.count >= 3
                                ? 'bg-amber-500/30 text-amber-300 font-bold border border-amber-500/40'
                                : cell.count >= 1
                                ? 'bg-emerald-500/20 text-emerald-300 font-semibold border border-emerald-500/30'
                                : 'bg-[#121216] text-zinc-400';

                            return (
                              <td key={cell.slotId} className="p-1">
                                <div
                                  onMouseEnter={() =>
                                    setHeatmapInspector(
                                      `${row.label} [${cell.slotLabel} IST]: ${cell.detail}`,
                                    )
                                  }
                                  onClick={() => {
                                    setActiveTab(row.id);
                                    setActiveView('stream');
                                  }}
                                  className={`rounded py-1 px-1.5 cursor-pointer transition-transform hover:scale-105 tabular-nums ${cellStyle}`}
                                >
                                  {cell.count > 0 ? cell.count : '-'}
                                </div>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Heatmap Inspector Panel */}
                <div className="mt-3 p-2 bg-[#121216] border border-[#27272a] rounded text-xs font-mono">
                  <span className="text-amber-400 font-bold">INSPECTOR:</span>
                  <span className="text-zinc-200 ml-1.5">{heatmapInspector}</span>
                </div>
              </div>

              {/* Heatmap Summary Stats */}
              <div className="mt-3 pt-2 border-t border-[#27272a] flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-zinc-300">
                <span>
                  Peak Burst: <span className="text-amber-400 font-bold">{heatmapMatrix.peakSummary}</span>
                </span>
                <span>
                  Hot Group: <span className="text-emerald-400 font-bold">{heatmapMatrix.hotRowLabel}</span>
                </span>
              </div>
            </div>

            {/* 2. CONSECUTIVE STREAK RADAR (col-span-1 md:col-span-2 lg:col-span-2) */}
            <div className="col-span-1 md:col-span-2 lg:col-span-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-3.5 flex flex-col justify-between shadow-xl transition-colors">
              <div>
                <div className="flex items-center justify-between mb-3 pb-2 border-b border-[#27272a]">
                  <div className="flex items-center gap-2">
                    <span className="text-emerald-400 font-bold text-sm">🔥</span>
                    <span className="font-bold text-white text-xs tracking-wider uppercase font-mono">
                      CONSECUTIVE STREAK RADAR
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20 font-bold">
                    {streakRadarNotifications.length} MOMENTUM RUNS DETECTED
                  </div>
                </div>

                {/* Streak Cards */}
                {streakRadarNotifications.length === 0 ? (
                  <div className="p-6 bg-[#121216] border border-[#27272a] rounded text-center">
                    <div className="text-amber-400 font-bold text-xs mb-1">
                      NO ACTIVE MULTI-DAY STREAKS (≥ {streakMinDays} DAYS)
                    </div>
                    <div className="text-zinc-300 text-xs">
                      Lower the Streak Min Days threshold or select another watchlist to inspect multi-session runs.
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2.5 max-h-[340px] overflow-y-auto pr-1">
                    {streakRadarNotifications.slice(0, 6).map((sn) => {
                      const days = parseStreakDays(sn.message) ?? Math.max(streakMinDays, 5);
                      const isBearish =
                        sn.trigger_type === 'streak_down_5d' ||
                        sn.trigger_type === 'repeated_52w_low' ||
                        /down/i.test(sn.message);
                      const blockCount = Math.min(Math.max(days, 3), 8);

                      return (
                        <div
                          key={sn.id}
                          className="p-2.5 bg-[#121216] border border-[#27272a] hover:border-zinc-500 rounded transition-colors"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs font-bold text-white tracking-wider">
                                {sn.symbol}
                              </span>
                              <span className="text-[10px] text-zinc-300 font-mono">
                                {sn.exchange || 'NSE'}
                              </span>
                              <span
                                className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                                  isBearish
                                    ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30'
                                    : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                                }`}
                              >
                                {isBearish
                                  ? `🔻 ${days}-DAY CONSECUTIVE LOW STREAK`
                                  : `⚡ ${days}-DAY CONSECUTIVE HIGH STREAK`}
                              </span>
                            </div>
                            <span className="text-[10px] text-zinc-300 font-mono tabular-nums">
                              {formatDateTime(sn.triggered_at)}
                            </span>
                          </div>

                          {/* Streak Visual Day-Blocks Strip */}
                          <div
                            className="grid gap-1 mb-2"
                            style={{ gridTemplateColumns: `repeat(${blockCount}, minmax(0, 1fr))` }}
                          >
                            {Array.from({ length: blockCount }).map((_, idx) => {
                              const isLast = idx === blockCount - 1;
                              return (
                                <div
                                  key={idx}
                                  className={`rounded p-1 text-center text-[10px] font-mono font-bold ${
                                    isLast
                                      ? 'bg-amber-400 text-black font-extrabold shadow'
                                      : isBearish
                                      ? 'bg-rose-500/20 border border-rose-500/40 text-rose-300'
                                      : 'bg-emerald-500/20 border border-emerald-500/40 text-emerald-300'
                                  }`}
                                >
                                  D{idx + 1}
                                </div>
                              );
                            })}
                          </div>

                          <div className="flex items-center justify-between gap-2 text-xs font-mono">
                            <span className="text-zinc-200 truncate" title={sn.message}>
                              {sn.message}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleRowClick(sn)}
                              className="text-amber-400 hover:underline font-bold text-xs shrink-0"
                            >
                              ⚡ Load Chart
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Bottom Footer */}
              <div className="mt-3 pt-2 border-t border-[#27272a] flex items-center justify-between text-xs font-mono text-zinc-300">
                <span>Threshold: ≥ {streakMinDays} Days Consecutive Trend</span>
                <span className="text-amber-400 font-bold">Algorithm: ScanStreakEngine</span>
              </div>
            </div>

            {/* 3. ACTIVE TRIGGER TABLE (col-span-1 md:col-span-4 lg:col-span-4) */}
            <div className="col-span-1 md:col-span-4 lg:col-span-4 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-4 shadow-xl transition-colors">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3 pb-2.5 border-b border-[#27272a]">
                <div className="flex items-center gap-2">
                  <span className="text-amber-400 font-bold text-sm">📋</span>
                  <span className="font-bold text-white text-xs tracking-wider uppercase font-mono">
                    ACTIVE TRIGGER TABLE
                  </span>
                  <span className="text-[10px] text-zinc-300 font-mono">
                    {'// HIGH-DENSITY SCANNER MATRIX & 1-CLICK EXECUTION'}
                  </span>
                </div>

                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-mono text-zinc-300 mr-1">FILTER EXCH:</span>
                  {(['ALL', 'NSE', 'BSE', 'NFO'] as const).map((exch) => (
                    <button
                      key={exch}
                      type="button"
                      onClick={() => setExchangeFilter(exch)}
                      className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                        exchangeFilter === exch
                          ? 'bg-amber-400 text-black font-bold'
                          : 'bg-[#121216] border border-[#27272a] text-zinc-200 hover:text-white'
                      }`}
                    >
                      {exch}
                    </button>
                  ))}
                </div>
              </div>

              {/* High-Density Tabular Bento Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-left font-mono text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-[#27272a] text-[10px] text-zinc-300 uppercase tracking-wider bg-[#121216]/60">
                      <th className="py-2.5 px-3">TIMESTAMP</th>
                      <th className="py-2.5 px-3">TICKER / EXCH</th>
                      <th className="py-2.5 px-3">TRIGGER TYPE</th>
                      <th className="py-2.5 px-2">SEVERITY</th>
                      <th className="py-2.5 px-4">TRIGGER PARAMETERS &amp; CONTEXT</th>
                      <th className="py-2.5 px-3 text-right">1-CLICK ACTION</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#27272a]/60">
                    {filteredNotifications.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-8 text-center text-zinc-300 text-xs">
                          No active triggers match the selected filters.
                        </td>
                      </tr>
                    ) : (
                      filteredNotifications.map((n) => {
                        const severity = getTriggerSeverity(n.trigger_type);
                        return (
                          <tr
                            key={n.id}
                            onClick={() => handleRowClick(n)}
                            className="hover:bg-zinc-900/60 transition-colors cursor-pointer"
                          >
                            <td className="py-2 px-3 text-zinc-200 tabular-nums whitespace-nowrap">
                              {formatDateTime(n.triggered_at)}
                            </td>
                            <td className="py-2 px-3 whitespace-nowrap">
                              <div className="flex items-center gap-1.5">
                                <span className="font-bold text-amber-400">{n.symbol}</span>
                                <span className="text-[10px] text-zinc-300 bg-zinc-800 px-1.5 py-0.5 rounded border border-[#27272a]">
                                  {n.exchange || 'NSE'}
                                </span>
                              </div>
                            </td>
                            <td className="py-2 px-3 whitespace-nowrap">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-bold ${getBentoBadgeStyle(
                                  n.trigger_type,
                                )}`}
                              >
                                {TRIGGER_LABELS[n.trigger_type] ?? getBadgeLabel(n.trigger_type)}
                              </span>
                            </td>
                            <td className="py-2 px-2 whitespace-nowrap">
                              <span
                                className={`text-[10px] font-bold ${
                                  severity === 'CRITICAL'
                                    ? 'text-rose-400'
                                    : severity === 'HIGH'
                                    ? 'text-amber-400'
                                    : 'text-emerald-400'
                                }`}
                              >
                                {severity}
                              </span>
                            </td>
                            <td className="py-2 px-4 text-zinc-200 text-xs max-w-md truncate" title={n.message}>
                              {n.message}
                            </td>
                            <td className="py-2 px-3 text-right whitespace-nowrap">
                              <div className="flex items-center justify-end gap-1.5">
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleRowClick(n);
                                  }}
                                  className="px-2.5 py-1 rounded bg-amber-400 hover:bg-amber-300 text-black font-bold text-[10px]"
                                >
                                  ⚡ CHART
                                </button>
                                <button
                                  type="button"
                                  onClick={(e) => handleDismiss(e, n.id)}
                                  className="px-2 py-1 rounded bg-[#121216] hover:bg-rose-500/15 text-zinc-300 hover:text-rose-400 border border-[#27272a] font-bold text-[10px]"
                                  title="Dismiss"
                                >
                                  ✕
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
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
            <div className="bg-[#121216] border border-amber-400/60 rounded-md shadow-2xl p-3 max-w-80 mb-1">
              <div className="text-amber-400 text-xs font-bold mb-1">
                {getBadgeLabel(
                  filteredNotifications.find((n) => n.id === hoveredNotif.id)?.trigger_type ?? '',
                )}
              </div>
              <div className="text-zinc-200 text-xs mb-1 leading-snug">
                {getTooltipDescription(
                  filteredNotifications.find((n) => n.id === hoveredNotif.id)?.trigger_type ?? '',
                )}
              </div>
              <div className="text-zinc-300 text-[11px] truncate">
                {filteredNotifications.find((n) => n.id === hoveredNotif.id)?.message}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

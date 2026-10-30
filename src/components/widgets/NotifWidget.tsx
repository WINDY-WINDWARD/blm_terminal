'use client';

import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useAtomValue, useAtom } from 'jotai';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactDOM from 'react-dom';
import {
  chartSymbolOverridesAtom,
  companySymbolOverridesAtom,
  type ChartSymbolOverride,
  type CompanySymbolOverride,
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

function getIstHour(iso: string): number | null {
  if (!iso) return null;
  const normalized = iso.includes('Z') || /[+-]\d{2}(:?\d{2})?$/.test(iso)
    ? iso
    : `${iso.replace(' ', 'T')}Z`;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return null;
  try {
    const istString = d.toLocaleString('en-US', { timeZone: 'Asia/Kolkata', hourCycle: 'h23', hour: 'numeric' });
    const parsed = parseInt(istString, 10);
    return Number.isNaN(parsed) ? d.getUTCHours() : parsed;
  } catch {
    const istMs = d.getTime() + 5.5 * 60 * 60 * 1000;
    return new Date(istMs).getUTCHours();
  }
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
    <div
      data-widget-tour="notif-subfilters"
      className="flex-shrink-0 px-3 py-1.5 border-b border-[#27272a] bg-[#0c0c0f] flex flex-wrap items-center gap-1.5 min-h-[32px]"
    >
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

export function NotifWidget({ defaultWatchlist }: { defaultWatchlist?: number | 'all' } = {}) {
  // NOTIF and SCAN render the same component. Anchor names must not collide.
  const tourId = defaultWatchlist === 'all' ? 'scan' : 'notif';
  const queryClient = useQueryClient();
  const watchlists = useAtomValue(watchlistsAtom);
  const activeWatchlistId = useAtomValue(activeWatchlistIdAtom);
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<number | 'all'>(
    defaultWatchlist ?? (watchlists.length > 0 ? watchlists[0].id : 1),
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

  useEffect(() => {
    if (symbolFilter !== null && selectedWatchlistId !== 'all') {
      setSelectedWatchlistId(activeWatchlistId);
    }
  }, [symbolFilter, activeWatchlistId, selectedWatchlistId]);

  const { data, isLoading, isError, error, refetch } = useQuery<Notification[]>({
    queryKey: ['notifications', selectedWatchlistId, readFilter],
    queryFn: async () => {
      const url =
        selectedWatchlistId === 'all'
          ? `/api/py/notifications/global?days=7&limit=500&read_filter=${readFilter}`
          : `/api/py/notifications?watchlist_id=${selectedWatchlistId}&days=7&limit=500&read_filter=${readFilter}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: streamPaused ? false : 30_000,
    refetchIntervalInBackground: false,
  });

  const dismissMutation = useMutation({
    mutationFn: async (id: number) => {
      const url =
        selectedWatchlistId === 'all'
          ? `/api/py/notifications/global/${id}`
          : `/api/py/notifications/${id}?watchlist_id=${selectedWatchlistId}`;
      const res = await fetch(url, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const markReadMutation = useMutation({
    mutationFn: async () => {
      const url =
        selectedWatchlistId === 'all'
          ? `/api/py/notifications/global?all=true`
          : `/api/py/notifications?all=true&watchlist_id=${selectedWatchlistId}`;
      const res = await fetch(url, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });

  const clearAllMutation = markReadMutation;

  const [, setChartOverrides] = useAtom(chartSymbolOverridesAtom);
  const [, setCompanyOverrides] = useAtom(companySymbolOverridesAtom);

  const handleOpenIndependentChart = useCallback((e: React.MouseEvent, symbol: string, exchange?: string) => {
    e.stopPropagation();
    const popoutKey = `popout_direct_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
    setChartOverrides((prev: Record<string, ChartSymbolOverride>) => ({
      ...prev,
      [popoutKey]: { symbol, exchange: exchange || 'NSE' },
    }));
    const query = new URLSearchParams({
      symbol,
      exchange: exchange || 'NSE',
      popoutPanelId: popoutKey,
    });
    window.open(
      `/widget/CHART?${query.toString()}`,
      `blm_widget_CHART_${popoutKey}`,
      'width=1100,height=720',
    );
  }, [setChartOverrides]);

  const handleOpenIndependentCompany = useCallback((e: React.MouseEvent, symbol: string) => {
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
  }, [setCompanyOverrides]);

  const [selectedIndustryModal, setSelectedIndustryModal] = useState<{
    industry: string;
    sector: string;
    notifications: Notification[];
  } | null>(null);

  
  const { data: globalIndustrySummary } = useQuery<{
    industries: Array<{ industry: string; sector: string; alertCount: number; symbols: string[] }>;
  }>({
    queryKey: ['notifications/industry-summary', selectedDate === 'today' ? 2 : 7],
    queryFn: async () => {
      const days = selectedDate === 'today' ? 2 : 7;
      const res = await fetch(`/api/py/notifications/industry-summary?days=${days}`);
      if (!res.ok) return { industries: [] };
      return res.json();
    },
    staleTime: 30_000,
  });

  const { data: stockCategories } = useQuery<Record<string, { industry: string; sector: string }>>({
    queryKey: ['market/stocks-categories'],
    queryFn: async () => {
      const res = await fetch('/api/py/markets/stocks-categories');
      if (!res.ok) return {};
      return res.json();
    },
    staleTime: 60 * 60 * 1000,
  });

  const handleDismiss = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    dismissMutation.mutate(id);
  };

  const toggleCardDetails = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    setExpandedCards((prev) => ({ ...prev, [id]: !prev[id] }));
  };

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
      { label: 'ALL DATES', value: 'all' },
      ...sorted.filter((d) => d !== todayStr).map((d) => ({ label: labels[d], value: d })),
    ];
  }, [data, todayStr]);

  const targetDate = selectedDate === 'today' ? todayStr : selectedDate;

  const dateScopedNotifications = useMemo(() => {
    const all = data ?? [];
    if (selectedDate === 'all') return all;
    return all.filter((n) => n.triggered_date === targetDate);
  }, [data, selectedDate, targetDate]);

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
      for (const [tabKey, triggers] of Object.entries(TAB_TRIGGERS) as [NotifTab, string[]][]) {
        if (tabKey === 'all') continue;
        if (triggers.includes(n.trigger_type)) {
          counts[tabKey] += 1;
        }
      }
    }
    return counts;
  }, [dateScopedNotifications, symbolFilter]);

  const streakFilterActive = activeTab === 'all' || activeTab === 'streaks';

  const filteredNotifications = useMemo(() => {
    let list = dateScopedNotifications;
    if (symbolFilter) {
      list = list.filter((n) => n.symbol === symbolFilter);
    }
    if (exchangeFilter !== 'ALL') {
      list = list.filter((n) => (n.exchange || 'NSE').toUpperCase() === exchangeFilter);
    }
    if (activeTab !== 'all') {
      const allowed = TAB_TRIGGERS[activeTab] ?? [];
      list = list.filter((n) => allowed.includes(n.trigger_type));
    }
    const activeSubFilterList = subFilters[activeTab] ?? [];
    if (activeSubFilterList.length > 0) {
      list = list.filter((n) => activeSubFilterList.includes(n.trigger_type));
    }
    if (streakFilterActive && streakMinDays > 0) {
      list = list.filter((n) => {
        if (!STREAK_TRIGGER_TYPES.has(n.trigger_type)) return true;
        const days = parseStreakDays(n.message);
        return days !== null && days >= streakMinDays;
      });
    }
    if (searchQuery.trim().length > 0) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter(
        (n) =>
          n.symbol.toLowerCase().includes(q) ||
          n.message.toLowerCase().includes(q) ||
          n.trigger_type.toLowerCase().includes(q),
      );
    }
    return list;
  }, [
    dateScopedNotifications,
    symbolFilter,
    exchangeFilter,
    activeTab,
    subFilters,
    streakFilterActive,
    streakMinDays,
    searchQuery,
  ]);

  const industryHeatmapGroups = useMemo(() => {
    // If global scan is active and backend returned pre-aggregated industry summary, use it for instant response
    if (selectedWatchlistId === 'all' && globalIndustrySummary?.industries && globalIndustrySummary.industries.length > 0) {
      return globalIndustrySummary.industries.map((ind) => {
        const notifs = dateScopedNotifications.filter((n) => ind.symbols.includes(n.symbol));
        return {
          industry: ind.industry,
          sector: ind.sector,
          alertCount: ind.alertCount,
          notifications: notifs,
          symbols: new Set(ind.symbols),
        };
      });
    }

    const groups: Record<
      string,
      {
        industry: string;
        sector: string;
        alertCount: number;
        notifications: Notification[];
        symbols: Set<string>;
      }
    > = {};

    for (const n of dateScopedNotifications) {
      if (symbolFilter && n.symbol !== symbolFilter) continue;
      const cat = stockCategories?.[n.symbol];
      const ind = cat?.industry || 'Diversified / General';
      const sec = cat?.sector || 'General';
      const key = `${ind}___${sec}`;
      if (!groups[key]) {
        groups[key] = {
          industry: ind,
          sector: sec,
          alertCount: 0,
          notifications: [],
          symbols: new Set(),
        };
      }
      groups[key].notifications.push(n);
      groups[key].alertCount += 1;
      groups[key].symbols.add(n.symbol);
    }

    return Object.values(groups).sort((a, b) => b.alertCount - a.alertCount);
  }, [dateScopedNotifications, stockCategories, symbolFilter, selectedWatchlistId, globalIndustrySummary]);

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
        <div
          data-widget-tour={tourId === 'scan' ? 'scan-scope' : 'notif-scope-selector'}
          className="flex flex-wrap items-center gap-2"
        >
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded bg-amber-400/10 border border-amber-400/30 text-amber-400 font-black text-xs">
              ◈
            </span>
            <span className="text-amber-400 font-bold text-xs uppercase tracking-wider">
              ALERTS &amp; SCANNER HUB
            </span>
          </div>

          <select
            value={String(selectedWatchlistId)}
            onChange={(e) => setSelectedWatchlistId(e.target.value === 'all' ? 'all' : Number(e.target.value))}
            className="bg-[#121216] text-amber-400 font-bold text-xs border border-[#27272a] hover:border-terminal-amber rounded px-2 py-1 max-w-[155px] truncate outline-none cursor-pointer transition-colors"
          >
            <option value="all">ALL (GLOBAL SCAN)</option>
            {watchlists.map((wl: Watchlist) => (
              <option key={wl.id} value={wl.id}>
                {wl.name}
              </option>
            ))}
          </select>

          <select
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="bg-[#121216] text-zinc-200 text-xs border border-[#27272a] hover:border-terminal-amber rounded px-2 py-1 max-w-[125px] outline-none cursor-pointer transition-colors"
          >
            {dateOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div
          data-widget-tour={tourId === 'scan' ? 'scan-view-mode' : 'notif-view-mode'}
          className="flex items-center bg-[#121216] p-1 rounded-md border border-[#27272a] gap-1"
          role="tablist"
        >
          <button
            type="button"
            role="tab"
            data-widget-tour-click="view-stream"
            aria-selected={activeView === 'stream'}
            onClick={() => setActiveView('stream')}
            className={`px-3 py-1 rounded text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
              activeView === 'stream'
                ? 'bg-amber-400 text-black font-extrabold shadow-[0_0_12px_rgba(245,158,11,0.4)]'
                : 'text-zinc-400 border border-[#27272a] hover:text-white hover:bg-zinc-800/60'
            }`}
          >
            <span>⚡</span>
            <span>[LIVE ALERTS]</span>
          </button>

          <button
            type="button"
            role="tab"
            data-widget-tour-click="view-heatmap"
            aria-selected={activeView === 'heatmap'}
            onClick={() => setActiveView('heatmap')}
            className={`px-3 py-1 rounded text-xs font-mono font-bold transition-all flex items-center gap-1.5 ${
              activeView === 'heatmap'
                ? 'bg-amber-400 text-black font-extrabold shadow-[0_0_12px_rgba(245,158,11,0.4)]'
                : 'text-zinc-400 border border-[#27272a] hover:text-white hover:bg-zinc-800/60'
            }`}
          >
            <span>📊</span>
            <span>[INDUSTRY HEATMAP]</span>
          </button>
        </div>
      </div>

      {activeView === 'stream' && (
        <SubFilterBar
          activeTab={activeTab}
          subFilters={subFilters}
          onSubFiltersChange={setSubFilters}
          streakMinDays={streakMinDays}
          onStreakMinDaysChange={(d) => setStreakMinDays(Math.max(2, d))}
        />
      )}

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
          <div id="alerts-concept-2" className="grid grid-cols-1 @4xl:grid-cols-[minmax(220px,0.85fr)_minmax(0,3fr)] gap-3 max-w-full">
            {/* LEFT FILTER COLUMN (col-span-1) */}
            <div
              className="order-2 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-2.5 @3xl:p-3.5 flex flex-col gap-2.5 @3xl:gap-3.5 shadow-xl transition-colors @4xl:order-1"
            >
              <div className="pb-2.5 border-b border-[#27272a]">
                <div className="flex items-center justify-between">
                  <span className="text-amber-400 font-bold text-xs uppercase tracking-wider font-mono">
                    FILTER &amp; SEVERITY MATRIX
                  </span>
                  <span className="text-[10px] font-mono text-zinc-300 bg-[#121216] px-1.5 py-0.5 rounded border border-[#27272a]">
                    V2 ENGINE
                  </span>
                </div>
                <div className="hidden text-[11px] text-zinc-300 mt-1 font-mono @3xl:block">
                  Dynamic multi-facet query filtering
                </div>
              </div>

              {/* Mark All Read Action (Unread badge removed per spec) */}
              <div className="flex flex-col gap-2 pb-2.5 border-b border-[#27272a]">
                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => clearAllMutation.mutate()}
                    disabled={markReadMutation.isPending || unreadCount === 0}
                    className="w-full px-2.5 py-1.5 rounded bg-amber-400 hover:bg-amber-300 disabled:opacity-40 disabled:pointer-events-none text-black font-bold text-xs font-mono transition-all shadow flex items-center justify-center gap-1 cursor-pointer"
                  >
                    <span>✓</span>
                    <span>Mark All Read</span>
                  </button>
                </div>

                <div>
                  <div className="text-[10px] font-bold text-zinc-300 uppercase tracking-wider mb-1">
                    READ STATUS FILTER
                  </div>
                  <div
                    className="grid grid-cols-3 gap-1"
                    data-widget-tour={tourId === 'notif' ? 'notif-read-filter' : undefined}
                  >
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

              {/* Category Triggers Pill List */}
              <div className="flex flex-col gap-1.5 flex-1">
                <div className="text-[10px] font-bold text-zinc-300 uppercase tracking-wider">
                  SIGNAL CATEGORIES
                </div>
                <div className="grid max-h-28 grid-cols-2 gap-1 overflow-y-auto @2xl:grid-cols-3 @4xl:max-h-none @4xl:grid-cols-1" data-widget-tour={tourId === 'scan' ? 'scan-categories' : 'notif-categories'}>
                  {(
                    [
                      { id: 'all', label: 'ALL TRIGGERS', icon: '⚡' },
                      { id: 'breakout', label: '52W / BREAKOUT', icon: '▲' },
                      { id: 'volume', label: 'VOLUME SURGE', icon: '📊' },
                      { id: 'movers', label: 'TOP MOVERS', icon: '↕' },
                      { id: 'deals', label: 'BULK & BLOCK', icon: '💼' },
                      { id: 'insider', label: 'INSIDER TRADES', icon: '👥' },
                      { id: 'technical', label: 'TECHNICAL (RSI/MACD)', icon: '📈' },
                      { id: 'momentum', label: 'MOMENTUM & 1W', icon: '🔥' },
                      { id: 'volatility', label: 'VOLATILITY & ATR', icon: '⚡' },
                      { id: 'streaks', label: 'STREAKS RADAR', icon: '⏱' },
                      { id: 'results', label: 'EARNINGS & RES', icon: '📋' },
                    ] as { id: NotifTab; label: string; icon: string }[]
                  ).map((cat) => {
                    const count = categoryCounts[cat.id];
                    const isSelected = activeTab === cat.id;

                    return (
                      <button
                        key={cat.id}
                        type="button"
                        onClick={() => setActiveTab(cat.id)}
                        className={`flex items-center justify-between px-2.5 py-1.5 rounded text-xs font-mono transition-all border text-left ${
                          isSelected
                            ? 'bg-amber-400 text-black font-extrabold border-amber-400 shadow-md'
                            : 'bg-[#121216] text-zinc-300 hover:text-white border-[#27272a] hover:border-zinc-500 hover:bg-zinc-800/40'
                        }`}
                      >
                        <span className="flex items-center gap-1.5 truncate">
                          <span>{cat.icon}</span>
                          <span className="truncate">{cat.label}</span>
                        </span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[10px] tabular-nums ${
                            isSelected ? 'bg-black text-amber-400 font-bold' : 'bg-zinc-800 text-zinc-400'
                          }`}
                        >
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Streak Min Days Selector */}
              <div className="pt-2 border-t border-[#27272a]">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-bold text-zinc-300 uppercase tracking-wider font-mono">
                    STREAK MIN DAYS
                  </span>
                  <span className="text-amber-400 font-bold text-xs tabular-nums">
                    ≥ {streakMinDays} Days
                  </span>
                </div>
                <div className="grid grid-cols-5 gap-1">
                  {STREAK_PRESET_DAYS.map((days) => (
                    <button
                      key={days}
                      type="button"
                      onClick={() => setStreakMinDays(days)}
                      className={`py-1 text-center rounded text-xs font-mono font-bold transition-all border ${
                        streakMinDays === days
                          ? 'bg-amber-400 text-black border-amber-400 shadow'
                          : 'bg-[#121216] text-zinc-300 hover:text-white border-[#27272a] hover:border-zinc-500'
                      }`}
                    >
                      {days}d
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* RIGHT LIVE STREAM MATRIX (col-span-3) */}
            <div className="order-1 col-span-full @4xl:order-2 @4xl:col-span-1 bg-[#0c0c0f] border border-[#27272a] hover:border-zinc-600 rounded-lg p-2.5 @3xl:p-3.5 flex flex-col shadow-xl transition-colors min-h-[260px] @4xl:min-h-[500px]">
              {/* Stream Header & Controls */}
              <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-3 border-b border-[#27272a]">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="font-bold text-white text-xs tracking-wider uppercase font-mono">
                    LIVE ALERTS STREAM
                  </span>
                  <span className="text-[10px] font-mono text-zinc-400 bg-[#121216] px-2 py-0.5 rounded border border-[#27272a]">
                    {filteredNotifications.length} Active Triggers
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search symbol, trigger…"
                    className="bg-[#121216] border border-[#27272a] hover:border-zinc-500 focus:border-amber-400 rounded px-2.5 py-1 text-xs text-white placeholder-zinc-500 outline-none w-full @2xl:w-44 font-mono transition-colors"
                  />

                  <div className="flex items-center bg-[#121216] border border-[#27272a] rounded overflow-hidden">
                    {(['ALL', 'NSE', 'BSE'] as const).map((ex) => (
                      <button
                        key={ex}
                        type="button"
                        onClick={() => setExchangeFilter(ex)}
                        className={`px-2 py-1 text-[10px] font-mono font-bold transition-colors ${
                          exchangeFilter === ex
                            ? 'bg-amber-400 text-black'
                            : 'text-zinc-400 hover:text-white'
                        }`}
                      >
                        {ex}
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => setCompactStream((p) => !p)}
                    className={`px-2.5 py-1 rounded text-xs font-mono font-bold border transition-colors ${
                      compactStream
                        ? 'bg-zinc-800 text-amber-400 border-amber-400/40'
                        : 'bg-[#121216] text-zinc-300 border-[#27272a] hover:text-white'
                    }`}
                  >
                    {compactStream ? 'Dense' : 'Spacious'}
                  </button>

                  <button
                    type="button"
                    onClick={() => setStreamPaused((p) => !p)}
                    className={`px-2.5 py-1 rounded text-xs font-mono font-bold border transition-colors flex items-center gap-1.5 ${
                      streamPaused
                        ? 'bg-rose-500/10 text-rose-400 border-rose-500/40'
                        : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    }`}
                  >
                    <span>{streamPaused ? '❚❚ Paused' : '▶ Live'}</span>
                  </button>
                </div>
              </div>

              {/* Alert Cards Feed */}
              {filteredNotifications.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-zinc-500 font-mono">
                  <span className="text-3xl mb-2">⚡</span>
                  <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">
                    NO ALERTS MATCHING CRITERIA
                  </span>
                  <span className="text-[11px] text-zinc-500 mt-1 max-w-sm">
                    No signals triggered for the selected timeframe, category, or watchlist filters.
                  </span>
                </div>
              ) : (
                <div className="flex flex-col gap-2.5 overflow-y-auto max-h-[640px] pr-1">
                  {filteredNotifications.map((n) => {
                    const severity = getTriggerSeverity(n.trigger_type);
                    const indicator = extractIndicatorParameter(n);
                    const isExpanded = Boolean(expandedCards[n.id]);

                    return (
                      <div
                        key={n.id}
                        data-widget-tour={tourId === 'scan' ? 'scan-alert-card' : 'notif-alert-card'}
                        className="p-3 bg-[#121216] border border-[#27272a] hover:border-zinc-500 rounded-md transition-all"
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
                              className="text-zinc-400 hover:text-rose-400 text-xs px-1.5 py-0.5 rounded hover:bg-rose-500/10 transition-colors cursor-pointer"
                              title="Dismiss trigger"
                            >
                              ✕
                            </button>
                          </div>
                        </div>

                        {!compactStream && (
                          <div className="grid grid-cols-2 @2xl:grid-cols-4 gap-2 bg-[#09090b] p-2 rounded border border-[#27272a]/80 text-xs font-mono mb-2.5">
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
                            <div className="col-span-2">
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
                          <div className="mb-2.5 p-2.5 bg-[#09090b] border border-[#27272a] rounded text-xs font-mono leading-relaxed">
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

                        {/* Card Actions: Tactile Independent Chart and Company Popouts */}
                        <div
                          data-widget-tour={tourId === 'scan' ? 'scan-popout-actions' : 'notif-card-actions'}
                          className="flex items-center justify-between gap-2 pt-2 border-t border-[#27272a]/60"
                        >
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={(e) => handleOpenIndependentChart(e, n.symbol, n.exchange)}
                              className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700/80 hover:border-terminal-amber/60 text-zinc-200 text-[11px] font-mono font-semibold transition-all inline-flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer"
                              title={`Open independent chart for ${n.symbol}`}
                            >
                              <span>⚡</span>
                              <span>Load Chart</span>
                            </button>

                            <button
                              type="button"
                              onClick={(e) => handleOpenIndependentCompany(e, n.symbol)}
                              className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700/80 hover:border-terminal-amber/60 text-zinc-200 text-[11px] font-mono font-semibold transition-all inline-flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer"
                              title={`Open independent company panel for ${n.symbol}`}
                            >
                              <span>🏢</span>
                              <span>Company</span>
                            </button>

                            <button
                              type="button"
                              onClick={(e) => toggleCardDetails(e, n.id)}
                              className="px-2 py-1 rounded bg-[#18181f] hover:bg-zinc-700 text-zinc-300 border border-[#27272a] text-xs font-mono transition-colors cursor-pointer"
                            >
                              {isExpanded ? '▴ Hide' : '▾ Details'}
                            </button>
                          </div>

                          <div className="text-[10px] text-zinc-400 font-mono">
                            Engine: <span className="text-zinc-300">NotifScanner_v2.6</span>
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
           * VIEW 2 — INDUSTRY / SECTOR ALERT HEATMAP (Strictly per spec)
           * ===================================================================== */
          <div className="flex flex-col gap-3 max-w-full">
            <div
              data-widget-tour={tourId === 'scan' ? 'scan-heatmap' : 'notif-heatmap'}
              className="p-3 bg-[#0c0c0f] border border-[#27272a] rounded-lg flex flex-wrap items-center justify-between gap-2 shadow-lg"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-amber-400 text-sm font-bold">📊</span>
                  <span className="font-bold text-white text-xs font-mono tracking-wider uppercase">
                    INDUSTRY &amp; SECTOR ALERT HEATMAP
                  </span>
                </div>
                <div className="text-[11px] text-zinc-400 font-mono mt-0.5">
                  Sectoral concentration of alerts for {selectedDate === 'all' ? 'all recorded dates' : selectedDate}. Click any industry card to view all alerting stocks.
                </div>
              </div>
              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="bg-[#121216] border border-[#27272a] px-2 py-1 rounded text-zinc-300">
                  Industries: <span className="text-amber-400 font-bold">{industryHeatmapGroups.length}</span>
                </span>
                <span className="bg-[#121216] border border-[#27272a] px-2 py-1 rounded text-zinc-300">
                  Total Signals: <span className="text-emerald-400 font-bold">{dateScopedNotifications.length}</span>
                </span>
              </div>
            </div>

            {industryHeatmapGroups.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-12 text-center text-zinc-500 font-mono bg-[#0c0c0f] border border-[#27272a] rounded-lg">
                <span className="text-3xl mb-2">📊</span>
                <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider">
                  NO ALERTS IN THIS TIMEFRAME
                </span>
                <span className="text-[11px] text-zinc-500 mt-1">
                  Try switching the date selector to ALL DATES or selecting a different watchlist.
                </span>
              </div>
            ) : (
              <div className="grid grid-cols-1 @md:grid-cols-2 @3xl:grid-cols-3 @4xl:grid-cols-4 gap-3">
                {industryHeatmapGroups.map((group) => {
                  const alertCount = group.notifications.length;
                  const intensityStyle =
                    alertCount >= 6
                      ? 'bg-amber-400 text-black font-extrabold shadow-[0_0_12px_rgba(245,158,11,0.5)]'
                      : alertCount >= 3
                      ? 'bg-amber-400/20 text-amber-300 border border-amber-400/40 font-bold'
                      : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold';

                  const uniqueSymbols = Array.from(group.symbols);

                  return (
                    <div
                      key={`${group.industry}-${group.sector}`}
                      onClick={() => setSelectedIndustryModal(group)}
                      className="p-3.5 bg-[#0c0c0f] hover:bg-[#121216] border border-[#27272a] hover:border-terminal-amber rounded-lg transition-all cursor-pointer shadow-md flex flex-col justify-between group"
                    >
                      <div>
                        <div className="flex items-center justify-between gap-1.5 mb-2">
                          <span className="text-[10px] font-mono uppercase bg-zinc-800/80 text-zinc-400 px-1.5 py-0.5 rounded border border-[#27272a] truncate max-w-[130px]">
                            {group.sector}
                          </span>
                          <span className={`text-xs font-mono px-2 py-0.5 rounded tabular-nums ${intensityStyle}`}>
                            {alertCount} {alertCount === 1 ? 'Alert' : 'Alerts'}
                          </span>
                        </div>

                        <div className="font-bold text-white text-xs font-mono tracking-wide mb-2 group-hover:text-amber-400 transition-colors line-clamp-2">
                          {group.industry}
                        </div>

                        <div className="flex flex-wrap gap-1 mb-3">
                          {uniqueSymbols.slice(0, 4).map((sym) => (
                            <span
                              key={sym}
                              className="text-[10px] font-mono font-bold bg-[#18181f] text-zinc-300 px-1.5 py-0.5 rounded border border-[#27272a]"
                            >
                              {sym}
                            </span>
                          ))}
                          {uniqueSymbols.length > 4 && (
                            <span className="text-[10px] font-mono text-zinc-500 self-center">
                              +{uniqueSymbols.length - 4} more
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="pt-2 border-t border-[#27272a]/60 flex items-center justify-between text-[11px] font-mono text-zinc-400 group-hover:text-amber-400 transition-colors">
                        <span>Inspect Stocks</span>
                        <span>→</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ─── Industry Alert Stocks Drill-Down Modal ──────────────────────────── */}
      {selectedIndustryModal && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in duration-200"
          onClick={() => setSelectedIndustryModal(null)}
        >
          <div
            className="bg-[#0c0c0f] border border-zinc-700 rounded-lg max-w-4xl w-full max-h-[85vh] flex flex-col shadow-2xl font-mono overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-3.5 bg-[#121216] border-b border-[#27272a] flex items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <span className="text-amber-400 text-base">📊</span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-white text-sm">
                      {selectedIndustryModal.industry}
                    </span>
                    <span className="text-[10px] text-zinc-400 bg-zinc-800 px-1.5 py-0.5 rounded border border-[#27272a]">
                      {selectedIndustryModal.sector}
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-400 mt-0.5">
                    {selectedIndustryModal.notifications.length} alerts triggered in this industry
                  </div>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setSelectedIndustryModal(null)}
                className="w-7 h-7 rounded bg-[#18181f] hover:bg-zinc-700 text-zinc-300 hover:text-white flex items-center justify-center text-sm font-bold border border-[#27272a] transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Modal List */}
            <div className="flex-1 overflow-y-auto p-3.5 flex flex-col gap-2 min-h-0">
              {selectedIndustryModal.notifications.map((n) => {
                const indicator = extractIndicatorParameter(n);
                return (
                  <div
                    key={n.id}
                    className="p-3 bg-[#121216] border border-[#27272a] hover:border-zinc-500 rounded-md transition-colors"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-amber-400 text-sm">
                          {n.symbol}
                        </span>
                        <span className="text-[10px] text-zinc-400 bg-zinc-800 px-1.5 py-0.5 rounded border border-[#27272a]">
                          {n.exchange || 'NSE'}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${getBentoBadgeStyle(
                            n.trigger_type,
                          )}`}
                        >
                          {TRIGGER_LABELS[n.trigger_type] ?? getBadgeLabel(n.trigger_type)}
                        </span>
                      </div>

                      <span className="text-xs text-zinc-400 tabular-nums">
                        {formatDateTime(n.triggered_at)}
                      </span>
                    </div>

                    <div className="text-xs text-zinc-200 mb-2 leading-relaxed">
                      {n.message}
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-[#27272a]/60">
                      <div className="text-[11px] text-zinc-400">
                        {indicator.paramLabel}: <span className="text-emerald-400 font-bold">{indicator.paramValue}</span>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={(e) => handleOpenIndependentChart(e, n.symbol, n.exchange)}
                          className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700/80 hover:border-terminal-amber/60 text-zinc-200 text-[11px] font-mono font-semibold transition-all inline-flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer"
                        >
                          <span>⚡</span>
                          <span>Load Chart</span>
                        </button>

                        <button
                          type="button"
                          onClick={(e) => handleOpenIndependentCompany(e, n.symbol)}
                          className="px-2.5 py-1 rounded bg-[#18181b] hover:bg-terminal-amber/20 hover:text-terminal-amber border border-zinc-700/80 hover:border-terminal-amber/60 text-zinc-200 text-[11px] font-mono font-semibold transition-all inline-flex items-center gap-1.5 shadow-sm active:scale-95 cursor-pointer"
                        >
                          <span>🏢</span>
                          <span>Company</span>
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Modal Footer */}
            <div className="p-2.5 bg-[#121216] border-t border-[#27272a] flex items-center justify-between text-xs text-zinc-400">
              <span>Independent chart &amp; company popouts do not modify the main terminal grid symbol.</span>
              <button
                type="button"
                onClick={() => setSelectedIndustryModal(null)}
                className="px-3 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-bold transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

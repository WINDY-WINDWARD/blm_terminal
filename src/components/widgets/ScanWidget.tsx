'use client';

import React, { useState } from 'react';
import { useAtom } from 'jotai';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { activeExchangeAtom, activeSymbolAtom } from '@/store/terminalStore';

interface GlobalNotification {
  id: number;
  symbol: string;
  exchange: string;
  trigger_type: string;
  message: string;
  triggered_at: string;
  triggered_date: string;
  is_read: boolean;
}

type NotifTab = 'all' | 'breakout' | 'volume' | 'movers' | 'deals' | 'technical' | 'momentum' | 'volatility' | 'streaks';

const TAB_TRIGGERS: Record<NotifTab, string[]> = {
  all: [],
  breakout: ['52w_high_breakout', '52w_low_breakout', 'near_52w_high', 'near_52w_low'],
  volume: ['volume_breakout'],
  movers: ['top_gainer', 'top_loser'],
  deals: ['bulk_deal', 'block_deal', 'short_deal'],
  technical: ['rsi_oversold', 'rsi_overbought', 'macd_bullish_cross', 'macd_bearish_cross', 'bb_squeeze_alert', 'bb_upper_break', 'bb_lower_break'],
  momentum: ['momentum_surge', 'return_1w_spike'],
  volatility: ['volatility_spike', 'atr_expansion'],
  streaks: ['streak_up_5d', 'streak_down_5d'],
};

function getBadgeColor(triggerType: string): string {
  if (triggerType.startsWith('52w_')) return 'bg-terminal-amber text-black';
  if (triggerType === 'volume_breakout') return 'bg-cyan-600 text-white';
  if (triggerType === 'top_gainer') return 'bg-terminal-green text-black';
  if (triggerType === 'top_loser') return 'bg-terminal-red text-white';
  if (triggerType === 'bulk_deal') return 'bg-orange-600 text-white';
  if (triggerType === 'block_deal') return 'bg-orange-700 text-white';
  if (triggerType === 'short_deal') return 'bg-orange-500 text-white';
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
  return triggerType.toUpperCase();
}

function getTooltipDescription(triggerType: string): string {
  switch (triggerType) {
    case '52w_high_breakout': return 'Price broke above its 52-week high — strong bullish signal';
    case '52w_low_breakout': return 'Price broke below its 52-week low — strong bearish signal';
    case 'volume_breakout': return 'Volume surged 3x+ above 20-day average — unusual activity';
    case 'top_gainer': return 'Among top gainers in the market today';
    case 'top_loser': return 'Among top losers in the market today';
    case 'bulk_deal': return 'Large bulk deal detected on NSE — significant institutional activity';
    case 'block_deal': return 'Block deal detected on NSE — large block transaction';
    case 'short_deal': return 'Short deal detected on NSE — short selling activity';
    case 'rsi_oversold': return 'RSI(14) below 30 — oversold condition, potential bounce';
    case 'rsi_overbought': return 'RSI(14) above 70 — overbought condition, potential pullback';
    case 'macd_bullish_cross': return 'MACD line crossed above signal line — bullish momentum shift';
    case 'macd_bearish_cross': return 'MACD line crossed below signal line — bearish momentum shift';
    case 'bb_squeeze_alert': return 'Bollinger Bands squeezed — low volatility, potential breakout coming';
    case 'bb_upper_break': return 'Price closed above upper Bollinger Band — overbought signal';
    case 'bb_lower_break': return 'Price closed below lower Bollinger Band — oversold signal';
    case 'volatility_spike': return 'HV20 is 1.5x+ higher than HV60 — volatility spike detected';
    case 'atr_expansion': return 'Daily price range expanded significantly — volatility increasing';
    case 'momentum_surge': return 'Momentum score above 70 — strong bullish momentum';
    case 'return_1w_spike': return '1-week return above 10% — short-term momentum surge';
    case 'streak_up_5d': return '5+ consecutive up days — strong upward streak';
    case 'streak_down_5d': return '5+ consecutive down days — strong downward streak';
    case 'near_52w_high': return 'Within 3% of 52-week high — approaching resistance';
    case 'near_52w_low': return 'Within 3% of 52-week low — approaching support';
    default: return triggerType;
  }
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  return `${hh}:${mm}`;
}

export function ScanWidget() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<NotifTab>('all');
  const [, setActiveSymbol] = useAtom(activeSymbolAtom);
  const [, setActiveExchange] = useAtom(activeExchangeAtom);

  const { data, isLoading, isError, error, refetch } = useQuery<GlobalNotification[]>({
    queryKey: ['global-notifications'],
    queryFn: async () => {
      const res = await fetch('/api/py/notifications/global');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });

  const dismissMutation = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`/api/py/notifications/global/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-notifications'] });
    },
  });

  const clearAllMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch('/api/py/notifications/global?all=true', { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-notifications'] });
    },
  });

  const handleRowClick = (n: GlobalNotification) => {
    setActiveSymbol(n.symbol);
    setActiveExchange(n.exchange);
  };

  const handleDismiss = (e: React.MouseEvent, id: number) => {
    e.stopPropagation();
    dismissMutation.mutate(id);
  };

  const filteredNotifications = (data ?? []).filter((n) => {
    if (activeTab === 'all') return true;
    return TAB_TRIGGERS[activeTab].includes(n.trigger_type);
  });

  const tabs: { id: NotifTab; label: string }[] = [
    { id: 'all', label: 'ALL' },
    { id: 'breakout', label: '52W' },
    { id: 'volume', label: 'VOLUME' },
    { id: 'movers', label: 'MOVERS' },
    { id: 'deals', label: 'DEALS' },
    { id: 'technical', label: 'TECHNICAL' },
    { id: 'momentum', label: 'MOMENTUM' },
    { id: 'volatility', label: 'VOLATILITY' },
    { id: 'streaks', label: 'STREAKS' },
  ];

  if (isLoading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center font-mono text-xs gap-1">
        <span className="text-terminal-amber/60 animate-pulse">SCANNING MARKET...</span>
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
      <div className="flex-shrink-0 px-3 py-1 border-b border-terminal-gray flex items-center gap-2 min-w-0">
        <span className="text-terminal-amber font-bold text-[11px] uppercase shrink-0">SCAN</span>
        <span className="text-white/60 text-[10px] shrink-0">
          ({(data ?? []).length})
        </span>
        {(data ?? []).length > 0 && (
          <button
            onClick={() => clearAllMutation.mutate()}
            className="ml-auto text-[9px] text-white/50 hover:text-terminal-red transition-colors shrink-0"
          >
            CLEAR ALL
          </button>
        )}
      </div>

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
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-auto px-2 py-1 min-h-0">
        {filteredNotifications.length === 0 ? (
          <div className="text-white/40 text-[10px] py-4 text-center">
            No global alerts detected.
          </div>
        ) : (
          <div className="flex flex-col gap-px">
            {filteredNotifications.map((n) => (
              <div
                key={n.id}
                onClick={() => handleRowClick(n)}
                className="relative flex items-center gap-2 px-2 py-[4px] bg-zinc-900 hover:bg-zinc-800 cursor-pointer group border border-terminal-gray/20 rounded-sm"
              >
                <span className={`shrink-0 text-[8px] font-bold px-1 py-px rounded ${getBadgeColor(n.trigger_type)}`}>
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
                <span className="text-white/40 text-[9px] shrink-0">{formatTime(n.triggered_at)}</span>
                <button
                  onClick={(e) => handleDismiss(e, n.id)}
                  className="shrink-0 text-white/30 hover:text-terminal-red text-[11px] w-4 text-center opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Dismiss"
                >
                  ×
                </button>
                <div className="absolute -top-1 left-0 z-[9999] hidden group-hover:block pointer-events-none">
                  <div className="bg-zinc-800 border border-terminal-amber/60 rounded-md shadow-2xl p-2 max-w-72 -translate-y-full">
                    <div className="text-terminal-amber text-[10px] font-bold mb-1">
                      {getBadgeLabel(n.trigger_type)}
                    </div>
                    <div className="text-white/80 text-[9px] mb-1 leading-snug">
                      {getTooltipDescription(n.trigger_type)}
                    </div>
                    <div className="text-white/50 text-[8px] truncate">
                      {n.message}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
'use client';

import React from 'react';

// Plain-language explanation for every scan threshold.
export const NOTIF_CONFIG_HELP: Record<string, string> = {
  'notif.rsi_oversold_threshold': 'Alert when RSI falls below this level (oversold bounce watch).',
  'notif.rsi_overbought_threshold': 'Alert when RSI rises above this level (pullback watch).',
  'notif.volatility_spike_ratio': 'Alert when the day range exceeds this multiple of its recent average.',
  'notif.atr_expansion_threshold': 'Alert when ATR expands past this multiple of baseline (volatility regime change).',
  'notif.momentum_surge_threshold': 'Alert when the momentum score crosses above this level.',
  'notif.return_1w_spike_threshold': 'Alert when the 1-week return exceeds this percent.',
  'notif.streak_days_threshold': 'Alert after this many consecutive up or down days.',
  'notif.near_52w_threshold': 'Alert when price trades within this % of the 52-week high or low.',
  'notif.deal_significance_pct': 'Bulk/block deals above this fraction of market cap trigger alerts (0.05 = 5%).',
  'notif.deal_absolute_threshold_cr': '…or above this ₹ Cr value when market cap is unknown.',
};

// Bento UI Component - modeled directly after CompanyTabs/FundamentalsTab.tsx
export function BentoCard({
  children,
  className = '',
  title,
  icon,
  badge,
  blurb,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
  icon?: string;
  badge?: React.ReactNode;
  blurb?: string;
}) {
  return (
    <div
      className={`bg-[#09090b] border border-[#27272a] rounded p-3 flex flex-col justify-between transition-colors duration-200 hover:bg-zinc-900/80 ${className}`}
    >
      <div className="flex flex-col gap-2">
        {(title || badge || icon) && (
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 min-w-0">
              {icon && (
                <span className="text-terminal-amber text-xs w-4 text-center shrink-0">
                  {icon}
                </span>
              )}
              {title && (
                <span className="text-[10px] uppercase font-mono tracking-wider text-zinc-400 font-semibold truncate">
                  {title}
                </span>
              )}
            </div>
            {badge && <div className="shrink-0 flex items-center">{badge}</div>}
          </div>
        )}
        {blurb && (
          <p className="text-white/50 text-[10px] leading-relaxed">{blurb}</p>
        )}
        <div className="flex flex-col gap-2">{children}</div>
      </div>
    </div>
  );
}

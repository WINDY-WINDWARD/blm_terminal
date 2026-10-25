export const NOTIF_CONFIG_KEYS = [
  'notif.rsi_oversold_threshold',
  'notif.rsi_overbought_threshold',
  'notif.volatility_spike_ratio',
  'notif.atr_expansion_threshold',
  'notif.momentum_surge_threshold',
  'notif.return_1w_spike_threshold',
  'notif.streak_days_threshold',
  'notif.near_52w_threshold',
  'notif.deal_significance_pct',
  'notif.deal_absolute_threshold_cr',
] as const;

export const NOTIF_CONFIG_LABELS: Record<(typeof NOTIF_CONFIG_KEYS)[number], string> = {
  'notif.rsi_oversold_threshold': 'RSI Oversold',
  'notif.rsi_overbought_threshold': 'RSI Overbought',
  'notif.volatility_spike_ratio': 'Volatility Spike Ratio',
  'notif.atr_expansion_threshold': 'ATR Expansion',
  'notif.momentum_surge_threshold': 'Momentum Surge',
  'notif.return_1w_spike_threshold': '1W Return Spike',
  'notif.streak_days_threshold': 'Streak Days',
  'notif.near_52w_threshold': 'Near 52W Threshold',
  'notif.deal_significance_pct': 'Deal Min % of Mkt Cap',
  'notif.deal_absolute_threshold_cr': 'Deal Min Value (₹ Cr)',
};

export type NotifConfigKey = (typeof NOTIF_CONFIG_KEYS)[number];

export type NotifConfigState = Record<NotifConfigKey, string>;

export const DEFAULT_NOTIF_CONFIG: NotifConfigState = {
  'notif.rsi_oversold_threshold': '30',
  'notif.rsi_overbought_threshold': '70',
  'notif.volatility_spike_ratio': '1.5',
  'notif.atr_expansion_threshold': '4',
  'notif.momentum_surge_threshold': '70',
  'notif.return_1w_spike_threshold': '10',
  'notif.streak_days_threshold': '5',
  'notif.near_52w_threshold': '3',
  'notif.deal_significance_pct': '0.05',
  'notif.deal_absolute_threshold_cr': '2',
};

export interface BrowserProvision {
  state: 'unknown' | 'ready' | 'missing' | 'downloading' | 'failed';
  downloaded: number;
  total: number;
  version: string | null;
  error: string | null;
}

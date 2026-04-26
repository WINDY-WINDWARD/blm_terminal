export interface Notification {
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

export const notifications: Notification[] = [
  {
    id: 1,
    watchlist_id: 1,
    symbol: 'RELIANCE',
    exchange: 'NSE',
    trigger_type: '52w_high_breakout',
    message: 'RELIANCE broke above its 52-week high of ₹2,600',
    triggered_at: '2025-04-24T09:15:00Z',
    triggered_date: '2025-04-24',
    is_read: false,
  },
  {
    id: 2,
    watchlist_id: 1,
    symbol: 'TCS',
    exchange: 'NSE',
    trigger_type: 'top_gainer',
    message: 'TCS is among top gainers today',
    triggered_at: '2025-04-24T09:30:00Z',
    triggered_date: '2025-04-24',
    is_read: false,
  },
  {
    id: 3,
    watchlist_id: 1,
    symbol: 'HDFCBANK',
    exchange: 'NSE',
    trigger_type: 'volume_breakout',
    message: 'HDFCBANK volume 3x above 20-day average',
    triggered_at: '2025-04-24T10:00:00Z',
    triggered_date: '2025-04-24',
    is_read: true,
  },
  {
    id: 4,
    watchlist_id: 1,
    symbol: 'INFY',
    exchange: 'NSE',
    trigger_type: 'insider_buy',
    message: 'Promoter bought 50,000 shares',
    triggered_at: '2025-04-23T14:00:00Z',
    triggered_date: '2025-04-23',
    is_read: false,
  },
  {
    id: 5,
    watchlist_id: 1,
    symbol: 'WIPRO',
    exchange: 'NSE',
    trigger_type: 'rsi_oversold',
    message: 'RSI(14) below 30 - oversold condition',
    triggered_at: '2025-04-24T11:00:00Z',
    triggered_date: '2025-04-24',
    is_read: false,
  },
];
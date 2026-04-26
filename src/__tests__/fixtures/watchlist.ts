export interface Watchlist {
  id: number;
  name: string;
  created_at: string;
  item_count?: number;
}

export interface WatchlistItem {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
}

export const watchlists: Watchlist[] = [
  { id: 1, name: 'DEFAULT', created_at: '2025-01-01T00:00:00Z', item_count: 3 },
  { id: 2, name: 'TECH', created_at: '2025-02-01T00:00:00Z', item_count: 2 },
];

export const watchlistItems: WatchlistItem[] = [
  { id: 1, watchlist_id: 1, symbol: 'RELIANCE', exchange: 'NSE' },
  { id: 2, watchlist_id: 1, symbol: 'TCS', exchange: 'NSE' },
  { id: 3, watchlist_id: 1, symbol: 'HDFCBANK', exchange: 'NSE' },
];
import { atom } from 'jotai';
import { atomWithStorage } from 'jotai/utils';
import type { TickData } from '@/lib/socket';
import type { FundsData } from '@/lib/openalgo';

// ─── Existing Atoms ───────────────────────────────────────────────────────────

export const activeCommandAtom = atom<string>('');

export const activePanelsAtom = atomWithStorage<{ [id: string]: string }>(
  'terminal.activePanels',
  { 'panel-1': 'CHART', 'panel-2': 'WATCH', 'panel-3': 'TOP', 'panel-4': 'POS' },
);

export const focusedPanelAtom = atomWithStorage<string>('terminal.focusedPanel', 'panel-1');

// ─── Global Active Symbol ─────────────────────────────────────────────────────

/** The currently active trading symbol — shared across all widgets */
export const activeSymbolAtom = atomWithStorage<string>('terminal.activeSymbol', 'RELIANCE');

/** The currently active exchange — shared across all widgets */
export const activeExchangeAtom = atomWithStorage<string>('terminal.activeExchange', 'NSE');

// ─── Other Atoms ─────────────────────────────────────────────────────────────

/** Live tick data keyed by "SYMBOL.EXCHANGE" — updated by wsService */
export const tickDataAtom = atom<Record<string, TickData>>({});

/** WebSocket connection status */
export const wsConnectedAtom = atom<boolean>(false);

/** Account funds data — updated periodically */
export const fundsAtom = atom<FundsData | null>(null);

// ─── Column Configuration ───────────────────────────────────────────────────

export const DEFAULT_WATCHLIST_COLUMNS = ['ltp', 'chg', '1w', '1m', '3m', '6m', '1y'];
export const DEFAULT_MOVERS_COLUMNS = ['close', 'chg', '1w', '1m', '3m', '6m', '1y'];

export const watchlistColumnsAtom = atomWithStorage<string[]>('terminal.watchlistColumns', DEFAULT_WATCHLIST_COLUMNS);
export const moversColumnsAtom = atomWithStorage<string[]>('terminal.moversColumns', DEFAULT_MOVERS_COLUMNS);

// ─── Watchlists ─────────────────────────────────────────────────────────────

export interface Watchlist {
  id: number;
  name: string;
  created_at: string;
  item_count?: number;
}

export const watchlistsAtom = atom<Watchlist[]>([]);

export const activeWatchlistIdAtom = atomWithStorage<number>('terminal.activeWatchlistId', 1);

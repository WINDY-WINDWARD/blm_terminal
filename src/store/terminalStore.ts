import { atom } from 'jotai';
import type { TickData } from '@/lib/socket';
import type { FundsData } from '@/lib/openalgo';

// ─── Existing Atoms ───────────────────────────────────────────────────────────

export const activeCommandAtom = atom<string>('');

export const activePanelsAtom = atom<{ [id: string]: string }>({
  'panel-1': 'CHART',
  'panel-2': 'WATCH',
  'panel-3': 'TOP',
  'panel-4': 'POS',
});

export const focusedPanelAtom = atom<string>('panel-1');

// ─── Global Active Symbol ─────────────────────────────────────────────────────

/** The currently active trading symbol — shared across all widgets */
export const activeSymbolAtom = atom<string>('RELIANCE');

/** The currently active exchange — shared across all widgets */
export const activeExchangeAtom = atom<string>('NSE');

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

export const watchlistColumnsAtom = atom<string[]>(DEFAULT_WATCHLIST_COLUMNS);
export const moversColumnsAtom = atom<string[]>(DEFAULT_MOVERS_COLUMNS);

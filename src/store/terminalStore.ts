import { atom } from 'jotai';
import { atomWithStorage } from 'jotai/utils';
import type { TickData } from '@/lib/socket';
import type { FundsData } from '@/lib/openalgo';

// ─── Existing Atoms ───────────────────────────────────────────────────────────

export const activeCommandAtom = atom<string>('');

export type PanelCount = 2 | 4 | 6 | 8;

export interface PanelSplitSizes {
  rowSizes: number[];
  colSizes: number[][];
}

export const PANEL_LAYOUTS: Record<PanelCount, { rows: number; cols: number }> = {
  2: { rows: 1, cols: 2 },
  4: { rows: 2, cols: 2 },
  6: { rows: 2, cols: 3 },
  8: { rows: 2, cols: 4 },
};

export function createDefaultPanelSizes(panelCount: PanelCount): PanelSplitSizes {
  const layout = PANEL_LAYOUTS[panelCount];
  const rowSizes = Array.from({ length: layout.rows }, () => 100 / layout.rows);
  const colSizes = Array.from({ length: layout.rows }, () =>
    Array.from({ length: layout.cols }, () => 100 / layout.cols),
  );

  return { rowSizes, colSizes };
}

export const DEFAULT_ACTIVE_PANELS: Record<string, string> = {
  'panel-1': 'CHART',
  'panel-2': 'WATCH',
  'panel-3': 'TOP',
  'panel-4': 'POS',
  'panel-5': 'NEWS',
  'panel-6': 'ANALYSIS',
  'panel-7': 'DEALS',
  'panel-8': 'ORDER',
};

export const activePanelsAtom = atomWithStorage<Record<string, string>>(
  'terminal.activePanels',
  DEFAULT_ACTIVE_PANELS,
);

export const panelCountAtom = atomWithStorage<PanelCount>('terminal.panelCount', 4);

export const panelSizesAtom = atomWithStorage<PanelSplitSizes | null>('terminal.panelSizes', null);

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

export const DEFAULT_WATCHLIST_COLUMNS = ['ltp', 'chg', 'msfv', '1w', '1m', '3m', '6m', '1y'];
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

import { atom } from 'jotai';
import { atomWithStorage } from 'jotai/utils';
import type { TickData } from '@/lib/socket';
import type { FundsData } from '@/lib/openalgo';

// ─── Per-Tab Storage (sessionStorage) ─────────────────────────────────────────

const getSessionStorage = () =>
  typeof window !== 'undefined' ? window.sessionStorage : undefined;

export const tabStorage = {
  getItem: <V>(key: string, initialValue: V): V => {
    const storage = getSessionStorage();
    if (!storage) return initialValue;
    const stored = storage.getItem(key);
    if (stored === null) return initialValue;
    try {
      return JSON.parse(stored) as V;
    } catch {
      return initialValue;
    }
  },
  setItem: <V>(key: string, newValue: V): void => {
    const storage = getSessionStorage();
    if (storage) {
      storage.setItem(key, JSON.stringify(newValue));
    }
  },
  removeItem: (key: string): void => {
    const storage = getSessionStorage();
    if (storage) {
      storage.removeItem(key);
    }
  },
};

// ─── Legacy LocalStorage Keys (to be cleaned up) ──────────────────────────────

export const OLD_LOCAL_STORAGE_KEYS = [
  'terminal.activePanels',
  'terminal.panelCount',
  'terminal.panelSizes',
  'terminal.focusedPanel',
  'terminal.activeSymbol',
  'terminal.activeExchange',
  'terminal.watchlistColumns',
  'terminal.moversColumns',
  'terminal.moversCategory',
  'terminal.activeWatchlistId',
  'notif.subFilters',
  'notif.streakMinDays',
  'scan.subFilters',
  'scan.streakMinDays',
];

/** Remove stale localStorage keys that have migrated to sessionStorage. */
export function cleanupOldLocalStorage(): void {
  if (typeof window === 'undefined') return;
  OLD_LOCAL_STORAGE_KEYS.forEach((key) => {
    window.localStorage.removeItem(key);
  });
}

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
  tabStorage,
);

export const panelCountAtom = atomWithStorage<PanelCount>('terminal.panelCount', 4, tabStorage);

export const panelSizesAtom = atomWithStorage<PanelSplitSizes | null>('terminal.panelSizes', null, tabStorage);

export const focusedPanelAtom = atomWithStorage<string>('terminal.focusedPanel', 'panel-1', tabStorage);

// ─── Global Active Symbol ─────────────────────────────────────────────────────

/** The currently active trading symbol — tab-isolated via sessionStorage */
export const activeSymbolAtom = atomWithStorage<string>('terminal.activeSymbol', 'RELIANCE', tabStorage);

/** The currently active exchange — tab-isolated via sessionStorage */
export const activeExchangeAtom = atomWithStorage<string>('terminal.activeExchange', 'NSE', tabStorage);

// ─── Other Atoms ─────────────────────────────────────────────────────────────

/** Live tick data keyed by "SYMBOL.EXCHANGE" — updated by wsService */
export const tickDataAtom = atom<Record<string, TickData>>({});

/** WebSocket connection status */
export const wsConnectedAtom = atom<boolean>(false);

/** Account funds data — updated periodically */
export const fundsAtom = atom<FundsData | null>(null);

// ─── Column Configuration ───────────────────────────────────────────────────

export const DEFAULT_WATCHLIST_COLUMNS = ['ltp', 'chg', 'msfv', '1w', '1m', '3m', '6m', '1y', 'results', 'alerts'];
export const DEFAULT_MOVERS_COLUMNS = ['close', 'chg', '1w', '1m', '3m', '6m', '1y'];

export const watchlistColumnsAtom = atomWithStorage<string[]>('terminal.watchlistColumns', DEFAULT_WATCHLIST_COLUMNS, tabStorage);
export const moversColumnsAtom = atomWithStorage<string[]>('terminal.moversColumns', DEFAULT_MOVERS_COLUMNS, tabStorage);

/** Currently selected category for top-gainers/top-losers (e.g. "allSec", "NIFTY") */
export const moversCategoryAtom = atomWithStorage<string>('terminal.moversCategory', 'allSec', tabStorage);

// ─── Watchlists ─────────────────────────────────────────────────────────────

export interface Watchlist {
  id: number;
  name: string;
  created_at: string;
  item_count?: number;
}

export const watchlistsAtom = atom<Watchlist[]>([]);

export const activeWatchlistIdAtom = atomWithStorage<number>('terminal.activeWatchlistId', 1, tabStorage);

// ─── Notif / Scan Sub-Filters ─────────────────────────────────────────────────

/**
 * Per-tab sub-filter state for NotifWidget and ScanWidget.
 * Keys are tab ids (e.g. "technical", "streaks"), values are arrays of
 * selected trigger_type strings (e.g. ["rsi_oversold", "macd_bullish_cross"]).
 * An empty array means no sub-filter active for that tab (show all).
 */
export type SubFilterMap = Partial<Record<string, string[]>>;

/** NotifWidget — selected trigger_type bubbles per tab */
export const notifSubFiltersAtom = atomWithStorage<SubFilterMap>('notif.subFilters', {}, tabStorage);

/** NotifWidget — minimum streak day count for the streaks tab (floor = 5) */
export const notifStreakMinDaysAtom = atomWithStorage<number>('notif.streakMinDays', 5, tabStorage);

/** ScanWidget — selected trigger_type bubbles per tab */
export const scanSubFiltersAtom = atomWithStorage<SubFilterMap>('scan.subFilters', {}, tabStorage);

/** ScanWidget — minimum streak day count for the streaks tab (floor = 5) */
export const scanStreakMinDaysAtom = atomWithStorage<number>('scan.streakMinDays', 5, tabStorage);

// ─── Notif Symbol Filter ──────────────────────────────────────────────────────

/**
 * Symbol filter set by WatchWidget when an alert count badge is clicked.
 * NotifWidget reads this and filters its list to only show the chosen symbol.
 * null = no filter active.
 */
export const notifSymbolFilterAtom = atom<string | null>(null);

// ─── Global Notification Alert Modal ──────────────────────────────────────────

/** IDs the alert modal has already notified for (persisted, capped at 1000) — global across tabs */
export const seenNotifIdsAtom = atomWithStorage<number[]>('notif.seenIds', []);

/** Whether the global notification alert modal is visible */
export const notifAlertVisibleAtom = atom<boolean>(false);

/** Number of new notifications shown in the alert modal */
export const notifAlertCountAtom = atom<number>(0);

/** Timestamp bump to trigger NOTIF panel highlight flash */
export const notifPanelHighlightAtom = atom<number>(0);

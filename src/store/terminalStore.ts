import { atom } from 'jotai';
import { atomWithStorage } from 'jotai/utils';
import type { FundsData } from '@/lib/openalgo';
import type { NewsArticle } from '@/lib/newsSocket';
import type { ActiveIndicator } from '@/lib/indicators/types';

/** Live tick data shape — LTP-centric, populated by marketWs SymbolData */
export interface TickData {
  symbol: string;
  exchange: string;
  ltp: number;
  pChange?: number;
  yearHigh?: number;
  yearLow?: number;
  /** Epoch ms when this tick was received — enables tick-age staleness checks */
  updatedAt?: number;
}

// ─── Dual Storage (Syncs between window.localStorage and Electron appData) ───

declare global {
  interface Window {
    electronAPI?: {
      getAppVersion: () => Promise<string>;
      checkForUpdates: () => Promise<unknown>;
      downloadUpdate: () => Promise<unknown>;
      installUpdate: () => Promise<void>;
      onUpdaterMessage: (callback: (msg: { status: string; data?: unknown }) => void) => void;
      getStoredItem?: (key: string) => Promise<unknown>;
      setStoredItem?: (key: string, value: unknown) => Promise<boolean>;
      removeStoredItem?: (key: string) => Promise<boolean>;
      getAllStoredItems?: () => Promise<Record<string, unknown>>;
    };
  }
}

const getLocalStorage = () =>
  typeof window !== 'undefined' ? window.localStorage : undefined;

export const persistentStorage = {
  getItem: <V>(key: string, initialValue: V): V => {
    const storage = getLocalStorage();
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
    const storage = getLocalStorage();
    if (storage) {
      storage.setItem(key, JSON.stringify(newValue));
    }
    // Eagerly backup to Electron's disk-based store if in desktop environment
    if (typeof window !== 'undefined' && window.electronAPI?.setStoredItem) {
      window.electronAPI.setStoredItem(key, newValue).catch(() => {});
    }
  },
  removeItem: (key: string): void => {
    const storage = getLocalStorage();
    if (storage) {
      storage.removeItem(key);
    }
    if (typeof window !== 'undefined' && window.electronAPI?.removeStoredItem) {
      window.electronAPI.removeStoredItem(key).catch(() => {});
    }
  },
};

export const tabStorage = persistentStorage;

// ─── Legacy LocalStorage Keys ──────────────────────────────────────────────────

export const OLD_LOCAL_STORAGE_KEYS: string[] = [];

/** No-op cleanup maintained for backward compatibility. */
export function cleanupOldLocalStorage(): void {
  // Retained as a safe no-op so persistent layout keys are not deleted.
}

// ─── Auth State ───────────────────────────────────────────────────────────────

export interface AuthUser {
  id: number;
  username: string;
  is_admin: boolean;
}

export interface AuthState {
  user: AuthUser;
}

/** User info persisted in localStorage (token lives in HTTP-only cookie) */
export const authAtom = atomWithStorage<AuthState | null>('terminal.auth', null);

export const isAuthenticatedAtom = atom((get) => get(authAtom) !== null);

/** Legal consent for generic browser automation / advanced scraping */
export const advancedScrapingConsentAtom = atomWithStorage<boolean | null>(
  'terminal.advancedScrapingConsent',
  null,
);

// ─── First-Launch Onboarding ────────────────────────────────────────────────

/** True once the user has completed (or finished) the first-launch setup wizard */
export const onboardingCompletedAtom = atomWithStorage<boolean>(
  'terminal.onboarding.v1',
  false,
);

/** Guided tutorial lifecycle: pending → active → done */
export type TutorialStatus = 'pending' | 'active' | 'done';

export const tutorialStatusAtom = atomWithStorage<TutorialStatus>(
  'terminal.tutorial.v1',
  'pending',
);

// ─── Existing Atoms ───────────────────────────────────────────────────────────

export const activeCommandAtom = atom<string>('');

export type PanelCount = 2 | 4 | 6 | 8;

export interface PanelSplitSizes {
  rowSizes: number[];
  colSizes: number[][];
  mergedColSizes?: number[];
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
  'panel-8': 'PORTFOLIO',
};

export const activePanelsAtom = atomWithStorage<Record<string, string>>(
  'terminal.activePanels',
  DEFAULT_ACTIVE_PANELS,
);

export const panelCountAtom = atomWithStorage<PanelCount>('terminal.panelCount', 4);

export const panelSizesAtom = atomWithStorage<PanelSplitSizes | null>('terminal.panelSizes', null);

export const focusedPanelAtom = atomWithStorage<string>('terminal.focusedPanel', 'panel-1');

// ─── Panel Selection & Merging ────────────────────────────────────────────────

/** Panels currently selected with Ctrl+Click (ephemeral — not persisted) */
export const selectedPanelsAtom = atom<string[]>([]);

export interface MergedGroup {
  panels: string[];
  primary: string;
}

/** Map from primary panel ID to its merge group (persisted across sessions) */
export const mergedGroupsAtom = atomWithStorage<Record<string, MergedGroup>>(
  'terminal.mergedGroups',
  {},
);

/**
 * Returns the MergedGroup that contains `panelId`, or `undefined` if none.
 */
export function getMergedGroupForPanel(
  panelId: string,
  mergedGroups: Record<string, MergedGroup>,
): MergedGroup | undefined {
  for (const group of Object.values(mergedGroups)) {
    if (group.panels.includes(panelId)) {
      return group;
    }
  }
  return undefined;
}

/**
 * Validates whether a set of selected panel IDs can be merged.
 * Rules:
 *   - Must be at least 2 panels.
 *   - Must be an even number of panels.
 *   - Must form a solid rectangle (no L-shapes, no gaps).
 *   - No panel may already belong to an existing merge group.
 */
export function validateMergeSelection(
  panelIds: string[],
  panelCount: PanelCount,
  mergedGroups: Record<string, MergedGroup>,
): { valid: boolean; error?: string } {
  if (panelIds.length < 2) {
    return { valid: false, error: 'Select at least 2 panels' };
  }

  if (panelIds.length % 2 !== 0) {
    return { valid: false, error: 'Select an even number of panels' };
  }

  const validPanelIds = new Set(
    Array.from({ length: panelCount }, (_, index) => `panel-${index + 1}`),
  );

  for (const panelId of panelIds) {
    if (!validPanelIds.has(panelId)) {
      return { valid: false, error: 'Selected panels must be in the current layout' };
    }
  }

  for (const panelId of panelIds) {
    for (const group of Object.values(mergedGroups)) {
      if (group.panels.includes(panelId)) {
        return { valid: false, error: 'Selected panels must not already be merged' };
      }
    }
  }

  const layout = PANEL_LAYOUTS[panelCount];
  const positions = panelIds.map((id) => {
    const num = Number(id.split('-')[1]);
    const zeroBasedIndex = num - 1;
    const row = Math.floor(zeroBasedIndex / layout.cols);
    const col = zeroBasedIndex % layout.cols;
    return { id, row, col };
  });

  const rows = positions.map((p) => p.row);
  const cols = positions.map((p) => p.col);
  const minRow = Math.min(...rows);
  const maxRow = Math.max(...rows);
  const minCol = Math.min(...cols);
  const maxCol = Math.max(...cols);

  const expectedCount = (maxRow - minRow + 1) * (maxCol - minCol + 1);
  if (expectedCount !== panelIds.length) {
    return { valid: false, error: 'Selection must form a solid rectangle' };
  }

  const selectedSet = new Set(panelIds);
  for (let r = minRow; r <= maxRow; r++) {
    for (let c = minCol; c <= maxCol; c++) {
      const expectedNum = r * layout.cols + c + 1;
      const expectedId = `panel-${expectedNum}`;
      if (!selectedSet.has(expectedId)) {
        return { valid: false, error: 'Selection must form a solid rectangle' };
      }
    }
  }

  return { valid: true };
}

// ─── Global Active Symbol ─────────────────────────────────────────────────────

/** The currently active trading symbol — global across tabs via localStorage */
export const activeSymbolAtom = atomWithStorage<string>('terminal.activeSymbol', 'RELIANCE');

/** The currently active exchange — global across tabs via localStorage */
export const activeExchangeAtom = atomWithStorage<string>('terminal.activeExchange', 'NSE');

// ─── Other Atoms ─────────────────────────────────────────────────────────────

/** Live tick data keyed by "SYMBOL.EXCHANGE" — updated by marketWs */
export const tickDataAtom = atom<Record<string, TickData>>({});

/** WebSocket connection status */
export const wsConnectedAtom = atom<boolean>(false);

/** Whether OpenAlgo broker is configured and reachable */
export const openAlgoAvailableAtom = atom<boolean>(true);

/** Account funds data — updated periodically */
export const fundsAtom = atom<FundsData | null>(null);

// ─── Column Configuration ───────────────────────────────────────────────────

export const DEFAULT_WATCHLIST_COLUMNS = ['ltp', 'chg', 'msfv', '1w', '1m', '3m', '6m', '1y', 'results', 'alerts'];
export const DEFAULT_MOVERS_COLUMNS = ['close', 'chg', '1w', '1m', '3m', '6m', '1y'];

export const watchlistColumnsAtom = atomWithStorage<string[]>('terminal.watchlistColumns', DEFAULT_WATCHLIST_COLUMNS);
export const moversColumnsAtom = atomWithStorage<string[]>('terminal.moversColumns', DEFAULT_MOVERS_COLUMNS);

/** Currently selected category for top-gainers/top-losers (e.g. "allSec", "NIFTY") */
export const moversCategoryAtom = atomWithStorage<string>('terminal.moversCategory', 'allSec');

// ─── Ticker Bar ──────────────────────────────────────────────────────────────

/** Ticker source preference. Values: 'default' | 'top' | 'watchlist:<id>' */
export const tickerSourceAtom = atomWithStorage<string>('terminal.tickerSource', 'default');

// ─── Watchlists ─────────────────────────────────────────────────────────────

export interface Watchlist {
  id: number;
  name: string;
  created_at: string;
  item_count?: number;
}

export const watchlistsAtom = atom<Watchlist[]>([]);

export const activeWatchlistIdAtom = atomWithStorage<number>('terminal.activeWatchlistId', 1);

// ─── Notif / Scan Sub-Filters ─────────────────────────────────────────────────

/**
 * Sub-filter state for NotifWidget and ScanWidget.
 * Keys are tab ids (e.g. "technical", "streaks"), values are arrays of
 * selected trigger_type strings (e.g. ["rsi_oversold", "macd_bullish_cross"]).
 * An empty array means no sub-filter active for that tab (show all).
 */
export type SubFilterMap = Partial<Record<string, string[]>>;

/** NotifWidget — selected trigger_type bubbles per tab */
export const notifSubFiltersAtom = atomWithStorage<SubFilterMap>('notif.subFilters', {});

/** NotifWidget — minimum streak day count for the streaks tab (floor = 5) */
export const notifStreakMinDaysAtom = atomWithStorage<number>('notif.streakMinDays', 5);

/** ScanWidget — selected trigger_type bubbles per tab */
export const scanSubFiltersAtom = atomWithStorage<SubFilterMap>('scan.subFilters', {});

/** ScanWidget — minimum streak day count for the streaks tab (floor = 5) */
export const scanStreakMinDaysAtom = atomWithStorage<number>('scan.streakMinDays', 5);

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

// ─── News ──────────────────────────────────────────────────────────────────────

export const newsWsConnectedAtom = atom<boolean>(false);

export const liveNewsArticlesAtom = atom<NewsArticle[]>([]);

export interface NewsFilters {
  excludedSources: string[];
  sentiment: string | null;
  threatLevel: string | null;
  searchQuery: string;
}

export const newsFiltersAtom = atomWithStorage<NewsFilters>('news.filters', {
  excludedSources: [],
  sentiment: null,
  threatLevel: null,
  searchQuery: '',
});

// ─── Saved Layouts ────────────────────────────────────────────────────────────

export interface SavedLayout {
  name: string;
  activePanels: Record<string, string>;
  panelCount: PanelCount;
  mergedGroups: Record<string, MergedGroup>;
  savedAt: number;
}

/** All saved layouts, keyed by lowercase name. Persisted in localStorage (cross-tab). */
export const savedLayoutsAtom = atomWithStorage<Record<string, SavedLayout>>(
  'terminal.savedLayouts',
  {},
);

// ─── Layout Toast & Confirm ──────────────────────────────────────────────────

export const layoutToastAtom = atom<{ visible: boolean; message: string; type: 'success' | 'error' }>({
  visible: false,
  message: '',
  type: 'success',
});

export const layoutConfirmAtom = atom<{
  visible: boolean;
  layoutName: string;
  pendingLayout: SavedLayout | null;
}>({
  visible: false,
  layoutName: '',
  pendingLayout: null,
});

export interface LayoutSyncStatus {
  status: 'synced' | 'pending' | 'error';
  pendingCount: number;
  lastError?: string;
}

export const layoutSyncStatusAtom = atom<LayoutSyncStatus>({
  status: 'synced',
  pendingCount: 0,
});

// ─── Chart Indicators ────────────────────────────────────────────────────────

/** Persisted chart indicator set — clamped via clampIndicators() on load. */
export const chartIndicatorsAtom = atomWithStorage<{ v: number; items: ActiveIndicator[] }>(
  'terminal.chartIndicators',
  { v: 1, items: [] },
);

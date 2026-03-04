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

// ─── Other Atoms ──────────────────────────────────────────────────────────────

/** Live tick data keyed by "SYMBOL.EXCHANGE" — updated by wsService */
export const tickDataAtom = atom<Record<string, TickData>>({});

/** WebSocket connection status */
export const wsConnectedAtom = atom<boolean>(false);

/** Account funds data — updated periodically */
export const fundsAtom = atom<FundsData | null>(null);

/** Top mover symbols list — loaded from SQLite via /api/top-symbols */
export const topSymbolsAtom = atom<Array<{ symbol: string; exchange: string }>>([]);

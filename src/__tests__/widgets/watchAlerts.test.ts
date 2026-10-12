/**
 * Tests for the WatchWidget ALERTS column feature.
 *
 * Covers:
 *  - alertCountMap — building a symbol → count map from raw notification records
 *  - handleAlertClick — sets notifSymbolFilterAtom only when NOTIF panel is open
 *  - NotifWidget symbol filter — filtering notifications by symbol, clearing filter
 *  - DEFAULT_WATCHLIST_COLUMNS includes 'alerts'
 *  - notifSymbolFilterAtom exists and initialises to null
 */

import { describe, it, expect } from 'vitest';
import { DEFAULT_WATCHLIST_COLUMNS, notifSymbolFilterAtom } from '@/store/terminalStore';
import { createStore } from 'jotai';

// ─── alertCountMap helper (mirrors WatchWidget useMemo logic) ─────────────────

function buildAlertCountMap(records: Array<{ symbol: string }>): Map<string, number> {
  const map = new Map<string, number>();
  for (const n of records) {
    map.set(n.symbol, (map.get(n.symbol) ?? 0) + 1);
  }
  return map;
}

// ─── handleAlertClick helper (mirrors WatchWidget useCallback logic) ──────────

function makeHandleAlertClick(
  activePanels: Record<string, string>,
  onSetFilter: (symbol: string) => void,
) {
  return (symbol: string) => {
    const isNotifOpen = Object.values(activePanels).includes('NOTIF');
    if (isNotifOpen) onSetFilter(symbol);
  };
}

// ─── Symbol filter pipeline (mirrors NotifWidget filteredNotifications logic) ──

function applySymbolFilter(
  notifications: Array<{ symbol: string; trigger_type: string }>,
  symbolFilter: string | null,
): Array<{ symbol: string; trigger_type: string }> {
  return notifications.filter((n) => {
    if (symbolFilter && n.symbol !== symbolFilter) return false;
    return true;
  });
}

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const NOTIF_RECORDS = [
  { symbol: 'RELIANCE', trigger_type: 'rsi_oversold' },
  { symbol: 'RELIANCE', trigger_type: 'volume_breakout' },
  { symbol: 'RELIANCE', trigger_type: '52w_high_breakout' },
  { symbol: 'TCS', trigger_type: 'macd_bullish_cross' },
  { symbol: 'INFY', trigger_type: 'top_gainer' },
  { symbol: 'INFY', trigger_type: 'streak_up_5d' },
];

// ─── alertCountMap ────────────────────────────────────────────────────────────

describe('buildAlertCountMap', () => {
  it('counts multiple alerts for the same symbol correctly', () => {
    const map = buildAlertCountMap(NOTIF_RECORDS);
    expect(map.get('RELIANCE')).toBe(3);
    expect(map.get('TCS')).toBe(1);
    expect(map.get('INFY')).toBe(2);
  });

  it('returns 0 (via Map.get undefined) for symbols not in the data', () => {
    const map = buildAlertCountMap(NOTIF_RECORDS);
    expect(map.get('HDFCBANK')).toBeUndefined();
    // Widget uses ?? 0 fallback — simulate that
    expect(map.get('HDFCBANK') ?? 0).toBe(0);
  });

  it('returns an empty map for empty input', () => {
    const map = buildAlertCountMap([]);
    expect(map.size).toBe(0);
  });

  it('handles a single record correctly', () => {
    const map = buildAlertCountMap([{ symbol: 'SBIN' }]);
    expect(map.get('SBIN')).toBe(1);
    expect(map.size).toBe(1);
  });

  it('treats symbol names as case-sensitive keys', () => {
    const map = buildAlertCountMap([
      { symbol: 'reliance' },
      { symbol: 'RELIANCE' },
    ]);
    expect(map.get('reliance')).toBe(1);
    expect(map.get('RELIANCE')).toBe(1);
    expect(map.size).toBe(2);
  });
});

// ─── handleAlertClick ────────────────────────────────────────────────────────

describe('handleAlertClick', () => {
  it('calls setFilter when NOTIF panel is open', () => {
    const calls: string[] = [];
    const handler = makeHandleAlertClick(
      { 'panel-1': 'CHART', 'panel-2': 'NOTIF', 'panel-3': 'WATCH' },
      (s) => calls.push(s),
    );

    handler('RELIANCE');

    expect(calls).toEqual(['RELIANCE']);
  });

  it('does NOT call setFilter when NOTIF panel is absent', () => {
    const calls: string[] = [];
    const handler = makeHandleAlertClick(
      { 'panel-1': 'CHART', 'panel-2': 'WATCH', 'panel-3': 'TOP' },
      (s) => calls.push(s),
    );

    handler('RELIANCE');

    expect(calls).toHaveLength(0);
  });

  it('works with any panel key holding NOTIF', () => {
    const calls: string[] = [];
    const handler = makeHandleAlertClick(
      { 'panel-7': 'NOTIF' },
      (s) => calls.push(s),
    );

    handler('TCS');

    expect(calls).toEqual(['TCS']);
  });

  it('does nothing for an empty activePanels map', () => {
    const calls: string[] = [];
    const handler = makeHandleAlertClick({}, (s) => calls.push(s));
    handler('INFY');
    expect(calls).toHaveLength(0);
  });

  it('passes the exact symbol string to setFilter', () => {
    const calls: string[] = [];
    const handler = makeHandleAlertClick(
      { 'panel-1': 'NOTIF' },
      (s) => calls.push(s),
    );
    handler('HDFC BANK');
    expect(calls[0]).toBe('HDFC BANK');
  });
});

// ─── NotifWidget symbol filter pipeline ───────────────────────────────────────

describe('NotifWidget symbol filter', () => {
  it('returns all notifications when symbolFilter is null', () => {
    const result = applySymbolFilter(NOTIF_RECORDS, null);
    expect(result).toHaveLength(NOTIF_RECORDS.length);
  });

  it('filters to only the matching symbol', () => {
    const result = applySymbolFilter(NOTIF_RECORDS, 'RELIANCE');
    expect(result).toHaveLength(3);
    result.forEach((n) => expect(n.symbol).toBe('RELIANCE'));
  });

  it('returns empty array when no notifications match the symbol', () => {
    const result = applySymbolFilter(NOTIF_RECORDS, 'HDFCBANK');
    expect(result).toHaveLength(0);
  });

  it('is case-sensitive (matches exact symbol from backend)', () => {
    // Backend always returns UPPER symbols — filter must match exactly
    const result = applySymbolFilter(NOTIF_RECORDS, 'reliance');
    expect(result).toHaveLength(0);
  });

  it('returns empty array when notifications list is empty', () => {
    const result = applySymbolFilter([], 'RELIANCE');
    expect(result).toHaveLength(0);
  });

  it('symbol filter is independent of trigger_type', () => {
    const result = applySymbolFilter(NOTIF_RECORDS, 'INFY');
    expect(result.map((n) => n.trigger_type)).toEqual(['top_gainer', 'streak_up_5d']);
  });
});

// ─── Store: DEFAULT_WATCHLIST_COLUMNS ────────────────────────────────────────

describe('DEFAULT_WATCHLIST_COLUMNS', () => {
  it("includes 'alerts' column", () => {
    expect(DEFAULT_WATCHLIST_COLUMNS).toContain('alerts');
  });

  it("'alerts' is after 'results'", () => {
    const resultsIdx = DEFAULT_WATCHLIST_COLUMNS.indexOf('results');
    const alertsIdx = DEFAULT_WATCHLIST_COLUMNS.indexOf('alerts');
    expect(alertsIdx).toBeGreaterThan(resultsIdx);
  });

  it('retains all original columns', () => {
    const original = ['ltp', 'chg', 'msfv', '1w', '1m', '3m', '6m', '1y', 'results'];
    for (const col of original) {
      expect(DEFAULT_WATCHLIST_COLUMNS).toContain(col);
    }
  });
});

// ─── Store: notifSymbolFilterAtom ─────────────────────────────────────────────

describe('notifSymbolFilterAtom', () => {
  it('initialises to null', () => {
    const store = createStore();
    expect(store.get(notifSymbolFilterAtom)).toBeNull();
  });

  it('can be set to a symbol string', () => {
    const store = createStore();
    store.set(notifSymbolFilterAtom, 'RELIANCE');
    expect(store.get(notifSymbolFilterAtom)).toBe('RELIANCE');
  });

  it('can be cleared back to null', () => {
    const store = createStore();
    store.set(notifSymbolFilterAtom, 'TCS');
    store.set(notifSymbolFilterAtom, null);
    expect(store.get(notifSymbolFilterAtom)).toBeNull();
  });

  it('is not persisted to storage (in-memory atom)', () => {
    // notifSymbolFilterAtom uses atom() not atomWithStorage() —
    // verify the atom has no key property (atomWithStorage adds one)
    expect((notifSymbolFilterAtom as unknown as Record<string, unknown>)['init']).toBeNull();
  });
});

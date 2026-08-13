import { describe, it, expect, beforeEach } from 'vitest';
import { Provider, createStore } from 'jotai';
import { render } from '@testing-library/react';
import React from 'react';
import {
  activePanelsAtom,
  panelCountAtom,
  panelSizesAtom,
  focusedPanelAtom,
  activeSymbolAtom,
  activeExchangeAtom,
  watchlistColumnsAtom,
  moversColumnsAtom,
  moversCategoryAtom,
  activeWatchlistIdAtom,
  notifSubFiltersAtom,
  notifStreakMinDaysAtom,
  scanSubFiltersAtom,
  scanStreakMinDaysAtom,
  seenNotifIdsAtom,
  cleanupOldLocalStorage,
  OLD_LOCAL_STORAGE_KEYS,
} from '@/store/terminalStore';

/**
 * Helper to set an atom value inside a Jotai Provider and flush the storage write.
 */
function setAtomValue<T>(atom: unknown, value: T): void {
  const store = createStore();
  const TestSetter = () => {
    React.useEffect(() => {
      store.set(atom as never, value);
    }, []);
    return null;
  };
  render(
    <Provider store={store}>
      <TestSetter />
    </Provider>
  );
}

describe('tab storage isolation', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  describe('atoms that should write to sessionStorage', () => {
    const sessionAtoms = [
      { atom: activePanelsAtom, key: 'terminal.activePanels', value: { 'panel-1': 'CHART' } },
      { atom: panelCountAtom, key: 'terminal.panelCount', value: 6 },
      {
        atom: panelSizesAtom,
        key: 'terminal.panelSizes',
        value: { rowSizes: [50, 50], colSizes: [[50, 50]], mergedColSizes: [50, 50] },
      },
      { atom: focusedPanelAtom, key: 'terminal.focusedPanel', value: 'panel-2' },
      { atom: watchlistColumnsAtom, key: 'terminal.watchlistColumns', value: ['ltp', 'chg'] },
      { atom: moversColumnsAtom, key: 'terminal.moversColumns', value: ['close', 'chg'] },
      { atom: moversCategoryAtom, key: 'terminal.moversCategory', value: 'NIFTY' },
      { atom: activeWatchlistIdAtom, key: 'terminal.activeWatchlistId', value: 3 },
      { atom: notifSubFiltersAtom, key: 'notif.subFilters', value: { technical: ['rsi_oversold'] } },
      { atom: notifStreakMinDaysAtom, key: 'notif.streakMinDays', value: 10 },
      { atom: scanSubFiltersAtom, key: 'scan.subFilters', value: { technical: ['macd_bullish_cross'] } },
      { atom: scanStreakMinDaysAtom, key: 'scan.streakMinDays', value: 7 },
    ] as const;

    sessionAtoms.forEach(({ atom, key, value }) => {
      it(`writes "${key}" to sessionStorage and not localStorage`, () => {
        setAtomValue(atom, value);

        expect(sessionStorage.getItem(key)).not.toBeNull();
        expect(localStorage.getItem(key)).toBeNull();
      });
    });
  });

  describe('Global atoms should use localStorage', () => {
    it('writes "notif.seenIds" to localStorage and not sessionStorage', () => {
      setAtomValue(seenNotifIdsAtom, [1, 2, 3]);

      expect(localStorage.getItem('notif.seenIds')).not.toBeNull();
      expect(sessionStorage.getItem('notif.seenIds')).toBeNull();
    });

    it('writes "terminal.activeSymbol" to localStorage and not sessionStorage', () => {
      setAtomValue(activeSymbolAtom, 'INFY');
      expect(localStorage.getItem('terminal.activeSymbol')).not.toBeNull();
      expect(sessionStorage.getItem('terminal.activeSymbol')).toBeNull();
    });

    it('writes "terminal.activeExchange" to localStorage and not sessionStorage', () => {
      setAtomValue(activeExchangeAtom, 'BSE');
      expect(localStorage.getItem('terminal.activeExchange')).not.toBeNull();
      expect(sessionStorage.getItem('terminal.activeExchange')).toBeNull();
    });
  });
});

describe('cleanupOldLocalStorage', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('removes every legacy localStorage key', () => {
    OLD_LOCAL_STORAGE_KEYS.forEach((key) => {
      localStorage.setItem(key, JSON.stringify('dummy'));
    });

    // Keep a key that should NOT be removed
    localStorage.setItem('notif.seenIds', JSON.stringify([1, 2, 3]));
    localStorage.setItem('blm_migrated_alerts_col_v1', '1');

    cleanupOldLocalStorage();

    OLD_LOCAL_STORAGE_KEYS.forEach((key) => {
      expect(localStorage.getItem(key)).toBeNull();
    });

    // Global keys must remain intact
    expect(localStorage.getItem('notif.seenIds')).not.toBeNull();
    expect(localStorage.getItem('blm_migrated_alerts_col_v1')).toBe('1');
  });

  it('does not throw when window is undefined (SSR)', () => {
    const originalWindow = globalThis.window;
    // @ts-expect-error — simulate SSR
    globalThis.window = undefined;

    expect(() => cleanupOldLocalStorage()).not.toThrow();

    globalThis.window = originalWindow;
  });

  it('does not remove non-legacy keys', () => {
    localStorage.setItem('some.other.app.key', 'value');
    cleanupOldLocalStorage();
    expect(localStorage.getItem('some.other.app.key')).toBe('value');
  });
});

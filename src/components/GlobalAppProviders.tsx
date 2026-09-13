'use client';

import React, { useEffect } from 'react';
import { useSetAtom } from 'jotai';
import {
  openAlgoAvailableAtom,
  wsConnectedAtom,
  cleanupOldLocalStorage,
} from '@/store/terminalStore';
import { marketDataService } from '@/lib/nseFetch';

export function GlobalAppProviders({ children }: { children: React.ReactNode }) {
  const setWsConnected = useSetAtom(wsConnectedAtom);
  const setOpenAlgoAvailable = useSetAtom(openAlgoAvailableAtom);

  // Restore Electron disk-backed storage into localStorage on cold boot
  useEffect(() => {
    cleanupOldLocalStorage();
    if (typeof window !== 'undefined' && window.electronAPI?.getAllStoredItems) {
      window.electronAPI.getAllStoredItems().then((items) => {
        if (items && typeof items === 'object') {
          let updated = false;
          for (const [key, value] of Object.entries(items)) {
            // If localStorage is empty for this key (e.g. fresh random port origin), restore it
            if (window.localStorage.getItem(key) === null && value !== undefined) {
              window.localStorage.setItem(key, JSON.stringify(value));
              updated = true;
            }
          }
          // If we restored keys to an empty origin, trigger a storage event or state reload
          if (updated) {
            window.dispatchEvent(new Event('storage'));
          }
        }
      }).catch(() => {});
    }
  }, []);

  // Track market WebSocket connection state and eagerly connect
  useEffect(() => {
    const unsub = marketDataService.onConnectionChange((connected) =>
      setWsConnected(connected)
    );
    marketDataService.connect();
    return () => {
      unsub();
    };
  }, [setWsConnected]);

  // Check OpenAlgo health on mount
  useEffect(() => {
    fetch('/api/openalgo/health')
      .then((r) => r.json())
      .then((data: { available: boolean }) => setOpenAlgoAvailable(data.available))
      .catch(() => setOpenAlgoAvailable(false));
  }, [setOpenAlgoAvailable]);

  return <>{children}</>;
}

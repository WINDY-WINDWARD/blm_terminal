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

  // Clean up legacy localStorage keys once on mount
  useEffect(() => {
    cleanupOldLocalStorage();
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

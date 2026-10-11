'use client';

import { useSyncExternalStore } from 'react';

const emptySubscribe = () => () => {};

function getIsMacClient(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /Mac|iPod|iPhone|iPad/i.test(navigator.platform || navigator.userAgent);
}

function getIsMacServer(): boolean {
  return false;
}

export function useIsMac(): boolean {
  return useSyncExternalStore(emptySubscribe, getIsMacClient, getIsMacServer);
}

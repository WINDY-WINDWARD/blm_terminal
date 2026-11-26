'use client';

import { useSyncExternalStore } from 'react';

const emptySubscribe = () => () => {};

function getHydratedClient(): boolean {
  return true;
}

function getHydratedServer(): boolean {
  return false;
}

export function useHydrated(): boolean {
  return useSyncExternalStore(emptySubscribe, getHydratedClient, getHydratedServer);
}

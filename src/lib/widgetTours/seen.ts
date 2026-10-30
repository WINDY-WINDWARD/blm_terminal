import { useSyncExternalStore } from 'react';
import { markWidgetTourSeen } from '../api/widgetTours';

export const SEEN_STORAGE_KEY = 'terminal.widgetTours.seen.v1';
export const PENDING_STORAGE_KEY = 'terminal.widgetTours.pending.v1';
export const OWNER_STORAGE_KEY = 'terminal.widgetTours.owner.v1';
export const SEEN_CUSTOM_EVENT = 'blm-widget-tour-seen';

const AUTH_STORAGE_KEY = 'terminal.auth';

const EMPTY_SEEN: Record<string, number> = Object.freeze({});

let cachedSnapshot: Record<string, number> = EMPTY_SEEN;
let isCacheInitialized = false;

const listeners = new Set<() => void>();

function notifySubscribers(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      // ignore listener error
    }
  }
}

function parseJsonSafe<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function currentUserId(): string {
  const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
  const parsed = parseJsonSafe<{ user?: { id?: number | string } }>(raw, {});
  const id = parsed.user?.id;
  return id === undefined || id === null ? 'anon' : String(id);
}

/**
 * The local cache is shared by every account that signs in on this machine.
 * When the signed-in user changes, drop the cached marks so the next user does
 * not inherit another user's completed tours.
 */
function ensureCacheOwner(): void {
  const owner = currentUserId();
  let stored: string | null = null;
  try {
    stored = window.localStorage.getItem(OWNER_STORAGE_KEY);
  } catch {
    return;
  }
  if (stored === null) {
    try {
      window.localStorage.setItem(OWNER_STORAGE_KEY, owner);
    } catch {
      // storage failed
    }
    return;
  }
  if (stored === owner) return;

  try {
    window.localStorage.removeItem(SEEN_STORAGE_KEY);
    window.localStorage.removeItem(PENDING_STORAGE_KEY);
    window.localStorage.setItem(OWNER_STORAGE_KEY, owner);
  } catch {
    // storage failed
  }
  cachedSnapshot = EMPTY_SEEN;
  isCacheInitialized = false;
}

export function readSeen(): Record<string, number> {
  if (typeof window === 'undefined') {
    return EMPTY_SEEN;
  }
  ensureCacheOwner();
  const raw = window.localStorage.getItem(SEEN_STORAGE_KEY);
  return parseJsonSafe<Record<string, number>>(raw, {});
}

function readPending(): string[] {
  if (typeof window === 'undefined') {
    return [];
  }
  ensureCacheOwner();
  const raw = window.localStorage.getItem(PENDING_STORAGE_KEY);
  return parseJsonSafe<string[]>(raw, []);
}

function writePending(pending: string[]): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify(pending));
  } catch {
    // quota exceeded or storage disabled
  }
}

function updateSnapshot(newSeen: Record<string, number>): void {
  cachedSnapshot = Object.freeze({ ...newSeen });
  isCacheInitialized = true;
}

function refreshSnapshotFromStorage(): void {
  const seen = readSeen();
  updateSnapshot(seen);
}

export function isSeen(command: string): boolean {
  const cmd = command.toUpperCase();
  const seen = readSeen();
  return Boolean(seen[cmd]);
}

export function markSeenLocal(command: string): void {
  const cmd = command.toUpperCase();
  const current = readSeen();
  const updated = { ...current, [cmd]: Date.now() };

  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(updated));
    } catch {
      // storage failed
    }

    const pending = readPending();
    if (!pending.includes(cmd)) {
      pending.push(cmd);
      writePending(pending);
    }
  }

  updateSnapshot(updated);
  notifySubscribers();

  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(SEEN_CUSTOM_EVENT, { detail: { command: cmd } }));
  }
}

export function hydrateSeen(remote: Record<string, number>): void {
  const current = readSeen();
  let changed = false;
  const merged: Record<string, number> = { ...current };

  for (const [key, value] of Object.entries(remote)) {
    const cmd = key.toUpperCase();
    if (typeof value === 'number') {
      const existing = merged[cmd];
      if (existing === undefined || value > existing) {
        merged[cmd] = value;
        changed = true;
      }
    }
  }

  if (changed && typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(SEEN_STORAGE_KEY, JSON.stringify(merged));
    } catch {
      // storage failed
    }
  }

  updateSnapshot(merged);
  if (changed) {
    notifySubscribers();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(SEEN_CUSTOM_EVENT));
    }
  }
}

let isFlushing = false;

export async function flushPending(): Promise<void> {
  if (typeof window === 'undefined' || isFlushing) {
    return;
  }
  isFlushing = true;
  try {
    const pending = readPending();
    if (pending.length === 0) return;

    const remaining: string[] = [];
    for (const cmd of pending) {
      try {
        await markWidgetTourSeen(cmd);
      } catch {
        // Keep entries on failure
        remaining.push(cmd);
      }
    }
    writePending(remaining);
  } finally {
    isFlushing = false;
  }
}

export function subscribeSeen(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSeenSnapshot(): Record<string, number> {
  if (!isCacheInitialized) {
    refreshSnapshotFromStorage();
  }
  return cachedSnapshot;
}

function getServerSeenSnapshot(): Record<string, number> {
  return EMPTY_SEEN;
}

export function useWidgetTourSeen(): Record<string, number> {
  return useSyncExternalStore(subscribeSeen, getSeenSnapshot, getServerSeenSnapshot);
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === SEEN_STORAGE_KEY) {
      refreshSnapshotFromStorage();
      notifySubscribers();
    }
  });

  window.addEventListener(SEEN_CUSTOM_EVENT, () => {
    refreshSnapshotFromStorage();
    notifySubscribers();
  });
}

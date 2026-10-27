'use client';

import { useSyncExternalStore } from 'react';

// Single source of truth for update state in the renderer.
//
// The main process owns the state (electron/updater.js) and broadcasts it. Two
// components used to subscribe independently and keep private copies, so they
// could disagree — and a remount silently stacked another listener. Here the
// state is hydrated once from `get-updater-state`, then kept current by the
// broadcast channel, and every consumer reads the same snapshot.

export type UpdaterPhase =
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'downloaded'
  | 'not-available'
  | 'error';

export interface UpdaterState {
  phase: UpdaterPhase;
  version: string | null;
  percent: number;
  error: string | null;
  checkedAt: number | null;
  installerPath: string | null;
  verified: boolean;
  /** Can this build verify a downloaded installer at all? */
  verification: 'unknown' | 'ok' | 'unavailable';
  /** A previous update was staged but never applied. */
  pendingInstall: { version: string; at: number | null } | null;
  canInstall: boolean;
  /** Who asked for the last check: background checks stay quiet when they fail. */
  trigger: 'auto' | 'manual';
  updatedAt: number;
}

const INITIAL: UpdaterState = {
  phase: 'idle',
  version: null,
  percent: 0,
  error: null,
  checkedAt: null,
  installerPath: null,
  verified: false,
  verification: 'unknown',
  pendingInstall: null,
  canInstall: false,
  trigger: 'auto',
  updatedAt: 0,
};

let snapshot: UpdaterState = INITIAL;
let started = false;
let broadcastSeq = 0;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function sameState(a: UpdaterState, b: UpdaterState) {
  return (
    a.phase === b.phase
    && a.version === b.version
    && a.percent === b.percent
    && a.error === b.error
    && a.checkedAt === b.checkedAt
    && a.installerPath === b.installerPath
    && a.verified === b.verified
    && a.verification === b.verification
    && a.canInstall === b.canInstall
    && a.trigger === b.trigger
    && a.pendingInstall?.version === b.pendingInstall?.version
  );
}

/** Merge an authoritative state fragment from main. */
export function applyUpdaterState(patch: Partial<UpdaterState> | null | undefined) {
  if (!patch || typeof patch !== 'object') return;
  const next = { ...snapshot, ...patch, updatedAt: Date.now() };
  if (sameState(snapshot, next)) return;
  snapshot = next;
  emit();
}

function start() {
  if (started) return;
  if (typeof window === 'undefined' || !window.electronAPI) return;
  started = true;

  // Hydrate: the state survives renderer reloads and app restarts, so a modal
  // that mounts late still knows an update is staged. The request is async, so
  // a broadcast can land first — in that case the snapshot is newer than the
  // reply and must not be overwritten by it (that race would reset a live
  // download back to idle).
  const hydrateSeq = broadcastSeq;
  void window.electronAPI
    .getUpdaterState?.()
    .then((state) => {
      if (broadcastSeq === hydrateSeq) applyUpdaterState(state as Partial<UpdaterState>);
    })
    .catch(() => {});

  window.electronAPI.onUpdaterMessage?.((message) => {
    const data = message?.data as Partial<UpdaterState> | undefined;
    if (data && typeof data === 'object' && 'phase' in data) {
      broadcastSeq += 1;
      applyUpdaterState(data);
      return;
    }
    // Defensive: tolerate the pre-controller payload shape ({status, data}).
    if (message?.status) {
      broadcastSeq += 1;
      applyUpdaterState({ phase: message.status as UpdaterPhase });
    }
  });
}

function subscribe(listener: () => void) {
  start();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot() {
  return snapshot;
}

export function useUpdaterState(): UpdaterState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Non-reactive read, for retry flows that need the phase right after an await. */
export function getUpdaterStateSnapshot(): UpdaterState {
  return snapshot;
}

// ── actions ────────────────────────────────────────────────────────────────

function describeError(err: unknown) {
  const raw = err instanceof Error ? err.message : String(err);
  // ipcRenderer.invoke prefixes rejections with "Error invoking remote method".
  return raw.replace(/^Error invoking remote method '[^']+':\s*/, '').replace(/^Error:\s*/, '');
}

export async function checkForUpdates() {
  if (typeof window === 'undefined' || !window.electronAPI) return;
  try {
    const state = await window.electronAPI.checkForUpdates();
    if (state && typeof state === 'object') applyUpdaterState(state as Partial<UpdaterState>);
  } catch (err) {
    // Main already recorded the failure; mirror it so the UI never stays idle.
    if (snapshot.phase !== 'error') {
      applyUpdaterState({ phase: 'error', error: describeError(err) });
    }
  }
}

export async function downloadUpdate() {
  if (typeof window === 'undefined' || !window.electronAPI) return;
  try {
    const result = await window.electronAPI.downloadUpdate();
    const state = (result as { state?: Partial<UpdaterState> } | null)?.state;
    if (state) applyUpdaterState(state);
  } catch (err) {
    if (snapshot.phase !== 'error') {
      applyUpdaterState({ phase: 'error', error: describeError(err) });
    }
  }
}

export async function installUpdate() {
  if (typeof window === 'undefined' || !window.electronAPI) return;
  try {
    await window.electronAPI.installUpdate();
  } catch (err) {
    // A launch the user asked for must never hide: force the manual trigger so
    // the dialog still shows the failure after an auto-found update.
    applyUpdaterState({ phase: 'error', error: describeError(err), trigger: 'manual' });
  }
}

export async function dismissPendingInstall() {
  if (typeof window === 'undefined' || !window.electronAPI) return;
  try {
    const state = await window.electronAPI.dismissPendingInstall?.();
    if (state && typeof state === 'object') applyUpdaterState(state as Partial<UpdaterState>);
  } catch {
    applyUpdaterState({ pendingInstall: null });
  }
}

export const RELEASES_PAGE_URL = 'https://github.com/WINDY-WINDWARD/blm_terminal/releases';

/** Test-only: drop module state so each case starts from a clean snapshot. */
export function resetUpdaterStoreForTests() {
  snapshot = INITIAL;
  started = false;
  broadcastSeq = 0;
  listeners.clear();
}

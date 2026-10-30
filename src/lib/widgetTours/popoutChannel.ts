'use client';

import { useEffect, useRef } from 'react';
import { requestWidgetTour } from '@/components/widgetTour/WidgetTourController';

export const POPOUT_REQUEST_KEY = '__blm_widget_tour_request';
export const POPOUT_ACK_KEY = '__blm_widget_tour_ack';
export const POPOUT_PRESENCE_KEY = '__blm_widget_tour_windows';

const PRESENCE_TTL_MS = 12 * 60 * 60 * 1000;
const ACK_TIMEOUT_MS = 700;

interface TourRequestMessage {
  id: string;
  command: string;
  /** Instance id of the single popout that must answer. */
  target: string;
}

interface TourAckMessage {
  id: string;
  command: string;
}

interface PopoutPresenceEntry {
  panelId: string;
  command: string;
  ts: number;
}

function getSafeLocalStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function parsePresence(raw: string | null): Record<string, PopoutPresenceEntry> {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return {};
    const clean: Record<string, PopoutPresenceEntry> = {};
    for (const [key, entry] of Object.entries(parsed)) {
      if (
        isRecord(entry) &&
        typeof entry.command === 'string' &&
        typeof entry.panelId === 'string' &&
        typeof entry.ts === 'number'
      ) {
        clean[key] = { command: entry.command, panelId: entry.panelId, ts: entry.ts };
      }
    }
    return clean;
  } catch {
    return {};
  }
}

function parseRequest(raw: string | null): TourRequestMessage | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return null;
    if (typeof parsed.id !== 'string' || typeof parsed.command !== 'string') return null;
    return { id: parsed.id, command: parsed.command, target: String(parsed.target ?? '') };
  } catch {
    return null;
  }
}

function parseAck(raw: string | null): TourAckMessage | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) return null;
    if (typeof parsed.id !== 'string' || typeof parsed.command !== 'string') return null;
    return { id: parsed.id, command: parsed.command };
  } catch {
    return null;
  }
}

/** Newest live popout instance for this widget, or null when none is registered. */
export function findPopoutTarget(command: string, storage: Storage): string | null {
  const presence = parsePresence(storage.getItem(POPOUT_PRESENCE_KEY));
  const cutoff = Date.now() - PRESENCE_TTL_MS;
  let best: string | null = null;
  let bestTs = -Infinity;
  for (const [instanceId, entry] of Object.entries(presence)) {
    if (entry.command !== command || entry.ts < cutoff) continue;
    if (entry.ts > bestTs) {
      best = instanceId;
      bestTs = entry.ts;
    }
  }
  return best;
}

/**
 * Runs the tour in a currently open popout of this widget.
 * Resolves false when no popout is registered or none acknowledges in time.
 */
export function requestPopoutTour(command: string): Promise<boolean> {
  const storage = getSafeLocalStorage();
  if (!storage || typeof window === 'undefined') {
    return Promise.resolve(false);
  }

  const target = findPopoutTarget(command, storage);
  // No popout of this widget is registered, so do not pay the ack timeout.
  if (!target) {
    return Promise.resolve(false);
  }

  return new Promise<boolean>((resolve) => {
    const id = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

    const cleanup = () => {
      clearTimeout(timer);
      window.removeEventListener('storage', handleStorage);
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== POPOUT_ACK_KEY) return;
      const ack = parseAck(event.newValue);
      if (ack && ack.id === id && ack.command === command) {
        cleanup();
        resolve(true);
      }
    };

    window.addEventListener('storage', handleStorage);

    const timer = setTimeout(() => {
      cleanup();
      resolve(false);
    }, ACK_TIMEOUT_MS);

    const payload: TourRequestMessage = { id, command, target };
    try {
      storage.setItem(POPOUT_REQUEST_KEY, JSON.stringify(payload));
    } catch {
      cleanup();
      resolve(false);
    }
  });
}

/**
 * Handles a raw request payload inside a popout. Returns true when this instance
 * accepted the request and started its tour.
 */
export function respondToPopoutRequest(
  storage: Storage,
  instanceId: string,
  panelId: string,
  command: string,
  raw: string | null,
): boolean {
  const request = parseRequest(raw);
  if (!request || request.command !== command) return false;
  // A missing target means a legacy payload. Ignore it rather than start in every popout.
  if (request.target !== instanceId) return false;

  requestWidgetTour({ panelId, command, mode: 'replay' });

  const ack: TourAckMessage = { id: request.id, command: request.command };
  try {
    storage.setItem(POPOUT_ACK_KEY, JSON.stringify(ack));
  } catch {
    // The tour already started. A missing ack only makes DOCS show its hint.
  }

  return true;
}

/** Registers this popout as a tour target and answers replay requests. */
export function usePopoutTourResponder(panelId: string, command: string): void {
  const instanceIdRef = useRef<string | null>(null);
  if (instanceIdRef.current === null) {
    instanceIdRef.current = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
  }
  const instanceId = instanceIdRef.current;

  useEffect(() => {
    const storage = getSafeLocalStorage();
    if (!storage) return;

    try {
      const presence = parsePresence(storage.getItem(POPOUT_PRESENCE_KEY));
      presence[instanceId] = { panelId, command, ts: Date.now() };
      storage.setItem(POPOUT_PRESENCE_KEY, JSON.stringify(presence));
    } catch {
      // Presence is an optimisation. Without it DOCS simply falls back to its hint.
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== POPOUT_REQUEST_KEY) return;
      respondToPopoutRequest(storage, instanceId, panelId, command, event.newValue);
    };

    window.addEventListener('storage', handleStorage);

    return () => {
      window.removeEventListener('storage', handleStorage);

      try {
        const presence = parsePresence(storage.getItem(POPOUT_PRESENCE_KEY));
        delete presence[instanceId];
        storage.setItem(POPOUT_PRESENCE_KEY, JSON.stringify(presence));
      } catch {
        // Ignore presence cleanup failure.
      }
    };
  }, [panelId, command, instanceId]);
}

'use client';

import { useEffect } from 'react';
import { requestWidgetTour } from '@/components/widgetTour/WidgetTourController';

export const POPOUT_REQUEST_KEY = '__blm_widget_tour_request';
export const POPOUT_ACK_KEY = '__blm_widget_tour_ack';
export const POPOUT_PRESENCE_KEY = '__blm_widget_tour_windows';

interface TourRequestMessage {
  id: string;
  command: string;
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

/** Any popout of this widget alive in the last 12 hours. */
function hasPopoutFor(command: string, storage: Storage): boolean {
  try {
    const raw = storage.getItem(POPOUT_PRESENCE_KEY);
    if (!raw) return false;
    const presence = JSON.parse(raw) as Record<string, PopoutPresenceEntry>;
    const cutoff = Date.now() - 12 * 60 * 60 * 1000;
    return Object.values(presence).some(
      (entry) => entry.command === command && entry.ts >= cutoff,
    );
  } catch {
    return false;
  }
}

export function requestPopoutTour(command: string): Promise<boolean> {
  const storage = getSafeLocalStorage();
  if (!storage || typeof window === 'undefined') {
    return Promise.resolve(false);
  }

  // No popout of this widget is registered, so do not pay the ack timeout.
  if (!hasPopoutFor(command, storage)) {
    return Promise.resolve(false);
  }

  return new Promise<boolean>((resolve) => {
    const id = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const cleanup = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      window.removeEventListener('storage', handleStorage);
    };

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== POPOUT_ACK_KEY || !event.newValue) return;
      try {
        const parsed = JSON.parse(event.newValue) as TourAckMessage;
        if (parsed.id === id && parsed.command === command) {
          cleanup();
          resolve(true);
        }
      } catch {
        // Ignore parse error
      }
    };

    window.addEventListener('storage', handleStorage);

    timer = setTimeout(() => {
      cleanup();
      resolve(false);
    }, 700);

    const payload: TourRequestMessage = { id, command };
    try {
      storage.setItem(POPOUT_REQUEST_KEY, JSON.stringify(payload));
    } catch {
      cleanup();
      resolve(false);
    }
  });
}

export function usePopoutTourResponder(panelId: string, command: string): void {
  useEffect(() => {
    const storage = getSafeLocalStorage();
    if (!storage || typeof window === 'undefined') return;

    const registrationKey = `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;

    // Register presence
    try {
      const rawPresence = storage.getItem(POPOUT_PRESENCE_KEY);
      const presenceMap: Record<string, PopoutPresenceEntry> = rawPresence ? JSON.parse(rawPresence) : {};
      presenceMap[registrationKey] = {
        panelId,
        command,
        ts: Date.now(),
      };
      storage.setItem(POPOUT_PRESENCE_KEY, JSON.stringify(presenceMap));
    } catch {
      // Ignore presence write failure
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key !== POPOUT_REQUEST_KEY || !event.newValue) return;
      try {
        const parsed = JSON.parse(event.newValue) as TourRequestMessage;
        if (parsed.command === command) {
          requestWidgetTour({ panelId, command, mode: 'replay' });
          const ack: TourAckMessage = { id: parsed.id, command: parsed.command };
          storage.setItem(POPOUT_ACK_KEY, JSON.stringify(ack));
        }
      } catch {
        // Ignore parse error
      }
    };

    window.addEventListener('storage', handleStorage);

    return () => {
      window.removeEventListener('storage', handleStorage);

      // Cleanup presence entry
      try {
        const rawPresence = storage.getItem(POPOUT_PRESENCE_KEY);
        if (rawPresence) {
          const presenceMap: Record<string, PopoutPresenceEntry> = JSON.parse(rawPresence);
          delete presenceMap[registrationKey];
          storage.setItem(POPOUT_PRESENCE_KEY, JSON.stringify(presenceMap));
        }
      } catch {
        // Ignore presence cleanup failure
      }
    };
  }, [panelId, command]);
}

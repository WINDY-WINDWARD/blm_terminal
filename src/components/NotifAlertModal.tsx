'use client';

import { useEffect, useRef } from 'react';
import { useAtom, useAtomValue } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import ReactDOM from 'react-dom';
import {
  activeCommandAtom,
  activeWatchlistIdAtom,
  seenNotifIdsAtom,
  notifAlertVisibleAtom,
  notifAlertCountAtom,
  notifPanelHighlightAtom,
} from '@/store/terminalStore';

const SOUND_URL = '/sound/universfield-new-notification-051-494246.mp3';
const POLL_INTERVAL = 30_000;
const AUTO_DISMISS_MS = 8_000;
const MAX_SEEN_IDS = 1000;

interface Notification {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
  trigger_type: string;
  message: string;
  triggered_at: string;
  triggered_date: string;
  is_read: boolean;
}

export function NotifAlertModal() {
  const activeWatchlistId = useAtomValue(activeWatchlistIdAtom);
  const [seenIds, setSeenIds] = useAtom(seenNotifIdsAtom);
  const [visible, setVisible] = useAtom(notifAlertVisibleAtom);
  const [alertCount, setAlertCount] = useAtom(notifAlertCountAtom);
  const setActiveCommand = useAtom(activeCommandAtom)[1];
  const setNotifHighlight = useAtom(notifPanelHighlightAtom)[1];

  const initialLoadRef = useRef(true);
  const progressRef = useRef(100);

  const { data } = useQuery<Notification[]>({
    queryKey: ['notif-alert-modal', activeWatchlistId],
    queryFn: async () => {
      const res = await fetch(
        `/api/py/notifications?watchlist_id=${activeWatchlistId}&days=1&read_filter=unread`,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: POLL_INTERVAL,
    refetchIntervalInBackground: true,
  });

  useEffect(() => {
    if (!data || data.length === 0) return;

    const currentIds = data.map((n) => n.id);

    // Compute newIds and update seenIds atomically inside the updater so we
    // never read `seenIds` directly in this effect. This avoids adding seenIds
    // to the dependency array, which would cause a double-execution on every
    // poll cycle and could suppress the first real alert after a page reload
    // (if seenIds was already populated from localStorage and the first data
    // batch happened to contain only known IDs, initialLoadRef would never
    // flip and the next real new notification would be silently skipped).
    let newIds: number[] = [];
    setSeenIds((prev) => {
      const seenSet = new Set(prev);
      newIds = currentIds.filter((id) => !seenSet.has(id));
      if (newIds.length === 0) return prev;
      const updated = [...prev, ...newIds];
      return updated.length > MAX_SEEN_IDS
        ? updated.slice(updated.length - MAX_SEEN_IDS)
        : updated;
    });

    // newIds is populated synchronously by the updater above before this line.
    if (newIds.length === 0) return;

    if (initialLoadRef.current) {
      initialLoadRef.current = false;
      return;
    }

    const audio = new Audio(SOUND_URL);
    audio.play().catch(() => {});

    setAlertCount(newIds.length);
    setVisible(true);
    progressRef.current = 100;
  }, [data, setSeenIds, setAlertCount, setVisible]);

  useEffect(() => {
    if (!visible) return;

    progressRef.current = 100;
    const startTime = Date.now();

    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      const remaining = Math.max(0, 100 - (elapsed / AUTO_DISMISS_MS) * 100);
      progressRef.current = remaining;
      const bar = document.getElementById('notif-alert-progress');
      if (bar) bar.style.width = `${remaining}%`;
    }, 50);

    const timeout = setTimeout(() => {
      setVisible(false);
    }, AUTO_DISMISS_MS);

    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [visible, alertCount, setVisible]);

  const handleDismiss = () => {
    setVisible(false);
  };

  const handleClick = () => {
    setActiveCommand('NOTIF');
    setNotifHighlight(Date.now());
    setVisible(false);
  };

  if (!visible) return null;

  return ReactDOM.createPortal(
    <div className="fixed inset-0 z-[9999] pointer-events-none">
      <div className="absolute top-4 right-4 sm:right-6 pointer-events-auto max-w-sm w-full">
        <div
          onClick={handleClick}
          className="bg-zinc-900 border-2 border-terminal-amber/80 rounded-lg shadow-2xl cursor-pointer hover:border-terminal-amber transition-colors overflow-hidden"
        >
          <div className="px-4 py-3 flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-terminal-amber flex items-center justify-center text-black font-bold text-sm shrink-0">
              {alertCount}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-terminal-amber font-bold text-xs uppercase">
                New Alert{alertCount > 1 ? 's' : ''}
              </div>
              <div className="text-white/80 text-[11px] mt-0.5">
                {alertCount === 1
                  ? '1 new notification triggered'
                  : `${alertCount} new notifications triggered`}
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleDismiss();
              }}
              className="text-white/40 hover:text-white text-lg leading-none shrink-0"
            >
              ×
            </button>
          </div>
          <div className="h-0.5 bg-zinc-800">
            <div
              id="notif-alert-progress"
              className="h-full bg-terminal-amber transition-none"
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

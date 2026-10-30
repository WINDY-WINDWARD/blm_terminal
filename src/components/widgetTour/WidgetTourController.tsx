'use client';

import { useEffect, useRef, useState } from 'react';
import { useAtom, useAtomValue } from 'jotai';
import { getDefaultStore } from 'jotai';
import { useQuery } from '@tanstack/react-query';
import { fetchWidgetTours } from '@/lib/api/widgetTours';
import { flushPending, hydrateSeen, isSeen, markSeenLocal } from '@/lib/widgetTours/seen';
import { WIDGET_TOURS, getWidgetTour } from '@/lib/widgetTours';
import type { WidgetTourRequest } from '@/lib/widgetTours/types';
import {
  activePanelsAtom,
  activeWidgetTourAtom,
  onboardingCompletedAtom,
  panelCountAtom,
  tutorialStatusAtom,
  widgetTourQueueAtom,
} from '@/store/terminalStore';

export interface WidgetTourControllerProps {
  surface: 'grid' | 'popout';
  panelId?: string;
  command?: string;
}

export function requestWidgetTour(request: WidgetTourRequest): void {
  const store = getDefaultStore();
  store.set(activeWidgetTourAtom, null);
  store.set(widgetTourQueueAtom, (queue) => [
    request,
    ...queue.filter((q) => !(q.panelId === request.panelId && q.command === request.command)),
  ]);
}

export function WidgetTourController({
  surface,
  panelId,
  command,
}: WidgetTourControllerProps) {
  const onboardingCompleted = useAtomValue(onboardingCompletedAtom);
  const tutorialStatus = useAtomValue(tutorialStatusAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  const panelCount = useAtomValue(panelCountAtom);

  const [queue, setQueue] = useAtom(widgetTourQueueAtom);
  const [activeTour, setActiveTour] = useAtom(activeWidgetTourAtom);

  const [cooldownTick, setCooldownTick] = useState(0);
  const cooldownRef = useRef(false);

  // Hydrate seen from backend
  const { data, isFetched, isError } = useQuery({
    queryKey: ['widget-tours'],
    queryFn: fetchWidgetTours,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (data) {
      hydrateSeen(data);
      flushPending().catch(() => {});
    }
  }, [data]);

  // Flush pending on window focus
  useEffect(() => {
    const handleFocus = () => {
      flushPending().catch(() => {});
    };
    window.addEventListener('focus', handleFocus);
    return () => window.removeEventListener('focus', handleFocus);
  }, []);

  // Grid panel diffing and initial load
  const hasInitializedGridRef = useRef(false);
  const prevPanelsRef = useRef<Record<string, string>>({});

  useEffect(() => {
    if (surface !== 'grid') return;

    const visibleKeys = Array.from({ length: panelCount }, (_, i) => `panel-${i + 1}`);
    const newItems: WidgetTourRequest[] = [];

    if (!hasInitializedGridRef.current) {
      hasInitializedGridRef.current = true;
      for (const key of visibleKeys) {
        const cmd = activePanels[key];
        if (cmd && cmd !== 'EMPTY' && WIDGET_TOURS[cmd.toUpperCase()]) {
          const upper = cmd.toUpperCase();
          if (!isSeen(upper)) {
            const alreadyInQueue = queue.some((q) => q.command === upper && q.panelId === key);
            const isCurrentlyActive = activeTour?.command === upper && activeTour?.panelId === key;
            if (!alreadyInQueue && !isCurrentlyActive) {
              newItems.push({ panelId: key, command: upper, mode: 'auto' });
            }
          }
        }
      }
    } else {
      for (const key of visibleKeys) {
        const cmd = activePanels[key];
        const prevCmd = prevPanelsRef.current[key];
        if (cmd && cmd !== prevCmd && cmd !== 'EMPTY' && WIDGET_TOURS[cmd.toUpperCase()]) {
          const upper = cmd.toUpperCase();
          if (!isSeen(upper)) {
            const alreadyInQueue = queue.some((q) => q.command === upper && q.panelId === key);
            const isCurrentlyActive = activeTour?.command === upper && activeTour?.panelId === key;
            if (!alreadyInQueue && !isCurrentlyActive) {
              newItems.push({ panelId: key, command: upper, mode: 'auto' });
            }
          }
        }
      }
    }

    prevPanelsRef.current = { ...activePanels };

    if (
      activeTour &&
      (activePanels[activeTour.panelId] ?? '').toUpperCase() !== activeTour.command
    ) {
      setActiveTour(null);
    }

    const isQueuedForThisPanel = (request: WidgetTourRequest) =>
      request.mode === 'replay' ||
      (activePanels[request.panelId] ?? '').toUpperCase() === request.command;
    const staleCount = queue.filter((request) => !isQueuedForThisPanel(request)).length;

    if (newItems.length > 0 || staleCount > 0) {
      setQueue((current) => [
        ...current.filter(isQueuedForThisPanel),
        ...newItems,
      ]);
    }
  }, [surface, panelCount, activePanels, queue, activeTour, setQueue, setActiveTour]);

  // Popout initial enqueue
  const hasEnqueuedPopoutRef = useRef(false);
  useEffect(() => {
    if (surface !== 'popout' || !panelId || !command || hasEnqueuedPopoutRef.current) return;
    const upper = command.toUpperCase();
    if (upper !== 'EMPTY' && WIDGET_TOURS[upper] && !isSeen(upper)) {
      const alreadyInQueue = queue.some((q) => q.command === upper && q.panelId === panelId);
      const isCurrentlyActive = activeTour?.command === upper && activeTour?.panelId === panelId;
      if (!alreadyInQueue && !isCurrentlyActive) {
        hasEnqueuedPopoutRef.current = true;
        setQueue((q) => [...q, { panelId, command: upper, mode: 'auto' }]);
      }
    }
  }, [surface, panelId, command, queue, activeTour, setQueue]);

  const isGatesPassing = (isFetched || isError) && onboardingCompleted && tutorialStatus !== 'active';

  // 250ms cooldown when active tour transitions to null
  const prevActiveRef = useRef<WidgetTourRequest | null>(null);
  useEffect(() => {
    if (prevActiveRef.current !== null && activeTour === null) {
      cooldownRef.current = true;
      const timer = setTimeout(() => {
        cooldownRef.current = false;
        setCooldownTick((t) => t + 1);
      }, 250);
      return () => clearTimeout(timer);
    }
    prevActiveRef.current = activeTour;
  }, [activeTour]);

  // Auto-finish active tour if it has no steps
  useEffect(() => {
    if (!activeTour) return;
    const def = getWidgetTour(activeTour.command);
    if (!def || def.steps.length === 0) {
      const timer = setTimeout(() => {
        setActiveTour(null);
      }, 250);
      return () => clearTimeout(timer);
    }
  }, [activeTour, setActiveTour]);

  // Start next tour from queue
  useEffect(() => {
    if (!isGatesPassing || activeTour !== null || queue.length === 0 || cooldownRef.current) {
      return;
    }

    const eligible = queue.filter(
      (request) => request.mode === 'replay' || !isSeen(request.command),
    );
    if (eligible.length !== queue.length) {
      setQueue(eligible);
      return;
    }

    const nextRequest = eligible[0];
    const remaining = eligible.slice(1);
    setQueue(remaining);
    setActiveTour(nextRequest);

    if (nextRequest.mode === 'auto') {
      markSeenLocal(nextRequest.command);
      flushPending().catch(() => {
        // keep local seen state even if network fails
      });
    }
  }, [isGatesPassing, activeTour, queue, cooldownTick, setActiveTour, setQueue]);

  return null;
}

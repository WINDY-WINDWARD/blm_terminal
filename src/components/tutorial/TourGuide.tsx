'use client';

import { useEffect, useRef } from 'react';
import { useAtom, useAtomValue, useSetAtom } from 'jotai';
import { driver, type Driver } from 'driver.js';
import {
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
  mergedGroupsAtom,
  panelCountAtom,
  selectedPanelsAtom,
  tutorialStatusAtom,
} from '@/store/terminalStore';
import { buildTutorialSteps } from '@/lib/tutorialSteps';

export function TourGuide() {
  const [status, setStatus] = useAtom(tutorialStatusAtom);
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const setActiveCmd = useSetAtom(activeCommandAtom);
  const driverRef = useRef<Driver | null>(null);
  const startedRef = useRef(false);

  // Monitor terminal state to auto-advance when user performs interactive actions
  const focusedPanel = useAtomValue(focusedPanelAtom);
  const selectedPanels = useAtomValue(selectedPanelsAtom);
  const mergedGroups = useAtomValue(mergedGroupsAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  const panelCount = useAtomValue(panelCountAtom);

  const currentActionRef = useRef<string | null>(null);
  const initialFocusedRef = useRef(focusedPanel);
  const initialWidgetsRef = useRef(activePanels);
  const initialPanelCountRef = useRef(panelCount);

  // TOUR command entry point (TerminalContainer clears unknown commands, so
  // consume it here and launch the tour instead of a widget).
  useEffect(() => {
    if (activeCommand === 'TOUR') {
      setActiveCmd('');
      setStatus('active');
    }
  }, [activeCommand, setActiveCmd, setStatus]);

  // Auto-advance listeners for interactive tour steps
  useEffect(() => {
    if (currentActionRef.current === 'focus' && focusedPanel !== initialFocusedRef.current) {
      currentActionRef.current = null;
      driverRef.current?.moveNext();
    }
  }, [focusedPanel]);

  useEffect(() => {
    if (currentActionRef.current === 'widget') {
      const changed = Object.keys(activePanels).some(
        (id) => activePanels[id] !== initialWidgetsRef.current[id],
      );
      if (changed) {
        currentActionRef.current = null;
        driverRef.current?.moveNext();
      }
    }
  }, [activePanels]);

  useEffect(() => {
    if (currentActionRef.current === 'select' && selectedPanels.length >= 2) {
      currentActionRef.current = null;
      driverRef.current?.moveNext();
    }
  }, [selectedPanels]);

  useEffect(() => {
    if (currentActionRef.current === 'merge' && Object.keys(mergedGroups).length > 0) {
      currentActionRef.current = null;
      driverRef.current?.moveNext();
    }
  }, [mergedGroups]);

  useEffect(() => {
    if (currentActionRef.current === 'unmerge' && Object.keys(mergedGroups).length === 0) {
      currentActionRef.current = null;
      driverRef.current?.moveNext();
    }
  }, [mergedGroups]);

  useEffect(() => {
    if (currentActionRef.current === 'layout' && panelCount !== initialPanelCountRef.current) {
      currentActionRef.current = null;
      driverRef.current?.moveNext();
    }
  }, [panelCount]);

  useEffect(() => {
    if (status !== 'active' || startedRef.current) return;
    startedRef.current = true;

    const onActionStepHighlight = (actionType: string | null) => {
      currentActionRef.current = actionType;
      initialFocusedRef.current = focusedPanel;
      initialWidgetsRef.current = { ...activePanels };
      initialPanelCountRef.current = panelCount;
    };

    const { steps } = buildTutorialSteps(undefined, onActionStepHighlight);
    const d = driver({
      showProgress: true,
      allowClose: false,
      overlayColor: '#000',
      overlayOpacity: 0.7,
      stagePadding: 6,
      stageRadius: 4,
      skipMissingElement: true,
      disableActiveInteraction: false,
      popoverClass: 'blm-tour-popover',
      nextBtnText: 'Next / Skip',
      prevBtnText: 'Back',
      doneBtnText: 'Finish tour',
      progressText: '{{current}} of {{total}}',
      onDestroyed: () => {
        driverRef.current = null;
        startedRef.current = false;
        currentActionRef.current = null;
        setStatus('done');
      },
      steps,
    });
    driverRef.current = d;
    // Let the post-onboarding layout settle before measuring targets.
    const t = setTimeout(() => d.drive(), 400);
    return () => {
      clearTimeout(t);
    };
  }, [status, setStatus, focusedPanel, activePanels, panelCount]);

  useEffect(
    () => () => {
      driverRef.current?.destroy();
      driverRef.current = null;
    },
    [],
  );

  return null;
}

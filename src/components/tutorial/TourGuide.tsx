'use client';

import { useEffect, useRef } from 'react';
import { useAtom, useSetAtom } from 'jotai';
import { driver, type Driver } from 'driver.js';
import { activeCommandAtom, tutorialStatusAtom } from '@/store/terminalStore';
import { buildTutorialSteps } from '@/lib/tutorialSteps';

export function TourGuide() {
  const [status, setStatus] = useAtom(tutorialStatusAtom);
  const [activeCommand, setActiveCommand] = useAtom(activeCommandAtom);
  const setActiveCmd = useSetAtom(activeCommandAtom);
  const driverRef = useRef<Driver | null>(null);
  const startedRef = useRef(false);

  // TOUR command entry point (TerminalContainer clears unknown commands, so
  // consume it here and launch the tour instead of a widget).
  useEffect(() => {
    if (activeCommand === 'TOUR') {
      setActiveCmd('');
      setStatus('active');
    }
  }, [activeCommand, setActiveCmd, setStatus]);

  useEffect(() => {
    if (status !== 'active' || startedRef.current) return;
    startedRef.current = true;
    const { steps } = buildTutorialSteps();
    const d = driver({
      showProgress: true,
      allowClose: true,
      overlayColor: '#000',
      overlayOpacity: 0.7,
      stagePadding: 4,
      stageRadius: 4,
      skipMissingElement: true,
      popoverClass: 'blm-tour-popover',
      nextBtnText: 'Next',
      prevBtnText: 'Back',
      doneBtnText: 'Finish tour',
      progressText: '{{current}} of {{total}}',
      onDestroyed: () => {
        driverRef.current = null;
        startedRef.current = false;
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
  }, [status, setStatus]);

  useEffect(
    () => () => {
      driverRef.current?.destroy();
      driverRef.current = null;
    },
    [],
  );

  return null;
}

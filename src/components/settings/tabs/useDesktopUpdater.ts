'use client';

import { useCallback } from 'react';
import {
  checkForUpdates,
  installUpdate,
  useUpdaterState,
} from '@/lib/updaterStore';

// Settings used to keep a second, private copy of the updater status that
// could disagree with UpdateModal. It now reads the shared store and only
// exposes the shape the settings panel already renders.
export function useDesktopUpdater() {
  const { phase, percent, canInstall, verification, pendingInstall } = useUpdaterState();

  const handleCheckForUpdates = useCallback(() => {
    void checkForUpdates();
  }, []);

  const handleInstallUpdate = useCallback(() => {
    void installUpdate();
  }, []);

  return {
    updaterStatus: phase,
    updaterProgress: { percent },
    updateReady: canInstall,
    verification,
    pendingInstall,
    handleCheckForUpdates,
    handleInstallUpdate,
  };
}

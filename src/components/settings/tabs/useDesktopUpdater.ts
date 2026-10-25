'use client';

import { useState, useEffect } from 'react';

export function useDesktopUpdater() {
  const [updaterStatus, setUpdaterStatus] = useState<string>('');
  const [updaterProgress, setUpdaterProgress] = useState<{ percent: number } | null>(null);
  const [updateReady, setUpdateReady] = useState(false);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.electronAPI) {
      window.electronAPI.onUpdaterMessage((msg) => {
        setUpdaterStatus(msg.status);
        if (msg.status === 'progress' && msg.data) {
          setUpdaterProgress(msg.data as { percent: number });
        } else if (msg.status === 'downloaded') {
          setUpdateReady(true);
        }
      });
    }
  }, []);

  const handleCheckForUpdates = () => {
    if (window.electronAPI) {
      setUpdaterStatus('checking');
      window.electronAPI.checkForUpdates();
    }
  };

  const handleInstallUpdate = () => {
    if (window.electronAPI) {
      window.electronAPI.installUpdate();
    }
  };

  return {
    updaterStatus,
    updaterProgress,
    updateReady,
    handleCheckForUpdates,
    handleInstallUpdate,
  };
}

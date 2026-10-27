'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  RELEASES_PAGE_URL,
  checkForUpdates,
  dismissPendingInstall,
  downloadUpdate,
  getUpdaterStateSnapshot,
  installUpdate,
  useUpdaterState,
} from '@/lib/updaterStore';

const openReleases = () => {
  if (typeof window !== 'undefined' && window.electronAPI) {
    void window.electronAPI.openExternal?.(RELEASES_PAGE_URL);
  }
};

export function UpdateModal() {
  const {
    phase, version, percent, error, verification, pendingInstall, canInstall, trigger,
  } = useUpdaterState();
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);

  // Re-surface on every phase change: installing always needs one explicit
  // click, so a modal hidden mid-download must come back when it finishes.
  useEffect(() => {
    setDismissed(false);
  }, [phase, version]);

  // The dialog never traps focus: Escape always closes it, whatever the phase.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDismissed(true);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleDownload = useCallback(async () => {
    setBusy(true);
    try {
      await downloadUpdate();
    } finally {
      setBusy(false);
    }
  }, []);

  // A failed check and a failed download need different retries, so try the
  // cheap one first and only download once main reports an update available.
  const handleRetry = useCallback(async () => {
    setBusy(true);
    try {
      await checkForUpdates();
      const { phase: nextPhase } = getUpdaterStateSnapshot();
      if (nextPhase === 'available') await downloadUpdate();
    } finally {
      setBusy(false);
    }
  }, []);

  const handleInstall = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await installUpdate();
    } finally {
      // The window is usually torn down by the installer; resetting keeps the
      // button usable when the hand-off fails instead of stranding it disabled.
      setBusy(false);
    }
  }, [busy]);

  // A background check that fails (laptop offline, portal hiccup) must not throw
  // a blocking dialog over someone who never asked to update. Only a failure the
  // user triggered, or a failure while an update was already in flight, is worth
  // interrupting them for.
  const showFailure = phase === 'error' && (trigger === 'manual' || version !== null);
  const visible = phase === 'available' || phase === 'downloading' || phase === 'downloaded' || showFailure;
  if (!visible || dismissed) return null;

  const ready = phase === 'downloaded';
  const downloading = phase === 'downloading';
  const failed = phase === 'error';
  const blocked = verification === 'unavailable';

  const headline = ready
    ? 'UPDATE READY TO INSTALL'
    : downloading
      ? 'DOWNLOADING UPDATE'
      : failed
        ? 'UPDATE FAILED'
        : 'NEW VERSION AVAILABLE';

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Application update"
        className="w-full max-w-md bg-terminal-panel border border-terminal-border shadow-2xl p-5 font-mono"
      >
        <div className="flex items-center justify-between border-b border-terminal-border pb-2 mb-3">
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full ${
                failed ? 'bg-terminal-red' : ready ? 'bg-terminal-green' : 'bg-terminal-amber animate-ping'
              }`}
            />
            <span
              className={`font-bold text-xs tracking-wider ${
                failed ? 'text-terminal-red' : ready ? 'text-terminal-green' : 'text-terminal-amber'
              }`}
            >
              {headline}
            </span>
          </div>
          <span className="text-terminal-muted text-[10px]">{version ? `v${version}` : ''}</span>
        </div>

        <div className="py-2 text-xs text-terminal-text space-y-2">
          {blocked && (
            <div className="bg-red-950/60 border border-red-500/60 p-2.5 text-red-200 text-[11px]">
              <p className="font-bold mb-1">Automatic updates are disabled in this build.</p>
              <p className="text-red-300/80">
                The update signature cannot be verified on this machine, so no update will be
                installed automatically. Please install the new version manually from the release
                page.
              </p>
            </div>
          )}

          {!blocked && pendingInstall && (
            <div className="bg-amber-950/40 border border-terminal-amber/40 p-2.5 text-amber-200 text-[11px]">
              <p className="font-bold mb-1">
                The update to v{pendingInstall.version} did not install.
              </p>
              <p className="text-amber-200/80">
                The installer never finished — a declined permission prompt or a locked file will do
                that. Download the update again, or install it manually from the release page.
              </p>
              <button
                type="button"
                onClick={() => void dismissPendingInstall()}
                className="mt-1 text-amber-300 underline underline-offset-2"
              >
                Dismiss
              </button>
            </div>
          )}

          {ready ? (
            <div className="bg-emerald-950/40 border border-emerald-500/40 p-3 text-emerald-200">
              <p className="font-bold mb-1">Update downloaded and verified.</p>
              <p className="text-[11px] text-emerald-300/80">
                Installing closes the backend, applies the new version and relaunches the app. A
                Windows permission prompt may appear.
              </p>
            </div>
          ) : failed ? (
            <div className="bg-red-950/60 border border-red-500/60 p-2.5 text-red-200 text-[11px]">
              <span className="font-bold">Error: </span>
              {error || 'The update could not be completed.'}
            </div>
          ) : (
            <p className="text-white/80">
              A new update for <span className="text-terminal-amber font-bold">BLM Terminal</span>{' '}
              is available. Update now, or keep working and do it later.
            </p>
          )}

          {downloading && (
            <div className="mt-3 space-y-1">
              <div className="flex justify-between text-[10px] text-terminal-muted">
                <span>Downloading package...</span>
                <span>{percent}%</span>
              </div>
              <div className="w-full h-1.5 bg-terminal-bg border border-terminal-border overflow-hidden">
                <div
                  className="h-full bg-terminal-amber transition-[width,background-color] duration-150"
                  style={{ width: `${percent}%` }}
                />
              </div>
              <p className="text-[10px] text-terminal-muted">
                You can hide this window — the download continues in the background.
              </p>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 mt-4 pt-3 border-t border-terminal-border">
          <button
            type="button"
            onClick={openReleases}
            className="text-[10px] text-terminal-muted hover:text-terminal-amber underline underline-offset-2"
          >
            Download manually
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setDismissed(true)}
              className="px-3 py-1.5 text-xs text-terminal-muted hover:text-white border border-terminal-border hover:border-terminal-muted transition-colors"
            >
              {ready ? 'Restart Later' : downloading ? 'Hide' : 'Remind Me Later'}
            </button>

            {ready ? (
              <button
                type="button"
                disabled={!canInstall || blocked || busy}
                onClick={handleInstall}
                className="px-4 py-1.5 text-xs font-bold bg-terminal-green text-black hover:brightness-110 transition-colors disabled:opacity-50"
              >
                Install &amp; Restart
              </button>
            ) : (
              <button
                type="button"
                disabled={downloading || busy || blocked}
                onClick={failed ? handleRetry : handleDownload}
                className="px-4 py-1.5 text-xs font-bold bg-terminal-amber text-terminal-bg hover:brightness-110 transition-colors disabled:opacity-50"
              >
                {downloading ? 'Downloading...' : failed ? 'Try Again' : busy ? 'Starting...' : 'Update Now'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

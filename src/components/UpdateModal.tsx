'use client';

import React, { useState, useEffect } from 'react';

interface UpdateInfo {
  version?: string;
  releaseDate?: string;
  releaseNotes?: string;
}

export function UpdateModal() {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<number>(0);
  const [updateReady, setUpdateReady] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.electronAPI) return;

    window.electronAPI.onUpdaterMessage((msg) => {
      if (msg.status === 'available' && msg.data) {
        setUpdateInfo(msg.data as UpdateInfo);
        setUpdateAvailable(true);
        setErrorMessage(null);
        setDismissed(false);
      } else if (msg.status === 'progress' && msg.data) {
        const progress = msg.data as { percent?: number };
        setDownloading(true);
        setErrorMessage(null);
        if (progress.percent !== undefined) {
          setDownloadProgress(Math.round(progress.percent));
        }
      } else if (msg.status === 'downloaded') {
        setDownloading(false);
        setUpdateReady(true);
        setErrorMessage(null);
      } else if (msg.status === 'error') {
        setDownloading(false);
        setUpdateReady(false);
        setErrorMessage(typeof msg.data === 'string' ? msg.data : 'Download failed');
      }
    });
  }, []);

  if (!updateAvailable || dismissed) {
    return null;
  }

  const handleUpdateNow = () => {
    if (window.electronAPI) {
      setDownloading(true);
      setDownloadProgress(0);
      setErrorMessage(null);
      setUpdateReady(false);
      window.electronAPI.downloadUpdate().catch((err: unknown) => {
        setDownloading(false);
        setUpdateReady(false);
        setErrorMessage(err instanceof Error ? err.message : String(err));
      });
    }
  };

  const handleInstallAndRestart = () => {
    if (window.electronAPI) {
      window.electronAPI.installUpdate().catch((err: unknown) => {
        setErrorMessage(err instanceof Error ? err.message : String(err));
      });
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-md bg-terminal-panel border border-terminal-border shadow-2xl p-5 font-mono">
        <div className="flex items-center justify-between border-b border-terminal-border pb-2 mb-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-terminal-amber animate-ping" />
            <span className="text-terminal-amber font-bold text-xs tracking-wider">
              {updateReady && !errorMessage ? 'UPDATE READY TO INSTALL' : 'NEW VERSION AVAILABLE'}
            </span>
          </div>
          <span className="text-terminal-muted text-[10px]">
            {updateInfo?.version ? `v${updateInfo.version}` : ''}
          </span>
        </div>

        <div className="py-2 text-xs text-terminal-text space-y-2">
          {(!updateReady || errorMessage) ? (
            <p className="text-white/80">
              A new update for <span className="text-terminal-amber font-bold">BLM Terminal</span> is available. Would you like to update now or continue working?
            </p>
          ) : (
            <div className="bg-emerald-950/40 border border-emerald-500/40 p-3 text-emerald-200">
              <p className="font-bold mb-1">Update downloaded successfully!</p>
              <p className="text-[11px] text-emerald-300/80">
                Clicking restart will cleanly close the backend, apply the new version, and relaunch the application.
              </p>
            </div>
          )}

          {errorMessage && (
            <div className="bg-red-950/60 border border-red-500/60 p-2.5 text-red-200 text-[11px]">
              <span className="font-bold">Error: </span>{errorMessage}
            </div>
          )}

          {downloading && (
            <div className="mt-3 space-y-1">
              <div className="flex justify-between text-[10px] text-terminal-muted">
                <span>Downloading package...</span>
                <span>{downloadProgress}%</span>
              </div>
              <div className="w-full h-1.5 bg-terminal-bg border border-terminal-border overflow-hidden">
                <div
                  className="h-full bg-terminal-amber transition-[width,background-color] duration-150"
                  style={{ width: `${downloadProgress}%` }}
                />
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-terminal-border">
          {(!updateReady || errorMessage) ? (
            <>
              <button
                type="button"
                disabled={downloading}
                onClick={() => setDismissed(true)}
                className="px-3 py-1.5 text-xs text-terminal-muted hover:text-white border border-terminal-border hover:border-terminal-muted transition-colors disabled:opacity-40"
              >
                Remind Me Later
              </button>
              <button
                type="button"
                disabled={downloading}
                onClick={handleUpdateNow}
                className="px-4 py-1.5 text-xs font-bold bg-terminal-amber text-terminal-bg hover:bg-yellow-500 transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {downloading ? 'Downloading...' : errorMessage ? 'Retry Download' : 'Update Now'}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setDismissed(true)}
                className="px-3 py-1.5 text-xs text-terminal-muted hover:text-white border border-terminal-border transition-colors"
              >
                Restart Later
              </button>
              <button
                type="button"
                onClick={handleInstallAndRestart}
                className="px-4 py-1.5 text-xs font-bold bg-emerald-500 text-black hover:bg-emerald-400 transition-colors"
              >
                Install &amp; Restart
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

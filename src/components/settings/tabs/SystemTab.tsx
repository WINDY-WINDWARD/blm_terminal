'use client';

import React from 'react';
import Link from 'next/link';
import type { Watchlist } from '@/store/terminalStore';
import { BentoCard } from './BentoCard';

export interface SystemTabProps {
  watchlists: Watchlist[];
  activeWatchlistId: number;
  onDeleteWatchlist: (id: number, name: string) => void;
  updaterStatus: string;
  updaterProgress: { percent: number } | null;
  updateReady: boolean;
  onCheckForUpdates: () => void;
  onInstallUpdate: () => void;
  appVersion: string;
  isAdmin: boolean;
}

export function SystemTab({
  watchlists,
  activeWatchlistId,
  onDeleteWatchlist,
  updaterStatus,
  updaterProgress,
  updateReady,
  onCheckForUpdates,
  onInstallUpdate,
  appVersion,
  isAdmin,
}: SystemTabProps) {
  return (
    <>
      {/* Watchlists Management */}
      <BentoCard
        icon="▤"
        title="Watchlists"
        blurb="Your symbol lists. The default list cannot be deleted. ● marks the active list."
        className="col-span-1 md:col-span-2 lg:col-span-2"
      >
        <div className="flex flex-col gap-1">
          <div className="flex flex-col gap-0.5">
            {watchlists.map((wl) => (
              <div key={wl.id} className="flex items-center justify-between gap-2">
                <span className="text-white">
                  {wl.name}
                  {activeWatchlistId === wl.id && (
                    <span className="ml-1 text-terminal-green text-[9px]">●</span>
                  )}
                </span>
                {wl.id !== 1 && (
                  <button
                    type="button"
                    onClick={() => onDeleteWatchlist(wl.id, wl.name)}
                    className="text-terminal-red hover:text-red-400 text-xs font-bold px-1"
                    title="Delete watchlist"
                  >
                    ✕
                  </button>
                )}
                {wl.id === 1 && (
                  <span className="text-white/40 text-[9px]">default</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </BentoCard>

      {/* Updates & Shortcuts */}
      <BentoCard
        icon="⌨"
        title="Updates & Shortcuts"
        blurb="Desktop updater and command-bar reference."
        className="col-span-1 md:col-span-2 lg:col-span-2"
      >
        <div className="flex flex-col gap-2">
          {typeof window !== 'undefined' && window.electronAPI && (
            <div className="flex flex-col items-start gap-2 border-b border-terminal-gray/40 pb-2">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onCheckForUpdates}
                  className="px-2 py-1 text-[10px] bg-terminal-amber text-terminal-bg font-bold"
                >
                  CHECK FOR UPDATES
                </button>
                {updaterStatus && (
                  <span className="text-[10px] text-white/60">
                    {updaterStatus === 'checking' && 'Checking...'}
                    {updaterStatus === 'available' && 'Update available! Prompt shown.'}
                    {updaterStatus === 'not-available' && 'App is up to date'}
                    {updaterStatus === 'error' && 'Update check failed'}
                    {updaterStatus === 'progress' && updaterProgress && `Downloading: ${Math.round(updaterProgress.percent)}%`}
                    {updaterStatus === 'downloaded' && 'Update downloaded & ready'}
                  </span>
                )}
              </div>
              {updateReady && (
                <button
                  type="button"
                  onClick={onInstallUpdate}
                  className="px-2 py-1 text-[10px] bg-terminal-green text-terminal-bg font-bold animate-pulse"
                >
                  INSTALL & RESTART
                </button>
              )}
            </div>
          )}

          <div className="text-white text-[10px]">
            Commands: CHART · WATCH · ORDER · POS · TOP · SETTINGS · FDM · DEALS · LARGEDEALS · BREAKOUTS · NEWS · ANALYSIS · PORTFOLIO
          </div>
          <div className="text-white text-[10px]">
            Layouts: :save &lt;name&gt; · :&lt;name&gt; to load
          </div>
          <div className="text-white text-[10px]">
            Press / or Escape to focus command bar
          </div>
          <div className="text-white text-[10px]">
            F1 = BUY · F2 = SELL (in ORDER widget)
          </div>
          {appVersion && (
            <div className="text-white/40 text-[10px] mt-1">
              v{appVersion}
            </div>
          )}
        </div>
      </BentoCard>

      {/* Admin Links */}
      {isAdmin && (
        <BentoCard
          icon="⧉"
          title="Links"
          blurb="Jump to background task monitoring."
          className="col-span-1 md:col-span-2 lg:col-span-4"
        >
          <div className="flex flex-col gap-1">
            <Link
              href="/jobs"
              className="text-white hover:text-terminal-amber text-[10px] transition-colors"
            >
              → Jobs (background tasks)
            </Link>
          </div>
        </BentoCard>
      )}
    </>
  );
}

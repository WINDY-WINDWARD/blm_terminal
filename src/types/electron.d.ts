export interface UpdaterStateSnapshot {
  phase: 'idle' | 'checking' | 'available' | 'downloading' | 'downloaded' | 'not-available' | 'error';
  version: string | null;
  percent: number;
  error: string | null;
  checkedAt: number | null;
  installerPath: string | null;
  verified: boolean;
  verification: 'unknown' | 'ok' | 'unavailable';
  pendingInstall: { version: string; at: number | null } | null;
  canInstall: boolean;
  updatedAt: number;
}

export interface ElectronAPI {
  getAppVersion: () => Promise<string>;
  checkForUpdates: () => Promise<UpdaterStateSnapshot>;
  downloadUpdate: () => Promise<{ ok: boolean; state: UpdaterStateSnapshot }>;
  installUpdate: () => Promise<{ ok: boolean; state?: UpdaterStateSnapshot }>;
  getUpdaterState: () => Promise<UpdaterStateSnapshot>;
  dismissPendingInstall: () => Promise<UpdaterStateSnapshot>;
  /** Returns an unsubscribe function so React effects can clean up. */
  onUpdaterMessage: (callback: (msg: { status: string; data?: unknown }) => void) => () => void;
  quitApp: () => void;
  openExternal: (url: string) => Promise<{ ok: boolean }>;
  openInApp: (url: string) => Promise<{ ok: boolean }>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

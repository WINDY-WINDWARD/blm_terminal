export interface ElectronAPI {
  getAppVersion: () => Promise<string>;
  checkForUpdates: () => Promise<void>;
  downloadUpdate: () => Promise<void>;
  installUpdate: () => Promise<void>;
  onUpdaterMessage: (callback: (msg: { status: string; data?: unknown }) => void) => void;
  quitApp: () => void;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

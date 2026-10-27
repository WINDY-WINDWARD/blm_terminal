const { contextBridge, ipcRenderer } = require('electron');

// Because Next.js runs on a random ephemeral port for security, the browser's
// Origin changes every launch, meaning localStorage is totally empty on boot.
// We synchronously restore the saved state from Electron's disk before the
// React app renders so that user settings, layout, and onboarding state survive.
try {
  const initialData = ipcRenderer.sendSync('storage-get-all-sync');
  if (initialData && typeof initialData === 'object') {
    for (const [key, val] of Object.entries(initialData)) {
      if (localStorage.getItem(key) === null) {
        localStorage.setItem(key, typeof val === 'string' ? val : JSON.stringify(val));
      }
    }
  }
} catch (e) {
  console.error('Failed to sync initial local storage:', e);
}

contextBridge.exposeInMainWorld('electronAPI', {
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  onUpdaterMessage: (callback) => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('updater-message', listener);
    // Return an unsubscribe so React effects can clean up; without it every
    // remount stacked another listener on the same channel.
    return () => ipcRenderer.removeListener('updater-message', listener);
  },
  getUpdaterState: () => ipcRenderer.invoke('get-updater-state'),
  dismissPendingInstall: () => ipcRenderer.invoke('dismiss-pending-install'),
  getStoredItem: (key) => ipcRenderer.invoke('storage-get', key),
  setStoredItem: (key, value) => ipcRenderer.invoke('storage-set', key, value),
  removeStoredItem: (key) => ipcRenderer.invoke('storage-remove', key),
  getAllStoredItems: () => ipcRenderer.invoke('storage-get-all'),
  // Close the whole app (EULA declined). fire-and-forget.
  quitApp: () => ipcRenderer.send('eula-decline'),
  // Links: system browser vs in-app reader window.
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  openInApp: (url) => ipcRenderer.invoke('open-in-app', url),
});

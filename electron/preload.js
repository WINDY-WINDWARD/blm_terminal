const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  onUpdaterMessage: (callback) => {
    ipcRenderer.on('updater-message', (_event, message) => callback(message));
  },
  getStoredItem: (key) => ipcRenderer.invoke('storage-get', key),
  setStoredItem: (key, value) => ipcRenderer.invoke('storage-set', key, value),
  removeStoredItem: (key) => ipcRenderer.invoke('storage-remove', key),
  getAllStoredItems: () => ipcRenderer.invoke('storage-get-all'),
});

/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Minimal preload for the license key window: license actions only.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('blmLicense', {
  submit: (key) => ipcRenderer.invoke('license-submit', key),
  retry: () => ipcRenderer.invoke('license-retry'),
  quit: () => ipcRenderer.invoke('license-quit'),
  checkUpdates: () => ipcRenderer.invoke('license-check-updates'),
  onMessage: (cb) => ipcRenderer.on('license-message', (_e, msg) => cb(msg)),
});

/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Launch gate orchestrator: key window <-> online validation <-> lease.
// Returns the licensed key string, or null (caller quits).
// The denial window always offers an update check (fix must stay deliverable).
'use strict';
const { BrowserWindow, ipcMain, app } = require('electron');
const path = require('path');
const licConfig = require('./config');
const licStore = require('./store');
const licClient = require('./client');
const licLease = require('./lease');
const { validateKeyFormat } = require('./keycodec');
const { SKEW_WARN_S, ROLLBACK_TOLERANCE_S } = require('./constants');
const ota = require('./ota');

const MESSAGES = {
  revoked: 'This license has been revoked. Contact support for a reissue.',
  expired: 'This license has expired. Renew to continue.',
  unknown: 'License not recognized. Check the key and try again.',
  offline: 'Connect to the internet to verify your license.',
};

let keyWin = null;
let gateState = null; // { cfg, resolve, attempts }

function sendMsg(text, cls) {
  if (keyWin && !keyWin.isDestroyed()) {
    keyWin.webContents.send('license-message', { text, cls: cls || '' });
  }
}

function showKeyWindow(prefill) {
  if (keyWin && !keyWin.isDestroyed()) {
    keyWin.focus();
    if (prefill) sendMsg(prefill.text, prefill.cls);
    return keyWin;
  }
  keyWin = new BrowserWindow({
    width: 480, height: 520, resizable: false,
    title: 'BLM Terminal — License',
    webPreferences: {
      contextIsolation: true, nodeIntegration: false,
      preload: path.join(__dirname, '..', 'licensePreload.js'),
    },
  });
  keyWin.setMenu(null);
  keyWin.loadFile(path.join(__dirname, '..', 'licenseWindow.html'));
  if (prefill) {
    keyWin.webContents.once('did-finish-load', () => sendMsg(prefill.text, prefill.cls));
  }
  keyWin.on('closed', () => { keyWin = null; });
  return keyWin;
}

/** Evaluate a stored lease against now + persisted clock state. */
async function leaseUsable(leaseRec, iid, leasePubs) {
  if (!leaseRec || !leaseRec.payload || !leaseRec.sig) return { ok: false };
  const st = licStore.load();
  const nowS = Math.floor(Date.now() / 1000);
  const v = await licLease.verifyLease(leaseRec.payload, leaseRec.sig, leasePubs, iid, nowS);
  if (!v.ok) return { ok: false, reason: v.reason };
  // Rollback guard: localNow + offset must not fall below max server ts.
  const offset = st.serverOffset || 0;
  if (nowS + offset < (st.maxServerTs || 0) - ROLLBACK_TOLERANCE_S) {
    return { ok: false, reason: 'clock_rollback' };
  }
  if (v.payload.lic_exp !== null && v.payload.lic_exp !== undefined && nowS >= v.payload.lic_exp) {
    return { ok: false, reason: 'license_expired' };
  }
  return { ok: true, payload: v.payload };
}

async function tryOnline(key, cfg, iid) {
  const res = await licClient.validateWithRetry({
    url: cfg.url, boxKid: cfg.boxKid, encPub: cfg.encPub, key, iid, timeoutMs: 10000,
  });
  const nowS = Math.floor(Date.now() / 1000);
  if (res.outcome === 'ok') {
    const P = res.reply;
    // Verify the fresh lease before storing (sig + iid bind).
    const v = await licLease.verifyLease(P.lease.payload, P.lease.sig, cfg.leasePubs, iid, nowS);
    if (!v.ok) return { outcome: 'indeterminate', detail: 'lease_verify_failed' };
    licStore.saveLease(P.lease, P.ts, nowS);
    if (Math.abs(P.skew_s || 0) > SKEW_WARN_S) {
      sendMsg('Note: your system clock disagrees with the server. Check it when convenient.', '');
    }
    return { outcome: 'ok' };
  }
  if (res.outcome === 'denied') {
    licStore.clearLease();
    return res;
  }
  return res; // indeterminate or invalid_key (no lease touch)
}

function closeKeyWindow() {
  try {
    if (keyWin && !keyWin.isDestroyed()) keyWin.close();
  } catch {}
  keyWin = null;
}

function wireIpc() {
  ipcMain.handle('license-submit', async (_e, key) => {
    const fmt = validateKeyFormat(key);
    if (!fmt.ok) return { ok: false, message: 'Key format invalid — check for typos.' };
    licStore.saveKey(key);
    const st = licStore.load();
    const r = await tryOnline(key, gateState.cfg, st.iid);
    if (r.outcome === 'ok') {
      closeKeyWindow();
      gateState.resolve(key);
      return { ok: true };
    }
    if (r.outcome === 'denied') {
      return { ok: false, message: MESSAGES[r.status] || MESSAGES.unknown };
    }
    // Indeterminate after submit: fall back to lease if one exists.
    const l = await leaseUsable(st.lease, st.iid, gateState.cfg.leasePubs);
    if (l.ok) {
      closeKeyWindow();
      gateState.resolve(key);
      return { ok: true };
    }
    return { ok: false, message: MESSAGES.offline };
  });
  ipcMain.handle('license-retry', async () => {
    const st = licStore.load();
    if (!st.key) return { ok: false };
    const r = await tryOnline(st.key, gateState.cfg, st.iid);
    if (r.outcome === 'ok') {
      closeKeyWindow();
      gateState.resolve(st.key);
      return { ok: true };
    }
    return { ok: false };
  });
  ipcMain.handle('license-quit', () => {
    gateState.resolve(null);
    app.quit();
  });
  ipcMain.handle('license-check-updates', async () => {
    try {
      const r = await runManifestCheckedUpdate(gateState.cfg, console.log.bind(console));
      return r;
    } catch (e) {
      return { ok: false, message: `Update check failed: ${e.message}` };
    }
  });
}

/**
 * Manifest-first update flow (A5). Shared by the denial window and the
 * post-boot handlers in main.js.
 */
async function runManifestCheckedUpdate(cfg, log) {
  const { autoUpdater } = require('electron-updater');
  if (!cfg.feedUrl) return { ok: false, message: 'No update feed configured.' };
  const manifest = await ota.fetchVerifiedManifest(cfg.feedUrl, cfg.otaPubs, app.isPackaged, log);
  const running = app.getVersion();
  if (ota.cmpVer(manifest.version, running) <= 0) {
    return { ok: false, message: `Already on latest (${running}).` };
  }
  const info = await autoUpdater.checkForUpdates();
  const avail = (info && info.updateInfo && info.updateInfo.version)
    || (info && info.version) || null;
  if (avail && avail !== manifest.version) {
    throw new Error(`updater offers ${avail} but manifest signs ${manifest.version}: refusing`);
  }
  const dl = await autoUpdater.downloadUpdate();
  const files = await ota.verifyDownloaded(dl, manifest);
  return { ok: true, message: `Update ${manifest.version} verified. Restart to install.`, manifest, files };
}

/**
 * Main entry: returns licensed key or null. Must run before spawning servers.
 * Update availability never depends on license state (denial window offers it).
 */
async function runGate(log = console.log) {
  const cfg = licConfig.resolve();
  if (!cfg.encPub || !cfg.leasePubs.length) {
    // No keys configured (fresh dev checkout): license enforcement off, loud log.
    log('[license] no keys configured — gate open (dev only; packaged builds refuse this)');
    return 'dev-no-key';
  }
  wireIpc();
  const st = licStore.load();

  // Fast path: stored key + online check.
  if (st.key && validateKeyFormat(st.key).ok) {
    const r = await tryOnline(st.key, cfg, st.iid);
    if (r.outcome === 'ok') return st.key;
    if (r.outcome === 'denied') {
      showKeyWindow({ text: MESSAGES[r.status] || MESSAGES.unknown, cls: 'err' });
    } else {
      const l = await leaseUsable(st.lease, st.iid, cfg.leasePubs);
      if (l.ok) {
        log('[license] offline lease accepted');
        return st.key;
      }
      showKeyWindow({ text: MESSAGES.offline, cls: 'err' });
    }
  } else {
    showKeyWindow(null);
  }

  return new Promise((resolve) => {
    gateState = { cfg, resolve };
  });
}

module.exports = { runGate, runManifestCheckedUpdate, leaseUsable, MESSAGES };

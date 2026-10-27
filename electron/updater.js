/* eslint-disable @typescript-eslint/no-require-imports -- Electron main-process CommonJS (mirrors server.js) */
// Authoritative update state machine for the main process.
//
// Before this module the updater was event-only: the renderer learned about a
// download solely from a one-shot `updater-message`, and main kept the staged
// installer in a closure variable. Two failures followed from that:
//   * a missed or suppressed event (c2026302's log-only `update-downloaded`)
//     left the modal downloading forever with no way out;
//   * a renderer reload, a second window, or an app restart forgot that a
//     verified installer was already staged.
// State now lives here, is broadcast to every window, is persisted across
// launches, and is queryable via `get-updater-state`.
'use strict';

const fs = require('fs');
const path = require('path');
const { cmpVer } = require('./ota');

const PHASES = {
  IDLE: 'idle',
  CHECKING: 'checking',
  AVAILABLE: 'available',
  DOWNLOADING: 'downloading',
  DOWNLOADED: 'downloaded',
  NOT_AVAILABLE: 'not-available',
  ERROR: 'error',
};

const DEFAULT_WATCHDOG_MS = 120000;

function emptyState() {
  return {
    phase: PHASES.IDLE,
    version: null,
    percent: 0,
    error: null,
    checkedAt: null,
    installerPath: null,
    verified: false,
    verification: 'unknown',
    pendingInstall: null,
    canInstall: false,
    trigger: 'auto',
    updatedAt: Date.now(),
  };
}

class UpdaterController {
  constructor({
    autoUpdater,
    app,
    log = () => {},
    broadcast = () => {},
    verifier = null,
    stateFile = null,
    pendingInstallFile = null,
    watchdogMs = DEFAULT_WATCHDOG_MS,
    setTimeoutImpl = setTimeout,
    clearTimeoutImpl = clearTimeout,
    now = () => Date.now(),
  }) {
    this.autoUpdater = autoUpdater;
    this.app = app;
    this.log = log;
    this.broadcast = broadcast;
    this.verifier = verifier;
    this.stateFile = stateFile;
    this.pendingInstallFile = pendingInstallFile;
    this.watchdogMs = watchdogMs;
    this.setTimeoutImpl = setTimeoutImpl;
    this.clearTimeoutImpl = clearTimeoutImpl;
    this.now = now;

    this.state = emptyState();
    this._watchdog = null;
    this._completing = null;
    this._wired = false;
    this._disposed = false;
    this._lastPersisted = { phase: this.state.phase, percent: 0 };
  }

  // ── state ────────────────────────────────────────────────────────────────

  getState() {
    return { ...this.state, canInstall: this.state.phase === PHASES.DOWNLOADED && this.state.verified };
  }

  _set(patch) {
    const phaseChanged = patch.phase !== undefined && patch.phase !== this.state.phase;
    this.state = { ...this.state, ...patch, updatedAt: this.now() };
    // A 363 MB download emits a progress event per chunk. Writing the state
    // file on each one is pure I/O churn, so only phase changes and 10% steps
    // are persisted; the in-memory state and the broadcast stay exact.
    if (phaseChanged || Math.abs(this.state.percent - this._lastPersisted.percent) >= 10) {
      this._persist();
      this._lastPersisted = { phase: this.state.phase, percent: this.state.percent };
    }
    this.broadcast({ status: this.state.phase, data: this.getState() });
  }

  _persist() {
    if (!this.stateFile) return;
    // A downloaded state only survives a restart if the file still exists and
    // was verified; the hash is re-checked at install time regardless.
    const persisted = {
      phase: this.state.phase === PHASES.DOWNLOADING ? PHASES.AVAILABLE : this.state.phase,
      version: this.state.version,
      percent: this.state.phase === PHASES.DOWNLOADING ? 0 : this.state.percent,
      checkedAt: this.state.checkedAt,
      installerPath: this.state.installerPath,
      verified: this.state.verified,
      verification: this.state.verification,
      trigger: this.state.trigger,
    };
    try {
      fs.mkdirSync(path.dirname(this.stateFile), { recursive: true });
      const tmp = `${this.stateFile}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify(persisted, null, 2));
      fs.renameSync(tmp, this.stateFile);
    } catch (err) {
      this.log(`[updater] could not persist state: ${err?.message || err}`);
    }
  }

  _hydrate() {
    if (!this.stateFile) return;
    let persisted = null;
    try {
      if (fs.existsSync(this.stateFile)) persisted = JSON.parse(fs.readFileSync(this.stateFile, 'utf8'));
    } catch (err) {
      this.log(`[updater] ignored unreadable state file: ${err?.message || err}`);
    }
    if (!persisted || typeof persisted !== 'object') return;

    const patch = {
      version: typeof persisted.version === 'string' ? persisted.version : null,
      checkedAt: typeof persisted.checkedAt === 'number' ? persisted.checkedAt : null,
      verification: typeof persisted.verification === 'string' ? persisted.verification : 'unknown',
      trigger: typeof persisted.trigger === 'string' ? persisted.trigger : 'auto',
    };
    if (persisted.phase === PHASES.DOWNLOADED) {
      const installer = persisted.installerPath;
      // A staged update for a version that is already running means the update
      // installed and the state file outlived it. Never offer it again: the
      // modal would ask the user to "install" the build they are using.
      const alreadyInstalled = typeof persisted.version === 'string'
        && cmpVer(persisted.version, this.app.getVersion()) <= 0;
      if (alreadyInstalled) {
        this.log(`[updater] dropping stale staged update for ${persisted.version} (running ${this.app.getVersion()})`);
        Object.assign(patch, { phase: PHASES.IDLE, percent: 0, installerPath: null, verified: false });
      } else if (installer && fs.existsSync(installer) && persisted.verified === true) {
        // Keep the staged state so a restart does not force a re-download.
        Object.assign(patch, {
          phase: PHASES.DOWNLOADED,
          percent: 100,
          installerPath: installer,
          verified: true,
        });
      } else {
        Object.assign(patch, { phase: PHASES.AVAILABLE, percent: 0 });
      }
    } else if (persisted.phase === PHASES.AVAILABLE) {
      patch.phase = PHASES.AVAILABLE;
    }
    // Any other phase is not worth restoring (checking/downloading/error).
    this.state = { ...this.state, ...patch, updatedAt: this.now() };
  }

  // ── pending-install marker ───────────────────────────────────────────────

  recordPendingInstall(version, installerPath) {
    const marker = { version, installerPath, at: this.now() };
    if (this.pendingInstallFile) {
      try {
        fs.mkdirSync(path.dirname(this.pendingInstallFile), { recursive: true });
        fs.writeFileSync(this.pendingInstallFile, JSON.stringify(marker, null, 2));
      } catch (err) {
        this.log(`[updater] could not write pending-install marker: ${err?.message || err}`);
      }
    }
    this.state = { ...this.state, pendingInstall: { version, at: marker.at } };
    return marker;
  }

  /**
   * A pending-install marker that survived a launch means the previous update
   * never applied — declined UAC, a locked file, a killed installer. Surface it
   * instead of pretending the streak is unbroken.
   */
  reconcilePendingInstall() {
    if (!this.pendingInstallFile) return null;
    try {
      if (!fs.existsSync(this.pendingInstallFile)) return null;
      const marker = JSON.parse(fs.readFileSync(this.pendingInstallFile, 'utf8'));
      const current = this.app.getVersion();
      if (!marker || typeof marker.version !== 'string') {
        fs.unlinkSync(this.pendingInstallFile);
        return null;
      }
      if (cmpVer(current, marker.version) >= 0) {
        this.log(`[updater] update to ${marker.version} applied (now ${current}); clearing marker`);
        fs.unlinkSync(this.pendingInstallFile);
        this.state = { ...this.state, pendingInstall: null };
        return null;
      }
      this.log(`[updater] previous update to ${marker.version} did not apply (still ${current})`);
      this.state = { ...this.state, pendingInstall: { version: marker.version, at: marker.at || null } };
      return this.state.pendingInstall;
    } catch (err) {
      this.log(`[updater] could not reconcile pending-install marker: ${err?.message || err}`);
      return null;
    }
  }

  dismissPendingInstall() {
    this.state = { ...this.state, pendingInstall: null };
    if (this.pendingInstallFile) {
      try {
        if (fs.existsSync(this.pendingInstallFile)) fs.unlinkSync(this.pendingInstallFile);
      } catch (err) {
        this.log(`[updater] could not remove pending-install marker: ${err?.message || err}`);
      }
    }
    this._persist();
    this.broadcast({ status: this.state.phase, data: this.getState() });
  }

  // ── lifecycle ────────────────────────────────────────────────────────────

  async init() {
    this._hydrate();
    this.reconcilePendingInstall();

    if (this.verifier) {
      const verdict = await this.verifier.selfTest();
      this.state = {
        ...this.state,
        verification: verdict.ok ? 'ok' : 'unavailable',
      };
      if (!verdict.ok) {
        this.log(`[updater] DISABLED: OTA verifier is unusable in this build (${verdict.error})`);
      }
    } else {
      this.state = { ...this.state, verification: 'unavailable' };
    }

    this._wire();
    this._persist();
    this.broadcast({ status: this.state.phase, data: this.getState() });
    return this.getState();
  }

  _wire() {
    if (this._wired) return;
    this._wired = true;
    const up = this.autoUpdater;

    up.on('checking-for-update', () => {
      this._set({ phase: PHASES.CHECKING, error: null, checkedAt: this.now() });
    });

    up.on('update-available', (info) => {
      const next = info?.version || null;
      // Re-announcing the same downloaded version must not downgrade the state.
      if (this.state.phase === PHASES.DOWNLOADED && cmpVer(next || this.state.version, this.state.version || '0') <= 0) {
        return;
      }
      this._set({ phase: PHASES.AVAILABLE, version: next, percent: 0, error: null, checkedAt: this.now() });
    });

    up.on('update-not-available', (info) => {
      if (this.state.phase === PHASES.DOWNLOADED) return;
      this._set({
        phase: PHASES.NOT_AVAILABLE,
        version: info?.version || this.app.getVersion(),
        error: null,
        checkedAt: this.now(),
      });
    });

    up.on('error', (err) => {
      const message = err?.message || String(err);
      this.log(`[updater] error event: ${message}`);
      // A failure raised after a verified download must not erase the staged
      // installer the user is about to install.
      if (this.state.phase === PHASES.DOWNLOADED) return;
      this._stopWatchdog();
      this._set({ phase: PHASES.ERROR, error: message });
    });

    up.on('download-progress', (progress) => {
      const percent = typeof progress?.percent === 'number' ? Math.round(progress.percent) : this.state.percent;
      if (this.state.phase !== PHASES.DOWNLOADING) this._set({ phase: PHASES.DOWNLOADING, percent });
      else this._set({ percent });
      this._touchWatchdog();
    });

    up.on('update-downloaded', (info) => {
      const paths = info?.downloadedFile ? [info.downloadedFile] : [];
      this.log(`[updater] update downloaded to cache: ${info?.version || 'unknown'}`);
      this._completeDownload(paths, info?.version).catch((err) => {
        this.log(`[updater] staged download failed verification: ${err?.message || err}`);
      });
    });
  }

  dispose() {
    this._disposed = true;
    this._stopWatchdog();
  }

  // ── actions ──────────────────────────────────────────────────────────────

  async check({ trigger = 'manual' } = {}) {
    if (this._disposed) return this.getState();
    // Remember who asked, so a background failure stays quiet while an
    // explicit "Check for updates" failure is reported to the user.
    this._set({ trigger });
    const result = await this.autoUpdater.checkForUpdates();
    void result;
    return this.getState();
  }

  /**
   * The user took over: they clicked install on an update that a background
   * check found. Anything that fails from here on is their business, so the
   * trigger must stop being 'auto' or the failure would be swallowed.
   */
  markManual() {
    if (this.state.trigger === 'manual') return this.getState();
    this._set({ trigger: 'manual' });
    return this.getState();
  }

  async download() {
    if (this.state.verification === 'unavailable') {
      throw new Error('Update verification is unavailable in this build, so the update cannot be installed.');
    }
    if (this.state.phase === PHASES.DOWNLOADED && this.state.verified && this.state.installerPath) {
      return this.getState();
    }
    if (this.state.phase === PHASES.DOWNLOADING) {
      // Already in flight: join it rather than starting a second transfer.
      return this.getState();
    }

    this._set({
      phase: PHASES.DOWNLOADING,
      percent: 0,
      error: null,
      verified: false,
      installerPath: null,
      trigger: 'manual',
    });
    this._startWatchdog();
    try {
      const paths = await this.autoUpdater.downloadUpdate();
      await this._completeDownload(paths, this.state.version);
      return this.getState();
    } catch (err) {
      this._stopWatchdog();
      const message = err?.message || String(err);
      // _completeDownload already recorded its own verdict; do not overwrite it.
      if (this.state.phase !== PHASES.ERROR) this._set({ phase: PHASES.ERROR, error: message });
      throw err;
    }
  }

  _completeDownload(paths, version) {
    if (!this._completing) {
      this._completing = this._doComplete(paths, version).finally(() => {
        this._completing = null;
      });
    }
    return this._completing;
  }

  async _doComplete(paths, version) {
    const list = (Array.isArray(paths) ? paths : [paths]).filter((p) => typeof p === 'string' && p);
    const installer = list.find((p) => /\.exe$/i.test(p)) || list[0];

    if (!installer) {
      // Cache hits can resolve without a path on some electron-updater paths;
      // fall back to what the previous download already told us.
      if (this.state.phase === PHASES.DOWNLOADED && this.state.installerPath) return;
      this._stopWatchdog();
      this._set({ phase: PHASES.ERROR, error: 'Download finished but reported no installer file.' });
      throw new Error('download reported no installer file');
    }

    if (
      this.state.phase === PHASES.DOWNLOADED
      && this.state.verified
      && this.state.installerPath === installer
    ) {
      this._stopWatchdog();
      return;
    }

    if (!this.verifier) {
      this._stopWatchdog();
      this._set({ phase: PHASES.ERROR, error: 'Update verification is unavailable in this build.' });
      throw new Error('no OTA verifier configured');
    }

    const verdict = await this.verifier.verifyInstaller(installer, version || this.state.version);
    if (!verdict.ok) {
      this._stopWatchdog();
      this._set({
        phase: PHASES.ERROR,
        error: `Update failed verification: ${verdict.error}`,
        verified: false,
        installerPath: installer,
      });
      throw new Error(verdict.error);
    }

    this._stopWatchdog();
    this._set({
      phase: PHASES.DOWNLOADED,
      percent: 100,
      verified: true,
      verification: 'ok',
      installerPath: installer,
      version: verdict.manifest?.version || version || this.state.version,
      error: null,
    });
  }

  /**
   * Re-verify the staged installer immediately before handing control to NSIS.
   * Returns { installerPath, version }; throws if anything is off.
   */
  async prepareInstall() {
    if (this.state.phase !== PHASES.DOWNLOADED || !this.state.verified || !this.state.installerPath) {
      throw new Error('No verified update is staged. Download the update first.');
    }
    if (!fs.existsSync(this.state.installerPath)) {
      this._set({ phase: PHASES.AVAILABLE, verified: false, installerPath: null, error: null });
      throw new Error('The staged installer is missing. Download the update again.');
    }
    if (!this.verifier) {
      throw new Error('Update verification is unavailable in this build, so the update cannot be installed.');
    }
    const verdict = await this.verifier.verifyInstaller(this.state.installerPath, this.state.version);
    if (!verdict.ok) {
      this._set({ phase: PHASES.ERROR, verified: false, error: `Update failed verification: ${verdict.error}` });
      throw new Error(verdict.error);
    }
    return { installerPath: this.state.installerPath, version: this.state.version };
  }

  // ── watchdog ─────────────────────────────────────────────────────────────

  _startWatchdog() {
    this._stopWatchdog();
    this._watchdog = this.setTimeoutImpl(() => {
      if (this.state.phase !== PHASES.DOWNLOADING) return;
      const seconds = Math.round(this.watchdogMs / 1000);
      this.log(`[updater] download stalled: no progress for ${seconds}s`);
      this._set({
        phase: PHASES.ERROR,
        error: `Download stalled — no progress for ${seconds} seconds. Retry, or install the update manually from the release page.`,
      });
      this._watchdog = null;
    }, this.watchdogMs);
    if (this._watchdog && typeof this._watchdog.unref === 'function') this._watchdog.unref();
  }

  _touchWatchdog() {
    if (this._watchdog) this._startWatchdog();
  }

  _stopWatchdog() {
    if (this._watchdog) {
      this.clearTimeoutImpl(this._watchdog);
      this._watchdog = null;
    }
  }
}

function createUpdaterController(options) {
  return new UpdaterController(options);
}

module.exports = { createUpdaterController, UpdaterController, PHASES, DEFAULT_WATCHDOG_MS };

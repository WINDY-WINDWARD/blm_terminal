import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import {
  afterAll, beforeEach, describe, expect, it, vi,
} from 'vitest';

// The updater controller replaced an event-only design that could strand the
// renderer forever (2026.10.9: `update-downloaded` was logged but never
// forwarded). These tests pin the state machine: every terminal outcome must be
// observable, verification failures must not install, and an interrupted
// download must not survive a restart as if it were complete.
const require = createRequire(import.meta.url);

type State = {
  phase: string;
  version: string | null;
  percent: number;
  error: string | null;
  installerPath: string | null;
  verified: boolean;
  verification: string;
  pendingInstall: { version: string; at: number | null } | null;
  canInstall: boolean;
};

const { createUpdaterController, PHASES } = require('../../../electron/updater.js') as {
  createUpdaterController: (opts: Record<string, unknown>) => {
    init: () => Promise<State>;
    getState: () => State;
    check: () => Promise<State>;
    download: () => Promise<State>;
    prepareInstall: () => Promise<{ installerPath: string; version: string | null }>;
    reconcilePendingInstall: () => { version: string } | null;
    dismissPendingInstall: () => void;
    dispose: () => void;
  };
  PHASES: Record<string, string>;
};

let tmpDir: string;
let installer: string;

function makeHarness({
  selfTest = async () => ({ ok: true }),
  verifyInstaller = async () => ({ ok: true, manifest: { version: '2026.10.10' } }),
  downloadResult,
  downloadImpl,
  currentVersion = '2026.10.9',
  timers,
}: {
  selfTest?: () => Promise<{ ok: boolean; error?: string }>;
  verifyInstaller?: (p: string, v?: string | null) => Promise<{ ok: boolean; error?: string; manifest?: { version: string } }>;
  downloadResult?: string[];
  downloadImpl?: () => Promise<string[]>;
  currentVersion?: string;
  timers?: { fire: () => void };
} = {}) {
  const autoUpdater = Object.assign(new EventEmitter(), {
    checkForUpdates: vi.fn(async () => ({ updateInfo: { version: '2026.10.10' } })),
    downloadUpdate: vi.fn(downloadImpl || (async () => downloadResult ?? [installer])),
    quitAndInstall: vi.fn(),
  });
  const app = { getVersion: () => currentVersion };
  const broadcast = vi.fn();
  const log = vi.fn();
  const verifier = { selfTest: vi.fn(selfTest), verifyInstaller: vi.fn(verifyInstaller) };

  const controller = createUpdaterController({
    autoUpdater,
    app,
    log,
    broadcast,
    verifier,
    stateFile: path.join(tmpDir, 'updater-state.json'),
    pendingInstallFile: path.join(tmpDir, 'pending-install.json'),
    watchdogMs: 120000,
    setTimeoutImpl: timers
      ? (fn: () => void) => {
        timers.fire = fn;
        return { unref() {} };
      }
      : undefined,
    clearTimeoutImpl: timers ? () => {} : undefined,
  });

  return {
    autoUpdater, broadcast, log, verifier, controller,
  };
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'blm-updater-test-'));
  installer = path.join(tmpDir, 'BLM Terminal Setup 2026.10.10.exe');
  fs.writeFileSync(installer, 'installer-bytes');
});

afterAll(() => {
  // Temp dirs are asserted on, so leave them for the OS to reap on Windows
  // file locks rather than failing a passing test run.
  void os;
});

describe('UpdaterController init', () => {
  it('reports a usable verifier and broadcasts idle state', async () => {
    const h = makeHarness();
    const state = await h.controller.init();
    expect(state.verification).toBe('ok');
    expect(state.phase).toBe(PHASES.IDLE);
    expect(h.broadcast).toHaveBeenCalled();
  });

  it('marks verification unavailable when the self-test fails', async () => {
    const h = makeHarness({ selfTest: async () => ({ ok: false, error: 'libsodium missing' }) });
    const state = await h.controller.init();
    expect(state.verification).toBe('unavailable');

    await expect(h.controller.download()).rejects.toThrow(/verification is unavailable/i);
    expect(h.autoUpdater.downloadUpdate).not.toHaveBeenCalled();
  });

  it('downgrades a stale downloaded state when the installer is gone', async () => {
    fs.writeFileSync(
      path.join(tmpDir, 'updater-state.json'),
      JSON.stringify({
        phase: 'downloaded', version: '2026.10.10', percent: 100, verified: true, installerPath: path.join(tmpDir, 'gone.exe'),
      }),
    );
    const h = makeHarness();
    const state = await h.controller.init();
    expect(state.phase).toBe(PHASES.AVAILABLE);
    expect(state.verified).toBe(false);
  });

  it('keeps a staged installer across restarts', async () => {
    fs.writeFileSync(
      path.join(tmpDir, 'updater-state.json'),
      JSON.stringify({
        phase: 'downloaded', version: '2026.10.10', percent: 100, verified: true, installerPath: installer,
      }),
    );
    const h = makeHarness();
    const state = await h.controller.init();
    expect(state.phase).toBe(PHASES.DOWNLOADED);
    expect(state.canInstall).toBe(true);
  });
});

describe('UpdaterController events', () => {
  it('tracks the available version', async () => {
    const h = makeHarness();
    await h.controller.init();
    h.autoUpdater.emit('update-available', { version: '2026.10.10' });
    expect(h.controller.getState().phase).toBe(PHASES.AVAILABLE);
    expect(h.controller.getState().version).toBe('2026.10.10');
  });

  it('does not downgrade a downloaded update on a repeat announcement', async () => {
    const h = makeHarness();
    await h.controller.init();
    await h.controller.download();
    expect(h.controller.getState().phase).toBe(PHASES.DOWNLOADED);

    h.autoUpdater.emit('update-available', { version: '2026.10.10' });
    expect(h.controller.getState().phase).toBe(PHASES.DOWNLOADED);
  });

  it('keeps a verified download when a later error event arrives', async () => {
    const h = makeHarness();
    await h.controller.init();
    await h.controller.download();

    h.autoUpdater.emit('error', new Error('socket hang up'));
    expect(h.controller.getState().phase).toBe(PHASES.DOWNLOADED);
    expect(h.controller.getState().canInstall).toBe(true);
  });

  it('records progress percentage', async () => {
    const h = makeHarness({ downloadImpl: () => new Promise<string[]>(() => {}) });
    await h.controller.init();
    void h.controller.download().catch(() => {});
    h.autoUpdater.emit('download-progress', { percent: 42.4 });
    expect(h.controller.getState().phase).toBe(PHASES.DOWNLOADING);
    expect(h.controller.getState().percent).toBe(42);
  });
});

describe('UpdaterController download', () => {
  it('completes from the resolved promise when no event fires (cache hit)', async () => {
    const h = makeHarness();
    await h.controller.init();
    h.autoUpdater.emit('update-available', { version: '2026.10.10' });
    const state = await h.controller.download();

    expect(state.phase).toBe(PHASES.DOWNLOADED);
    expect(state.verified).toBe(true);
    expect(state.canInstall).toBe(true);
    expect(h.verifier.verifyInstaller).toHaveBeenCalledWith(installer, '2026.10.10');
  });

  it('completes from the update-downloaded event', async () => {
    const h = makeHarness({ downloadImpl: () => new Promise<string[]>(() => {}) });
    await h.controller.init();
    void h.controller.download().catch(() => {});

    h.autoUpdater.emit('update-downloaded', { version: '2026.10.10', downloadedFile: installer });

    await vi.waitFor(() => {
      expect(h.controller.getState().phase).toBe(PHASES.DOWNLOADED);
    });
  });

  it('refuses to stage an installer that fails verification', async () => {
    const h = makeHarness({
      verifyInstaller: async () => ({ ok: false, error: 'installer sha256 does not match the signed manifest' }),
    });
    await h.controller.init();

    await expect(h.controller.download()).rejects.toThrow(/sha256/);
    const state = h.controller.getState();
    expect(state.phase).toBe(PHASES.ERROR);
    expect(state.verified).toBe(false);
    expect(state.canInstall).toBe(false);
    expect(state.error).toMatch(/failed verification/i);
  });

  it('reports a stall when no progress arrives before the watchdog fires', async () => {
    const timers = { fire: () => {} };
    const h = makeHarness({ timers, downloadImpl: () => new Promise<string[]>(() => {}) });
    await h.controller.init();

    void h.controller.download().catch(() => {});
    expect(h.controller.getState().phase).toBe(PHASES.DOWNLOADING);

    timers.fire();

    const state = h.controller.getState();
    expect(state.phase).toBe(PHASES.ERROR);
    expect(state.error).toMatch(/stalled/i);
  });

  it('is a no-op when the update is already staged', async () => {
    const h = makeHarness();
    await h.controller.init();
    await h.controller.download();
    await h.controller.download();
    expect(h.autoUpdater.downloadUpdate).toHaveBeenCalledTimes(1);
  });
});

describe('UpdaterController install guard', () => {
  it('refuses to install without a staged update', async () => {
    const h = makeHarness();
    await h.controller.init();
    await expect(h.controller.prepareInstall()).rejects.toThrow(/No verified update is staged/);
  });

  it('re-verifies the installer immediately before installing', async () => {
    const h = makeHarness();
    await h.controller.init();
    await h.controller.download();

    h.verifier.verifyInstaller.mockResolvedValueOnce({ ok: false, error: 'hash changed on disk' });
    await expect(h.controller.prepareInstall()).rejects.toThrow(/hash changed/);
    expect(h.controller.getState().phase).toBe(PHASES.ERROR);
  });

  it('returns the staged installer when it still verifies', async () => {
    const h = makeHarness();
    await h.controller.init();
    await h.controller.download();

    const staged = await h.controller.prepareInstall();
    expect(staged.installerPath).toBe(installer);
    expect(staged.version).toBe('2026.10.10');
  });
});

describe('pending-install reconciliation', () => {
  const markerPath = () => path.join(tmpDir, 'pending-install.json');

  it('surfaces an update that never applied', async () => {
    fs.writeFileSync(markerPath(), JSON.stringify({ version: '2026.10.10', at: 1 }));
    const h = makeHarness({ currentVersion: '2026.10.9' });
    const state = await h.controller.init();
    expect(state.pendingInstall?.version).toBe('2026.10.10');
  });

  it('clears the marker once the new version is running', async () => {
    fs.writeFileSync(markerPath(), JSON.stringify({ version: '2026.10.10', at: 1 }));
    const h = makeHarness({ currentVersion: '2026.10.10' });
    const state = await h.controller.init();
    expect(state.pendingInstall).toBeNull();
    expect(fs.existsSync(markerPath())).toBe(false);
  });

  it('drops the marker on dismissal', async () => {
    fs.writeFileSync(markerPath(), JSON.stringify({ version: '2026.10.10', at: 1 }));
    const h = makeHarness({ currentVersion: '2026.10.9' });
    await h.controller.init();
    h.controller.dismissPendingInstall();
    expect(h.controller.getState().pendingInstall).toBeNull();
    expect(fs.existsSync(markerPath())).toBe(false);
  });
});

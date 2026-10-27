import React from 'react';
import {
  describe, it, expect, beforeEach, afterEach, vi,
} from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { UpdateModal } from '@/components/UpdateModal';
import { resetUpdaterStoreForTests } from '@/lib/updaterStore';
import type { ElectronAPI, UpdaterStateSnapshot } from '@/types/electron';

/**
 * Regression coverage for the 2026.10.9 update stall: the main process stopped
 * forwarding `update-downloaded`, the modal sat on "Downloading... 0%" with both
 * buttons disabled, and the window could not even be dismissed.
 *
 * The modal now renders whatever authoritative state main broadcasts, so these
 * cases drive it the same way main does: a broadcast, or the IPC return value.
 */

const idleState = (patch: Partial<UpdaterStateSnapshot> = {}): UpdaterStateSnapshot => ({
  phase: 'idle',
  version: null,
  percent: 0,
  error: null,
  checkedAt: null,
  installerPath: null,
  verified: false,
  verification: 'ok',
  pendingInstall: null,
  canInstall: false,
  trigger: 'auto',
  updatedAt: Date.now(),
  ...patch,
});

function installElectronMock(overrides: Partial<ElectronAPI> = {}) {
  let emit: ((msg: { status: string; data?: unknown }) => void) | null = null;
  const api: ElectronAPI = {
    getAppVersion: vi.fn(async () => '2026.10.9'),
    getUpdaterState: vi.fn(async () => idleState()),
    checkForUpdates: vi.fn(async () => idleState()),
    downloadUpdate: vi.fn(async () => ({ ok: true, state: idleState() })),
    installUpdate: vi.fn(async () => ({ ok: true })),
    dismissPendingInstall: vi.fn(async () => idleState()),
    onUpdaterMessage: vi.fn((callback: (msg: { status: string; data?: unknown }) => void) => {
      emit = callback;
      return () => {
        emit = null;
      };
    }),
    quitApp: vi.fn(),
    openExternal: vi.fn(async () => ({ ok: true })),
    openInApp: vi.fn(async () => ({ ok: true })),
    ...overrides,
  };
  window.electronAPI = api;

  return {
    api,
    emit: (msg: { status: string; data?: unknown }) => act(() => emit?.(msg)),
  };
}

const broadcast = (patch: Partial<UpdaterStateSnapshot>) => ({
  status: patch.phase || 'idle',
  data: idleState(patch),
});

describe('UpdateModal', () => {
  beforeEach(() => {
    resetUpdaterStoreForTests();
  });

  afterEach(() => {
    delete window.electronAPI;
    vi.restoreAllMocks();
    resetUpdaterStoreForTests();
  });

  it('stays hidden while idle', () => {
    installElectronMock();
    render(<UpdateModal />);
    expect(screen.queryByText('NEW VERSION AVAILABLE')).not.toBeInTheDocument();
  });

  it('shows the available version from a broadcast', async () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);
    emit(broadcast({ phase: 'available', version: '2026.10.10' }));

    await waitFor(() => {
      expect(screen.getByText('NEW VERSION AVAILABLE')).toBeInTheDocument();
    });
    expect(screen.getByText('v2026.10.10')).toBeInTheDocument();
  });

  it('stays quiet when a background check fails', async () => {
    // The launch-time check runs on every start: an offline laptop must not get
    // a blocking "UPDATE FAILED" dialog it never asked for.
    const { emit } = installElectronMock();
    render(<UpdateModal />);

    emit(broadcast({ phase: 'error', error: 'net::ERR_INTERNET_DISCONNECTED', trigger: 'auto', version: null }));

    await waitFor(() => {
      expect(screen.queryByText('UPDATE FAILED')).not.toBeInTheDocument();
    });
  });

  it('surfaces a failure the user asked for', async () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);

    emit(broadcast({ phase: 'error', error: 'download stalled', trigger: 'manual', version: '2026.10.10' }));

    await waitFor(() => {
      expect(screen.getByText('UPDATE FAILED')).toBeInTheDocument();
    });
    expect(screen.getByText('download stalled')).toBeInTheDocument();
  });

  it('hydrates a staged update after a restart', async () => {
    // The installer was downloaded in a previous session: main replays it via
    // get-updater-state, and the modal must offer the install immediately.
    installElectronMock({
      getUpdaterState: vi.fn(async () => idleState({
        phase: 'downloaded',
        version: '2026.10.10',
        percent: 100,
        canInstall: true,
        verified: true,
      })),
    });
    render(<UpdateModal />);

    await waitFor(() => {
      expect(screen.getByText('UPDATE READY TO INSTALL')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Install & Restart/i })).not.toBeDisabled();
  });

  it('reaches the ready state when main forwards the downloaded event', async () => {
    const { api, emit } = installElectronMock();
    render(<UpdateModal />);
    emit(broadcast({ phase: 'available', version: '2026.10.10' }));

    await act(async () => {
      screen.getByRole('button', { name: 'Update Now' }).click();
    });
    expect(api.downloadUpdate).toHaveBeenCalledTimes(1);

    emit(broadcast({ phase: 'downloading', version: '2026.10.10', percent: 0 }));
    await waitFor(() => {
      expect(screen.getByText('Downloading...')).toBeInTheDocument();
    });

    emit(broadcast({
      phase: 'downloaded', version: '2026.10.10', percent: 100, canInstall: true, verified: true,
    }));
    await waitFor(() => {
      expect(screen.getByText('UPDATE READY TO INSTALL')).toBeInTheDocument();
    });
  });

  it('shows a stall reported by main as a retryable error', async () => {
    // The watchdog lives in the main process now; the modal only renders the
    // resulting error phase instead of running its own timer.
    const { api, emit } = installElectronMock();
    render(<UpdateModal />);
    emit(broadcast({ phase: 'available', version: '2026.10.10' }));

    emit(broadcast({
      phase: 'error',
      version: '2026.10.10',
      trigger: 'manual',
      error: 'Download stalled — no progress for 120 seconds.',
    }));

    await waitFor(() => {
      expect(screen.getByText('UPDATE FAILED')).toBeInTheDocument();
    });
    expect(screen.getByText(/Download stalled/i)).toBeInTheDocument();

    await act(async () => {
      screen.getByRole('button', { name: 'Try Again' }).click();
    });
    expect(api.checkForUpdates).toHaveBeenCalledTimes(1);
  });

  it('can be dismissed while a download is running and re-surfaces when ready', async () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);
    emit(broadcast({ phase: 'available', version: '2026.10.10' }));
    emit(broadcast({ phase: 'downloading', version: '2026.10.10', percent: 12 }));

    const hide = screen.getByRole('button', { name: 'Hide' });
    expect(hide).not.toBeDisabled();
    await act(async () => {
      hide.click();
    });
    expect(screen.queryByText('Downloading package...')).not.toBeInTheDocument();

    emit(broadcast({
      phase: 'downloaded', version: '2026.10.10', percent: 100, canInstall: true, verified: true,
    }));
    await waitFor(() => {
      expect(screen.getByText('UPDATE READY TO INSTALL')).toBeInTheDocument();
    });
  });

  it('blocks installing when the build cannot verify signatures', async () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);
    emit(broadcast({ phase: 'available', version: '2026.10.10', verification: 'unavailable' }));

    await waitFor(() => {
      expect(screen.getByText(/Automatic updates are disabled in this build/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: 'Update Now' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Download manually' })).not.toBeDisabled();
  });

  it('surfaces a previous install that never applied', async () => {
    const { api, emit } = installElectronMock();
    render(<UpdateModal />);
    emit(broadcast({
      phase: 'available',
      version: '2026.10.10',
      pendingInstall: { version: '2026.10.9', at: Date.now() },
    }));

    await waitFor(() => {
      expect(screen.getByText(/The update to v2026\.10\.9 did not install/i)).toBeInTheDocument();
    });

    await act(async () => {
      screen.getByRole('button', { name: 'Dismiss' }).click();
    });
    expect(api.dismissPendingInstall).toHaveBeenCalledTimes(1);
  });
});

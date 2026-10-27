import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import { UpdateModal } from '@/components/UpdateModal';
import type { ElectronAPI } from '@/types/electron';

type UpdaterMessage = { status: string; data?: unknown };

/**
 * Regression coverage for the 2026.10.9 update stall: the main process stopped
 * forwarding `update-downloaded`, so this modal stayed on "Downloading... 0%"
 * with both buttons disabled and no way out. The component must reach the
 * "ready to install" state from either signal, and must never trap the user.
 */
function installElectronMock(overrides: Partial<ElectronAPI> = {}) {
  let emit: ((msg: UpdaterMessage) => void) | null = null;
  const api: ElectronAPI = {
    getAppVersion: vi.fn(async () => '2026.10.9'),
    checkForUpdates: vi.fn(async () => undefined),
    // Default: a download that never settles (the pathological case).
    downloadUpdate: vi.fn(() => new Promise<void>(() => {})),
    installUpdate: vi.fn(async () => undefined),
    onUpdaterMessage: vi.fn((callback: (msg: UpdaterMessage) => void) => {
      emit = callback;
    }),
    quitApp: vi.fn(),
    openExternal: vi.fn(async () => ({ ok: true })),
    openInApp: vi.fn(async () => ({ ok: true })),
    ...overrides,
  };
  window.electronAPI = api;

  return {
    api,
    emit: (msg: UpdaterMessage) => act(() => emit?.(msg)),
  };
}

function announceUpdate(emit: (msg: UpdaterMessage) => void) {
  emit({ status: 'available', data: { version: '2026.10.9' } });
}

describe('UpdateModal', () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    delete window.electronAPI;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('stays hidden until an update is available', () => {
    installElectronMock();
    render(<UpdateModal />);
    expect(screen.queryByText('NEW VERSION AVAILABLE')).not.toBeInTheDocument();
  });

  it('shows the available version', () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);
    announceUpdate(emit);

    expect(screen.getByText('NEW VERSION AVAILABLE')).toBeInTheDocument();
    expect(screen.getByText('v2026.10.9')).toBeInTheDocument();
  });

  it('reaches the ready state when main forwards the downloaded event', async () => {
    const { api, emit } = installElectronMock();
    render(<UpdateModal />);
    announceUpdate(emit);

    await act(async () => {
      screen.getByRole('button', { name: 'Update Now' }).click();
    });
    expect(api.downloadUpdate).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Downloading...')).toBeInTheDocument();

    emit({ status: 'downloaded', data: { version: '2026.10.9' } });

    await waitFor(() => {
      expect(screen.getByText('UPDATE READY TO INSTALL')).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Install & Restart/i })).toBeInTheDocument();
  });

  it('reaches the ready state from a resolved download even without the event', async () => {
    // Cache hits resolve without ever emitting download-progress or
    // update-downloaded; the resolved promise alone must be enough.
    const { emit } = installElectronMock({ downloadUpdate: vi.fn(async () => undefined) });
    render(<UpdateModal />);
    announceUpdate(emit);

    await act(async () => {
      screen.getByRole('button', { name: 'Update Now' }).click();
    });

    await waitFor(() => {
      expect(screen.getByText('UPDATE READY TO INSTALL')).toBeInTheDocument();
    });
  });

  it('can be dismissed while a download is running', async () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);
    announceUpdate(emit);

    await act(async () => {
      screen.getByRole('button', { name: 'Update Now' }).click();
    });

    const hide = screen.getByRole('button', { name: 'Hide' });
    expect(hide).not.toBeDisabled();

    await act(async () => {
      hide.click();
    });
    expect(screen.queryByText('Downloading package...')).not.toBeInTheDocument();
  });

  it('re-surfaces when the download completes after being hidden', async () => {
    const { emit } = installElectronMock();
    render(<UpdateModal />);
    announceUpdate(emit);

    await act(async () => {
      screen.getByRole('button', { name: 'Update Now' }).click();
    });
    await act(async () => {
      screen.getByRole('button', { name: 'Hide' }).click();
    });
    expect(screen.queryByText('Downloading package...')).not.toBeInTheDocument();

    emit({ status: 'downloaded', data: { version: '2026.10.9' } });

    await waitFor(() => {
      expect(screen.getByText('UPDATE READY TO INSTALL')).toBeInTheDocument();
    });
  });

  it('reports a stall instead of an endless progress bar', async () => {
    vi.useFakeTimers();
    const { emit } = installElectronMock();
    render(<UpdateModal />);

    act(() => announceUpdate(emit));
    act(() => {
      screen.getByRole('button', { name: 'Update Now' }).click();
    });
    expect(screen.getByText('Downloading...')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(90_000);
    });

    expect(screen.getByText(/Download stalled/i)).toBeInTheDocument();
    expect(screen.queryByText('Downloading package...')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry Download' })).not.toBeDisabled();
  });
});

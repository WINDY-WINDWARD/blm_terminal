import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '../utils/renderWithProviders';
import { TerminalContainer } from '@/components/TerminalContainer';
import { SavedLayoutsSyncProvider } from '@/components/SavedLayoutsSyncProvider';
import {
  showSettingsModalAtom,
  settingsModalTabAtom,
  activeCommandAtom,
  activePanelsAtom,
  focusedPanelAtom,
} from '@/store/terminalStore';
import { useAtomValue } from 'jotai';

function StatusWatcher() {
  const isSettingsOpen = useAtomValue(showSettingsModalAtom);
  const activeTab = useAtomValue(settingsModalTabAtom);
  const activePanels = useAtomValue(activePanelsAtom);
  return (
    <div>
      <div data-testid="is-settings-open">{String(isSettingsOpen)}</div>
      <div data-testid="active-settings-tab">{activeTab}</div>
      <div data-testid="panel-1-widget">{activePanels['panel-1']}</div>
    </div>
  );
}

describe('SettingsModal rendering via TerminalContainer', () => {
  it('does not render modal when showSettingsModalAtom is false', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
          ],
        },
      }
    );

    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    expect(screen.queryByText(/TERMINAL SETTINGS/i)).not.toBeInTheDocument();
  });

  it('renders modal when showSettingsModalAtom is true and displays all tabs', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByText(/TERMINAL SETTINGS/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^WORKSPACE$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^CONNECTIONS$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^INTELLIGENCE$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^AUTOMATION$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^SYSTEM$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\[CLOSE\]/i })).toBeInTheDocument();
  });

  it('closes modal via [CLOSE] button', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    const closeBtn = screen.getByRole('button', { name: /\[CLOSE\]/i });
    fireEvent.click(closeBtn);
    expect(screen.getByTestId('is-settings-open').textContent).toBe('false');
  });

  it('closes modal via [X] button', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    const xBtn = screen.getByRole('button', { name: /close settings/i });
    fireEvent.click(xBtn);
    expect(screen.getByTestId('is-settings-open').textContent).toBe('false');
  });

  it('closes modal via Escape key', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, true],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.getByTestId('is-settings-open').textContent).toBe('false');
  });

  it('submitting SETTINGS command opens modal and does not populate focused panel', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
            [focusedPanelAtom, 'panel-1'],
            [activePanelsAtom, { 'panel-1': 'CHART' }],
            [activeCommandAtom, 'SETTINGS'],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    expect(screen.getByTestId('panel-1-widget').textContent).toBe('CHART');
  });

  it('submitting bare LAYOUT command opens Settings modal on workspace tab', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <StatusWatcher />
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showSettingsModalAtom, false],
            [settingsModalTabAtom, 'system'],
            [focusedPanelAtom, 'panel-1'],
            [activePanelsAtom, { 'panel-1': 'CHART' }],
            [activeCommandAtom, 'LAYOUT'],
          ],
        },
      }
    );

    expect(screen.getByTestId('is-settings-open').textContent).toBe('true');
    expect(screen.getByTestId('active-settings-tab').textContent).toBe('workspace');
    expect(screen.getByTestId('panel-1-widget').textContent).toBe('CHART');
  });
});

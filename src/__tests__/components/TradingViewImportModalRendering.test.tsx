import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '../utils/renderWithProviders';
import { TerminalContainer } from '@/components/TerminalContainer';
import { SavedLayoutsSyncProvider } from '@/components/SavedLayoutsSyncProvider';
import { showTradingViewImportModalAtom, watchlistsAtom, activeWatchlistIdAtom } from '@/store/terminalStore';

describe('TradingViewImportModal rendering via TerminalContainer', () => {
  it('does not render modal when showTradingViewImportModalAtom is false', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showTradingViewImportModalAtom, false],
            [watchlistsAtom, [{ id: 1, name: 'Default', created_at: '', updated_at: '', items: [] }]],
            [activeWatchlistIdAtom, 1],
          ],
        },
      }
    );

    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    expect(screen.queryByText(/TradingView Watchlist Import/i)).not.toBeInTheDocument();
  });

  it('renders modal when showTradingViewImportModalAtom is true and allows closing via CANCEL', () => {
    render(
      <SavedLayoutsSyncProvider>
        <TerminalContainer>
          <div data-testid="child-content">Terminal Content</div>
        </TerminalContainer>
      </SavedLayoutsSyncProvider>,
      {
        wrapperProps: {
          initialAtomValues: [
            [showTradingViewImportModalAtom, true],
            [watchlistsAtom, [{ id: 1, name: 'Default', created_at: '', updated_at: '', items: [] }]],
            [activeWatchlistIdAtom, 1],
          ],
        },
      }
    );

    expect(screen.getByText(/TradingView Watchlist Import/i)).toBeInTheDocument();
    expect(screen.getByText(/FILE UPLOAD/i)).toBeInTheDocument();
    expect(screen.getByText(/PASTE SYMBOLS/i)).toBeInTheDocument();
    expect(screen.getByText(/SHARED URL/i)).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    expect(cancelBtn).toBeInTheDocument();
    fireEvent.click(cancelBtn);
  });
});

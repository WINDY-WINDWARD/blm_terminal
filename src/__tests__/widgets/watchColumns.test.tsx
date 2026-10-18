import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { watchlistColumnsAtom } from '@/store/terminalStore';
import { WatchWidget } from '@/components/widgets/WatchWidget';
import { render } from '../utils/renderWithProviders';

vi.mock('@/lib/nseFetch', () => ({
  marketDataService: {
    onChangeRanges: vi.fn(() => () => {}),
    requestChangeRanges: vi.fn(),
    onSymbolData: vi.fn(() => () => {}),
    requestSymbolData: vi.fn(),
  },
}));

function headerText(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole('columnheader')
    .map((header) => header.textContent?.replace(/[⋮⋮▲▼\s]/g, '') ?? '');
}

describe('WatchWidget columns', () => {
  it('reorders data columns by drag without sorting', async () => {
    render(<WatchWidget />, {
      wrapperProps: { initialAtomValues: [[watchlistColumnsAtom, ['ltp', 'chg', '1w']]] },
    });

    await screen.findByText('RELIANCE');
    const table = screen.getByRole('table');
    expect(headerText(table)).toEqual(['✕', 'SYMBOL', 'LTP', 'CHG%', '1W%']);

    const dataTransfer = {
      effectAllowed: 'move',
      setData: vi.fn(),
      getData: vi.fn(),
    };
    const source = within(table).getByRole('columnheader', { name: /1W%/i });
    const target = within(table).getByRole('columnheader', { name: /LTP/i });
    Object.defineProperty(target, 'getBoundingClientRect', {
      value: () => ({ left: 0, width: 100, right: 100, top: 0, bottom: 20, height: 20, x: 0, y: 0, toJSON: () => ({}) }),
    });

    fireEvent.dragStart(source, { dataTransfer });
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    await waitFor(() => {
      expect(headerText(table)).toEqual(['✕', 'SYMBOL', 'LTP', '1W%', 'CHG%']);
    });
    expect(within(table).getByRole('columnheader', { name: /SYMBOL/i })).toHaveAttribute('aria-sort', 'none');
  });

  it('sorts rows when a header is clicked', async () => {
    render(<WatchWidget />, {
      wrapperProps: { initialAtomValues: [[watchlistColumnsAtom, ['ltp', 'chg']]] },
    });

    await screen.findByText('RELIANCE');
    const table = screen.getByRole('table');
    const symbolHeader = within(table).getByRole('columnheader', { name: /SYMBOL/i });
    fireEvent.click(symbolHeader);

    await waitFor(() => {
      const rows = within(table).getAllByRole('row').slice(1);
      expect(rows[0]).toHaveTextContent('HDFCBANK');
      expect(rows[1]).toHaveTextContent('RELIANCE');
      expect(rows[2]).toHaveTextContent('TCS');
    });
    expect(symbolHeader).toHaveAttribute('aria-sort', 'ascending');
  });
});

import { fireEvent, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { useSetAtom } from 'jotai';
import { moversColumnsAtom } from '@/store/terminalStore';
import { MoversWidget } from '@/components/widgets/MoversWidget';
import { server } from '../mocks/msw-server';
import { render } from '../utils/renderWithProviders';

vi.mock('@/lib/nseFetch', () => ({
  marketDataService: {
    onChangeRanges: vi.fn(() => () => {}),
    requestChangeRanges: vi.fn(),
    onSymbolData: vi.fn(() => () => {}),
    requestSymbolData: vi.fn(),
  },
}));

function MoversColumnSettingsProbe() {
  const setColumns = useSetAtom(moversColumnsAtom);
  return <button type="button" onClick={() => setColumns(['vol', '52wh'])}>Enable 52W High</button>;
}


describe('MoversWidget', () => {
  it('shows one matrix view and pages through rows without widget scrolling', async () => {
    const rows = Array.from({ length: 8 }, (_, index) => ({
      symbol: `TEST${index + 1}`,
      lastPrice: 100 + index,
      pChange: 1 + index,
      trade_quantity: 1000,
    }));
    server.use(
      http.get('/api/py/market/top-gainers', () => HttpResponse.json(rows)),
      http.get('/api/py/market/top-losers', () => HttpResponse.json([])),
      http.get('/api/py/market/movers-categories', () => HttpResponse.json([])),
    );
    render(<MoversWidget />);

    const tabs = await screen.findByRole('tablist', { name: /movers views/i });
    expect(within(tabs).getByRole('tab', { name: /matrix/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('movers-widget')).toHaveClass('overflow-hidden');
    expect(await screen.findByText('TEST8')).toBeInTheDocument();
    expect(screen.getByText('TEST3')).toBeInTheDocument();
    expect(screen.queryByText('TEST2')).not.toBeInTheDocument();
    expect(screen.getByText(/PAGE 1 OF 2/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /next page/i }));

    expect(await screen.findByText('TEST2')).toBeInTheDocument();
    expect(screen.getByText('TEST1')).toBeInTheDocument();
    expect(screen.queryByText('TEST8')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /next page/i })).toBeDisabled();
  });

  it('applies optional column settings to the visible matrix', async () => {
    render(<><MoversWidget /><MoversColumnSettingsProbe /></>, {
      wrapperProps: { initialAtomValues: [[moversColumnsAtom, ['vol']]] },
    });

    await screen.findAllByText('RELIANCE');
    const matrix = screen.getByTestId('movers-matrix-table');
    expect(within(matrix).getByRole('columnheader', { name: /volume/i })).toBeInTheDocument();
    expect(within(matrix).queryByRole('columnheader', { name: /52w high/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('CLOSE')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /enable 52w high/i }));

    expect(within(matrix).getByRole('columnheader', { name: /52w high/i })).toBeInTheDocument();
    expect(within(matrix).getByRole('columnheader', { name: /volume/i })).toBeInTheDocument();
  });

  it('switches between matrix, gainer, and loser views', async () => {
    render(<MoversWidget />);

    const tabs = await screen.findByRole('tablist', { name: /movers views/i });
    fireEvent.click(within(tabs).getByRole('tab', { name: /losers/i }));

    expect(within(tabs).getByRole('tab', { name: /losers/i })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findAllByText('INFY')).not.toHaveLength(0);
    expect(screen.queryAllByText('RELIANCE')).toHaveLength(0);
  });
});

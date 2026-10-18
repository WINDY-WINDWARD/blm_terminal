import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { useSetAtom } from 'jotai';
import { moversColumnOrderAtom, moversColumnsAtom } from '@/store/terminalStore';
import { MoversWidget } from '@/components/widgets/MoversWidget';
import { server } from '../mocks/msw-server';
import { render } from '../utils/renderWithProviders';

vi.mock('@/lib/nseFetch', () => ({
  marketDataService: {
    onChangeRanges: vi.fn((handler) => {
      (globalThis as unknown as { __moversRangesHandler?: typeof handler }).__moversRangesHandler = handler;
      return () => {};
    }),
    requestChangeRanges: vi.fn(),
    onSymbolData: vi.fn((handler) => {
      (globalThis as unknown as { __moversSymbolHandler?: typeof handler }).__moversSymbolHandler = handler;
      return () => {};
    }),
    requestSymbolData: vi.fn(),
  },
}));

function matrixRows(table: HTMLElement): string[] {
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => row.textContent ?? '');
}

function columnKeys(table: HTMLElement): string[] {
  return Array.from(table.querySelectorAll<HTMLTableCellElement>('th[data-column-key]'))
    .map((header) => header.dataset.columnKey ?? '');
}

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

  it('makes the active view explicit', async () => {
    render(<MoversWidget />);

    const tabs = await screen.findByRole('tablist', { name: /movers views/i });
    const matrixTab = within(tabs).getByRole('tab', { name: /matrix/i });
    expect(screen.getByText('VIEW:')).toBeInTheDocument();
    expect(matrixTab).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('movers-active-view')).toHaveTextContent(/matrix/i);

    fireEvent.click(within(tabs).getByRole('tab', { name: /gainers/i }));
    expect(within(tabs).getByRole('tab', { name: /gainers/i })).toHaveAttribute('data-active', 'true');
    expect(screen.getByTestId('movers-active-view')).toHaveTextContent(/top gainers/i);
  });

  it('reorders all visible columns by drag and shares that order across views', async () => {
    render(<MoversWidget />, {
      wrapperProps: {
        initialAtomValues: [
          [moversColumnsAtom, ['vol']],
          [moversColumnOrderAtom, ['ticker', 'ltp', 'chg', 'momentum', 'velocity', 'vol', 'radar', '52wh']],
        ],
      },
    });

    await screen.findAllByText('RELIANCE');
    const table = screen.getByTestId('movers-matrix-table');
    expect(columnKeys(table)).toEqual(['ticker', 'ltp', 'chg', 'momentum', 'velocity', 'vol', 'radar']);

    const dataTransfer = { effectAllowed: 'move', setData: vi.fn(), getData: vi.fn() };
    const source = table.querySelector<HTMLElement>('[data-column-key="vol"]')!;
    const target = table.querySelector<HTMLElement>('[data-column-key="ticker"]')!;
    fireEvent.dragStart(source, { dataTransfer });
    fireEvent.dragOver(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    await waitFor(() => {
      expect(columnKeys(table)).toEqual(['ticker', 'vol', 'ltp', 'chg', 'momentum', 'velocity', 'radar']);
    });

    fireEvent.click(screen.getByRole('tab', { name: /gainers/i }));
    await waitFor(() => {
      expect(columnKeys(screen.getByTestId('movers-matrix-table'))).toEqual(['ticker', 'vol', 'ltp', 'chg']);
    });
  });

  it('sorts direct columns and resets to the first page', async () => {
    const rows = [
      { symbol: 'AAA', lastPrice: 100, pChange: 10, trade_quantity: 1000 },
      { symbol: 'BBB', lastPrice: 300, pChange: 5, trade_quantity: 3000 },
      { symbol: 'CCC', lastPrice: 200, pChange: 1, trade_quantity: 2000 },
    ];
    server.use(
      http.get('/api/py/market/top-gainers', () => HttpResponse.json(rows)),
      http.get('/api/py/market/top-losers', () => HttpResponse.json([])),
      http.get('/api/py/market/movers-categories', () => HttpResponse.json([])),
    );
    render(<MoversWidget />);

    await screen.findByText('AAA');
    const table = screen.getByTestId('movers-matrix-table');
    expect(matrixRows(table).map((text) => text.match(/AAA|BBB|CCC/)?.[0])).toEqual(['AAA', 'BBB', 'CCC']);

    const ltpHeader = within(table).getByRole('columnheader', { name: /LTP/i });
    fireEvent.click(ltpHeader);

    await waitFor(() => {
      expect(matrixRows(table).map((text) => text.match(/AAA|BBB|CCC/)?.[0])).toEqual(['BBB', 'CCC', 'AAA']);
    });
    expect(ltpHeader).toHaveAttribute('aria-sort', 'descending');

    fireEvent.click(ltpHeader);
    await waitFor(() => {
      expect(matrixRows(table).map((text) => text.match(/AAA|BBB|CCC/)?.[0])).toEqual(['AAA', 'CCC', 'BBB']);
    });
    expect(ltpHeader).toHaveAttribute('aria-sort', 'ascending');
  });

  it('sorts the computed velocity column when ranges arrive', async () => {
    const rows = [
      { symbol: 'AAA', lastPrice: 100, pChange: 1, trade_quantity: 1000 },
      { symbol: 'BBB', lastPrice: 100, pChange: 10, trade_quantity: 1000 },
    ];
    server.use(
      http.get('/api/py/market/top-gainers', () => HttpResponse.json(rows)),
      http.get('/api/py/market/top-losers', () => HttpResponse.json([])),
      http.get('/api/py/market/movers-categories', () => HttpResponse.json([])),
    );
    render(<MoversWidget />);

    await screen.findByText('AAA');
    const table = screen.getByTestId('movers-matrix-table');
    const rangesHandler = (globalThis as unknown as {
      __moversRangesHandler?: (symbol: string, ranges: unknown) => void;
    }).__moversRangesHandler;
    const ranges = {
      oneDayPercent: 1,
      oneWeekPercent: 1,
      oneMonthPercent: 1,
      threeMonthPercent: 1,
      sixMonthPercent: 1,
      oneYearPercent: 1,
      twoYearPercent: 1,
      threeYearPercent: 1,
      fiveYearPercent: 1,
    };
    act(() => {
      rangesHandler?.('AAA', ranges);
      rangesHandler?.('BBB', {
        ...ranges,
        oneWeekPercent: -1,
        oneMonthPercent: -1,
        threeMonthPercent: -1,
        sixMonthPercent: -1,
        oneYearPercent: -1,
      });
    });

    fireEvent.click(within(table).getByRole('columnheader', { name: /velocity score/i }));
    await waitFor(() => {
      expect(matrixRows(table).map((text) => text.match(/AAA|BBB/)?.[0])).toEqual(['AAA', 'BBB']);
    });
  });
});

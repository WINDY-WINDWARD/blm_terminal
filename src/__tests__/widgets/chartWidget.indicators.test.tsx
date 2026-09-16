import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { render } from '../utils/renderWithProviders';
import { ChartWidget } from '@/components/widgets/ChartWidget';
import { createChart } from 'lightweight-charts';
import { marketDataService } from '@/lib/nseFetch';

vi.mock('lightweight-charts', async () => {
  const mock = await import('../mocks/lightweightCharts');
  return mock;
});

const DAILY = {
  symbol: 'RELIANCE',
  count: 30,
  candles: Array.from({ length: 30 }, (_, i) => ({
    Date: `2026-08-${String(i + 1).padStart(2, '0')}`,
    open: 100 + i,
    high: 102 + i,
    low: 99 + i,
    close: 101 + i,
    volume: 1000 + i * 10,
  })),
};

function mockFetch() {
  vi.spyOn(global, 'fetch').mockImplementation((url) => {
    if (typeof url === 'string' && url.includes('/api/py/stockuniverse/search/')) {
      return Promise.resolve({ ok: true, json: async () => [] } as Response);
    }
    return Promise.resolve({ ok: true, json: async () => DAILY } as Response);
  });
}

function mockTicks() {
  const handlers = new Set<(s: string, d: unknown) => void>();
  vi.spyOn(marketDataService, 'onSymbolData').mockImplementation((h) => {
    handlers.add(h as (s: string, d: unknown) => void);
    return () => {
      handlers.delete(h as (s: string, d: unknown) => void);
    };
  });
  vi.spyOn(marketDataService, 'requestSymbolData').mockImplementation(() => {});
  return handlers;
}

describe('ChartWidget indicators + LIVE overlay', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    mockFetch();
  });

  it('checkbox menu adds up to 6 indicators, blocks the 7th', async () => {
    mockTicks();
    render(<ChartWidget panelId="chart-ind" />);

    await waitFor(() => {
      expect(screen.getByText('Fx')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Fx'));
    // Check SMA, EMA, RSI via their row checkboxes
    const smaBox = screen.getByTitle('Show Moving Average (SMA)');
    fireEvent.click(smaBox);
    expect(screen.getByText('Fx 1')).toBeInTheDocument();

    fireEvent.click(screen.getByTitle('Show Moving Average (EMA)'));
    fireEvent.click(screen.getByTitle('Show RSI'));
    fireEvent.click(screen.getByTitle('Show MACD'));
    fireEvent.click(screen.getByTitle('Show Volume'));
    fireEvent.click(screen.getByTitle('Show ATR'));
    expect(screen.getByText('Fx 6')).toBeInTheDocument();

    // 7th blocked with hint
    expect(
      screen.getByText(/Max 6 visible — uncheck one to show another/),
    ).toBeInTheDocument();
    const stochBox = screen.getByTitle('Show Stochastic') as HTMLInputElement;
    expect(stochBox.disabled).toBe(true);
  });

  it('unchecking frees a slot: a different indicator can be checked, params kept', async () => {
    mockTicks();
    render(<ChartWidget panelId="chart-ind-free" />);

    await waitFor(() => {
      expect(screen.getByText('Fx')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Fx'));
    for (const label of [
      'Show Moving Average (SMA)',
      'Show Moving Average (EMA)',
      'Show RSI',
      'Show MACD',
      'Show Volume',
      'Show ATR',
    ]) {
      fireEvent.click(screen.getByTitle(label));
    }
    expect(screen.getByText('Fx 6')).toBeInTheDocument();

    // Tune SMA, then uncheck it — slot frees, entry + params persist
    fireEvent.click(screen.getAllByTitle('Settings')[0]);
    fireEvent.change(screen.getAllByDisplayValue('20')[0], { target: { value: '50' } });
    fireEvent.click(screen.getByTitle('Show Moving Average (SMA)'));
    expect(screen.getByText('Fx 5')).toBeInTheDocument();

    // A different indicator can now be checked despite 6 stored entries
    fireEvent.click(screen.getByTitle('Show Stochastic'));
    expect(screen.getByText('Fx 6')).toBeInTheDocument();

    // The hidden SMA entry is still stored with its tuned param
    fireEvent.click(screen.getByTitle('Show Moving Average (SMA)')); // would exceed → blocked
    expect(screen.getByText('Fx 6')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Show Stochastic')); // free the slot again
    fireEvent.click(screen.getByTitle('Show Moving Average (SMA)')); // load back
    expect(screen.getByText('Fx 6')).toBeInTheDocument();
    fireEvent.click(screen.getAllByTitle('Settings')[0]);
    expect(screen.getByDisplayValue('50')).toBeInTheDocument();
  });

  it('unchecking hides the overlay but keeps the entry (params survive)', async () => {
    mockTicks();
    render(<ChartWidget panelId="chart-ind-hide" />);

    await waitFor(() => {
      expect(screen.getByText('Fx')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Fx'));
    fireEvent.click(screen.getByTitle('Show RSI'));
    expect(screen.getByText('Fx 1')).toBeInTheDocument();

    // Tune a param via settings, then uncheck
    fireEvent.click(screen.getByTitle('Settings'));
    const periodInput = screen.getByDisplayValue('14') as HTMLInputElement;
    fireEvent.change(periodInput, { target: { value: '21' } });
    fireEvent.click(screen.getByTitle('Show RSI')); // uncheck → hidden
    expect(screen.getByText('Fx')).toBeInTheDocument(); // visible count back to 0
    expect(screen.queryByText('Fx 1')).not.toBeInTheDocument();

    // Re-check → entry restored with tuned param
    fireEvent.click(screen.getByTitle('Show RSI'));
    expect(screen.getByText('Fx 1')).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Settings'));
    expect(screen.getByDisplayValue('21')).toBeInTheDocument();
  });

  it('removes an indicator via row ✕', async () => {
    mockTicks();
    render(<ChartWidget panelId="chart-ind-rm" />);

    await waitFor(() => {
      expect(screen.getByText('Fx')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Fx'));
    fireEvent.click(screen.getByTitle('Show Volume'));
    expect(screen.getByText('Fx 1')).toBeInTheDocument();

    fireEvent.click(screen.getByTitle('Remove'));
    expect(screen.getByText('Fx')).toBeInTheDocument();
    // Menu stayed open: checkbox is unchecked again
    expect((screen.getByTitle('Show Volume') as HTMLInputElement).checked).toBe(false);
  });

  it('creates a LIVE price line when a fresh tick arrives', async () => {
    // Pin clock to Monday 10:00 IST (inside NSE hours) so the tick counts as fresh.
    const marketOpenMs = Date.UTC(2026, 8, 14, 4, 30, 0);
    vi.spyOn(Date, 'now').mockReturnValue(marketOpenMs);
    const handlers = mockTicks();
    render(<ChartWidget panelId="chart-live" />);

    await waitFor(() => {
      expect(marketDataService.requestSymbolData).toHaveBeenCalledWith(['RELIANCE']);
    });

    // Push a fresh tick through the subscribed handler
    for (const h of handlers) {
      h('RELIANCE', { ltp: 150.5, pChange: 1.2, yearHigh: 200, yearLow: 100 });
    }

    await waitFor(() => {
      expect(screen.getByText(/LIVE 150\.50/)).toBeInTheDocument();
    });

    // The mocked chart instance should have a price line created on the main series
    const chartInstance = (createChart as ReturnType<typeof vi.fn>).mock.results.at(-1)?.value;
    expect(chartInstance).toBeDefined();
    const mainSeries = chartInstance.addSeries.mock.results[0]?.value;
    expect(mainSeries.createPriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 150.5, title: 'LIVE' }),
    );
  });

  it('symbol switch clears overlays (extra panes removed)', async () => {
    mockTicks();
    render(<ChartWidget panelId="chart-switch" />);

    await waitFor(() => {
      expect(screen.getByPlaceholderText('RELIANCE')).toBeInTheDocument();
    });

    // Add an oscillator (creates an extra pane), then switch symbol
    fireEvent.click(screen.getByText('Fx'));
    fireEvent.click(screen.getByTitle('Show RSI'));

    const input = screen.getByPlaceholderText('RELIANCE');
    fireEvent.change(input, { target: { value: 'TCS' } });
    fireEvent.submit(input.closest('form') as HTMLFormElement);

    const chartInstance = (createChart as ReturnType<typeof vi.fn>).mock.results.at(-1)?.value;
    await waitFor(() => {
      // removePane called during teardown of the symbol switch
      expect(chartInstance.removePane).toHaveBeenCalled();
    });
  });
});


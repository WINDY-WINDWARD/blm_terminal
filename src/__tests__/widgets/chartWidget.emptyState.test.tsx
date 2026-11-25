import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import React from 'react';
import { render } from '../utils/renderWithProviders';
import { ChartWidget } from '@/components/widgets/ChartWidget';
import { visibleRangeHandlers } from '../mocks/lightweightCharts';
import { marketDataService } from '@/lib/nseFetch';
import { historyCache } from '@/lib/chartHistory';

vi.mock('lightweight-charts', async () => {
  const mock = await import('../mocks/lightweightCharts');
  return mock;
});

const DAILY = {
  symbol: 'RELIANCE',
  count: 1,
  candles: [{ Date: '2026-08-01', open: 99, high: 101, low: 98, close: 100, volume: 1000 }],
};

const EMPTY_INTRADAY = { symbol: 'RELIANCE', interval: '5m', candles: [], count: 0 };

const POPULATED_INTRADAY = {
  symbol: 'RELIANCE',
  interval: '5m',
  count: 1,
  candles: [
    { timestamp: 1795619400000, open: 100, high: 101, low: 99, close: 100.5, volume: 1000 },
  ],
};

function mockFetch(intradayBody: unknown) {
  vi.spyOn(global, 'fetch').mockImplementation((url) => {
    if (typeof url === 'string') {
      if (url.includes('/api/py/stockuniverse/search/')) {
        return Promise.resolve({ ok: true, json: async () => [] } as Response);
      }
      if (url.includes('/api/py/ticker/intraday/')) {
        return Promise.resolve({ ok: true, json: async () => intradayBody } as Response);
      }
      if (url.includes('/api/py/ticker/ohlcv/')) {
        return Promise.resolve({ ok: true, json: async () => DAILY } as Response);
      }
    }
    return Promise.resolve({ ok: true, json: async () => DAILY } as Response);
  });
}

function mockTicks() {
  vi.spyOn(marketDataService, 'onSymbolData').mockImplementation(() => () => {});
  vi.spyOn(marketDataService, 'requestSymbolData').mockImplementation(() => {});
}

async function mountIntraday() {
  render(<ChartWidget panelId="chart-empty" />);
  await waitFor(() => {
    expect(screen.getByText('Fx')).toBeInTheDocument();
  });
  // Daily interval must never show the badge.
  expect(screen.queryByText(/No candles returned/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '5m' }));
}

describe('ChartWidget empty intraday state', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    visibleRangeHandlers.clear();
    historyCache.clear();
  });

  it('shows the no-candles badge when the intraday window is empty', async () => {
    mockFetch(EMPTY_INTRADAY);
    mockTicks();
    await mountIntraday();

    expect(await screen.findByText(/No candles returned/)).toBeInTheDocument();
  });

  it('hides the badge when intraday candles exist', async () => {
    mockFetch(POPULATED_INTRADAY);
    mockTicks();
    await mountIntraday();

    await waitFor(() => {
      expect(screen.getByText(/EOD as of/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/No candles returned/)).not.toBeInTheDocument();
  });
});

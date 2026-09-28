import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import React from 'react';
import { render } from '../utils/renderWithProviders';
import { ChartWidget } from '@/components/widgets/ChartWidget';
import { createChart, visibleRangeHandlers } from '../mocks/lightweightCharts';
import { marketDataService } from '@/lib/nseFetch';
import { historyCache } from '@/lib/chartHistory';

vi.mock('lightweight-charts', async () => {
  const mock = await import('../mocks/lightweightCharts');
  return mock;
});

const candle = (date: string, close: number) => ({
  Date: date,
  open: close - 1,
  high: close + 1,
  low: close - 2,
  close,
  volume: 1000,
});

// Head window: 30 bars, 2026-08-01..30.
const HEAD = {
  symbol: 'RELIANCE',
  count: 30,
  candles: Array.from({ length: 30 }, (_, i) =>
    candle(`2026-08-${String(i + 1).padStart(2, '0')}`, 100 + i),
  ),
};

// Backfill window: 10 older bars, 2024-07-01..10.
const OLDER = {
  symbol: 'RELIANCE',
  count: 10,
  candles: Array.from({ length: 10 }, (_, i) =>
    candle(`2024-07-${String(i + 1).padStart(2, '0')}`, 50 + i),
  ),
};

function mockFetch() {
  const calls: string[] = [];
  vi.spyOn(global, 'fetch').mockImplementation((url) => {
    if (typeof url === 'string') {
      calls.push(url);
      if (url.includes('/api/py/stockuniverse/search/')) {
        return Promise.resolve({ ok: true, json: async () => [] } as Response);
      }
      if (url.includes('/api/py/ticker/ohlcv/')) {
        // Older-window fetches carry a 2024 from_date.
        const body = url.includes('2024') ? OLDER : HEAD;
        return Promise.resolve({ ok: true, json: async () => body } as Response);
      }
    }
    return Promise.resolve({ ok: true, json: async () => HEAD } as Response);
  });
  return calls;
}

function mockTicks() {
  vi.spyOn(marketDataService, 'onSymbolData').mockImplementation(() => () => {});
  vi.spyOn(marketDataService, 'requestSymbolData').mockImplementation(() => {});
}

function mainSeries() {
  const chart = (
    createChart as unknown as {
      mock: { results: { value: { addSeries: { mock: { results: { value: unknown }[] } } } }[] };
    }
  ).mock.results[0].value;
  return chart.addSeries.mock.results[0].value as {
    setData: ReturnType<typeof vi.fn>;
  };
}

function timeScaleWithSubscription() {
  const chart = (
    createChart as unknown as {
      mock: {
        results: {
          value: {
            timeScale: {
              mock: {
                results: {
                  value: {
                    subscribeVisibleLogicalRangeChange: { mock: { calls: unknown[][] } };
                    setVisibleLogicalRange: ReturnType<typeof vi.fn>;
                    getVisibleLogicalRange: ReturnType<typeof vi.fn>;
                  };
                }[];
              };
            };
          };
        }[];
      };
    }
  ).mock.results[0].value;
  const inst = chart.timeScale.mock.results.find(
    (r) => r.value.subscribeVisibleLogicalRangeChange.mock.calls.length > 0,
  );
  return inst?.value;
}

describe('ChartWidget scroll-back history', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    visibleRangeHandlers.clear();
    historyCache.clear();
  });

  it('scrolling near bar 0 fetches the older window and prepends without yanking', async () => {
    const calls = mockFetch();
    mockTicks();
    render(<ChartWidget panelId="chart-backfill" />);

    await waitFor(() => {
      expect(screen.getByText('Fx')).toBeInTheDocument();
    });
    // Head window painted (30 bars).
    await waitFor(() => {
      const s = mainSeries();
      const last = s.setData.mock.calls.at(-1)?.[0] as { time: number }[];
      expect(last?.length).toBe(30);
    });

    // Pan left: visible edge within 50 bars of bar 0.
    expect(visibleRangeHandlers.size).toBeGreaterThan(0);
    for (const h of [...visibleRangeHandlers]) h({ from: 5, to: 60 });

    // Older window fetched with a 2024 from_date (2-year chunk back).
    await waitFor(() => {
      expect(calls.some((u) => u.includes('/api/py/ticker/ohlcv/') && u.includes('2024'))).toBe(true);
    });

    // Merged paint: 40 bars ascending, viewport restored (+10 shift).
    await waitFor(() => {
      const s = mainSeries();
      const last = s.setData.mock.calls.at(-1)?.[0] as { time: number }[];
      expect(last?.length).toBe(40);
      const times = last.map((b) => b.time);
      expect([...times].sort((a, b) => a - b)).toEqual(times);
    });
    const ts = timeScaleWithSubscription();
    expect(ts?.setVisibleLogicalRange).toBeDefined();
    const shifted = (ts!.setVisibleLogicalRange as ReturnType<typeof vi.fn>).mock.calls;
    expect(shifted.length).toBeGreaterThan(0);
    expect(shifted.at(-1)?.[0]).toEqual({ from: 15, to: 70 });
  });

  it('does not fetch when the viewport is mid-range', async () => {
    const calls = mockFetch();
    mockTicks();
    render(<ChartWidget panelId="chart-nofetch" />);

    await waitFor(() => {
      expect(screen.getByText('Fx')).toBeInTheDocument();
    });
    const before = calls.filter((u) => u.includes('/api/py/ticker/ohlcv/')).length;
    for (const h of [...visibleRangeHandlers]) h({ from: 500, to: 560 });
    await new Promise((r) => setTimeout(r, 200));
    const after = calls.filter((u) => u.includes('/api/py/ticker/ohlcv/')).length;
    expect(after).toBe(before);
  });
});

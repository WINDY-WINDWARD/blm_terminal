import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { render } from '../utils/renderWithProviders';
import { ChartWidget } from '@/components/widgets/ChartWidget';

vi.mock('lightweight-charts', () => {
  return {
    createChart: () => ({
      applyOptions: vi.fn(),
      timeScale: () => ({
        fitContent: vi.fn(),
        getVisibleLogicalRange: vi.fn(() => ({ from: 60, to: 120 })),
        setVisibleLogicalRange: vi.fn(),
        subscribeVisibleLogicalRangeChange: vi.fn(),
        unsubscribeVisibleLogicalRangeChange: vi.fn(),
      }),
      addSeries: vi.fn().mockReturnValue({
        setData: vi.fn(),
        update: vi.fn(),
        priceScale: () => ({ applyOptions: vi.fn() }),
        createPriceLine: vi.fn(),
        removePriceLine: vi.fn(),
      }),
      removeSeries: vi.fn(),
      removePane: vi.fn(),
      panes: vi.fn(() => [{ setStretchFactor: vi.fn() }]),
      priceScale: () => ({ applyOptions: vi.fn() }),
      remove: vi.fn(),
      resize: vi.fn(),
    }),
    ColorType: { Solid: 'solid' },
    LineStyle: { Solid: 0, Dotted: 1, Dashed: 2, LargeDashed: 3, SparseDotted: 4 },
    CandlestickSeries: 'Candlestick',
    LineSeries: 'line',
    HistogramSeries: 'histogram',
  };
});

describe('ChartWidget Autocomplete', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('renders input with default placeholder and searches symbols on input', async () => {
    const mockResults = [
      { symbol: 'TCS', companyName: 'Tata Consultancy Services Limited' },
      { symbol: 'TATAMOTORS', companyName: 'Tata Motors Limited' },
    ];

    vi.spyOn(global, 'fetch').mockImplementation((url) => {
      if (typeof url === 'string' && url.includes('/api/py/stockuniverse/search/')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockResults,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ symbol: 'TCS', candles: [], count: 0 }),
      } as Response);
    });

    render(<ChartWidget panelId="test-chart-panel" />);

    const symbolInput = screen.getByPlaceholderText('RELIANCE');
    expect(symbolInput).toBeInTheDocument();

    fireEvent.change(symbolInput, { target: { value: 'TAT' } });

    await waitFor(() => {
      expect(screen.getByText('TCS')).toBeInTheDocument();
      expect(screen.getByText('Tata Consultancy Services Limited')).toBeInTheDocument();
      expect(screen.getByText('TATAMOTORS')).toBeInTheDocument();
    });
  });

  it('selects suggestion when clicked', async () => {
    const mockResults = [
      { symbol: 'INFY', companyName: 'Infosys Limited' },
    ];

    vi.spyOn(global, 'fetch').mockImplementation((url) => {
      if (typeof url === 'string' && url.includes('/api/py/stockuniverse/search/')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockResults,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ symbol: 'INFY', candles: [], count: 0 }),
      } as Response);
    });

    render(<ChartWidget panelId="test-chart-panel" />);

    const symbolInput = screen.getByPlaceholderText('RELIANCE') as HTMLInputElement;
    fireEvent.change(symbolInput, { target: { value: 'INF' } });

    await waitFor(() => {
      expect(screen.getByText('INFY')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('INFY'));

    expect(symbolInput.value).toBe('INFY');
    expect(screen.queryByText('Infosys Limited')).not.toBeInTheDocument();
  });

  it('supports keyboard navigation with ArrowDown, ArrowUp, Enter, and Escape', async () => {
    const mockResults = [
      { symbol: 'INFY', companyName: 'Infosys Limited' },
      { symbol: 'ITC', companyName: 'ITC Limited' },
    ];

    vi.spyOn(global, 'fetch').mockImplementation((url) => {
      if (typeof url === 'string' && url.includes('/api/py/stockuniverse/search/')) {
        return Promise.resolve({
          ok: true,
          json: async () => mockResults,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ symbol: 'ITC', candles: [], count: 0 }),
      } as Response);
    });

    render(<ChartWidget panelId="test-chart-panel" />);

    const symbolInput = screen.getByPlaceholderText('RELIANCE') as HTMLInputElement;
    fireEvent.change(symbolInput, { target: { value: 'I' } });

    await waitFor(() => {
      expect(screen.getByText('INFY')).toBeInTheDocument();
      expect(screen.getByText('ITC')).toBeInTheDocument();
    });

    // Navigate down to second item and select with Enter
    fireEvent.keyDown(symbolInput, { key: 'ArrowDown' });
    fireEvent.keyDown(symbolInput, { key: 'ArrowDown' });
    fireEvent.keyDown(symbolInput, { key: 'Enter' });

    expect(symbolInput.value).toBe('ITC');
    expect(screen.queryByText('ITC Limited')).not.toBeInTheDocument();

    // Escape closes dropdown
    fireEvent.change(symbolInput, { target: { value: 'INF' } });
    await waitFor(() => {
      expect(screen.getByText('INFY')).toBeInTheDocument();
    });
    fireEvent.keyDown(symbolInput, { key: 'Escape' });
    expect(screen.queryByText('INFY')).not.toBeInTheDocument();
  });
});

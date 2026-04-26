import { vi } from 'vitest';

export const createChart = vi.fn(() => ({
  addSeries: vi.fn(() => ({
    setData: vi.fn(),
    update: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
  })),
  remove: vi.fn(),
  applyOptions: vi.fn(),
  timeScale: vi.fn(() => ({
    fitContent: vi.fn(),
    setVisibleRange: vi.fn(),
  })),
  subscribeCrosshairMove: vi.fn(),
  unsubscribeCrosshairMove: vi.fn(),
}));

export const ColorType = {
  Solid: 'solid',
  Gradient: 'gradient',
};

export const CandlestickSeries = 'candlestick';
export const LineSeries = 'line';
export const AreaSeries = 'area';
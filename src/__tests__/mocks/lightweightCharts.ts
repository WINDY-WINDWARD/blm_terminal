import { vi } from 'vitest';

const makeSeries = () => ({
  setData: vi.fn(),
  update: vi.fn(),
  priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
  createPriceLine: vi.fn(() => ({ id: Math.random() })),
  removePriceLine: vi.fn(),
});

export const createChart = vi.fn(() => {
  const series: ReturnType<typeof makeSeries>[] = [];
  const panes: { setStretchFactor: ReturnType<typeof vi.fn> }[] = [
    { setStretchFactor: vi.fn() },
  ];
  return {
    addSeries: vi.fn((_def: unknown, _opts?: unknown, paneIndex?: number) => {
      // Mirror v5 behavior: adding a series at a new pane index creates the pane.
      const idx = paneIndex ?? 0;
      while (panes.length <= idx) panes.push({ setStretchFactor: vi.fn() });
      const s = makeSeries();
      series.push(s);
      return s;
    }),
    removeSeries: vi.fn((s: unknown) => {
      const i = series.indexOf(s as (typeof series)[number]);
      if (i >= 0) series.splice(i, 1);
    }),
    addPane: vi.fn(() => {
      const p = { setStretchFactor: vi.fn() };
      panes.push(p);
      return p;
    }),
    removePane: vi.fn((index: number) => {
      panes.splice(index, 1);
    }),
    panes: vi.fn(() => panes),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({
      fitContent: vi.fn(),
      setVisibleRange: vi.fn(),
    })),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
  };
});

export const ColorType = {
  Solid: 'solid',
  Gradient: 'gradient',
};

export const LineStyle = {
  Solid: 0,
  Dotted: 1,
  Dashed: 2,
  LargeDashed: 3,
  SparseDotted: 4,
};

export const CandlestickSeries = 'candlestick';
export const LineSeries = 'line';
export const AreaSeries = 'area';
export const HistogramSeries = 'histogram';

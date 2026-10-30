import type { WidgetTourDefinition } from '../types';

export const breakoutsTour: WidgetTourDefinition = {
  command: 'BREAKOUTS',
  title: '52-Week Breakouts',
  steps: [
    {
      id: 'breakouts-view-tabs',
      anchor: 'breakouts-tabs',
      title: 'Radar View Tabs',
      body: 'ALL MATRIX shows four cards at once. The other tabs open a full table for 52W High, 52W Low, Volume Shockers, or Repeated breakouts. The tour opens 52W HIGH next.',
      actions: [{ selector: '[data-widget-tour-click="tab-matrix"]' }],
    },
    {
      id: 'breakouts-high-table',
      anchor: 'breakouts-rows',
      title: '52-Week High Table',
      body: 'Each row is a stock at a new 52-week high. Read Change against the previous close, and Vol Shocker to see how far volume exceeds the average.',
      actions: [{ selector: '[data-widget-tour-click="tab-high"]' }],
    },
    {
      id: 'breakouts-matrix-grid',
      anchor: 'breakouts-matrix',
      title: 'Four-Card Matrix Grid',
      body: 'The matrix compares highs, lows, volume shocks, and repeated persistence side by side. Counts at the top of each card show how many stocks qualify.',
      actions: [{ selector: '[data-widget-tour-click="tab-matrix"]' }],
    },
    {
      id: 'breakouts-volume-shockers',
      anchor: 'breakouts-volume',
      title: 'Volume Shockers Radar',
      body: 'Volume expansion shows institutional footprint. Compare Wk1 and Wk2 average volume to see if the surge is new or already cooling.',
      actions: [{ selector: '[data-widget-tour-click="tab-volume"]' }],
    },
    {
      id: 'breakouts-repeated',
      anchor: 'breakouts-rows',
      title: 'Repeated Breakouts',
      body: 'A repeated breakout stays on the list across sessions. Appearances and Window show persistence. Replay this tour from DOCS with both panels open.',
      actions: [{ selector: '[data-widget-tour-click="tab-repeated"]' }],
    },
  ],
};

import type { WidgetTourDefinition } from '../types';

export const topTour: WidgetTourDefinition = {
  command: 'TOP',
  title: 'Top Movers',
  steps: [
    {
      id: 'movers-universe-bar',
      anchor: 'movers-universe-bar',
      title: 'Market Universe',
      body: 'Pick the index or sector universe. Every table below is scoped to it, so a NIFTY 50 view and a BANKNIFTY view never mix.',
    },
    {
      id: 'movers-view-tabs',
      anchor: 'movers-view-tabs',
      title: 'Matrix, Gainers and Losers',
      body: 'The tour is switching to the gainers list now. The matrix ranks by multi-period momentum, while gainers and losers rank by the current day move.',
      actions: [{ selector: 'view-gainers' }],
    },
    {
      id: 'movers-matrix-columns',
      anchor: 'movers-matrix-columns',
      title: 'Momentum, Velocity and Radar',
      body: 'Back on the matrix: the momentum strip shows 1W to 1Y returns, velocity scores alignment from 0 to 100, and radar names the trend as ALL BULLISH down to ALL BEARISH.',
      actions: [{ selector: 'view-matrix' }],
    },
    {
      id: 'movers-filter-input',
      anchor: 'movers-filter-input',
      title: 'Filter Ticker',
      body: 'Type part of a ticker to narrow the rows. The filter applies to the current view and keeps the active sort.',
    },
    {
      id: 'movers-pagination-controls',
      anchor: 'movers-pagination-controls',
      title: 'Pagination',
      body: 'Each page holds six rows. Page forward without losing the sort. Replay this tour from DOCS with both panels open.',
    },
  ],
};

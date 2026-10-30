import type { WidgetTourDefinition } from '../types';

export const topTour: WidgetTourDefinition = {
  command: 'TOP',
  title: 'Top Movers',
  steps: [
    {
      id: 'movers-universe-bar',
      anchor: 'movers-universe-bar',
      title: 'Market Universe',
      body: 'Choose the index or sector universe to scope the scan. The table updates with symbols from that universe.',
    },
    {
      id: 'movers-view-tabs',
      anchor: 'movers-view-tabs',
      title: 'View Modes',
      body: 'Switch between the momentum matrix, top gainers, and top losers. The matrix tracks returns across multiple timeframes.',
    },
    {
      id: 'movers-matrix-columns',
      anchor: 'movers-matrix-columns',
      title: 'Momentum and Alignment',
      body: 'Read momentum, velocity, and radar together to gauge trend strength. Note the BULL or BEAR badge next to each ticker.',
    },
    {
      id: 'movers-filter-input',
      anchor: 'movers-filter-input',
      title: 'Filter Ticker',
      body: 'Filter rows by entering a ticker substring. Matching symbols display immediately.',
    },
    {
      id: 'movers-pagination-controls',
      anchor: 'movers-pagination-controls',
      title: 'Pagination Controls',
      body: 'Page through rows without losing your active sort order. You can replay this tour from DOCS with both panels open.',
    },
  ],
};

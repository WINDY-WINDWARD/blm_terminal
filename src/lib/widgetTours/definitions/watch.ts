import type { WidgetTourDefinition } from '../types';

export const watchTour: WidgetTourDefinition = {
  command: 'WATCH',
  title: 'Watchlist',
  steps: [
    {
      id: 'select-watchlist',
      anchor: 'watch-selector-deck',
      title: 'Pick a watchlist',
      body: 'Use LIST to switch lists. The + button creates a list. IMPORT copies a TradingView list into this app.',
      placement: 'below',
    },
    {
      id: 'add-symbol',
      anchor: 'watch-add-symbol-form',
      title: 'Add symbols',
      body: 'Type a ticker and pick a suggestion. Set the exchange first. Then press +ADD to add the symbol to the active list.',
      placement: 'below',
    },
    {
      id: 'read-breadth',
      anchor: 'watch-breadth-indicator',
      title: 'Read breadth',
      body: 'SORT shows the active sort order. ADV and DEC count the stocks that are up and down today. Use the gap as a quick breadth read.',
      placement: 'below',
    },
    {
      id: 'use-table',
      anchor: 'watch-table-header',
      title: 'Sort and reorder columns',
      body: 'Click a header to sort. Drag a header to move the column. Long-horizon columns show 2Y, 3Y and 5Y returns next to the 52-week range.',
      placement: 'below',
    },
    {
      id: 'review-alerts',
      anchor: 'watch-alerts-cell',
      title: 'Check alerts',
      body: 'The bell shows the unread alert count. Open it to load a chart, open the company, or ask AI to summarize. Click a row to set the global symbol. Replay this tour from DOCS with both panels open.',
      placement: 'below',
    },
  ],
};

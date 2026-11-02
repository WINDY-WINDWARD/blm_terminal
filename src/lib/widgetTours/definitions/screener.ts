import type { WidgetTourDefinition } from '../types';

export const screenerTour: WidgetTourDefinition = {
  command: 'SCREENER',
  title: 'Stock Screener (TQL)',
  steps: [
    {
      id: 'screener-intervals',
      anchor: 'screener-intervals',
      title: 'Interval Selection',
      body: 'Daily, 1h, Weekly, and Monthly change the candles that indicators use. The tour opens Weekly, then returns to Daily.',
      actions: [{ selector: '[data-widget-tour-click="interval-W"]' }],
    },
    {
      id: 'screener-query',
      anchor: 'screener-query',
      title: 'TQL Query Input',
      body: 'Type filter expressions with autocomplete for fields, operators, and sectors. Press Run to scan the universe. Unprefixed indicators use the active interval.',
      actions: [{ selector: '[data-widget-tour-click="interval-1d"]' }],
    },
    {
      id: 'screener-actions',
      anchor: 'screener-actions',
      title: 'Header Actions',
      body: 'TQL opens the syntax reference. CSV exports the current result set. Clear resets the query. Refresh reruns the same query.',
    },
    {
      id: 'screener-table',
      anchor: 'screener-table',
      title: 'Results Table',
      body: 'Columns follow the indicators in your query. Read 52H % and 52L % as distance from the yearly range. Click a row to set the active symbol. Replay this tour from DOCS with both panels open.',
      optional: true,
    },
  ],
};

import type { WidgetTourDefinition } from '../types';

export const screenerTour: WidgetTourDefinition = {
  command: 'SCREENER',
  title: 'Stock Screener (TQL)',
  steps: [
    {
      id: 'screener-actions',
      anchor: 'screener-actions',
      title: 'Header Actions',
      body: 'Use the action bar to review TQL syntax, export filtered results to CSV, clear filters, or refresh the cache.',
    },
    {
      id: 'screener-intervals',
      anchor: 'screener-intervals',
      title: 'Interval Selection',
      body: 'Switch between Daily, 1h, Weekly, and Monthly intervals. Unprefixed indicators calculate over the active timeframe.',
    },
    {
      id: 'screener-query',
      anchor: 'screener-query',
      title: 'TQL Query Input',
      body: 'Type filter expressions with automatic syntax suggestions for fields, operators, and sectors. Press Enter or click Run to scan the stock universe.',
    },
    {
      id: 'screener-table',
      anchor: 'screener-table',
      title: 'Screener Results Table',
      body: 'Inspect indicator columns, review valuation gaps against Morningstar fair value, and click a row to set the active symbol. Replay this tour from DOCS with both panels open.',
    },
  ],
};

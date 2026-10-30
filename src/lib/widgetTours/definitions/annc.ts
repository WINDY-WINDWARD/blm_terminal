import type { WidgetTourDefinition } from '../types';

export const anncTour: WidgetTourDefinition = {
  command: 'ANNC',
  title: 'Corporate Announcements',
  steps: [
    {
      id: 'annc-tabs',
      anchor: 'annc-tabs',
      title: 'Five Filing Categories',
      body: 'RESULTS, ALL, CORP ACTION, BOARD, and AGM/EGM. The tour keeps RESULTS selected first, because that is the default view.',
      placement: 'below',
      actions: [{ selector: 'tab-results' }],
    },
    {
      id: 'annc-results-split',
      anchor: 'annc-results-split',
      title: 'Upcoming and Announced',
      body: 'The RESULTS tab splits into Upcoming board meetings with dates, and Announced filings already published. Results dates are the ones that move a stock.',
      placement: 'below',
    },
    {
      id: 'annc-tabs-corp',
      anchor: 'annc-tabs',
      title: 'Corporate Actions',
      body: 'The tour switched to CORP ACTION. Dividends, splits, bonus issues, and buybacks appear here with the exchange filing attached.',
      placement: 'below',
      actions: [{ selector: 'tab-corp-action' }],
    },
    {
      id: 'annc-search',
      anchor: 'annc-search',
      title: 'Search Filings',
      body: 'Search by company name, ticker, subject, or description. The filter applies to the tab you are on and clears when you switch tabs.',
      placement: 'below',
    },
    {
      id: 'annc-filing-open',
      anchor: 'annc-filing-open',
      title: 'Open the Source Filing',
      body: 'Click a row to open the filing in the in-app reader. An XML badge opens the structured filing viewer. Ctrl+click sends it to the system browser. Replay this tour from DOCS with both panels open.',
      placement: 'below',
      actions: [{ selector: 'tab-results' }],
    },
  ],
};

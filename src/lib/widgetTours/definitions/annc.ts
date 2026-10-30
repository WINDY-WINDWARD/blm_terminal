import type { WidgetTourDefinition } from '../types';

export const anncTour: WidgetTourDefinition = {
  command: 'ANNC',
  title: 'Corporate Announcements',
  steps: [
    {
      id: 'annc-categories',
      anchor: 'annc-tabs',
      title: 'Announcement Categories',
      body: 'Switch between RESULTS, ALL, CORP ACTION, BOARD, and AGM/EGM. View record counts, sync time, and refresh filings on demand.',
      placement: 'below',
    },
    {
      id: 'annc-split-schedule',
      anchor: 'annc-results-split',
      title: 'Split Results Schedule',
      body: 'Inspect Upcoming board meetings alongside Announced results. Upcoming entries reveal upcoming catalysts before filings arrive.',
      placement: 'below',
    },
    {
      id: 'annc-filter-filings',
      anchor: 'annc-search',
      title: 'Search and Filter Filings',
      body: 'Filter filings and calendar entries by company name, description, or subject. Clear the filter instantly with the cross button.',
      placement: 'below',
    },
    {
      id: 'annc-open-filing',
      anchor: 'annc-filing-open',
      title: 'Inspect and Open Filings',
      body: 'Click a row to open the filing. XML links launch the in-app viewer and other links open the reader. Replay this tour from DOCS with both panels open.',
      placement: 'above',
    },
  ],
};


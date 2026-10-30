import type { WidgetTourDefinition } from '../types';

export const notifTour: WidgetTourDefinition = {
  command: 'NOTIF',
  title: 'Notifications',
  steps: [
    {
      id: 'notif-scope-selector',
      anchor: 'notif-scope-selector',
      title: 'Watchlist & Date Scope',
      body: 'Filter alerts by active watchlist or select all symbols. Choose a specific trading date or view all recorded dates.',
    },
    {
      id: 'notif-view-mode',
      anchor: 'notif-view-mode',
      title: 'Live Stream & Heatmap Views',
      body: 'Switch between the LIVE ALERTS stream and the INDUSTRY HEATMAP. Heatmap cards colour by alert count and open a drill-down modal.',
    },
    {
      id: 'notif-category-matrix',
      anchor: 'notif-category-matrix',
      title: 'Filter & Severity Matrix',
      body: 'Filter signals across 11 trigger categories, severity levels, and streak presets. Severity indicates signal urgency, not market direction. A streak reflects momentum, not valuation.',
    },
    {
      id: 'notif-subfilters',
      anchor: 'notif-subfilters',
      title: 'Trigger Sub-Filters',
      body: 'Type trigger names into the search bar with autocomplete. Combine specific triggers or use the streak day stepper to refine queries.',
    },
    {
      id: 'notif-alert-card',
      anchor: 'notif-alert-card',
      title: 'Alert Stream Cards',
      body: 'Inspect parameters, severity badges, and MTF indicators. MTF means timeframes agree. Alerts are computed signals, not financial advice. Replay this tour from DOCS with both panels open.',
    },
  ],
};

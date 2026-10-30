import type { WidgetTourDefinition } from '../types';

export const notifTour: WidgetTourDefinition = {
  command: 'NOTIF',
  title: 'Notifications',
  steps: [
    {
      id: 'notif-scope',
      anchor: 'notif-scope-selector',
      title: 'Watchlist and Date Scope',
      body: 'These two dropdowns set the scope. The first picks a watchlist or every symbol you track. The second picks one trading date or all recorded dates.',
      placement: 'below',
    },
    {
      id: 'notif-views',
      anchor: 'notif-view-mode',
      title: 'Stream and Heatmap',
      body: 'Two views sit behind these tabs. LIVE ALERTS is a chronological stream. INDUSTRY HEATMAP groups the same alerts by sector.',
      placement: 'below',
    },
    {
      id: 'notif-view-heatmap',
      anchor: 'notif-heatmap',
      title: 'Industry Heatmap',
      body: 'This is the heatmap view. The banner counts industries and signals. Amber cards hold six or more alerts, so the busiest sector stands out first.',
      placement: 'below',
      actions: [{ selector: '[data-widget-tour-click="view-heatmap"]' }],
    },
    {
      id: 'notif-view-stream',
      anchor: 'notif-view-mode',
      title: 'Back to the Live Stream',
      body: 'The tour returns to the stream. Alerts refresh every 30 seconds while the feed is live. The pause button freezes the list so a card does not move while you read it.',
      placement: 'below',
      actions: [{ selector: '[data-widget-tour-click="view-stream"]' }],
    },
    {
      id: 'notif-categories',
      anchor: 'notif-categories',
      title: 'Signal Categories',
      body: 'Eleven categories filter the feed. Each button shows its own count, so you can see where the signals cluster before you click.',
      placement: 'right',
    },
    {
      id: 'notif-read-filter',
      anchor: 'notif-read-filter',
      title: 'Read Status',
      body: 'Unread, read, or all. Read state is stored per user, so clearing the feed does not delete the alert.',
      placement: 'right',
    },
    {
      id: 'notif-card',
      anchor: 'notif-alert-card',
      title: 'Alert Card',
      body: 'Each card shows the symbol, trigger, severity, and the measured parameter. CRITICAL marks a structural event such as a 52-week break. HIGH marks an active condition such as an RSI extreme. Details expands the raw payload. Replay this tour from DOCS with both panels open.',
      placement: 'left',
      optional: true,
      actions: [{ selector: '[data-widget-tour-click="view-stream"]' }],
    },
  ],
};

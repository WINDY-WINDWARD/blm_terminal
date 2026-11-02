import type { WidgetTourDefinition } from '../types';

export const scanTour: WidgetTourDefinition = {
  command: 'SCAN',
  title: 'Global Scan',
  steps: [
    {
      id: 'scan-universe',
      anchor: 'scan-scope',
      title: 'Universe and Date',
      body: 'SCAN starts on ALL (GLOBAL SCAN), so it reads every NSE symbol instead of your watchlist. The date dropdown limits the search to one session or every stored session.',
      placement: 'below',
    },
    {
      id: 'scan-views',
      anchor: 'scan-view-mode',
      title: 'Stream and Heatmap',
      body: 'The same two views as NOTIF. The stream lists alerts in time order. The heatmap groups them by industry across the whole universe.',
      placement: 'below',
    },
    {
      id: 'scan-view-heatmap',
      anchor: 'scan-heatmap',
      title: 'Sector Concentration',
      body: 'The banner counts the industries and signals in the current window. Open an amber card to see every alerting stock in that sector. A cluster of alerts in one sector often marks an institutional flow.',
      placement: 'below',
      actions: [{ selector: '[data-widget-tour-click="view-heatmap"]' }],
    },
    {
      id: 'scan-categories',
      anchor: 'scan-categories',
      title: 'Signal Categories',
      body: 'Back on the stream, these eleven buttons filter by trigger family. Each count shows how many signals the universe produced in that family.',
      placement: 'right',
      actions: [{ selector: '[data-widget-tour-click="view-stream"]' }],
    },
    {
      id: 'scan-card',
      anchor: 'scan-alert-card',
      title: 'Universe Alert Card',
      body: 'A card names the symbol, the trigger, the severity, and the measured value. Severity ranks urgency within the scan. It does not rank the size of a possible move.',
      placement: 'left',
      optional: true,
    },
    {
      id: 'scan-card-actions',
      anchor: 'scan-popout-actions',
      title: 'Inspect Without Losing Context',
      body: 'Load Chart and Company open separate windows. The scan stays on screen. Replay this tour from DOCS with both panels open.',
      placement: 'left',
      optional: true,
    },
  ],
};

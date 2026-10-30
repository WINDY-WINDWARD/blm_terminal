import type { WidgetTourDefinition } from '../types';

export const scanTour: WidgetTourDefinition = {
  command: 'SCAN',
  title: 'Global Market Scanner',
  steps: [
    {
      id: 'scan-scope-selector',
      anchor: 'scan-scope',
      title: 'Universe Scope & Date Filter',
      body: 'Defaults to ALL (GLOBAL SCAN) across the entire stock universe. Choose a specific trading date or view all recorded dates.',
    },
    {
      id: 'scan-industry-heatmap',
      anchor: 'scan-heatmap-toggle',
      title: 'Sector Heatmap Concentration',
      body: 'Switch to the INDUSTRY HEATMAP to spot sectoral momentum concentration. Uses the pre-aggregated industry summary and opens a drill-down modal.',
    },
    {
      id: 'scan-filter-matrix',
      anchor: 'scan-filters',
      title: 'Signal Categories & Severity',
      body: 'Filter signals across 11 trigger categories, severity levels, and streak presets. Severity ranks event urgency, not market direction. Treat hits as research leads, not trades.',
    },
    {
      id: 'scan-popout-window-actions',
      anchor: 'scan-popout-actions',
      title: 'Independent Card Actions',
      body: 'Open detached chart or company windows without changing the terminal grid symbol. Replay this tour from DOCS with both panels open.',
    },
  ],
};

import type { WidgetTourDefinition } from '../types';

export const analysisTour: WidgetTourDefinition = {
  command: 'ANALYSIS',
  title: 'Sector & Industry Analysis',
  steps: [
    {
      id: 'analysis-tabs',
      anchor: 'analysis-tabs',
      title: 'Analysis Navigation Tabs',
      body: 'Switch between Summary, Sectors, Industries, and Heatmap views to examine market structure at different levels.',
    },
    {
      id: 'analysis-kpis',
      anchor: 'analysis-kpis',
      title: 'Summary KPI Deck',
      body: 'Track market advance-decline breadth, total NSE market capitalization, average P/E, and median earnings growth.',
    },
    {
      id: 'analysis-cockpit',
      anchor: 'analysis-cockpit',
      title: 'Category Detail Cockpit',
      body: 'Review category valuation metrics, advance-decline donut breakdown, trend insights, and constituent stocks table.',
    },
    {
      id: 'analysis-actions',
      anchor: 'analysis-actions',
      title: 'Constituent Row Actions',
      body: 'Open an instant chart, view the company page, or save any constituent stock to a watchlist.',
    },
    {
      id: 'analysis-heatmap',
      anchor: 'analysis-heatmap',
      title: 'Market Heatmap Grid',
      body: 'Inspect category tiles colored by metric intensity, and click any tile to open its detail drawer. Replay this tour from DOCS when both DOCS and ANALYSIS are open.',
    },
  ],
};

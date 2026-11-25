import type { WidgetTourDefinition } from '../types';

export const analysisTour: WidgetTourDefinition = {
  command: 'ANALYSIS',
  title: 'Sector & Industry Analysis',
  steps: [
    {
      id: 'analysis-tabs',
      anchor: 'analysis-tabs',
      title: 'Four Analysis Views',
      body: 'Summary reads the whole market. Sectors and Industries open a split cockpit. Heatmap colors every category by the metric you choose. The tour walks through all four.',
      actions: [{ selector: '[data-widget-tour-click="tab-summary"]' }],
    },
    {
      id: 'analysis-kpis',
      anchor: 'analysis-kpis',
      title: 'Market Breadth, Cap and Earnings',
      body: 'Breadth compares advancers with decliners across the scoped universe. Total cap is the summed market value. Earnings YoY is the median growth of the sector set, so one large company cannot pull it.',
      placement: 'below',
    },
    {
      id: 'analysis-rail',
      anchor: 'analysis-rail',
      title: 'Sector Rail',
      body: 'Click any sector to load its cockpit on the right. The number beside the heading is how many categories are in scope.',
      actions: [{ selector: '[data-widget-tour-click="tab-sectors"]' }],
      placement: 'right',
    },
    {
      id: 'analysis-stats',
      anchor: 'analysis-stats',
      title: 'Category Scorecard',
      body: 'Six cells summarize the selected sector: market cap, P/E, day change, advancers, decliners and breadth. Read the breadth pair first, then the valuation cells.',
      placement: 'below',
    },
    {
      id: 'analysis-actions',
      anchor: 'analysis-actions',
      title: 'Act On A Constituent',
      body: 'Every constituent row opens the company page on click. The row buttons open a detached chart, the company view, or a watchlist picker. The terminal symbol does not change.',
      placement: 'above',
    },
    {
      id: 'analysis-heat-controls',
      anchor: 'analysis-heat-controls',
      title: 'Heatmap Scope And Metric',
      body: 'Scope sets Sectors, Industries or All. The metric sets the color: breadth, earnings, sentiment or performance. The sort control decides tile order, and the arrow flips it.',
      actions: [{ selector: '[data-widget-tour-click="tab-heatmap"]' }],
      placement: 'below',
    },
    {
      id: 'analysis-heat-legend',
      anchor: 'analysis-heat-legend',
      title: 'Read The Color Scale',
      body: 'The legend names the active metric and shows its five buckets, from strong selling to strong buying. Click a bucket to isolate it. Click clear to show every tile again.',
      placement: 'below',
    },
    {
      id: 'analysis-heatmap',
      anchor: 'analysis-heatmap',
      title: 'Tile Map And Drawer',
      body: 'Tile area is uniform, so color carries the meaning. Click a tile to open the constituent drawer with LTP, change and P/E. Replay this tour from DOCS with ANALYSIS open.',
      placement: 'above',
    },
  ],
};

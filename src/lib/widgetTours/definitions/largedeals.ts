import type { WidgetTourDefinition } from '../types';

export const largedealsTour: WidgetTourDefinition = {
  command: 'LARGEDEALS',
  title: 'Institutional Deals Radar',
  steps: [
    {
      id: 'largedeals-categories',
      anchor: 'largedeals-tabs',
      title: 'Deal Categories',
      body: 'Each tab is a separate filing feed: BULK DEALS, BLOCK DEALS, SHORT DEALS, and FII / DII RADAR. The tour opens FII / DII RADAR next.',
      placement: 'below',
      actions: [{ selector: '[data-widget-tour-click="tab-bulk"]' }],
    },
    {
      id: 'largedeals-fii-radar',
      anchor: 'largedeals-table',
      title: 'Institutional Net Flow',
      body: 'FII / DII RADAR replaces the table with net flow by institution. Positive net flow is accumulation. Negative net flow is distribution.',
      placement: 'above',
      actions: [{ selector: '[data-widget-tour-click="tab-fii"]' }],
    },
    {
      id: 'largedeals-read-flow',
      anchor: 'largedeals-kpis',
      title: 'Read the Flow',
      body: 'Turnover is the total value in view. Buy flow shows accumulation. Sell flow shows distribution. Bias compares the two.',
      placement: 'below',
      actions: [{ selector: '[data-widget-tour-click="tab-bulk"]' }],
    },
    {
      id: 'largedeals-filter-deals',
      anchor: 'largedeals-filters',
      title: 'Filter the Feed',
      body: 'Search a symbol or client. Select BUY or SELL. Set a minimum value in crore rupees to hide small trades.',
      placement: 'below',
    },
    {
      id: 'largedeals-inspect-trade',
      anchor: 'largedeals-table',
      title: 'Inspect a Trade',
      body: 'Read WATP as the effective trade price. Use CHART or COMPANY to open the stock in a separate window. Replay this tour from DOCS with both panels open.',
      placement: 'above',
    },
  ],
};

import type { WidgetTourDefinition } from '../types';

export const largedealsTour: WidgetTourDefinition = {
  command: 'LARGEDEALS',
  title: 'Institutional Deals Radar',
  steps: [
    {
      id: 'largedeals-categories',
      anchor: 'largedeals-tabs',
      title: 'Deal Categories',
      body: 'Switch between bulk, block, and short deals. FII / DII RADAR shows institutional net flow instead of a table.',
      placement: 'below',
    },
    {
      id: 'largedeals-filter-deals',
      anchor: 'largedeals-filters',
      title: 'Filter the Feed',
      body: 'Search a symbol or client. Select BUY or SELL. Set a minimum value in crore rupees to hide small trades.',
      placement: 'below',
    },
    {
      id: 'largedeals-read-flow',
      anchor: 'largedeals-kpis',
      title: 'Read the Flow',
      body: 'Turnover is the total value in view. Buy flow shows accumulation and sell flow shows distribution. Bias compares the two.',
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

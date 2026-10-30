import type { WidgetTourDefinition } from '../types';

export const posTour: WidgetTourDefinition = {
  command: 'POS',
  title: 'Positions & P&L',
  steps: [
    {
      id: 'pos-mode-toggle',
      anchor: 'pos-mode-toggle',
      title: 'Execution Mode & Sub-Tabs',
      body: 'Switch between LIVE broker positions and PAPER simulation. Paper mode provides OPEN and CLOSED sub-tabs to inspect active and completed trades.',
    },
    {
      id: 'pos-kpi-deck',
      anchor: 'pos-kpi-deck',
      title: 'Portfolio P&L Metrics',
      body: 'Review total, realized, and unrealized profit and loss. Realized P&L tracks booked gains, while unrealized P&L tracks open market risk.',
    },
    {
      id: 'pos-matrix-table',
      anchor: 'pos-matrix-table',
      title: 'Position Contract Matrix',
      body: 'Inspect net quantity direction, average execution price, live LTP, current holding value, and mark-to-market returns for each open contract.',
    },
    {
      id: 'pos-add-leg-action',
      anchor: 'pos-add-leg-action',
      title: 'Multi-Leg Averaging',
      body: 'Add order legs to existing paper positions. New tranches recalculate your position volume and weighted average purchase price.',
    },
    {
      id: 'pos-square-off-action',
      anchor: 'pos-square-off-action',
      title: 'Position Liquidation',
      body: 'Square off paper holdings or submit live broker exit orders with explicit confirmation. Replay this tour anytime from DOCS with both panels open.',
    },
  ],
};

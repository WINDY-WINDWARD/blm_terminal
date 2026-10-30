import type { WidgetTourDefinition } from '../types';

export const posTour: WidgetTourDefinition = {
  command: 'POS',
  title: 'Positions & P&L',
  steps: [
    {
      id: 'pos-mode-toggle',
      anchor: 'pos-mode-toggle',
      title: 'Live or Paper',
      body: 'LIVE reads the OpenAlgo position book. PAPER runs a simulated ledger stored on this machine. The toggle appears only when the broker gateway is connected. The tour opens PAPER next.',
      optional: true,
      actions: [{ selector: '[data-widget-tour-click="mode-paper"]' }],
    },
    {
      id: 'pos-paper-tabs',
      anchor: 'pos-paper-tabs',
      title: 'Open and Closed Trades',
      body: 'Open shows trades still held. Closed shows realised results. The tour opens CLOSED, then returns to OPEN.',
      optional: true,
      actions: [{ selector: '[data-widget-tour-click="tab-closed"]' }],
    },
    {
      id: 'pos-kpi-deck',
      anchor: 'pos-kpi-deck',
      title: 'Portfolio P&L',
      body: 'Total combines realised and floating P&L. REALIZED is booked from closed legs. UNREALIZED is marked to the live price and moves while the market is open.',
      actions: [{ selector: '[data-widget-tour-click="tab-open"]' }],
    },
    {
      id: 'pos-matrix-table',
      anchor: 'pos-matrix-table',
      title: 'Position Matrix',
      body: 'NET QTY is signed. A negative quantity is a short. CURRENT VALUE is quantity times LTP. P&L is the difference against AVG BUY.',
    },
    {
      id: 'pos-add-leg-action',
      anchor: 'pos-add-leg-action',
      title: 'Multi-Leg Averaging',
      body: 'ADD LEG adds a tranche to a paper position. The average buy price recalculates as a weighted average across all legs.',
      optional: true,
    },
    {
      id: 'pos-square-off-action',
      anchor: 'pos-square-off-action',
      title: 'Square Off',
      body: 'SQUARE OFF closes a paper trade or sends a live broker exit. Live exits ask for confirmation first. Replay this tour from DOCS with both panels open.',
      optional: true,
    },
  ],
};

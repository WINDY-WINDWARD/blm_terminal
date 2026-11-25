import type { WidgetTourDefinition } from '../types';

export const orderTour: WidgetTourDefinition = {
  command: 'ORDER',
  title: 'Order Entry & Book',
  steps: [
    {
      id: 'order-instrument-setup',
      anchor: 'order-instrument-setup',
      title: 'Instrument Setup',
      body: 'Pick the market exchange and trading symbol. Quick instrument pills load live prices directly into the ticket.',
    },
    {
      id: 'order-type-selector',
      anchor: 'order-type-lot-selector',
      title: 'Order Types',
      body: 'The tour selected LMT, so the LIMIT PRICE field is now live. MKT executes at the touch, SL and SL-M wait for the trigger price. The order is not sent here.',
      actions: [{ selector: 'type-lmt' }],
    },
    {
      id: 'order-product-selector',
      anchor: 'order-product-selector',
      title: 'Product and Leverage',
      body: 'MIS is intraday with leverage, CNC is delivery, NRML carries F&O overnight. The EST. MARGIN line below the ticket reflects this choice.',
    },
    {
      id: 'order-risk-kpi-deck',
      anchor: 'order-risk-kpi-deck',
      title: 'Account Margins & Risk',
      body: 'Available cash, collateral, and M2M come from the gateway. The utilisation bar marks 50% as comfortable and 85% as the margin call zone.',
    },
    {
      id: 'order-execution-buttons',
      anchor: 'order-execution-buttons',
      title: 'Order Execution Deck',
      body: 'BUY and SELL transmit through OpenAlgo, also on F1 and F2. The inline banner reports broker acceptance or rejection. The tour never presses these buttons.',
    },
    {
      id: 'order-book-table',
      anchor: 'order-book-table',
      title: 'Audit Trail and Order Book',
      body: 'Filter by COMPLETE, PENDING, or REJECTED and click a symbol to reload the ticket. Replay this tour from DOCS with both panels open.',
    },
  ],
};

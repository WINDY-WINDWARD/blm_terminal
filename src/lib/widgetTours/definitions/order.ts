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
      id: 'order-type-lot-selector',
      anchor: 'order-type-lot-selector',
      title: 'Order Types and Lots',
      body: 'Select MKT, LMT, SL, or SL-M with MIS, CNC, or NRML products. Quick lot buttons adjust execution size instantly.',
    },
    {
      id: 'order-execution-buttons',
      anchor: 'order-execution-buttons',
      title: 'Order Execution Deck',
      body: 'Transmit BUY and SELL orders using buttons or F1 and F2 keys. The inline status banner confirms broker acceptance or rejection.',
    },
    {
      id: 'order-risk-kpi-deck',
      anchor: 'order-risk-kpi-deck',
      title: 'Account Margins & Risk',
      body: 'Monitor available cash, collateral, and M2M metrics. The utilisation bar highlights the 50% threshold and 85% margin call level.',
    },
    {
      id: 'order-book-table',
      anchor: 'order-book-table',
      title: 'Audit Trail and Order Book',
      body: 'Filter orders by status and audit execution timestamps. Click any symbol to reload the ticket. You can replay this tour from DOCS with both panels open.',
    },
  ],
};

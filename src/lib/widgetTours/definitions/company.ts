import type { WidgetTourDefinition } from '../types';

export const companyTour: WidgetTourDefinition = {
  command: 'COMPANY',
  title: 'Company Overview & Fundamentals',
  steps: [
    {
      id: 'company-tabs',
      anchor: 'company-tabs',
      title: 'Five Company Tabs',
      body: 'Fundamentals, Deals, News, Alerts, and Corporate. The tour opens the tab it describes. The active symbol stays on the right.',
      placement: 'below',
      actions: [{ selector: 'tab-fundamentals' }],
    },
    {
      id: 'company-ratios',
      anchor: 'company-ratios',
      title: 'Core Ratios and Piotroski Score',
      body: 'The top grid holds Market Cap, CMP, P/E, Book Value, ROCE, ROE, the 52-week range, dividend yield, and the Piotroski score. A Piotroski score of 8 or 9 marks strong accounting quality.',
      placement: 'below',
    },
    {
      id: 'company-valuation',
      anchor: 'company-valuation',
      title: 'Intrinsic Valuation Models',
      body: 'DCF, Graham, DDM, and PEG each give a fair value and an upside percentage. Green upside means the model sees the stock below fair value. Red means above.',
      placement: 'below',
    },
    {
      id: 'company-deals',
      anchor: 'company-deals',
      title: 'Deals, Insider Trades and SAST',
      body: 'Bulk deals, block deals, insider trades, and SAST disclosures for this company. The count on each pill shows how many records exist. A cluster of insider buys is stronger than a single trade.',
      placement: 'below',
      actions: [{ selector: 'tab-deals' }, { selector: 'deals-insider' }],
    },
    {
      id: 'company-corporate',
      anchor: 'company-corporate',
      title: 'Corporate Records',
      body: 'Board meetings, dividends, capital history, and legal cases sit in collapsible sections. Replay this tour from DOCS with both panels open.',
      placement: 'below',
      actions: [{ selector: 'tab-corporate' }],
    },
  ],
};

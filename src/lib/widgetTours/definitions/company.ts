import type { WidgetTourDefinition } from '../types';

export const companyTour: WidgetTourDefinition = {
  command: 'COMPANY',
  title: 'Company Overview & Fundamentals',
  steps: [
    {
      id: 'company-tabs',
      anchor: 'company-tabs',
      title: 'Company Navigation Tabs',
      body: 'Switch between Fundamentals, Deals, News, Alerts, and Corporate disclosures. The active symbol displays on the right.',
      placement: 'below',
    },
    {
      id: 'company-fundamentals',
      anchor: 'company-fundamentals',
      title: 'Core Ratios and Accounting Health',
      body: 'Review key financial metrics including Market Cap, P/E, ROCE, and ROE. Check the Piotroski Score to assess accounting quality.',
      placement: 'below',
    },
    {
      id: 'company-valuation',
      anchor: 'company-valuation',
      title: 'Intrinsic Valuation Models',
      body: 'Inspect fair value targets and upside percentages across DCF, Graham, DDM, and PEG models. Adjust WACC and terminal growth inputs.',
      placement: 'below',
    },
    {
      id: 'company-corporate',
      anchor: 'company-corporate',
      title: 'Corporate Filings and Disclosures',
      body: 'Track statutory board meetings, dividend actions, capital history, and legal disputes. You can replay this tour from DOCS with both panels open.',
      placement: 'below',
    },
  ],
};

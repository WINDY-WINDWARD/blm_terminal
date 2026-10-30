import type { DocField, WidgetDoc } from '../types';

export const companyDoc: WidgetDoc = {
  command: 'COMPANY',
  title: 'Company Overview & Fundamentals',
  summary:
    'Consolidated fundamental research, deal records, company news, and statutory corporate disclosures across five tabs.',
  kind: 'panel',
  order: 60,
  screenshot: {
    src: '/docs/widgets/COMPANY.png',
    alt: 'Company Fundamentals widget screenshot',
    caption: 'Company Overview & Fundamentals as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A single-stock research workspace with five focused tabs: FUNDAMENTALS, DEALS, NEWS, ALERTS, and CORPORATE. It brings together Screener ratios, intrinsic valuation models, institutional deal flow, live news, and regulatory filings for the active symbol.',
    },
    {
      heading: 'Controls',
      items: [
        {
          name: 'Navigation tabs',
          desc: 'Click FUNDAMENTALS, DEALS, NEWS, ALERTS, or CORPORATE to change the active pane.',
        },
        {
          name: 'Show / Hide Metrics toggle',
          desc: 'Click Show n Metrics ▼ to expand extra Screener ratios. Click Hide Metrics ▲ to collapse them.',
        },
        {
          name: 'Valuation WACC selector',
          desc: 'Select a Weighted Average Cost of Capital from 10% to 15% to recalculate the DCF model.',
        },
        {
          name: 'Valuation Terminal Growth selector',
          desc: 'Select a long-term terminal growth rate from 3% to 7% to update terminal value.',
        },
        {
          name: 'Valuation recalculate button',
          desc: 'Click ↺ to recompute intrinsic valuation models with current assumptions.',
        },
        {
          name: 'Deals sub-tabs',
          desc: 'Switch between BULK, BLOCK, INSIDER, and SAST transaction records.',
        },
        {
          name: 'Deals client filter',
          desc: 'Type in the search field to filter transaction records by client or entity name.',
        },
        {
          name: 'Corporate disclosure accordions',
          desc: 'Click any section header to expand or collapse statutory filings, meetings, dividends, or litigation records.',
        },
      ] as DocField[],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'MARKET CAP',
          desc: 'Total market capitalization in ₹ crore. Indicates business scale and market valuation band.',
        },
        {
          name: 'CURRENT PRICE',
          desc: 'Latest traded price for the instrument on the primary exchange.',
        },
        {
          name: 'P/E',
          desc: 'Price to earnings ratio. Higher numbers indicate premium growth expectations. Lower numbers may suggest undervaluation or earnings risk.',
        },
        {
          name: 'BOOK VALUE',
          desc: 'Net asset value per share. Comparing price to book value reveals asset backing per share.',
        },
        {
          name: 'ROCE',
          desc: 'Return on Capital Employed. Measures how efficiently total capital yields operating profit. Higher values indicate efficient capital use.',
        },
        {
          name: 'ROE',
          desc: 'Return on Equity. Measures profitability generated on shareholder equity funds.',
        },
        {
          name: '52W HIGH / 52W LOW',
          desc: 'Highest and lowest execution prices reached in the preceding 52 weeks. Sits as a reference range for current price levels.',
        },
        {
          name: 'DIV YIELD',
          desc: 'Dividend yield percentage. Reflects trailing annual cash dividend payout relative to current market price.',
        },
        {
          name: 'FACE VALUE',
          desc: 'Stated nominal share value recorded in company capital documentation.',
        },
        {
          name: 'PIOTROSKI SCORE',
          desc: 'Accounting health score from 0 to 9. Scores of 8 to 9 indicate strong operational and balance-sheet health. Scores of 0 to 2 suggest financial distress.',
        },
        {
          name: 'INTRINSIC VALUATION MATRIX',
          desc: 'Intrinsic model estimates including DCF, Graham Number, DDM, and PEG fair values. Positive upside means the model target exceeds the current market price.',
        },
        {
          name: 'DEALS TAB COLUMNS',
          desc: 'Transaction audit fields showing date, symbol, client name, action BUY or SELL, quantity, trade price, and total value in ₹ crore.',
        },
        {
          name: 'SAST DISCLOSURES',
          desc: 'Substantial Acquisition of Shares and Takeovers disclosures. Highlights significant promoter or institutional stake shifts.',
        },
        {
          name: 'NSE MARKET SNAPSHOT',
          desc: 'Corporate tab comparative snapshot displaying stock P/E, Sector P/E, 52W High (green), and 52W Low (red).',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Fundamentals and core ratios load from Screener. Deals and corporate disclosures flow through iInvest integration. When iInvest is unavailable, the banner displays OFFLINE (REDUCED MODE) and those disclosure panels remain empty. A SELECT A SYMBOL prompt appears when no global symbol is active.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour has 5 steps and opens each view it describes: 1) the five tabs, 2) the core ratio grid and Piotroski score, 3) the DCF / Graham / DDM / PEG valuation card, 4) the Deals tab with Insider Trades selected, and 5) the Corporate records. It returns to the tab that was active before it started. To replay it, open DOCS in another panel, keep the COMPANY panel open, then click REPLAY TOUR.',
    },
  ],
};

import type { DocField, WidgetDoc } from '../types';

export const largedealsDoc: WidgetDoc = {
  command: 'LARGEDEALS',
  title: 'Institutional Deals Radar',
  summary:
    'Bulk, block, and short deals plus FII and DII net flow for the latest NSE and BSE filing session.',
  kind: 'panel',
  order: 70,
  screenshot: {
    src: '/docs/widgets/LARGEDEALS.png',
    alt: 'Institutional Deals widget screenshot',
    caption: 'Institutional deals, flow KPIs, and the deal table in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A filing feed of large trades by institutions, promoters, and other reported clients. Four tabs separate bulk deals, block deals, short deals, and FII / DII net flow. Four KPI cards summarise the value, direction, and bias of the trades in view.',
    },
    {
      heading: 'Controls',
      items: [
        {
          name: 'Deal tabs',
          desc: 'BULK DEALS, BLOCK DEALS, SHORT DEALS, and FII / DII RADAR. Each tab loads its own records. The badge shows the record count for that tab.',
        },
        {
          name: 'Search box',
          desc: 'Filters the table by symbol, company name, or client name as you type.',
        },
        {
          name: 'ALL / BUY / SELL',
          desc: 'Filters rows by deal direction. ALL shows both directions.',
        },
        {
          name: 'Value pills',
          desc: 'ALL CR, ≥ 5Cr, ≥ 20Cr, and ≥ 50Cr hide deals below the selected value. The filter acts on the trade value, not on the share count.',
        },
        {
          name: '⚡ Chart',
          desc: 'Opens the symbol in a detached CHART window. The terminal layout does not change.',
        },
        {
          name: '🏢 Company',
          desc: 'Opens the symbol in a detached COMPANY window for fundamentals and filings.',
        },
      ] as DocField[],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'DATE',
          desc: 'The trade date reported in the filing. A deal can arrive in the feed after the session ends, so the newest row is not always from today.',
        },
        {
          name: 'SECURITY',
          desc: 'The traded symbol in amber, with the full company name below. Use it to confirm that two similar tickers are different companies.',
        },
        {
          name: 'CLIENT / INSTITUTION',
          desc: 'The reported buyer or seller. A fund name here means institutional activity. A promoter name means promoter activity.',
        },
        {
          name: 'ACTION',
          desc: 'BUY in green or SELL in red. This is the direction of the reported client, not the direction of the price.',
        },
        {
          name: 'QUANTITY',
          desc: 'Number of shares in the trade. Compare it with the float to judge size. A large quantity in a small company is more significant than the same quantity in a large company.',
        },
        {
          name: 'WATP',
          desc: 'Volume-weighted average trade price. It shows the effective price the client paid or received across all fills, so it is more useful than a single print price.',
        },
        {
          name: 'VALUE (CR)',
          desc: 'Trade value in crore rupees. This is the field that the value pills filter on. A high value shows conviction, but confirm it against the market capitalisation.',
        },
        {
          name: 'TOTAL DEALS TURNOVER',
          desc: 'Sum of the value of every row in view. It changes when you change the tab or the filters, so read it as the value of the current view, not the whole market.',
        },
        {
          name: 'BUY FLOW (ACCUMULATION)',
          desc: 'Total buy value in view. The count below shows how many buy trades contribute to the number. A large value from a few clients is more concentrated than the same value from many clients.',
        },
        {
          name: 'SELL FLOW (DISTRIBUTION)',
          desc: 'Total sell value in view. The count below shows how many sell trades contribute. Distribution means sellers are supplying stock to the market.',
        },
        {
          name: 'INSTITUTIONAL BIAS',
          desc: 'Net difference between buy flow and sell flow. A green label means net accumulation. A red label means net distribution. A near-zero value means the two sides are balanced.',
        },
        {
          name: 'FII / DII NET FLOW',
          desc: 'Buy value minus sell value for foreign or domestic institutions on the radar tab. A positive number in green is net buying. A negative number in red is net selling. Read the buy and sell pies together to see whether the net number hides large two-way activity.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'NSE and BSE publish deal filings after the trade. The header shows the session date for the current filing set. A filing can arrive late, so a deal that happened today can be absent until the exchange publishes it. The KPI cards and the table always describe the current tab and filters. Insider trades are not in this widget. Open COMPANY > DEALS > INSIDER for those filings.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour covers four areas: 1) Deal Categories, 2) Filter the Feed, 3) Read the Flow, and 4) Inspect a Trade. To replay the tour, open DOCS in another panel, keep this LARGEDEALS panel open, then click REPLAY TOUR.',
    },
  ],
};

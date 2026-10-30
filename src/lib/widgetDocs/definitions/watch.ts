import type { DocField, WidgetDoc } from '../types';

export const watchDoc: WidgetDoc = {
  command: 'WATCH',
  title: 'Watchlist',
  summary:
    'A monitored list of symbols with live prices, period returns, 52-week range, fair value and unread alert counts.',
  kind: 'panel',
  order: 20,
  screenshot: {
    src: '/docs/widgets/WATCH.png',
    alt: 'Watchlist widget screenshot',
    caption: 'Watchlist as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'One row per symbol in the active watchlist. The table joins a live last-traded price with cached period returns, the 52-week range, the Morningstar fair value gap, the results date and the unread alert count. Use it to scan a short list, not the full market.',
    },
    {
      heading: 'Controls',
      items: [
        'Use the LIST dropdown to switch watchlists. The + button creates a new list. IMPORT copies a TradingView list.',
        'Set the exchange, type a ticker, pick an autocomplete result, then press +ADD.',
        'Click a column header to sort. Click again to reverse the order. Drag a header to move the column.',
        'Click a row to set the global active symbol for CHART, ORDER, COMPANY and AI.',
        'Click the alert bell to open the alert list for that symbol. The modal offers Load Chart, Company, AI Summarize and Dismiss All.',
        'Press the remove cross on a row to delete the symbol from the active list.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SYMBOL',
          desc: 'Ticker and exchange. The active row is highlighted. Click it to broadcast the symbol to linked panels.',
        },
        {
          name: 'LTP',
          desc: 'Last traded price in rupees. A green or red flash shows tick direction only. It is not a trend signal.',
        },
        {
          name: 'CHG%',
          desc: 'Change from the previous close. Green is positive and red is negative. Large moves on low volume are less reliable.',
        },
        {
          name: 'MOMENTUM (1W-1Y)',
          desc: 'Five pills for 1W, 1M, 3M, 6M and 1Y. A green up arrow means a positive return for that window. All five green shows aligned momentum. Mixed pills show a conflict.',
        },
        {
          name: '1W% / 1M% / 3M% / 6M% / 1Y%',
          desc: 'Exact price return for each window. Use the number when the direction matters and the pills when speed matters.',
        },
        {
          name: '2Y% / 3Y% / 5Y%',
          desc: 'Longer-horizon returns. Use them to separate a short-term spike from a durable trend.',
        },
        {
          name: '52W HIGH',
          desc: 'Highest traded price in the last 52 weeks. A price near this level faces possible resistance and possible breakout demand.',
        },
        {
          name: '52W LOW',
          desc: 'Lowest traded price in the last 52 weeks. A price near this level faces possible support and possible breakdown risk.',
        },
        {
          name: 'MS FAIR VALUE',
          desc: 'Gap to the Morningstar fair value. Green +x% Undervalued means the price is below fair value. Red x% Premium means the price is above fair value. This is a model estimate, not a target.',
        },
        {
          name: 'RESULTS',
          desc: 'Scheduled or last results date. Green marks an upcoming date. A near date warns of event risk.',
        },
        {
          name: 'ALERTS',
          desc: 'Unread alert count for the symbol. Amber means at least one unread alert. Zero means no unread alert. Open the bell to review them.',
        },
        {
          name: 'SORT / ADV / DEC',
          desc: 'The current sort column and direction, then the count of advancing and declining stocks in the list. A wide positive gap is broad strength. A narrow gap is a mixed list.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'LTP streams from the market WebSocket. Period returns, the 52-week range, fair value and the results date come from cached backend data and can lag the live tick. The advancing and declining counts use the current list only, not the whole market. Alert counts include unread items only.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour has five steps: list selection, add symbol, breadth, table controls and alerts. To replay it, open DOCS in another panel, keep this WATCH panel open, then click REPLAY TOUR.',
    },
  ],
};

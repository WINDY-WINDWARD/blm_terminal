import type { DocField, WidgetDoc } from '../types';

export const topDoc: WidgetDoc = {
  command: 'TOP',
  title: 'Top Movers',
  summary:
    'Multi-period momentum matrix and ranked gainers or losers across market universes.',
  kind: 'panel',
  order: 10,
  screenshot: {
    src: '/docs/widgets/TOP.png',
    alt: 'Top Movers widget screenshot',
    caption: 'Top Movers as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A multi-period momentum matrix and ranked gainers and losers across selected NSE universes. The default matrix view tracks return alignment across five horizons to find high-velocity leaders.',
    },
    {
      heading: 'Controls',
      items: [
        'Universe selector: click an index pill such as NIFTY 50, F&O, or NIFTY 500 to scope the scan.',
        'View tabs: switch between matrix, gainers, and losers views.',
        'Quick sort: click ▲ Gains or ▼ Drops in matrix view to sort by intraday change.',
        'Header sort and drag: click any column header to sort rows, or drag to reorder columns.',
        'Filter input: type ticker characters into the filter box to narrow results.',
        'Symbol selection: click any row to set the global active symbol across all terminal panels.',
        'Pagination: click ← PREV and NEXT → to page through rows.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'UNIVERSE',
          desc: 'Index or market category that scopes the scan, such as NIFTY 50, Bank NIFTY, or F&O.',
        },
        {
          name: 'VIEW TABS',
          desc: 'Mode toggle between the multi-period momentum matrix, top gainers, and top losers.',
        },
        {
          name: 'TICKER / BULL / BEAR / #RANK',
          desc: 'NSE symbol. Matrix view displays a BULL or BEAR badge based on momentum bias. Gainers and losers views show #Rank inside that list.',
        },
        {
          name: 'LTP',
          desc: 'Last traded price in rupees, sourced from cache snapshots and market ticks.',
        },
        {
          name: 'CHG%',
          desc: 'Intraday percentage change from previous session close. Positive values indicate price gains; negative values indicate price drops.',
        },
        {
          name: 'MOMENTUM STRIP',
          desc: 'Five-segment heat strip reflecting price returns across 1W, 1M, 3M, 6M, and 1Y periods.',
        },
        {
          name: 'VELOCITY',
          desc: 'Momentum score out of 100. Scores >= 70 show strong multi-timeframe alignment (green), 45-69 show mixed momentum (amber), and < 45 show weak momentum (rose).',
        },
        {
          name: 'RADAR',
          desc: 'Alignment summary across the five return horizons: ALL BULLISH, BULLISH BIAS, MIXED, BEARISH BIAS, or ALL BEARISH. A high velocity with mixed radar is a conflict, not a buy signal.',
        },
        {
          name: 'VOL',
          desc: 'Total traded quantity for the session. K, L, and Cr suffixes indicate thousands, lakhs, and crores.',
        },
        {
          name: 'TRNVR',
          desc: 'Total trading value in rupees expressed in crores (₹ Cr).',
        },
        {
          name: 'OPEN / HIGH / LOW',
          desc: 'Session open, intraday high, and intraday low price levels.',
        },
        {
          name: 'CA (CORPORATE ACTION)',
          desc: 'Ex-date for dividend, bonus, split, or rights issue. Hover badge to view details.',
        },
        {
          name: '2Y / 3Y / 5Y',
          desc: 'Longer-term multi-year price returns from market data for macro context.',
        },
        {
          name: '52WH / 52WL',
          desc: '52-week highest and lowest traded prices, showing current proximity to extremes.',
        },
        {
          name: 'PAGINATION',
          desc: 'Footer navigation showing current page and row counts. Page controls cycle through results without resetting the sort.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Data comes from background scans and cache snapshots. LTP can lag the live tick, and this matrix is not a real-time order book. The page size is 6 rows. Text filters apply across the universe before pagination splits the results.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour has 5 steps and switches the view as it explains it: 1) the universe bar, 2) the view tabs, where it opens the gainers list, 3) the matrix columns, which it returns to, 4) the ticker filter, and 5) pagination. It restores the view that was active before the tour. To replay it, open DOCS in another panel, keep the TOP panel open, then click REPLAY TOUR.',
    },
  ],
};

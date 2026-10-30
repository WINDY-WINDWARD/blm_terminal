import type { DocField, WidgetDoc } from '../types';

export const screenerDoc: WidgetDoc = {
  command: 'SCREENER',
  title: 'Stock Screener (TQL)',
  summary:
    'Filter the entire NSE universe using Ticker Query Language (TQL). Type a query in the bar and press Enter or Run.',
  kind: 'panel',
  order: 140,
  screenshot: {
    src: '/docs/widgets/SCREENER.png',
    alt: 'Stock Screener (TQL) widget screenshot',
    caption: 'Stock Screener (TQL) as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'Filter the NSE universe using Ticker Query Language (TQL). The widget displays matching stocks in a sortable table with fixed market quotes and dynamic indicator columns requested by the query. You can inspect technical indicators, momentum metrics, valuation ratios, and Morningstar fair value estimates across multiple calculation intervals.',
    },
    {
      heading: 'Controls',
      items: [
        'TQL button: opens the syntax reference modal and query documentation.',
        'CSV button: exports the active table rows and columns to a downloaded CSV file.',
        'Clear button: resets the query input and clears the submitted filter state.',
        'Refresh button: re-runs the current filter query against the backend cache.',
        'Interval tabs: switch between Daily, 1h, Weekly, and Monthly calculation horizons.',
        'TQL input bar: type queries with autocomplete suggestions for fields, operators, and sector names.',
        'Run button / Enter key: executes the filter query against the stock universe.',
        'Sortable headers: click any column header to sort ascending or descending.',
        'Row click: updates the terminal active symbol and exchange to NSE.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SYMBOL',
          desc: 'NSE trading symbol. Click any row to broadcast the symbol and exchange to linked widgets.',
        },
        {
          name: 'LTP',
          desc: 'Last traded price in rupees.',
        },
        {
          name: 'CHG %',
          desc: 'Session percentage change from previous close. Positive values are green and negative values are red.',
        },
        {
          name: 'MS FV',
          desc: 'Morningstar fair value estimate in rupees. Compare MS FV with LTP to evaluate the valuation gap.',
        },
        {
          name: 'RSI',
          desc: 'Relative Strength Index (14 periods). Readings above 70 indicate overbought conditions. Readings below 30 indicate oversold conditions.',
        },
        {
          name: 'ATR %',
          desc: 'Average True Range as a percentage of price. Low values indicate price compression. High values indicate elevated volatility.',
        },
        {
          name: 'MACD / MACD SIG / MACD H',
          desc: 'Moving Average Convergence Divergence line, signal line, and histogram (MACD minus Signal).',
        },
        {
          name: 'BB WID / SQUEEZE (SQ)',
          desc: 'Bollinger Band width as a percentage of the middle band. The SQ badge indicates an active squeeze with low width and breakout expansion risk.',
        },
        {
          name: 'HV20 / HV60',
          desc: 'Historical volatility across 20 and 60 trading days. HV20 above HV60 shows that recent volatility is rising.',
        },
        {
          name: 'SHARPE60 / SHARPE126',
          desc: 'Risk-adjusted return ratio over 60 and 126 days. Sharpe60 above Sharpe126 shows improving recent risk-adjusted performance.',
        },
        {
          name: 'VOL RATIO',
          desc: 'Current trading volume relative to its 20-day moving average. Values above 1.0 indicate above-average trading activity.',
        },
        {
          name: '1W% / 1M% / 3M% / 6M% / 1Y%',
          desc: 'Historical price return percentages across one-week, one-month, three-month, six-month, and one-year horizons.',
        },
        {
          name: '52H % / 52L %',
          desc: 'Distance from 52-week extremes. 52H % shows distance below the annual high. 52L % shows distance above the annual low.',
        },
        {
          name: 'PE',
          desc: 'Price-to-earnings valuation ratio based on reported company earnings.',
        },
        {
          name: 'MOMENTUM (MOM.)',
          desc: 'Composite momentum score from 0 to 100 based on price velocity and multi-window trend strength.',
        },
        {
          name: 'SECTOR / INDUSTRY',
          desc: 'NSE sector classification and industry sub-category. Visible when named in the TQL filter query.',
        },
        {
          name: 'STATS BAR',
          desc: 'Summary bar displaying returned result count against total scanned universe count, and active dynamic indicator column names.',
        },
        {
          name: 'STATES',
          desc: 'Displays Loading…, Enter a TQL query above and press Run, No results match your query, or inline red error text for invalid syntax.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'The screener queries backend indicator caches refreshed periodically during market operations. Unprefixed indicator expressions calculate over the active interval tab. Displays up to 200 matching records per execution. Table sorting executes client-side on the returned result set.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour covers four key areas: 1) Header Actions, 2) Interval Selection, 3) TQL Query Input, and 4) Screener Results Table. To replay the tour, open DOCS in another panel, keep this SCREENER panel open, then click REPLAY TOUR.',
    },
  ],
};

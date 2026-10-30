import type { DocField, WidgetDoc } from '../types';

export const breakoutsDoc: WidgetDoc = {
  command: 'BREAKOUTS',
  title: '52-Week Breakouts',
  summary:
    'All NSE stocks touching new 52-week highs or lows, volume shockers, and 10-day repeated breakout persistence.',
  kind: 'panel',
  order: 80,
  screenshot: {
    src: '/docs/widgets/BREAKOUTS.png',
    alt: '52-Week Breakouts widget screenshot',
    caption: '52-Week Breakouts as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A real-time momentum scanner and breakout cockpit tracking NSE stocks hitting 52-week milestones. ALL MATRIX displays four cards: 52-Week High Breakout Radar, 52-Week Low Breakdown Radar, Volume Shockers & Surge Radar, and Repeated Breakout Persistence (10-day). Tabs switch to full tables for deeper inspection.',
    },
    {
      heading: 'Controls',
      items: [
        'ALL MATRIX tab: shows the four breakout and breakdown radar cards in a bento layout.',
        '52W HIGH tab: opens the full sortable table of symbols touching new 52-week highs.',
        '52W LOW tab: opens the full sortable table of symbols touching new 52-week lows.',
        'VOLUME SHOCKERS tab: displays the complete relative volume surge and turnover table.',
        'REPEATED tab: inspects the 10-day multi-session persistence tracker.',
        'Search symbols: filters radar cards and tables by ticker symbol in real time.',
        'Row click: click any ticker in cards or tables to synchronize the active symbol across the terminal.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SYMBOL',
          desc: 'Trading ticker symbol on NSE. Click any row or card item to synchronize the active instrument across terminal panels.',
        },
        {
          name: 'NAME',
          desc: 'Registered corporate company name of the listed instrument.',
        },
        {
          name: 'LTP',
          desc: 'Last Traded Price in Indian Rupees from live market feeds.',
        },
        {
          name: 'CHANGE / CHANGE %',
          desc: 'Absolute point difference and percentage change from the previous session closing price.',
        },
        {
          name: 'NEW 52W',
          desc: 'New 52-week high or low price level printed during the session.',
        },
        {
          name: 'PREV 52W',
          desc: 'Benchmark 52-week milestone price level before the current session.',
        },
        {
          name: 'PREV HL DATE',
          desc: 'Calendar date when the prior 52-week milestone high or low was recorded.',
        },
        {
          name: 'VOL SHOCKER',
          desc: 'Relative volume surge badge highlighting unusual volume expansion against historical baselines.',
        },
        {
          name: 'CLEARANCE STATUS',
          desc: 'Clearance categorization: UPPER CIRCUIT, FRESH ATH, MULTI-YR HIGH, CRITICAL BREAKDOWN, or NEW 52W LOW.',
        },
        {
          name: 'WK1 AVG',
          desc: 'One-week average daily trading volume. A 52-week high with volume expansion over the 1-week average is stronger.',
        },
        {
          name: 'WK1 CHG %',
          desc: 'Percentage change of current volume compared to the 1-week average volume.',
        },
        {
          name: 'WK2 AVG',
          desc: 'Two-week average daily trading volume baseline.',
        },
        {
          name: 'WK2 CHG %',
          desc: 'Percentage change of current volume compared to the 2-week average volume.',
        },
        {
          name: 'TURNOVER ₹CR',
          desc: 'Total executed turnover value for the session measured in crore rupees.',
        },
        {
          name: 'TYPE',
          desc: 'Repeated breakout category classification, tracking recurring 52WH highs or 52WL lows.',
        },
        {
          name: 'APPEARANCES',
          desc: 'Count of breakout sessions within the 10-day window displayed with a progress bar. Repeated appearances mean persistence, not a new signal.',
        },
        {
          name: 'WINDOW',
          desc: 'Rolling tracking period (10 trading days) used to measure signal persistence.',
        },
        {
          name: 'LAST SEEN',
          desc: 'Most recent trading date when the breakout trigger was detected.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Breakout benchmarks and prices refresh from NSE feeds during market hours. Volume comparisons use rolling 1-week and 2-week trading histories. Repeated breakout persistence evaluates occurrences over a 10-day window. Corporate actions like splits and bonuses adjust previous benchmark levels.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour has five steps and changes tabs as it goes: 1) Radar View Tabs, 2) the 52-week high table, 3) the four-card matrix, 4) the Volume Shockers table, and 5) the Repeated Breakouts table. It returns to the tab that was open before the tour started. To replay the tour, open DOCS in another panel, keep this BREAKOUTS panel open, then click REPLAY TOUR.',
    },
  ],
};

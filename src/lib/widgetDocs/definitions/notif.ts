import type { DocField, WidgetDoc } from '../types';

export const notifDoc: WidgetDoc = {
  command: 'NOTIF',
  title: 'Notifications',
  summary:
    'Real-time alerts and scanner hub monitoring 11 signal categories, multi-timeframe technical triggers, and sectoral heatmap concentration.',
  kind: 'panel',
  order: 110,
  screenshot: {
    src: '/docs/widgets/NOTIF.png',
    alt: 'Notifications widget screenshot',
    caption: 'Notifications as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A real-time notification cockpit and alert scanning hub. The widget monitors watchlist and market-wide instruments across 11 trigger categories, including 52-week breakouts, unusual volume, bulk deals, insider trades, technical crosses, and streaks. Traders can inspect real-time alert streams, filter by severity and parameter thresholds, or switch to an industry heatmap to pinpoint sectoral momentum concentration.',
    },
    {
      heading: 'Controls',
      items: [
        'Watchlist selector: choose an active watchlist or select ALL (GLOBAL SCAN) to monitor all tracked symbols.',
        'Date selector: filter notifications by a specific trading date or view all recorded alerts.',
        'View mode toggle: switch between the LIVE ALERTS stream and the INDUSTRY HEATMAP.',
        'Severity matrix filters: toggle CRITICAL, HIGH, and NORMAL severity filters in the left filter deck.',
        'Category filters: select one of 11 trigger categories or ALL to filter alert signals.',
        'Streak presets: click 3D, 5D, 7D, or 10D buttons, or configure custom consecutive streak days.',
        'Sub-filter search: type trigger names into the autocomplete input to add or remove specific trigger filters.',
        'Symbol search & Exchange filter: filter stream alerts by symbol name and toggle between NSE and BSE.',
        'Live / Paused toggle: pause or resume automated 30-second polling for live alert updates.',
        'Compact mode toggle: switch between detailed multi-metric cards and compact single-line stream items.',
        'Mark All Read: dismiss all unread notifications in the current view with a single click.',
        'Alert card actions: click Load Chart, Company, or card headers to inspect detailed signal parameters.',
        'Heatmap drill-down: click any industry tile in the heatmap view to open a drill-down modal.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'WATCHLIST SCOPE',
          desc: 'Active watchlist or global scan across all tracked symbols.',
        },
        {
          name: 'DATE SCOPE',
          desc: 'Calendar trading session filter or all historical recorded dates.',
        },
        {
          name: 'VIEW MODE',
          desc: 'Toggle between the LIVE ALERTS stream and the INDUSTRY HEATMAP concentration grid.',
        },
        {
          name: 'SEVERITY LEVEL',
          desc: 'Urgency categorization: CRITICAL, HIGH, or NORMAL. Severity indicates anomaly magnitude, not market direction.',
        },
        {
          name: 'TRIGGER CATEGORY',
          desc: 'Classification across 11 trigger groups: 52W, VOLUME, MOVERS, DEALS, INSIDER, TECHNICAL, MOMENTUM, VOLATILITY, STREAKS, RESULTS, or ALL.',
        },
        {
          name: 'STREAK PRESET',
          desc: 'Consecutive trading day streak filter (e.g. 3D, 5D, 7D, 10D). A streak indicates price momentum, not valuation.',
        },
        {
          name: 'SUB-FILTERS',
          desc: 'Individual trigger types selected via autocomplete search to narrow active category streams.',
        },
        {
          name: 'TIMEFRAME',
          desc: 'Signal detection window: 1D (daily), 1H (hourly), 1W (weekly), 1M (monthly), or MTF (multi-timeframe). MTF indicates that multiple timeframes agree on the signal.',
        },
        {
          name: 'PARAMETERS',
          desc: 'Quantitative indicators extracted from triggers (such as RSI value, volume ratio, streak count, or 52W milestone). Alerts are computed technical signals, not financial advice.',
        },
        {
          name: 'STREAM CONTROLS',
          desc: 'Search filter by ticker, exchange filter (NSE/BSE), compact density toggle, and a Live/Paused toggle that polls every 30 seconds.',
        },
        {
          name: 'CARD ACTIONS',
          desc: 'Direct execution links: Load Chart to open technical charts, Company to view fundamental profiles, or Details to inspect raw payloads.',
        },
        {
          name: 'INDUSTRY HEATMAP',
          desc: 'Sectoral concentration cards. Heatmap cards colour by alert count and open a drill-down modal of alerting stocks.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Notification workers scan live market data, technical indicator models, insider filings, and block deal feeds during market hours. The live stream automatically polls for updates every 30 seconds when streaming is active. Alerts are deduplicated daily per symbol and trigger type to prevent noise. Historical alerts remain queryable across recorded trading dates in the local database.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour has 7 steps and switches views as it goes: 1) Watchlist and Date Scope, 2) Stream and Heatmap tabs, 3) it opens INDUSTRY HEATMAP to show the sector banner, 4) it returns to LIVE ALERTS, 5) Signal Categories, 6) Read Status, 7) an Alert Card with its severity fields. The tour restores the view you were on when it ends. Replay it from DOCS with both panels open.',
    },
  ],
};

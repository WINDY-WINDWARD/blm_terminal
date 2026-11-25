import type { DocField, WidgetDoc } from '../types';

export const scanDoc: WidgetDoc = {
  command: 'SCAN',
  title: 'Global Market Scanner',
  summary:
    'Universe-wide market scanner monitoring 11 signal categories, sectoral heatmaps, and real-time technical alerts across all tracked symbols.',
  kind: 'panel',
  order: 120,
  screenshot: {
    src: '/docs/widgets/SCAN.png',
    alt: 'Global Market Scanner widget screenshot',
    caption: 'Global Market Scanner as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A market-wide scanning hub monitoring the entire stock universe rather than a single watchlist. The widget shares the notification engine architecture with NOTIF, defaulting its scope to ALL (GLOBAL SCAN). It tracks 11 signal categories, including 52-week breakouts, volume surges, block deals, insider filings, technical indicator crosses, and momentum streaks. Traders can monitor live streams or switch to an industry heatmap to spot sectoral momentum concentration. This view discovers symbols you do not normally watch, so treat each alert as a research lead rather than an immediate trade.',
    },
    {
      heading: 'Controls',
      items: [
        'Watchlist selector: defaults to ALL (GLOBAL SCAN) to scan the entire universe, or switch to a specific watchlist.',
        'Date selector: filter scan alerts by a specific trading date or view all recorded alerts.',
        'View mode toggle: switch between the LIVE ALERTS stream and the INDUSTRY HEATMAP.',
        'Severity matrix filters: filter by CRITICAL, HIGH, and NORMAL severity levels in the left filter deck.',
        'Category filters: select one of 11 signal categories or ALL to narrow scan results.',
        'Streak presets: select 3D, 5D, 7D, or 10D buttons, or configure custom streak day thresholds.',
        'Sub-filter search: type trigger names into the autocomplete bar to filter by specific trigger types.',
        'Symbol search & Exchange filter: filter stream alerts by symbol name and toggle between ALL, NSE, and BSE.',
        'Live / Paused toggle: pause or resume automated 30-second polling for global notifications.',
        'Compact mode toggle: switch between detailed parameter cards and compact stream rows.',
        'Mark All Read: clear unread status across all visible alerts with a single click.',
        'Popout actions: click Load Chart or Company to launch detached windows without altering the active terminal symbol.',
        'Heatmap drill-down: click any industry tile in the heatmap view to inspect all alerting stocks in that sector.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'UNIVERSE SCOPE',
          desc: 'Global scan scope across the entire stock universe, defaulting to ALL (GLOBAL SCAN).',
        },
        {
          name: 'DATE FILTER',
          desc: 'Active trading date filter or historical all-dates view.',
        },
        {
          name: 'VIEW MODE',
          desc: 'Toggle between the live signal stream and the pre-aggregated industry heatmap.',
        },
        {
          name: 'SEVERITY RANK',
          desc: 'Event importance ranking (CRITICAL, HIGH, NORMAL). Severity ranks the event magnitude, not market direction.',
        },
        {
          name: 'SIGNAL CATEGORIES',
          desc: '11 trigger categories: 52W breakouts, volume surges, top movers, deals, insider trades, technicals, momentum, volatility, streaks, and earnings.',
        },
        {
          name: 'STREAKS RADAR',
          desc: 'Consecutive session streak tracker. A streak indicates price persistence, not valuation.',
        },
        {
          name: 'SIGNAL PARAMETERS',
          desc: 'Extracted metrics such as indicator readings, volume ratios, or milestone thresholds.',
        },
        {
          name: 'POPOUT ACTIONS',
          desc: 'Action buttons to open independent chart or company windows without modifying the terminal grid symbol.',
        },
        {
          name: 'INDUSTRY HEATMAP',
          desc: 'Pre-aggregated sectoral alert concentration grid with drill-down modal inspection.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'The scanner polls the global notifications endpoint every 30 seconds when live streaming is active. Alerts originate from continuous background analysis of live ticks, filings, and end-of-day models. There is no separate GlobalNotification table: SCAN queries the notifications table with global universe scope. Data is not 30 minutes old; it updates with the 30-second polling cycle and live background jobs.',
    },
    {
      heading: 'Guided tour',
      body: 'The tour has 6 steps and switches views as it goes: 1) Universe and Date, 2) Stream and Heatmap tabs, 3) it opens INDUSTRY HEATMAP to show sector concentration, 4) it returns to the stream for Signal Categories, 5) a Universe Alert Card, 6) the Load Chart and Company actions. The tour restores the view you were on when it ends. Replay it from DOCS with both panels open.',
    },
  ],
};

import type { DocField, WidgetDoc } from '../types';

export const newsDoc: WidgetDoc = {
  command: 'NEWS',
  title: 'News & Wire Feed',
  summary:
    'Real-time financial news radar hub aggregating multi-stream wire feeds with automated sentiment, threat ratings, and entity tags.',
  kind: 'panel',
  order: 90,
  screenshot: {
    src: '/docs/widgets/NEWS.png',
    alt: 'News widget screenshot',
    caption: 'News as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A unified real-time financial wire feed across global news services, Indian media, and regulatory sources. The widget streams articles over WebSocket into a single multi-stream feed. Automated pipelines enrich each dispatch with sentiment, threat scores, credibility warnings, and extracted entity tags. The feed displays 50 articles per page with live updates.',
    },
    {
      heading: 'Controls',
      items: [
        'Click BULLISH, BEARISH, or NEUTRAL pills to filter headlines by sentiment.',
        'Type in the search input to filter by ticker or text with a 350 ms debounce. Click ✕ to clear the filter.',
        'Click the MULTI-STREAM tab button to view the live multi-source wire.',
        'Click ALL in the SOURCES row to reset all source exclusions.',
        'Click primary source pills (AP, BLOOMBERG, MC, REUTERS, ET, WSJ, CNBC, SEC, MINT) to toggle individual feeds.',
        'Click ALL 38 FEEDS ▼ to expand the full source selector, or LESS FEEDS ▲ to collapse it.',
        'Click any article row to open the reader modal inside the terminal.',
        'Hold Ctrl or Cmd and click an article to open the external source in a browser.',
        'Click any $TICKER chip to set the active terminal symbol for linked panels.',
        'Click Prev or Next in the footer to navigate through pages of 50 articles.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SOURCE BADGE',
          desc: 'Source name displayed with a distinct colour tag. Use it to distinguish Tier 1 wire services from local blogs.',
        },
        {
          name: 'TIME & RELATIVE AGE',
          desc: 'Publication timestamp and elapsed time since release (for example, "12m ago"). Verify article age before acting on fast-moving news.',
        },
        {
          name: 'LIVE BADGE',
          desc: 'Green pulsing badge on incoming dispatches received through the active WebSocket connection.',
        },
        {
          name: 'THREAT LEVEL',
          desc: 'Threat rating: LOW (green), MED (amber), HIGH (rose), or CRIT (red). A high threat rating with low confidence indicates an item to review, not an immediate trigger to trade.',
        },
        {
          name: 'CREDIBILITY WARNING (⚠)',
          desc: 'Yellow warning triangle displayed for state-affiliated media or caution-flagged outlets. Treat unverified claims from flagged sources with caution.',
        },
        {
          name: 'SENTIMENT & CONFIDENCE %',
          desc: 'Coloured dot (green for BULLISH, red for BEARISH, gray for NEUTRAL) with percentage confidence. High confidence reflects multiple matching keywords. Low confidence indicates weak text signals.',
        },
        {
          name: 'ENTITY TAGS (T / O / P / C)',
          desc: 'Extracted named entities: T for tickers, O for organizations, P for people, and C for countries. Amber T chips set the active terminal symbol.',
        },
        {
          name: 'IMPACT NOTE',
          desc: 'Displays "• Impact: <category>" when an event category matches (such as market, regulatory, conflict, or cyber).',
        },
        {
          name: 'PAGE COUNTER',
          desc: 'Displays the visible item range and total count of stored records (for example, "1–50 of 420"). Shows active wire count when database records are empty.',
        },
        {
          name: 'FEED STATES',
          desc: 'Displays "SYNCING WIRE FEEDS..." during initial load, "WIRE STREAM ERROR" on network failure, or "No wire articles match current filters." when filters exclude all records.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Articles stream through a real-time WebSocket connection and fall back to periodic REST polling when disconnected. Automated rule-based pipelines compute sentiment, threat levels, and entity extractions. These automated scores can make errors. Always read the source text before making trading decisions. High threat with low confidence is a headline to inspect, not confirmed market direction.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour covers five key areas: source filters, sentiment and search controls, multi-stream feed list, extracted entity chips, and feed pagination. To replay the tour, open DOCS with DOCS and NEWS both open, then click REPLAY TOUR.',
    },
  ],
};

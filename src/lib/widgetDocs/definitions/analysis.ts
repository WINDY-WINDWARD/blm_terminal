import type { DocField, WidgetDoc } from '../types';

export const analysisDoc: WidgetDoc = {
  command: 'ANALYSIS',
  title: 'Sector & Industry Analysis',
  summary:
    'Comprehensive sector and industry intelligence featuring market breadth KPIs, category drill-down cockpits, constituent tracking, and interactive treemaps.',
  kind: 'panel',
  order: 100,
  screenshot: {
    src: '/docs/widgets/ANALYSIS.png',
    alt: 'Sector & Industry Analysis widget screenshot',
    caption: 'Sector & Industry Analysis as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'Top-down market structure across sectors and industries. It synthesizes advance-decline breadth, cap-weighted performance, price-to-earnings multiples, and median earnings growth into summary KPIs, split-view category cockpits, and multi-metric heatmaps.',
    },
    {
      heading: 'Controls',
      items: [
        'Tab bar navigation: switch between the four primary tabs: Summary, Sectors, Industries, and Heatmap.',
        'Summary horizon pills: toggle between 1D, 1W, 1M, and 6M performance horizons to update leaders, laggards, and momentum rankings.',
        'Category navigation rail: select a sector or industry in the left rail to load its detailed analytics in the right cockpit.',
        'Constituent actions: click ⚡ Chart to open a chart panel, 🏢 Company to inspect company fundamentals, or ★ Watch to open the watchlist picker modal.',
        'Watchlist picker modal: manage target watchlists with + Create, Cancel, and Save options.',
        'Heatmap scope selector: filter treemap tiles across Sectors, Industries, or All categories.',
        'Heatmap metric chips: switch the coloring and bucket calculations between A/D (Advance/Decline), Earn (Earnings YoY), Sent (Sentiment), and Perf (Performance).',
        'Heatmap sorting and ordering: pick sort criteria (1D %, 1W %, 1M %, 6M %, MCap, Net A/D, Earn YoY, P/E, Adv %, Sentiment, Name) and toggle ascending or descending direction with the ↓/↑ button.',
        'Heatmap legend filter: click color swatches to isolate or dim specific performance tiers, and click clear to reset filtering.',
        'Heatmap slide-out drawer: click any treemap tile to open a resizable slide-out drawer (with a drag resize edge and ✕ close button) displaying sortable Symbol, LTP, Chg%, and P/E columns with per-row ⚡/🏢/★ action buttons.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'BREADTH (adv▲ / dec▼)',
          desc: 'Number of advancing stocks (adv▲) versus declining stocks (dec▼), displayed alongside net advance and advancing percentage (advPct). Breadth above 60% advancing with a flat cap-weighted index means the move is broad, not index-heavy.',
        },
        {
          name: 'NET ADVANCE',
          desc: 'Advancers minus decliners across the universe or category. Green indicates net buying participation; red indicates prevailing selling pressure.',
        },
        {
          name: 'TOTAL MCAP',
          desc: 'Aggregate market capitalization formatted as ₹x.xxL Cr (lakh crores) or ₹x Cr, representing category market size.',
        },
        {
          name: 'P/E (PRICE TO EARNINGS)',
          desc: 'Valuation multiple comparing price to trailing earnings. Displayed with an x suffix, or as — when earnings are negative or data is missing.',
        },
        {
          name: 'EARNINGS YOY',
          desc: 'Year-over-year median earnings growth rate across constituents, highlighting operational momentum and earnings drags.',
        },
        {
          name: 'CAP-WEIGHTED DAY CHANGE',
          desc: 'Weighted daily return reflecting total market cap exposure, contrasting broad equal-weight market breadth against index heavyweights.',
        },
        {
          name: 'SENTIMENT CLASSIFICATION',
          desc: 'Algorithmic market classification: Very Bullish (V.Bull), Bullish, Neutral, Bearish, or Very Bearish (V.Bear) based on breadth distribution and momentum.',
        },
        {
          name: 'HEATMAP BUCKETS & INTENSITY',
          desc: 'Tiles distribute into five distinct intensity tiers: severe selling, moderate selling, neutral, moderate buying, and strong buying. Deeper green shades highlight stronger buying concentration, while deeper red shades denote concentrated capital liquidation.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'The tab bar displays a green status dot with a live timestamp (<time> IST) or LIVE status indicator. Category overviews and constituent breakdowns load asynchronously, displaying "Loading constituents..." while constituent rows populate.',
    },
    {
      heading: 'Guided tour',
      items: [
        'Step 1: Analysis Tabs — The tour starts on Summary and names the four views.',
        'Step 2: Summary KPIs — Market breadth, total market cap, P/E and median earnings growth.',
        'Step 3: Sector Rail — The tour switches to Sectors, then points at the category list.',
        'Step 4: Category Scorecard — The six cells above the donut for the selected sector.',
        'Step 5: Constituent Actions — Chart, company and watchlist buttons on a constituent row.',
        'Step 6: Heatmap Controls — The tour switches to Heatmap and points at scope, metric, sort and direction.',
        'Step 7: Heatmap Legend — The five color buckets of the active metric.',
        'Step 8: Tile Map — Tile coloring and the constituent drawer.',
        'The tour returns to the view that was active before it started. Replay it from DOCS when both DOCS and ANALYSIS panels are open.',
      ],
    },
  ],
};

// ─── Widget Documentation ─────────────────────────────────────────────────────
// Static reference content shown in the DOCS panel.
// Each entry maps a widget command string to its documentation.

export interface DocField {
  name: string;
  desc: string;
}

export interface DocSection {
  heading: string;
  body?: string;
  items?: DocField[] | string[];
}

export interface WidgetDoc {
  command: string;
  title: string;
  summary: string;
  sections: DocSection[];
}

// ─── Trigger Type Glossary (shared by NOTIF + SCAN) ──────────────────────────

export const TRIGGER_TYPE_DOCS: DocField[] = [
  // 52-Week
  {
    name: '52w_high_breakout',
    desc: 'Stock touched a new 52-week high today. Signals strong bullish momentum; often a continuation pattern when volume confirms.',
  },
  {
    name: '52w_low_breakout',
    desc: 'Stock hit a new 52-week low today. Can indicate capitulation or a breakdown — check sector context before acting.',
  },
  {
    name: 'near_52w_high',
    desc: 'Price is within 3% of its 52-week high. Watch for breakout or rejection at resistance.',
  },
  {
    name: 'near_52w_low',
    desc: 'Price is within 3% of its 52-week low. Potential support zone; elevated risk of further downside.',
  },
  // Volume
  {
    name: 'volume_breakout',
    desc: 'Today\'s volume is significantly above the weekly average. Validates price moves — high volume on a rally is bullish; on a decline is bearish.',
  },
  // Movers
  {
    name: 'top_gainer',
    desc: 'Among the top percentage gainers on NSE today. Could signal news, results, or sector rotation — investigate the catalyst.',
  },
  {
    name: 'top_loser',
    desc: 'Among the top percentage losers on NSE today. May reflect negative news, results, or broader selling pressure.',
  },
  // Deals
  {
    name: 'bulk_deal',
    desc: 'A bulk deal was reported: a single entity traded ≥0.5% of shares outstanding in one session. Often indicates institutional conviction.',
  },
  {
    name: 'block_deal',
    desc: 'A block deal was reported: a large negotiated trade (≥500,000 shares or ₹5 Cr) executed via the block window. Institutional change of hands.',
  },
  {
    name: 'short_deal',
    desc: 'A significant short position or short-covering deal was detected. Elevated if deal size is large relative to market cap.',
  },
  // Insider
  {
    name: 'insider_buy',
    desc: 'A promoter, director, or key management person bought shares. Insiders buying with their own money is a classic bullish signal.',
  },
  {
    name: 'insider_sell',
    desc: 'An insider sold shares. Can be for personal liquidity reasons; more meaningful when multiple insiders sell concurrently.',
  },
  // Technical — RSI
  {
    name: 'rsi_oversold',
    desc: 'RSI (14-day) dropped below 30. Historically a mean-reversion zone — but can remain oversold in strong downtrends. Combine with price action.',
  },
  {
    name: 'rsi_overbought',
    desc: 'RSI (14-day) exceeded 70. Momentum is stretched; watch for reversal signals, but trend-following strategies may stay long.',
  },
  // Technical — MACD
  {
    name: 'macd_bullish_cross',
    desc: 'MACD line crossed above the signal line. A lagging momentum buy signal; more reliable when it occurs below zero.',
  },
  {
    name: 'macd_bearish_cross',
    desc: 'MACD line crossed below the signal line. A lagging momentum sell signal; more reliable when it occurs above zero.',
  },
  // Technical — Bollinger Bands
  {
    name: 'bb_squeeze_alert',
    desc: 'Bollinger Band width is at a multi-month low. Low volatility periods (squeezes) often precede large directional moves — direction is unknown.',
  },
  {
    name: 'bb_upper_break',
    desc: 'Price closed above the upper Bollinger Band (2σ). Can signal a breakout continuation or an overextension depending on context.',
  },
  {
    name: 'bb_lower_break',
    desc: 'Price closed below the lower Bollinger Band (2σ). Indicates a potential oversold condition or a strong downside breakout.',
  },
  // Volatility
  {
    name: 'volatility_spike',
    desc: 'Historical volatility (20-day HV) is significantly higher than the 60-day baseline. Elevated risk environment — widen stops or size down.',
  },
  {
    name: 'atr_expansion',
    desc: 'Average True Range (ATR) has expanded sharply. Day ranges are widening; be prepared for larger intraday swings.',
  },
  // Momentum
  {
    name: 'momentum_surge',
    desc: 'Composite momentum score exceeded 70 (top percentile). Multi-factor signal combining price change, volume, and returns.',
  },
  {
    name: 'return_1w_spike',
    desc: '1-week return is in the top percentile of the NSE universe. Sharp short-term outperformance — check if it is driven by news or a structural shift.',
  },
  // Streaks
  {
    name: 'streak_up_5d',
    desc: 'Stock has closed higher for 5+ consecutive sessions. Sustained buying pressure; can indicate trend establishment or short-term exhaustion.',
  },
  {
    name: 'streak_down_5d',
    desc: 'Stock has closed lower for 5+ consecutive sessions. Persistent selling; monitor for capitulation or support-level reactions.',
  },
  // Results
  {
    name: 'results_upcoming',
    desc: 'NSE board meeting scheduled to announce quarterly / annual financial results. Expect increased volatility around the event date.',
  },
];

// ─── Per-Widget Documentation ─────────────────────────────────────────────────

const DOCS_MAP: WidgetDoc[] = [
  // ── CHART ──────────────────────────────────────────────────────────────────
  {
    command: 'CHART',
    title: 'Chart',
    summary:
      'Interactive candlestick chart for the active symbol. Displays OHLCV data with configurable timeframes and overlays.',
    sections: [
      {
        heading: 'What it shows',
        body: 'OHLC candlesticks for the symbol set globally via WATCH or by clicking any symbol in the terminal. Data is fetched from OpenAlgo and refreshed on symbol change.',
      },
      {
        heading: 'Candle anatomy',
        items: [
          { name: 'Green candle', desc: 'Close ≥ Open. Buyers were in control for that period.' },
          { name: 'Red candle', desc: 'Close < Open. Sellers were in control for that period.' },
          {
            name: 'Upper wick',
            desc: 'Price reached higher intraday but was rejected — potential resistance.',
          },
          {
            name: 'Lower wick',
            desc: 'Price dipped lower intraday but recovered — potential support.',
          },
          {
            name: 'Doji',
            desc: 'Open ≈ Close (tiny body). Indecision — watch next candle for direction.',
          },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Click any symbol in WATCH or TOP to update the chart.',
          'Use timeframe selector to switch between intraday and daily views.',
          'Long upper wicks at highs = distribution. Long lower wicks at lows = accumulation.',
        ],
      },
    ],
  },

  // ── WATCH ──────────────────────────────────────────────────────────────────
  {
    command: 'WATCH',
    title: 'Watchlist',
    summary:
      'Monitors a curated list of symbols with live prices, multi-timeframe returns, Morningstar fair value, and alert badges.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Live quote data refreshed via WebSocket / polling. Each row represents one symbol in the active watchlist.',
      },
      {
        heading: 'Columns',
        items: [
          { name: 'LTP', desc: 'Last traded price, live from NSE.' },
          { name: 'CHG', desc: 'Intraday % change from previous close.' },
          { name: 'MSFV', desc: 'Morningstar fair value estimate. Green = undervalued, Red = overvalued.' },
          { name: '1W / 1M / 3M / 6M / 1Y', desc: 'Price return over the stated period.' },
          { name: 'RESULTS', desc: 'Days until the next scheduled results announcement (board meeting).' },
          { name: 'ALERTS', desc: 'Count of unread NOTIF alerts for this symbol. Click to filter NOTIF panel.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Click a row to set the global active symbol (updates CHART, ORDER, FDM).',
          'Click the ALERTS badge to jump to filtered notifications for that symbol.',
          'Switch watchlists using the dropdown in the header.',
          'Columns can be configured in SETTINGS.',
        ],
      },
    ],
  },

  // ── ORDER ──────────────────────────────────────────────────────────────────
  {
    command: 'ORDER',
    title: 'Order Entry & Book',
    summary:
      'Place market, limit, and SL orders for the active symbol via OpenAlgo. Also shows today\'s order book.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Order entry form at the top. Order book below showing all orders placed today with status, price, and quantity.',
      },
      {
        heading: 'Order fields',
        items: [
          { name: 'Symbol', desc: 'Pre-filled from the global active symbol.' },
          { name: 'Type', desc: 'MARKET, LIMIT, or SL-M (stop-loss market).' },
          { name: 'Product', desc: 'CNC (delivery/equity) or MIS (intraday margin).' },
          { name: 'Qty', desc: 'Number of shares to buy or sell.' },
          { name: 'Price', desc: 'Required for LIMIT and SL orders; ignored for MARKET.' },
          { name: 'Trigger', desc: 'Stop-loss trigger price for SL orders.' },
        ] as DocField[],
      },
      {
        heading: 'Order book statuses',
        items: [
          { name: 'open', desc: 'Order is live at the exchange, waiting to be matched.' },
          { name: 'complete', desc: 'Order fully executed.' },
          { name: 'rejected', desc: 'Exchange or broker rejected the order — check the rejection reason.' },
          { name: 'cancelled', desc: 'Order was cancelled before execution.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Set the active symbol in WATCH or CHART before opening ORDER.',
          'Use CNC for positional/delivery trades; MIS for intraday with margin.',
          'Limit orders give price control; market orders guarantee execution.',
        ],
      },
    ],
  },

  // ── POS ────────────────────────────────────────────────────────────────────
  {
    command: 'POS',
    title: 'Positions & P&L',
    summary:
      'Live view of all open positions with mark-to-market P&L, average cost, and day change.',
    sections: [
      {
        heading: 'What it shows',
        body: 'All open positions fetched from OpenAlgo. Refreshed periodically. P&L updates with live LTP from WebSocket.',
      },
      {
        heading: 'Columns',
        items: [
          { name: 'Symbol', desc: 'NSE ticker of the position.' },
          { name: 'Qty', desc: 'Net open quantity. Positive = long, negative = short (F&O).' },
          { name: 'Avg', desc: 'Average buy/sell price of the open position.' },
          { name: 'LTP', desc: 'Last traded price — live.' },
          { name: 'P&L', desc: 'Mark-to-market profit or loss on the open position. Green = profit, Red = loss.' },
          { name: 'Day P&L', desc: 'P&L for today\'s session only (useful for MIS positions).' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Negative P&L in red — consider whether the trade thesis is still valid.',
          'Click a position row to set that symbol as active for CHART / ORDER.',
          'MIS positions must be squared off before 3:20 PM or the broker may auto-square.',
        ],
      },
    ],
  },

  // ── TOP ────────────────────────────────────────────────────────────────────
  {
    command: 'TOP',
    title: 'Top Movers',
    summary:
      'Real-time NSE top gainers and losers ranked by intraday percentage change.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Two lists side-by-side: top gainers (highest % up) and top losers (highest % down) for the current session. Refreshes every 30 seconds.',
      },
      {
        heading: 'Columns',
        items: [
          { name: 'Symbol', desc: 'NSE ticker.' },
          { name: 'LTP', desc: 'Last traded price.' },
          { name: 'CHG%', desc: 'Intraday % change from previous close.' },
          { name: '1W / 1M / 3M', desc: 'Multi-timeframe return context (configurable).' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Click any symbol to set it as the global active symbol.',
          'Strong movers early in the session often sustain momentum; late-session movers may reverse.',
          'Cross-reference with BREAKOUTS to see if movers are also hitting 52-week levels.',
        ],
      },
    ],
  },

  // ── SETTINGS ───────────────────────────────────────────────────────────────
  {
    command: 'SETTINGS',
    title: 'Settings',
    summary:
      'Configure terminal preferences: visible columns, layout, and connection parameters.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Application settings grouped into categories. Changes are persisted to the local database and take effect immediately.',
      },
      {
        heading: 'Configuration areas',
        items: [
          { name: 'Watchlist Columns', desc: 'Toggle which columns appear in the WATCH widget (LTP, CHG, MSFV, returns, RESULTS, ALERTS).' },
          { name: 'Movers Columns', desc: 'Toggle which columns appear in the TOP widget.' },
          { name: 'Panel Layout', desc: 'Switch between 2, 4, 6, or 8 panel grid layouts.' },
          { name: 'OpenAlgo', desc: 'API URL and key for broker connectivity (ORDER, POS, CHART data).' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Changes to columns apply instantly — no page reload required.',
          'Layout changes resize all panels; drag dividers to adjust individual panel sizes.',
        ],
      },
    ],
  },

  // ── FDM ────────────────────────────────────────────────────────────────────
  {
    command: 'FDM',
    title: 'Fundamentals',
    summary:
      'Key fundamental ratios and recent quarterly financial results for the active symbol, sourced from Screener.in.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Valuation multiples, profitability ratios, and the last 4 quarters of revenue/profit data. Uses consolidated financials by default.',
      },
      {
        heading: 'Key ratios',
        items: [
          { name: 'P/E', desc: 'Price-to-Earnings. How many years of current earnings you pay at today\'s price. Compare within sector.' },
          { name: 'P/B', desc: 'Price-to-Book. Market value vs. accounting book value. High P/B means market expects strong ROE.' },
          { name: 'ROE', desc: 'Return on Equity. Net profit as % of shareholder equity. >15% is generally healthy.' },
          { name: 'ROCE', desc: 'Return on Capital Employed. Broader than ROE — includes debt. Indicates capital efficiency.' },
          { name: 'Debt/Equity', desc: 'Total debt relative to equity. High D/E amplifies both gains and losses.' },
          { name: 'Sales Growth', desc: 'Year-on-year revenue growth. Proxy for business momentum.' },
          { name: 'Promoter Holding', desc: '% of shares held by promoters. Declining promoter stake warrants scrutiny.' },
        ] as DocField[],
      },
      {
        heading: 'Quarterly results',
        items: [
          { name: 'Net Sales', desc: 'Revenue for the quarter. Growing QoQ + YoY is positive.' },
          { name: 'Net Profit', desc: 'Bottom-line profit. Watch for one-off items inflating/deflating numbers.' },
          { name: 'OPM%', desc: 'Operating profit margin. Stable or expanding margin = pricing power.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Compare P/E and ROCE against sector peers for context.',
          'Declining margins QoQ despite rising revenue can be an early warning.',
          'Screener.in data has a ~1-day lag; not suitable for intraday decisions.',
        ],
      },
    ],
  },

  // ── DEALS ──────────────────────────────────────────────────────────────────
  {
    command: 'DEALS',
    title: 'Bulk & Block Deals',
    summary:
      'Historical bulk and block deal records from NSE, searchable by symbol and date range.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Bulk deals (≥0.5% of shares in one session) and block deals (large negotiated trades via the block window). Sourced from Screener.in historical data.',
      },
      {
        heading: 'Fields',
        items: [
          { name: 'Date', desc: 'Date of the deal.' },
          { name: 'Symbol', desc: 'NSE ticker.' },
          { name: 'Client', desc: 'Entity name (buyer or seller). Institutions and FIIs are significant.' },
          { name: 'Buy/Sell', desc: 'Direction of the trade from the reported client\'s perspective.' },
          { name: 'Qty', desc: 'Number of shares transacted.' },
          { name: 'Price', desc: 'Deal execution price.' },
          { name: 'Value (₹ Cr)', desc: 'Total deal value. Larger values carry more signal weight.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Institutional buys in bulk/block deals signal conviction — especially if the buying continues across sessions.',
          'Check if the deal price is at a premium or discount to market — block deals at premium = urgency to buy.',
          'Repeated selling by promoters in bulk deals is a red flag.',
        ],
      },
    ],
  },

  // ── LARGEDEALS ─────────────────────────────────────────────────────────────
  {
    command: 'LARGEDEALS',
    title: 'Large Deals Snapshot',
    summary:
      'Real-time combined snapshot of all significant insider, bulk, and block deals across the entire NSE universe for today.',
    sections: [
      {
        heading: 'What it shows',
        body: 'A live feed of today\'s large deal activity across all NSE stocks in a single view. Refreshes frequently during market hours. Filtered by significance thresholds (deal size as % of market cap or absolute ₹ Cr value).',
      },
      {
        heading: 'Deal types shown',
        items: [
          { name: 'Bulk Deal', desc: 'Single entity traded ≥0.5% of shares in one session via the exchange.' },
          { name: 'Block Deal', desc: 'Large negotiated trade executed via the block window before/after market.' },
          { name: 'Insider Trade', desc: 'Trade reported by a promoter, director, or key management person.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Use as a discovery tool — find stocks with institutional activity you may not be tracking.',
          'Filter by deal type to focus on insider activity vs. institutional deals.',
          'Click a symbol to set it globally and deep-dive with CHART or FDM.',
        ],
      },
    ],
  },

  // ── BREAKOUTS ──────────────────────────────────────────────────────────────
  {
    command: 'BREAKOUTS',
    title: '52-Week Breakouts',
    summary:
      'All NSE stocks that touched a new 52-week high or low today, with multi-timeframe return context.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Two lists: 52-week highs and 52-week lows. Data is sourced from NSE live data, refreshed during market hours. Returns for multiple timeframes give context on the trend.',
      },
      {
        heading: 'Interpreting breakouts',
        items: [
          {
            name: '52W High',
            desc: 'Stock at an annual high. Bullish momentum signal — but verify with volume. False breakouts without volume tend to reverse quickly.',
          },
          {
            name: '52W Low',
            desc: 'Stock at an annual low. Can be a breakdown (bearish continuation) or a capitulation bottom. Sector weakness must be checked.',
          },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          '52W highs with expanding volume are the most reliable breakout candidates.',
          '52W lows with contracting volume + reversal candles may signal a bottom.',
          'Cross-reference with FDM — a 52W high on strong fundamentals is higher conviction.',
        ],
      },
    ],
  },

  // ── NEWS ───────────────────────────────────────────────────────────────────
  {
    command: 'NEWS',
    title: 'News',
    summary:
      'Market and company-specific news articles from MoneyControl, covering global events and watchlist stocks.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Two tabs: Global (market-wide headlines) and Company (news specific to watchlist symbols). Articles are fetched every 5 minutes and stored locally.',
      },
      {
        heading: 'Tabs',
        items: [
          { name: 'Global', desc: 'Broad market news — macroeconomic events, RBI/SEBI announcements, global markets.' },
          { name: 'Company', desc: 'Symbol-specific news for stocks in your active watchlist. Auto-refreshed when symbols change.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Global news is essential context — a market-wide risk-off event affects all positions.',
          'Filter company news by clicking a symbol in WATCH — the NEWS panel updates to show that symbol\'s articles.',
          'News articles are time-stamped; older articles provide background but do not drive intraday price action.',
        ],
      },
    ],
  },

  // ── ANALYSIS ───────────────────────────────────────────────────────────────
  {
    command: 'ANALYSIS',
    title: 'Sector & Industry Analysis',
    summary:
      'Broad market analysis by sector and industry: sentiment, PE, advance/decline ratios, and earnings growth.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Sector and industry-level aggregates from MoneyControl. Refreshed every 5 minutes. Provides top-down context for individual stock decisions.',
      },
      {
        heading: 'Fields',
        items: [
          { name: 'Sentiment', desc: 'Bullish / Bearish / Neutral classification based on advance/decline and price trend.' },
          { name: 'PE', desc: 'Sector-level price-to-earnings ratio. Useful for comparing with individual stock PE.' },
          { name: 'Advance/Decline', desc: 'Number of stocks in the sector that are up vs. down today. Breadth indicator.' },
          { name: 'Earnings YoY', desc: 'Year-on-year earnings growth for the sector aggregate.' },
          { name: 'Market Cap', desc: 'Total market cap of all stocks in the sector (₹ Cr).' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Trade with the sector tailwind — a bullish sector amplifies individual stock moves.',
          'A/D ratio below 0.5 in your stock\'s sector signals broad weakness; raises the bar for longs.',
          'Click a sector to drill down into its constituent stocks ranked by market cap.',
        ],
      },
    ],
  },

  // ── NOTIF ──────────────────────────────────────────────────────────────────
  {
    command: 'NOTIF',
    title: 'Notifications',
    summary:
      'Watchlist-scoped alerts generated every 5 minutes during market hours. Covers 26 trigger types across price, volume, deals, insider activity, and technicals.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Alerts generated specifically for stocks in your active watchlist. The background worker checks NSE live data, Screener.in insider data, and pre-computed technical indicators every 5 minutes. One alert per trigger type per symbol per day (deduplication prevents noise).',
      },
      {
        heading: 'Categories',
        items: [
          { name: '52W', desc: 'Price touching or near 52-week high/low levels.' },
          { name: 'VOLUME', desc: 'Unusual volume spikes vs. weekly average.' },
          { name: 'MOVERS', desc: 'Stock appearing in NSE top gainers or losers.' },
          { name: 'DEALS', desc: 'Bulk, block, or short deals reported today.' },
          { name: 'INSIDER', desc: 'Promoter or director buy/sell transactions.' },
          { name: 'TECHNICAL', desc: 'RSI, MACD, and Bollinger Band signals from daily data.' },
          { name: 'MOMENTUM', desc: 'Composite momentum surge or 1-week return spike.' },
          { name: 'VOLATILITY', desc: 'Historical volatility spike or ATR expansion.' },
          { name: 'STREAKS', desc: 'Consecutive up or down close streaks (configurable minimum days).' },
          { name: 'RESULTS', desc: 'Upcoming board meetings scheduled to announce financial results.' },
        ] as DocField[],
      },
      {
        heading: 'Trigger type glossary',
        items: TRIGGER_TYPE_DOCS.map((t) => ({ name: t.name, desc: t.desc })) as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Use the category tabs to focus on a class of signals (e.g. only TECHNICAL).',
          'Sub-filter bubbles let you narrow within a category to specific trigger types.',
          'Click an alert row to set that symbol globally — use with CHART for confirmation.',
          'CLEAR ALL marks all alerts as read; they are gone from the unread feed but kept in the database.',
          'Alerts are deduplicated daily — you will only see one RSI oversold alert per symbol per day.',
        ],
      },
    ],
  },

  // ── ANNC ───────────────────────────────────────────────────────────────────
  {
    command: 'ANNC',
    title: 'Announcements',
    summary:
      'NSE corporate announcements feed: board meetings, dividends, AGMs, and regulatory filings.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Official NSE corporate announcements filed by listed companies. Filtered to show recent filings with search and symbol filter capability.',
      },
      {
        heading: 'Announcement types',
        items: [
          { name: 'Board Meeting', desc: 'Scheduled meeting to discuss dividends, results, buybacks, or other corporate actions.' },
          { name: 'Financial Results', desc: 'Quarterly or annual results filed with NSE after the board meeting.' },
          { name: 'Dividend', desc: 'Dividend declaration — note record date to be eligible.' },
          { name: 'AGM / EGM', desc: 'Annual or Extraordinary General Meeting. Can include resolutions on capital raise, mergers.' },
          { name: 'Regulatory Filing', desc: 'SEBI or exchange-mandated disclosures (insider trades, pledging, shareholding pattern).' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Filter by symbol to see all announcements for a specific stock.',
          'Board meeting + results = catalyst event. Add the stock to WATCH ahead of time.',
          'Dividend record dates determine eligibility — buy before the record date to receive the dividend.',
        ],
      },
    ],
  },

  // ── SCAN ───────────────────────────────────────────────────────────────────
  {
    command: 'SCAN',
    title: 'Global Market Scanner',
    summary:
      'Universe-wide scan alerts covering all ~2000 NSE stocks (not just your watchlist). Updated every 30 minutes.',
    sections: [
      {
        heading: 'What it shows',
        body: 'The same 26 trigger types as NOTIF, but applied to the full NSE stock universe. The backend scan runs every 30 minutes. Results are stored in a separate table (GlobalNotification) and are not watchlist-scoped.',
      },
      {
        heading: 'Difference from NOTIF',
        items: [
          {
            name: 'Scope',
            desc: 'NOTIF = your watchlist only, every 5 min. SCAN = all NSE stocks, every 30 min.',
          },
          {
            name: 'Purpose',
            desc: 'NOTIF monitors known holdings. SCAN discovers new opportunities across the market.',
          },
          {
            name: 'Volume',
            desc: 'SCAN produces significantly more alerts — use category tabs and sub-filters to manage noise.',
          },
        ] as DocField[],
      },
      {
        heading: 'Trigger type glossary',
        items: TRIGGER_TYPE_DOCS.map((t) => ({ name: t.name, desc: t.desc })) as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Use SCAN to discover stocks generating signals that are not in your watchlist.',
          'Filter to high-conviction trigger types: 52w_high_breakout + volume_breakout together are stronger than either alone.',
          'Click a symbol to set it globally — cross-reference with FDM, DEALS, and NEWS before acting.',
          'SCAN data is 30 minutes old — validate with current price and volume in CHART.',
        ],
      },
    ],
  },
  // ─── AI Chat ─────────────────────────────────────────────────────────────────
  {
    command: 'AI',
    title: 'AI Chat',
    summary:
      'Conversational AI assistant with live access to all NSE market data tools. Powered by MiniMax via OpenCode Zen.',
    sections: [
      {
        heading: 'Overview',
        body: 'Ask questions in plain English about any NSE stock, sector, or market condition. The AI calls live data tools to answer — it does not rely on memorised training data for prices, fundamentals, or news.',
      },
      {
        heading: 'Available data tools',
        items: [
          { name: 'Live quotes', desc: 'get_symbol_data — LTP, 52-week range, sector' },
          { name: 'Fundamentals', desc: 'screener_company — P/E, ROCE, ROE, quarterly results' },
          { name: 'News', desc: 'get_company_news, get_global_news — MoneyControl articles' },
          { name: 'Deals', desc: 'get_bulk_deals, get_block_deals, screener_trades — institutional activity' },
          { name: 'Market movers', desc: 'get_top_gainers, get_top_losers, get_volume_gainers' },
          { name: 'Breakouts', desc: 'get_52week_high_stocks, get_52week_low_stocks, get_global_notifications' },
          { name: 'Sectors', desc: 'list_sectors, list_industries, get_sector_stocks, get_industry_stocks' },
          { name: 'Fair value', desc: 'get_morningstar_fairvalue — Morningstar estimates' },
          { name: 'Watchlists', desc: 'list_watchlists, get_watchlist_items' },
          { name: 'Alerts', desc: 'get_notifications, get_global_notifications — unread scan alerts' },
        ] as DocField[],
      },
      {
        heading: 'Models',
        items: [
          { name: 'M2.5 Free', desc: 'Zero cost — for development and testing only. Do not use with sensitive data.' },
          { name: 'M2.5', desc: 'Best for coding-style data queries and structured output. Fast.' },
          { name: 'M2.7', desc: 'Highest quality reasoning. Slower and more verbose — use for complex analysis.' },
          { name: 'M2.1', desc: 'Strong multilingual support. Lower cost than M2.7.' },
        ] as DocField[],
      },
      {
        heading: 'Tips',
        items: [
          'The active symbol is injected automatically — ask "what\'s the PE?" without specifying the ticker.',
          'Press Enter to send, Shift+Enter for a newline.',
          'Click Stop to cancel a running response.',
          'Tool call badges appear while the AI is fetching data — green check when done.',
          'The AI follows an agentic loop: it can call multiple tools across turns to build a complete answer.',
          'Set OPENCODE_ZEN_API_KEY in backend .env to enable this widget.',
        ],
      },
    ],
  },
];

// ─── Lookup helper ────────────────────────────────────────────────────────────

export const WIDGET_DOCS: Record<string, WidgetDoc> = Object.fromEntries(
  DOCS_MAP.map((d) => [d.command, d]),
);

export const DOCS_INDEX: WidgetDoc[] = DOCS_MAP;

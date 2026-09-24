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
  // Repeated Breakouts
  {
    name: 'repeated_52w_high',
    desc: 'Stock appeared in the 52W HIGH list multiple times in the last 10 calendar days. Persistent bullish momentum — consistent buying interest across sessions.',
  },
  {
    name: 'repeated_52w_low',
    desc: 'Stock appeared in the 52W LOW list multiple times in the last 10 calendar days. Persistent bearish pressure — sustained selling across sessions.',
  },
  {
    name: 'repeated_volume_breakout',
    desc: 'Stock appeared in the volume gainers list multiple times in the last 10 calendar days. Sustained unusual trading activity — may indicate accumulation or distribution.',
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
        body: 'OHLC candlesticks for the panel symbol: linked panels follow the global active symbol, detached ([FREE]) panels hold their own per-panel override. Daily candles come from the backend ticker warehouse (/api/py/ticker/ohlcv); intraday/weekly/monthly from /api/py/ticker/intraday; live LTP overlays arrive via the market WebSocket.',
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
          'Click any symbol in WATCH or TOP to update all linked charts (detached charts are unaffected).',
          'Searching or pressing GO inside a chart detaches that panel ([FREE]) so it keeps its own symbol.',
          'Use the [FREE]/[LINK] toggle in the panel header (CHART panels only) to re-link a detached chart to the global symbol.',
          'Popping out ([POP]) a chart carries its symbol along: the popout gets its own override key seeded from the home panel, and docking ([SEND BACK]) moves it back. Each open popout is independent.',
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
        body: 'Two lists: top gainers (highest % up) and top losers (highest % down) for the current session. Refreshes every 60 seconds. Filter by market category (NIFTY 50, Bank NIFTY, F&O, etc.).',
      },
      {
        heading: 'Columns',
        items: [
          { name: 'Symbol', desc: 'NSE ticker.' },
          { name: 'CLOSE', desc: 'Last traded price (LTP).' },
          { name: 'CHG%', desc: 'Intraday % change from previous close.' },
          { name: 'OPEN / HIGH / LOW', desc: 'Session open, intraday high, and intraday low prices.' },
          { name: 'VOL', desc: 'Total traded quantity for the session.' },
          { name: 'TRNVR', desc: 'Total turnover in ₹ Crores.' },
          { name: 'CA', desc: 'Corporate Action ex-date (dividend, bonus, split, etc.). Hover for the purpose.' },
          { name: '1W% / 1M% / 3M% / 6M% / 1Y% / 2Y% / 3Y% / 5Y%', desc: 'Price return over the stated period (from market WebSocket / NSE data).' },
          { name: '52W HIGH / 52W LOW', desc: '52-week high and low prices (fetched via market WebSocket).' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Click any symbol to set it as the global active symbol.',
          'Toggle columns in SETTINGS → Movers Columns.',
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
      'Configure terminal preferences: data extraction and browser provisioning, visible columns, layout, AI providers, and connection parameters.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Application settings grouped into categories. Changes are persisted to the local database and take effect immediately.',
      },
      {
        heading: 'Configuration areas',
        items: [
          { name: 'Data Extraction & Privacy', desc: 'Advanced Extraction consent plus the headless-browser provisioning status (unknown / ready / missing / downloading / failed) with download progress and a Retry button (shown for failed/missing). Granting consent triggers a backend Camoufox fetch; the status poll runs every 5s while consented and stops once ready.' },
          { name: 'Watchlist Columns', desc: 'Toggle which columns appear in the WATCH widget (LTP, CHG, MSFV, returns, RESULTS, ALERTS).' },
          { name: 'Movers Columns', desc: 'Toggle which columns appear in the TOP widget.' },
          { name: 'Panel Layout', desc: 'Switch between 2, 4, 6, or 8 panel grid layouts.' },
          { name: 'AI Provider', desc: 'Engine, keys/OAuth, and model list for the AI widget (auto-saved to system-config ai.*).' },
          { name: 'OpenAlgo', desc: 'API URL and key for broker connectivity (ORDER, POS execution).' },
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
      'Key fundamental ratios and recent quarterly financial results for the active symbol, sourced from Screener.in with NSE ratios and iinvest enrichment as fallbacks.',
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
        heading: 'Calculated Ratios',
        items: [
          { name: 'Piotroski Score', desc: '9-point quality score. ≥7 = strong, 4–6 = average, <4 = weak.' },
          { name: 'Peter Lynch FV', desc: 'Fair value from EPS growth × EPS. Compare to current price.' },
          { name: 'Peter Lynch FV Ratio', desc: '(EPS Growth + Div Yield) / P/E. >1.0 suggests undervaluation.' },
          { name: 'MS Fair Value', desc: 'Morningstar fair value estimate when available.' },
        ] as DocField[],
      },
      {
        heading: 'Valuation Columns',
        items: [
          { name: 'Model', desc: 'The valuation methodology being applied.' },
          { name: 'Fair Value', desc: 'The intrinsic value price per share calculated by the model.' },
          { name: 'vs CMP', desc: 'The percentage difference between the computed Fair Value and the Current Market Price. Positive indicates potential upside.' },
          { name: 'Signal', desc: 'Categorization based on upside: UNDERVALUED (>+15% upside), FAIR (±15%), or OVERVALUED (<-15% upside).' },
        ] as DocField[],
      },
      {
        heading: 'Valuation Models',
        items: [
          { name: 'Graham Number', desc: '√(22.5 × EPS × Book Value). Conservative floor price from screener.in or computed.' },
          { name: 'DCF (10Y)', desc: 'Discounted cash flow with 2-stage growth. Requires FCF; auto-growth from revenue/earnings growth.' },
          { name: 'DDM', desc: 'Dividend Discount Model. Only shown when dividend > 0.' },
          { name: 'EV/EBITDA', desc: 'Enterprise value at sector median multiple. Uses screener EBITDA when available.' },
          { name: 'PEG Fair Value', desc: 'Forward EPS × earnings growth rate (Lynch rule).' },
        ] as DocField[],
      },
      {
        heading: 'Valuation Controls',
        items: [
          { name: 'Weighted Average Cost of Capital', desc: 'The discount rate applied to future cash flows. A higher WACC reflects higher risk and lowers the present fair value.' },
          { name: 'Terminal Growth Rate', desc: 'The perpetual growth rate of cash flows after the 10-year forecast period. Changing these triggers a live re-calculation.' },
        ] as DocField[],
      },
      {
        heading: 'Data sources & enrichment',
        items: [
          { name: 'Screener.in', desc: 'Primary source for ratios, quarterly results, and valuation inputs. Needs a session; ~1-day lag.' },
          { name: 'NSE Market Ratios', desc: '4 of 10 core ratios (P/E, sector P/E, 52W high/low) from NSE GetQuoteApi — no session needed, shown when screener is unavailable.' },
          { name: 'iinvest Enrichment (6 sections)', desc: 'Announcements, board meetings, corporate actions, legal cases, capital history, and key ratios from iinvest. Requires Advanced Extraction consent (Safe Mode disables it); authenticated automatically with a guest JWT. Sections render only while the token is live.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Compare P/E and ROCE against sector peers for context.',
          'Declining margins QoQ despite rising revenue can be an early warning.',
          'Screener.in data has a ~1-day lag; not suitable for intraday decisions.',
          'Valuation models use screener.in data first; yfinance fills gaps for FCF, forward EPS, and shares outstanding.',
          'Not all models compute for every stock — DDM requires dividends, DCF requires FCF.',
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
      'Multi-source financial news aggregator combining 35+ RSS feeds (global wire services, financial media, India business, crypto, and tech) with MoneyControl scraped articles. Articles are NLP-enriched with sentiment, threat classification, entity extraction, and source credibility scoring.',
    sections: [
      {
        heading: 'What it shows',
        body: 'Two tabs. Global shows a unified feed of all RSS and MoneyControl articles with source filtering, sentiment indicators, and threat badges. Company defaults to merged coverage: iinvest full stories (/api/v1/news/stories) first with MoneyControl fallback for deep history; Safe Mode (Advanced Extraction declined) forces MoneyControl only. A source selector (auto / iinvest / moneycontrol / merged) and force-refresh (bypasses the 2h cache) sit in the Company header; responses tag source_used. Articles are stored locally. A live WebSocket connection pushes new articles in real time as they are fetched.',
      },
      {
        heading: 'Sources & coverage',
        items: [
          { name: 'Tier 1 Wire & Regulatory', desc: 'AP Top News, SEC Press Releases, Federal Reserve, ECB, Bank of England — primary-source regulatory and macro announcements.' },
          { name: 'Tier 1 Financial Media', desc: 'Bloomberg Markets, WSJ Markets, CNBC Finance — major global financial outlets.' },
          { name: 'Tier 2 India', desc: 'MoneyControl RSS, Economic Times, LiveMint, The Hindu Business — India-focused business and market news.' },
          { name: 'Tier 2 Global', desc: 'MarketWatch, Seeking Alpha, Investing.com, Benzinga, BBC Business, Nikkei Asia, CNA, The Economist, Al Jazeera, Foreign Policy.' },
          { name: 'Tier 2 Crypto', desc: 'CoinDesk, CoinTelegraph, The Block.' },
          { name: 'Tier 2 Tech', desc: 'TechCrunch, Finextra, The Verge, Ars Technica.' },
          { name: 'Tier 3 Blogs & Aggregators', desc: 'BBC World, Calculated Risk, ZeroHedge (flagged CAUTION), Bellingcat, Hacker News, Abnormal Returns.' },
          { name: 'MoneyControl Scraped', desc: 'Full article text scraped from MoneyControl global and company pages. Serves as fallback when RSS feeds are unavailable.' },
        ] as DocField[],
      },
      {
        heading: 'NLP pipeline (rule-based)',
        items: [
          { name: 'Sentiment analysis', desc: 'Weighted keyword matching against curated positive/negative word lists (e.g. "surge" +3, "crash" -3). Net score ≥ 2 → BULLISH; ≤ -2 → BEARISH; otherwise NEUTRAL. Confidence scales with total signal count.' },
          { name: 'Entity extraction', desc: 'Regex-based extraction of countries (60+ mapped to ISO codes), organizations (30+ including central banks, regulators, tech giants), known persons (20+ political and business leaders), and tickers (uppercase 2–5 letter words, filtered against common false positives).' },
          { name: 'Threat classification', desc: 'Keyword-pattern matching for CRITICAL (nuclear strike, market crash), HIGH (invasion, rate hike, sanction), MEDIUM (protest, tariff, recession), and LOW (general) threat levels. Each level has an associated category: conflict, market, cyber, natural, or regulatory.' },
          { name: 'Language detection', desc: 'Character-script detection for Chinese (zh), Japanese (ja), Korean (ko), Russian (ru), Arabic (ar), Hindi (hi). Defaults to English (en).' },
          { name: 'Source credibility', desc: 'Static classification: STATE_MEDIA (Xinhua, CGTN, RT, TASS, etc.), CAUTION (ZeroHedge, Infowars, Daily Mail, NY Post), or NONE (default). Flagged sources show a yellow warning icon (⚠).' },
        ] as DocField[],
      },
      {
        heading: 'UI indicators',
        items: [
          { name: 'Sentiment dot', desc: 'Green = BULLISH, Red = BEARISH, Gray = NEUTRAL. Opacity scales with confidence score (0.3–1.0).' },
          { name: 'Threat badge', desc: 'LOW (green), MED (yellow), HIGH (red), CRIT (red bold). Appears next to article titles when threat_level is not LOW.' },
          { name: 'Credibility warning', desc: 'Yellow ⚠ icon appears for STATE_MEDIA and CAUTION sources.' },
          { name: 'LIVE indicator', desc: 'Green pulsing dot in the Global tab header when the WebSocket is connected. New articles pushed live appear in a separate "LIVE" section above the paginated DB feed.' },
        ] as DocField[],
      },
      {
        heading: 'Filtering & pagination',
        items: [
          { name: 'Source filter chips', desc: 'Toggle individual sources on/off in the Global tab. Only selected sources are shown. Clear to reset.' },
          { name: 'Sentiment filter', desc: 'Filter by BULLISH, BEARISH, or NEUTRAL (stored in news.filters atom).' },
          { name: 'Threat filter', desc: 'Filter by LOW, MEDIUM, HIGH, or CRITICAL (stored in news.filters atom).' },
          { name: 'Pagination', desc: '50 articles per page. Prev/Next buttons at the bottom. Total count displayed.' },
        ] as DocField[],
      },
      {
        heading: 'How to use',
        items: [
          'Global news provides macro context — a risk-off event or central bank announcement affects all positions.',
          'Use source filter chips to focus on specific outlets (e.g. only Tier 1 wire services for unfiltered primary-source news).',
          'Click a symbol in WATCH to auto-filter Company news to that ticker.',
          'Sentiment dots + threat badges give at-a-glance signal strength. A BULLISH + LOW article from a Tier 1 source is high-confidence context.',
          'The NLP pipeline is rule-based, not ML — treat sentiment and threat scores as directional hints, not definitive forecasts.',
          'LIVE articles arrive via WebSocket and are deduplicated by URL. They appear for 5 minutes before being absorbed into the paginated DB feed.',
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
        body: 'Locally built sector and industry aggregates (advance/decline breadth, PE, earnings, market cap). Rebuilt by the market_data job every 20 minutes. Provides top-down context for individual stock decisions.',
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
          'Expand a sector to see constituent stocks; clicking a company name sets it as the global active symbol (CHART, ORDER, FDM follow).',
          'Click a heatmap tile to open that category\'s stock table in a modal (Esc/backdrop closes).',
          'Name column keeps a 160px floor; narrow panels scroll horizontally (header scrolls with rows).',
          'If every market cap shows —, the universe has not synced yet: trigger market_caps or fundamentals from the Jobs page.',
        ],
      },
    ],
  },

  // ── NOTIF ──────────────────────────────────────────────────────────────────
  {
    command: 'NOTIF',
    title: 'Notifications',
    summary:
      'Watchlist-scoped alerts generated every 5 minutes during market hours. Covers 29 trigger types across price, volume, deals, insider activity, and technicals.',
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
          'iinvest-backed enrichment needs Advanced Extraction consent: with consent, guest login supplies the token automatically (no browser needed).',
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
        body: 'The same 29 trigger types as NOTIF, but applied to the full NSE stock universe. The backend scan runs every 30 minutes. Results are stored in a separate table (GlobalNotification) and are not watchlist-scoped.',
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
          'iinvest-backed enrichment needs Advanced Extraction consent: with consent, guest login supplies the token automatically (no browser needed).',
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
      'Conversational AI assistant with live access to all NSE market data tools. Engine is the provider selected in Settings → AI Provider.',
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
        heading: 'Research Agent Personas',
        items: [
          { name: 'Value Analyst', desc: 'Graham/Buffett framework — margin of safety, moat assessment, Graham Number, ROCE/ROE quality, red flags.' },
          { name: 'Earnings Analyst', desc: 'QoQ/YoY earnings forensics — revenue/profit trends, EPS trajectory, margin analysis, earnings quality.' },
          { name: 'F&O Analyst', desc: 'Options strategy & derivatives — trend assessment, IV context, CE/PE bias, hedging suggestions, risk management.' },
          { name: 'Macro Analyst', desc: 'Sector rotation & India macro — market breadth, FII/DII flows, RBI policy, sector positioning, macro tailwinds/headwinds.' },
        ] as DocField[],
      },
      {
        heading: 'Models',
        items: [
          { name: 'Per-provider catalog', desc: 'Models are listed per provider via the provider-models endpoint — there is no fixed lineup. Pick the engine in Settings → AI Provider first.' },
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
          'Select a persona before asking for focused, disciplined analysis on a specific framework.',
          'Configure the provider key/OAuth in Settings; check the AI status endpoint for Connected before troubleshooting.',
        ],
      },
    ],
  },
  // ─── Script Lab ──────────────────────────────────────────────────────────────
  {
    command: 'SCRIPTS',
    title: 'Script Lab — AI chart scripts',
    summary:
      'Pine-like but plain-JS chart overlays written by the AI in Script mode. You describe intent, the AI saves a versioned script, and Accept puts it on the chart. There is no code editor — you never author code.',
    sections: [
      {
        heading: 'Overview',
        body: 'Scripts are small calculate(ctx) programs: declared params, up to 8 outputs (line, histogram, markers, priceline, band). They run in a Web Worker with a 2s watchdog over the chart bars plus optional fundamentals context, and paint through the same overlay path as built-in indicators. User scripts are private to your login; 5 builtin seeds ship read-only.',
      },
      {
        heading: 'AI Script mode',
        items: [
          { name: 'Research | Σ Script toggle', desc: 'Per-session switch in the AI header, sent with every chat POST. Script mode adds the Script Lab system prompt (manifest format, BLM stdlib, limits).' },
          { name: 'Workflow', desc: 'Ask in plain words ("RSI bands with 70/30 lines"). The AI lists/gets prior scripts, validates the code with validate_script_code, then create_script / revise_script. Validation is static + fixture dry-run — you accept before anything renders.' },
          { name: 'Script card', desc: 'Each create/revise emits a Σ card in the turn (name, created vs revised + rev number). Accept → chart enables that revision on the focused chart panel; Discard only hides the card — the script stays saved.' },
          { name: 'Revisions', desc: 'Revises are immutable and append-only. Roll back from history, tune params live in the chart Σ menu (params survive revises and rollback). Nothing renders until you Accept.' },
        ] as DocField[],
      },
      {
        heading: 'Chart side',
        items: [
          { name: 'Σ menu', desc: 'Chart toolbar popover: ON THIS CHART (enabled scripts, per-slot param forms, ✕ detach, ✎ refine-with-AI) and BROWSE (enable any saved script).' },
          { name: 'Refine handoff', desc: '✎ prefills the AI input with a script-scoped prompt and focuses the AI panel — or opens an AI popout when no AI panel is on the grid.' },
          { name: 'Failure policy', desc: 'A script that errors 3 runs in a row is auto-disabled with the message shown in the Σ menu; Retry via Browse. Fundamentals-backed scripts wait for consent + quarterly/ratios fetch.' },
        ] as DocField[],
      },
      {
        heading: 'Limits (v1)',
        items: [
          'Main pane only — no separate oscillator panes; histograms get their own scale.',
          'Line cap 2000 bars per run; 24 params and 8 outputs max; 64KB code max.',
          'No custom drawings (markers cover the v1 cases), no alerts, no backtesting.',
          'Scripts needing fundamentals require Advanced Extraction consent (Safe Mode hides them).',
        ],
      },
    ],
  },
  // ─── Portfolio Optimizer ───────────────────────────────────────────────────────
  {
    command: 'PORTFOLIO',    title: 'Portfolio Optimizer',
    summary:
      'Modern Portfolio Theory optimizer using PyPortfolioOpt. Select watchlist stocks, choose an objective, and receive optimal allocation weights.',
    sections: [
      {
        heading: 'Overview',
        body: 'Build a statistically optimal portfolio from your watchlist stocks. The optimizer uses mean-variance optimization (Markowitz) or hierarchical risk parity to find weights that maximise risk-adjusted return.',
      },
      {
        heading: 'Data Source',
        body: 'Historical prices come from the local ticker_daily warehouse (SQLite DB populated by nightly NSE backfill). If data is missing or insufficient, the optimizer automatically triggers an NSE backfill via nsepython before computing. No external Yahoo Finance calls are made.',
      },
      {
        heading: 'Watchlist Selection',
        body: 'Choose any watchlist from the dropdown at the top of the left panel. Symbols load dynamically when you switch watchlists. Only one watchlist can be active at a time.',
      },
      {
        heading: 'Objectives',
        items: [
          { name: 'Max Sharpe', desc: 'Maximise the Sharpe ratio — best risk-adjusted return.' },
          { name: 'Min Volatility', desc: 'Minimise portfolio volatility — most conservative allocation.' },
          { name: 'Risk Parity', desc: 'Equal risk contribution from each asset — HRP algorithm.' },
        ] as DocField[],
      },
      {
        heading: 'Inputs',
        items: [
          { name: 'Stocks', desc: 'Select 3–30 symbols from the active watchlist.' },
          { name: 'Period', desc: 'Historical lookback: 1Y, 2Y, or 3Y of daily prices from the DB.' },
          { name: 'Risk-free rate', desc: 'Fixed at 6.5% (approx RBI repo rate).' },
        ] as DocField[],
      },
      {
        heading: 'Outputs',
        items: [
          { name: 'Optimal weights', desc: 'Horizontal bar chart showing allocation % per symbol.' },
          { name: 'Expected return', desc: 'Annualised return of the optimised portfolio.' },
          { name: 'Expected volatility', desc: 'Annualised standard deviation.' },
          { name: 'Sharpe ratio', desc: 'Risk-adjusted return metric.' },
          { name: 'Correlation heatmap', desc: 'Visual grid showing pairwise correlations.' },
          { name: 'Per-symbol stats', desc: 'Individual annual return, volatility, and Sharpe for each selected stock.' },
        ] as DocField[],
      },
      {
        heading: 'Tips',
        items: [
          'Select at least 3 stocks — the optimizer requires a minimum for meaningful diversification.',
          'Highly correlated stocks (e.g. all PSU banks) may produce extreme weights — this is mathematically correct.',
          'If max_sharpe fails (no asset exceeds risk-free rate), the optimizer falls back to equal weights.',
          'Use Risk Parity when you want balanced risk contribution rather than pure return maximisation.',
          'Results are cached for 15 minutes — click Optimize again to force a recompute.',
          'Symbols with no price data after backfill appear in the "Failed" list and are excluded from optimization.',
        ],
      },
    ],
  },

  // ─── SCREENER ────────────────────────────────────────────────────────────────
  {
    command: 'SCREENER',
    title: 'Stock Screener (TQL)',
    summary: 'Filter the entire NSE universe using Ticker Query Language (TQL). Type a query in the bar and press Enter or Run.',
    sections: [
      {
        heading: 'Ticker Query Language (TQL)',
        body: 'TQL is a plain-English filter expression. Combine conditions with AND, OR, NOT, and parentheses. Each condition is FIELD OPERATOR VALUE. Use Tab/↑↓ to navigate autocomplete suggestions.',
      },
      {
        heading: 'Operators',
        items: [
          { name: '>  <  >=  <=', desc: 'Numeric comparisons. Example: RSI > 60' },
          { name: '=  !=',        desc: 'Equality / inequality. Works for numbers and strings. Example: Sector = "Banks"' },
          { name: 'IN (...)',     desc: 'Match any value in a list. Example: Sector IN ("Banks", "IT", "Pharma")' },
          { name: 'AND',          desc: 'Both conditions must be true.' },
          { name: 'OR',           desc: 'Either condition must be true.' },
          { name: 'NOT',          desc: 'Negate a condition. Example: NOT BBSqueeze' },
        ] as DocField[],
      },
      {
        heading: 'Interval Prefix',
        body: 'By default, indicator fields use the active interval tab (Daily / 1h / Weekly / Monthly). Override per-field with a prefix: 1h:RSI, W:ATR, M:MACD.',
        items: [
          { name: '1d:RSI', desc: 'Daily RSI (same as RSI when Daily tab is active)' },
          { name: '1h:RSI', desc: 'Hourly RSI' },
          { name: 'W:ATR',  desc: 'Weekly ATR %' },
          { name: 'M:MACD', desc: 'Monthly MACD' },
        ] as DocField[],
      },
      {
        heading: 'Indicator Fields',
        items: [
          { name: 'RSI',          desc: 'RSI(14). Oversold < 30, overbought > 70.' },
          { name: 'ATR',          desc: 'ATR as % of price. Low = compressed, high = volatile.' },
          { name: 'MACD',         desc: 'MACD line value.' },
          { name: 'MACDSignal',   desc: 'MACD signal line.' },
          { name: 'MACDHist',     desc: 'MACD histogram (MACD − Signal).' },
          { name: 'BBWidth',      desc: 'Bollinger Band width (% of middle band).' },
          { name: 'BBSqueeze',    desc: 'Boolean — true when bands are in a squeeze.' },
          { name: 'HV20',         desc: 'Historical volatility over 20 days.' },
          { name: 'HV60',         desc: 'Historical volatility over 60 days.' },
          { name: 'Sharpe60',     desc: 'Sharpe ratio over 60 trading days.' },
          { name: 'Sharpe126',    desc: 'Sharpe ratio over 126 trading days.' },
        ] as DocField[],
      },
      {
        heading: 'Price & Return Fields',
        items: [
          { name: 'Change',        desc: 'Today\'s % price change (open → last).' },
          { name: 'Close',         desc: 'Last traded price.' },
          { name: 'Volume',        desc: 'Volume ratio: today\'s volume ÷ 20-day average.' },
          { name: 'Return1w',      desc: '1-week return %.' },
          { name: 'Return1m',      desc: '1-month return %.' },
          { name: 'Return3m',      desc: '3-month return %.' },
          { name: 'Return6m',      desc: '6-month return %.' },
          { name: 'Return1y',      desc: '1-year return %.' },
          { name: 'From52wHigh',   desc: '% below the 52-week high (usually negative). Example: From52wHigh > -5 means within 5% of 52w high.' },
          { name: 'From52wLow',    desc: '% above the 52-week low.' },
        ] as DocField[],
      },
      {
        heading: 'Fundamental & Meta Fields',
        items: [
          { name: 'PE',            desc: 'Price-to-earnings ratio.' },
          { name: 'MomentumScore', desc: 'Composite momentum score (0–100).' },
          { name: 'Sector',        desc: 'NSE sector string. Use quotes: Sector = "Banks".' },
          { name: 'Industry',      desc: 'Industry sub-category (partial match).' },
          { name: 'Symbol',        desc: 'Ticker symbol. Example: Symbol = "RELIANCE".' },
          { name: 'DataPoints',    desc: 'Number of daily candles available. Use DataPoints > 200 to filter out recently listed stocks.' },
        ] as DocField[],
      },
      {
        heading: 'Example Queries',
        items: [
          // Momentum / breakout
          'RSI > 60 AND Change > 1',
          'RSI > 60 AND Volume > 2 AND Return1w > 3',
          'MomentumScore > 80 AND RSI > 55 AND RSI < 75',
          'MomentumScore > 70 AND Return1m > 10 AND Return3m > 20',
          'From52wHigh > -5 AND Volume > 2',
          'From52wHigh > -3 AND MomentumScore > 65',
          'Return1w > 5 AND Return1m > 10 AND Return3m > 20',
          'Change > 3 AND Volume > 3',
          'Change > 5 AND From52wHigh > -10',

          // Oversold / reversal
          'RSI < 35 AND Volume > 2',
          'RSI < 30 AND From52wLow < 10',
          'RSI < 40 AND MACDHist > 0',
          'RSI < 45 AND MACD > MACDSignal',

          // Sector filters
          'Sector = "Banks" AND Return1m > 5',
          'Sector = "Banks" AND RSI > 55 AND RSI < 70',
          'Sector = "Pharma" AND MomentumScore > 60 AND PE < 30',
          'Sector IN ("Banks", "IT") AND MomentumScore > 60',
          'Sector IN ("FMCG", "Consumer Durables") AND Return3m > 15',
          'Sector = "IT" AND From52wHigh > -10 AND Volume > 1.5',
          'Sector = "Auto" AND RSI > 55 AND Return1m > 5',

          // Volatility / squeeze setups
          'BBSqueeze AND ATR < 2',
          'BBSqueeze AND Volume > 1.5 AND MomentumScore > 50',
          'NOT BBSqueeze AND BBWidth > 10 AND Volume > 2',
          'HV20 < 20 AND MomentumScore > 60',
          'HV20 < 25 AND Sharpe60 > 1',
          'ATR < 2 AND RSI > 55 AND Volume > 1.5',

          // Multi-timeframe
          '1h:RSI > 65 AND W:RSI > 55',
          '1h:RSI > 60 AND 1d:RSI > 55 AND W:RSI > 50',
          'W:MACD > 0 AND 1d:RSI > 55',
          'W:RSI > 60 AND M:RSI > 55 AND Return3m > 15',
          '1h:BBSqueeze AND 1d:RSI > 50',

          // Value / fundamentals
          'PE < 15 AND Return1y > 20',
          'PE < 20 AND MomentumScore > 60',
          '(Return1m > 10 OR Return3m > 20) AND PE < 30',
          'PE > 0 AND PE < 12 AND Sector = "Banks"',
          'Sharpe126 > 1 AND PE < 25 AND Return1y > 15',

          // Quality / risk-adjusted
          'Sharpe60 > 1 AND HV20 < 25',
          'Sharpe60 > 1.5 AND MomentumScore > 65',
          'Sharpe126 > 1 AND Return1y > 20 AND PE < 30',
          'HV60 < 20 AND Return1y > 15 AND DataPoints > 200',

          // Universe hygiene
          'DataPoints > 200 AND MomentumScore > 70',
          'DataPoints > 240 AND RSI > 60 AND Volume > 1.5',

          // Complex / combined
          'RSI > 55 AND MACD > 0 AND Volume > 1.5 AND Return1m > 5',
          '(Sector = "Banks" OR Sector = "IT") AND RSI > 60 AND Volume > 2',
          'NOT BBSqueeze AND RSI > 55 AND Volume > 2 AND Return1m > 5',
          'BBSqueeze AND HV20 < 20 AND MomentumScore > 55',
          'From52wHigh > -5 AND Volume > 3 AND RSI > 50 AND RSI < 70',
          'Change > 2 AND Volume > 2 AND MomentumScore > 65 AND DataPoints > 200',
          '(Return1w > 3 AND Return1m > 8) AND RSI < 70 AND PE < 40',
          'Sector = "Pharma" AND From52wHigh > -15 AND Volume > 1.5 AND RSI > 50',
        ],
      },
      {
        heading: 'Tips',
        items: [
          'Press Tab to accept the highlighted autocomplete suggestion.',
          'Press Enter or click Run to execute the query.',
          'The active interval tab sets the default for un-prefixed indicator fields — switch tabs to rerun on a different timeframe.',
          'Results are sorted by clicking any column header. Sorting happens client-side on the returned page.',
          'Click any row to set that symbol as the active chart symbol.',
          'The screener cache refreshes every 5 minutes — click Refresh to force an update.',
        ],
      },
    ],
  },
  // ── DOCS ───────────────────────────────────────────────────────────────────
  {
    command: 'DOCS',
    title: 'Documentation',
    summary:
      'Meta-widget: shows the docs for the focused panel, otherwise the full index.',
    sections: [
      {
        heading: 'Auto-navigate',
        body: 'Focusing any non-DOCS panel auto-loads its doc (badged (auto)); focusing DOCS itself or an empty slot shows the index instead.',
      },
      {
        heading: 'Index & tour',
        items: [
          { name: '← INDEX', desc: 'Clears the manual selection and returns to the full widget list (each row shows an 80-char summary).' },
          { name: '▸ TOUR', desc: 'Replays the guided first-run tour from the current layout.' },
          { name: 'Popouts', desc: 'A popped-out DOCS shows the docs snapshot for the grid focus at load time; it does not track focus changes.' },
        ] as DocField[],
      },
    ],
  },
];

// ─── Lookup helper ────────────────────────────────────────────────────────────

export const WIDGET_DOCS: Record<string, WidgetDoc> = Object.fromEntries(
  DOCS_MAP.map((d) => [d.command, d]),
);

export const DOCS_INDEX: WidgetDoc[] = DOCS_MAP;

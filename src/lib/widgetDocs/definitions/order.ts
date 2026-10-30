import type { DocField, WidgetDoc } from '../types';

export const orderDoc: WidgetDoc = {
  command: 'ORDER',
  title: 'Order Entry & Book',
  summary:
    'Order entry deck, risk margins audit, and recent order book execution trail via OpenAlgo.',
  kind: 'panel',
  order: 40,
  // No screenshot: the deck only renders its full layout when a broker gateway is connected,
  // and a capture of the GATEWAY STANDBY state would misrepresent the widget.
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A unified execution deck featuring a direct order ticket, live risk margin audit cards, and a real-time order book. The deck enables fast order placement via hotkeys or buttons while tracking account buffer, peak VaR exposure, and execution status across supported exchanges.',
    },
    {
      heading: 'Controls',
      items: [
        'Quick instrument pills: click RELIANCE, HDFCBANK, TCS, or INFY to load that symbol and market tick into the ticket.',
        'Active symbol input: type an instrument symbol and press Enter or blur to set the symbol across the terminal.',
        'Exchange dropdown: select NSE, BSE, NFO, MCX, BFO, or CDS.',
        'Order type selector: toggle between MKT (market), LMT (limit), SL (stop-loss limit), and SL-M (stop-loss market).',
        'Product selector: toggle between MIS (intraday 5x), CNC (cash delivery 1x), and NRML (F&O normal margin 2.5x).',
        'Lot size buttons: click +1, +5, +10, +50, or MAX to increment or cap the trade quantity.',
        'Quantity stepper: click - or + to adjust trade quantity by single share increments.',
        'Limit / Trigger price inputs: specify exact execution or stop activation price thresholds.',
        'Execution triggers: click BUY [F1] or SELL [F2], or press keyboard shortcuts F1 / F2 to dispatch orders.',
        'Margin re-audit: click ⚡ RE-AUDIT MARGINS to trigger an immediate broker funds refresh.',
        'Order book filter chips: toggle between ALL, COMPLETE, PENDING, and REJECTED executions.',
        'Order book refresh: click ↻ to reload order book records from the gateway.',
        'Order book row click: click a symbol in the order book to reload that ticker into the order ticket.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'EXCHANGE',
          desc: 'Target execution market venue: NSE (National Stock Exchange), BSE (Bombay Stock Exchange), NFO (NSE Futures & Options), MCX (Multi Commodity Exchange), BFO (BSE Futures & Options), or CDS (Currency Derivatives Segment).',
        },
        {
          name: 'SYMBOL',
          desc: 'Trading ticker instrument symbol. Sourced from the active symbol or quick instrument selector.',
        },
        {
          name: 'ORDER TYPE',
          desc: 'Order pricing behavior. MKT executes immediately at prevailing market prices. LMT executes only at the specified limit price or better. SL triggers a limit order once the stop price is hit. SL-M triggers an unpriced market order when stop price is touched.',
        },
        {
          name: 'PRODUCT',
          desc: 'Trading product category. MIS represents intraday positions with up to 5x leverage requiring square-off before market close. CNC represents delivery trades with 1x equity cash backing. NRML represents overnight F&O carry-forward contracts with 2.5x leverage.',
        },
        {
          name: 'QUANTITY / LOT',
          desc: 'Order volume in shares or lot units. Pre-calculated lot buttons allow fast entry or sizing up to the maximum permitted position cap.',
        },
        {
          name: 'LIMIT PRICE',
          desc: 'Maximum price paid for a BUY limit order, or minimum price accepted for a SELL limit order. Inactive for market orders.',
        },
        {
          name: 'TRIGGER PRICE',
          desc: 'Stop-loss threshold price that arms and activates an SL or SL-M order on the exchange book when touched.',
        },
        {
          name: 'BID / ASK',
          desc: 'Best available buying bid and selling ask quotes from the live feed, displaying the current execution spread.',
        },
        {
          name: 'EST. MARGIN',
          desc: 'Estimated capital required to execute the trade based on quantity, price, and product leverage multiplier. Note that EST. MARGIN is an estimate, not a broker confirmation.',
        },
        {
          name: 'BUY / SELL',
          desc: 'Order transmission buttons bound to keyboard shortcuts [F1] for BUY and [F2] for SELL.',
        },
        {
          name: 'STATUS BANNER',
          desc: 'Inline visual indicator displaying execution state, including submission in-flight, broker confirmation, or gateway rejection messages.',
        },
        {
          name: 'AVAILABLE CASH',
          desc: 'Total liquid unencumbered cash balance cleared and available for opening new positions.',
        },
        {
          name: 'COLLATERAL MARGIN',
          desc: 'Margin value derived from pledged equity and debt holdings with exchange haircut reductions.',
        },
        {
          name: 'REALIZED M2M',
          desc: 'Booked profit or loss from trades closed and settled during the current session.',
        },
        {
          name: 'UNREALIZED M2M',
          desc: 'Floating live profit or loss across currently open positions and derivative legs.',
        },
        {
          name: 'UTILISATION BAR',
          desc: 'Percentage bar of total margin deployed. Values up to 50% indicate conservative leverage. Utilisation above 85% is the red zone approaching broker margin calls.',
        },
        {
          name: 'AVAILABLE BUFFER',
          desc: 'Remaining margin headroom before reaching total leverage or collateral limits.',
        },
        {
          name: 'PEAK VA-R EXPOSURE',
          desc: 'Maximum statistical Value-at-Risk margin obligation required across all active open legs.',
        },
        {
          name: 'MAX LEVERAGE CAP',
          desc: 'Maximum allowable leverage multiplier enforced by exchange and broker risk controls.',
        },
        {
          name: 'ORDER BOOK COLUMNS',
          desc: 'Audit trail fields: TIMESTAMP (order dispatch time), ORDER ID (broker execution reference), SYMBOL (instrument), SIDE (BUY/SELL), TYPE (MKT/LMT/SL), PROD (MIS/CNC/NRML), QTY (shares), PRICE (execution level), and STATUS (COMPLETE/PENDING/REJECTED).',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: "Funds and the order book come from the OpenAlgo gateway. When disconnected, GATEWAY STANDBY means no broker data is accessible. TODAY's order book is a filterable local view of modern session executions. An order submitted successfully through the UI can still be rejected by the broker or exchange risk management system.",
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour has 6 steps: 1) instrument setup, 2) order type with LIMIT selected, 3) product and leverage, 4) account margins and risk, 5) the execution buttons, and 6) the order book. It selects no product and never presses BUY or SELL. To replay the tour, open DOCS in another panel, keep this ORDER panel open, then click REPLAY TOUR.',
    },
  ],
};

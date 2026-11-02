import type { DocField, WidgetDoc } from '../types';

export const posDoc: WidgetDoc = {
  command: 'POS',
  title: 'Positions & P&L',
  summary:
    'Real-time positions deck for live broker holdings and simulated paper portfolios with MTM analytics, leg averaging, and order liquidation.',
  kind: 'panel',
  order: 50,
  screenshot: {
    src: '/docs/widgets/POS.png',
    alt: 'Positions & P&L widget screenshot',
    caption: 'Positions & P&L as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'The Positions deck displays active broker contracts via OpenAlgo alongside local paper trading portfolios. It provides real-time mark-to-market valuations, realized versus unrealized gain segmentation, position leg history, and instant square-off liquidation controls.',
    },
    {
      heading: 'Controls',
      items: [
        'LIVE / PAPER: Switch between live broker execution accounts and the local simulated paper portfolio.',
        'OPEN / CLOSED: Toggle between active holdings and liquidated trades in paper trading mode.',
        '+ NEW POSITION: Open the ticket modal to initiate a simulated paper position with custom entry pricing.',
        '↻ REFRESH: Force a manual reconciliation query against the OpenAlgo broker positions endpoint.',
        '+ ADD LEG: Average into an active paper holding by adding incremental lots at custom price points.',
        '✕ SQUARE OFF: Trigger exit order execution with confirmation to liquidate a contract.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'LIVE / PAPER',
          desc: 'Execution environment selector. LIVE queries OpenAlgo broker state; PAPER manages local simulated positions.',
        },
        {
          name: 'OPEN / CLOSED',
          desc: 'Paper book sub-tabs. OPEN lists positions with remaining lots; CLOSED archives fully liquidated contracts.',
        },
        {
          name: 'Total P&L',
          desc: 'Aggregate portfolio profit and loss combining closed realized returns and floating mark-to-market value.',
        },
        {
          name: 'Realized P&L',
          desc: 'Booked profit or loss locked in from squared-off positions or closed lots.',
        },
        {
          name: 'Unrealized P&L',
          desc: 'Floating profit or loss on active open lots based on live market price movements.',
        },
        {
          name: 'INSTRUMENT',
          desc: 'NSE trading symbol and trading exchange for the underlying contract.',
        },
        {
          name: 'PRODUCT',
          desc: 'Broker product code (such as MIS for intraday margin or CNC/NRML for delivery/carryforward).',
        },
        {
          name: 'NET QTY',
          desc: 'Signed open quantity. Positive values indicate long holdings (green); negative values indicate short exposure (rose).',
        },
        {
          name: 'AVG BUY',
          desc: 'Volume-weighted average purchase price across all executed legs in rupees.',
        },
        {
          name: 'LTP',
          desc: 'Last Traded Price updating in real time from the terminal market WebSocket feed.',
        },
        {
          name: 'CURRENT VALUE',
          desc: 'Current gross market value of the position, calculated as absolute quantity multiplied by LTP.',
        },
        {
          name: 'P&L',
          desc: 'Mark-to-market profit or loss amount calculated against the average acquisition price.',
        },
        {
          name: 'P&L %',
          desc: 'Percentage return on the position investment cost, showing relative trade performance.',
        },
        {
          name: 'Technical State Badge',
          desc: 'Real-time technical condition indicator (Overbought, Oversold, Bullish, Bearish). A bearish badge on a long holding signals a thesis conflict to review.',
        },
        {
          name: 'Leg Count',
          desc: 'Number of discrete entry orders averaged together to establish the current position basis.',
        },
        {
          name: '+ ADD LEG',
          desc: 'Interactive action to execute an additional entry tranche, updating position size and weighted average price.',
        },
        {
          name: '✕ SQUARE OFF',
          desc: 'Liquidation action to close open exposure. Opens a broker order confirmation modal in LIVE mode, or immediate close modal in PAPER mode.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'LTP updates stream continuously over the terminal market WebSocket feed. Live positions and fund balances are queried directly from OpenAlgo broker endpoints. Paper trades are stored persistently in the local backend database, where closed trades immediately transfer to the CLOSED tab with audited realized P&L. Paper order fills simulate instant execution at the user-specified entry price without slippage.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour walks through six surfaces and switches modes as it goes: LIVE / PAPER, the paper OPEN / CLOSED tabs, the portfolio KPIs, the position matrix, multi-leg averaging, and square-off. The mode and paper-tab steps are skipped when the gateway or the paper ledger is empty. It returns to the mode that was open before the tour started. To replay the tour, open DOCS in another panel, keep this POS panel open, then click REPLAY TOUR.',
    },
  ],
};

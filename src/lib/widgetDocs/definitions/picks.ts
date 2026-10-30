import type { DocField, WidgetDoc } from '../types';

export const picksDoc: WidgetDoc = {
  command: 'PICKS',
  title: 'AI Picks',
  summary: 'Automated AI trading picks with entry, stop loss, and target levels.',
  kind: 'panel',
  order: 160,
  screenshot: {
    src: '/docs/widgets/PICKS.png',
    alt: 'AI Picks widget screenshot',
    caption: 'AI Picks as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'AI-generated trade picks with entry, target, and stop levels. Cards categorize picks into new recommendations, active trades, historical closed setups, and abandoned ideas. Admin triggers run morning scans and evening evaluations with a live progress banner.',
    },
    {
      heading: 'Controls',
      items: [
        'Category tabs: switch between PICKS, ACTIVE, HISTORY, and ABANDONED lists.',
        'RUN HUNTER: trigger the morning pre-market candidate scan with live progress tracking.',
        'RUN VERIFIER: trigger the evening evaluation loop with live progress tracking.',
        'Symbol header button: click any symbol to set it as the active terminal ticker.',
        'DETAILS button: open the pick modal to view the full model thesis and technical notes.',
        'Admin actions: update trade status with Act on Pick, Close Position, or Abandon.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'SYMBOL',
          desc: 'The trading ticker for the recommended trade setup.',
        },
        {
          name: 'DIRECTION',
          desc: 'The trade bias, displayed as LONG or SHORT.',
        },
        {
          name: 'STATUS',
          desc: 'Lifecycle state: NEW, ACTED_ON, CLOSED, or ABANDONED. Status records operator actions, not model predictions.',
        },
        {
          name: 'ACTION BADGE',
          desc: 'Latest model recommendation or verdict tag, such as BUY, SELL, or HOLD.',
        },
        {
          name: 'OPEN P&L',
          desc: 'Unrealized profit or loss marked against live ticks. This value changes continuously while you read.',
        },
        {
          name: 'ENTRY',
          desc: 'Model recommended execution price level. Entry, Target, and Stop define the risk-reward before any action.',
        },
        {
          name: 'TARGET',
          desc: 'Profit target level calculated by the model.',
        },
        {
          name: 'STOP',
          desc: 'Risk stop-loss price level calculated by the model.',
        },
        {
          name: 'PROGRESS BANNER',
          desc: 'Live execution percentage and task status message for active Hunter or Verifier loops.',
        },
        {
          name: 'THESIS MODAL',
          desc: 'Detailed model reasoning, technical analysis, fundamental context, catalysts, and risk factors.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Picks are model output, so verify the thesis before acting. Open P&L calculates from real-time WebSocket ticks. Admin trigger actions require administrative privileges. Loading states show LOADING AI PICKS..., ERROR: {message}, or NO {tab} PICKS when empty.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour has four steps: 1) the PICKS tab, 2) the ACTIVE tab and the RUN HUNTER / RUN VERIFIER actions, 3) a pick card with its entry, target and stop, and 4) the DETAILS button that opens the full thesis. It returns to the tab that was open before the tour started. To replay the tour, open DOCS in another panel, keep this PICKS panel open, then click REPLAY TOUR.',
    },
  ],
};

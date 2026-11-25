import type { DocField, WidgetDoc } from '../types';

export const chartDoc: WidgetDoc = {
  command: 'CHART',
  title: 'Chart',
  summary:
    'Interactive candlestick chart for the active symbol. Displays OHLCV data with configurable timeframes and overlays.',
  kind: 'panel',
  order: 30,
  screenshot: {
    src: '/docs/widgets/CHART.png',
    alt: 'Chart widget screenshot',
    caption: 'Chart as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'Interactive OHLC candlestick and volume chart for the active symbol. Linked panels follow the global terminal symbol, while detached panels retain a dedicated override. The canvas displays historical price bars, volume histogram, technical indicator overlays, and Script Lab execution plots.',
    },
    {
      heading: 'Controls',
      items: [
        'Symbol search: type an exchange prefix (default NSE) and ticker to load autocompleted symbols.',
        'GO button: submit the input to load data and detach this panel from the global symbol sync.',
        'Interval selector: click any interval button (1m, 5m, 15m, 30m, 1h, D, W, M) to change candle compression.',
        'Fx menu: toggle built-in indicator overlays (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, SuperTrend, VWAP).',
        'Σ script menu: assign, configure, or inspect custom user and AI indicators from Script Lab.',
        'Refresh (↺): reload candle history and indicators from the backend ticker warehouse.',
        'Recenter (⊡): reset horizontal time scale and vertical price auto-scaling to fit all rendered bars.',
        'Panel link toggle: click [FREE] or [LINK] in the panel header to toggle between dedicated and shared symbol modes.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'LIVE',
          desc: 'Current traded price in rupees (INR) rendered in amber text. Sourced from the live market WebSocket feed during trading sessions.',
        },
        {
          name: 'EOD',
          desc: 'Previous official session closing price in rupees (INR) rendered in muted white. Serves as the baseline for net change calculations.',
        },
        {
          name: 'PERCENT CHANGE',
          desc: 'Percentage deviation between current LIVE price and reference EOD close. Positive values indicate intraday gains; negative values indicate intraday losses.',
        },
        {
          name: 'EOD AS OF',
          desc: 'Calendar date corresponding to the reference EOD closing price. Confirms whether the baseline reflects yesterday or an earlier settlement session.',
        },
        {
          name: 'STALE',
          desc: 'Red alert badge indicating outdated market quotes or a disconnected WebSocket stream. Prompts manual refresh (↺) or stream inspection.',
        },
        {
          name: 'CANDLESTICKS',
          desc: 'Price bars where green (#00E5A0) signifies Close >= Open and red (#F23645) signifies Close < Open. Long upper wicks near highs indicate supply rejection; long lower wicks indicate buyer absorption.',
        },
        {
          name: 'VOLUME',
          desc: 'Histogram bars at canvas base measuring total traded shares per candle period. Tall bars confirm breakout conviction; low volume warns of false moves.',
        },
        {
          name: 'FX OVERLAYS',
          desc: 'Mathematical indicators plotted over candles (e.g. EMA, Bollinger Bands, VWAP) or sub-panes (RSI, MACD) to confirm momentum and support or resistance.',
        },
        {
          name: 'Σ SCRIPTS',
          desc: 'Custom algorithmic indicators and strategies authored in Script Lab. Plots overlay lines, shapes, or signals directly on the chart.',
        },
        {
          name: 'GO / DETACH',
          desc: 'Action button that commits the typed symbol and detaches this panel ([FREE]), isolating it from external symbol changes in WATCH or TOP.',
        },
        {
          name: 'REFRESH (↺)',
          desc: 'Manual reload button. Fetches fresh intraday or EOD candle arrays directly from backend storage when network hiccups occur.',
        },
        {
          name: 'RECENTER (⊡)',
          desc: 'Auto-fit control. Realigns viewport zoom and vertical price scale to enclose all historical bars and active overlays.',
        },
        {
          name: 'INTERVALS',
          desc: 'Time compression buttons: 1m through 1h for intraday execution, D for swing setups, and W or M for multi-month trend structure.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Daily candles load from the backend ticker warehouse (/api/py/ticker/ohlcv), while intraday, weekly, and monthly candles load from /api/py/ticker/intraday. The latest candle represents the current in-progress period and can be incomplete. Live price overlays stream over the market WebSocket. A STALE badge indicates that the last refresh failed or the tick feed is older than expected.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour covers 5 key areas: 1) Symbol Search and Detach, 2) Timeframe Selection, 3) Technical Indicators, 4) Script Lab Overlays, and 5) Recenter and Status. To replay the tour, open DOCS in another panel, keep this CHART panel open, then click REPLAY TOUR.',
    },
  ],
};

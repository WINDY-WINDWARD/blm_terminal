import type { WidgetTourDefinition } from '../types';

export const chartTour: WidgetTourDefinition = {
  command: 'CHART',
  title: 'Chart',
  steps: [
    {
      id: 'chart-symbol-search',
      anchor: 'chart-symbol-search',
      title: 'Symbol Search and Detach',
      body: 'Search any exchange and symbol here. Submitting or clicking GO detaches this panel from the global ticker so it keeps its own symbol.',
    },
    {
      id: 'chart-timeframe-bar',
      anchor: 'chart-timeframe-bar',
      title: 'Timeframe Selection',
      body: 'Select intraday periods from 1m to 1h for fast execution, or switch to D, W, or M for swing analysis and macro trend structure.',
    },
    {
      id: 'chart-indicators-menu',
      anchor: 'chart-indicators-menu',
      title: 'Technical Indicators',
      body: 'Open the Fx menu to add technical overlays including RSI, MACD, Bollinger Bands, EMA, and intraday VWAP.',
    },
    {
      id: 'chart-scripts-menu',
      anchor: 'chart-scripts-menu',
      title: 'Script Lab Overlays',
      body: 'Attach user or AI-authored scripts using the Σ menu. Configure script input parameters directly behind the gear icon.',
    },
    {
      id: 'chart-recenter-control',
      anchor: 'chart-recenter-control',
      title: 'Recenter and Status',
      body: 'Compare LIVE tick price against EOD close, watch the STALE alert, and click ⊡ to refit chart scales. Replay this tour from DOCS with both panels open.',
    },
  ],
};

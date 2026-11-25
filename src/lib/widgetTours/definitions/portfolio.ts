import type { WidgetTourDefinition } from '../types';

export const portfolioTour: WidgetTourDefinition = {
  command: 'PORTFOLIO',
  title: 'Portfolio Optimizer',
  steps: [
    {
      id: 'portfolio-selection',
      anchor: 'portfolio-selection',
      title: 'Universe Selection',
      body: 'Load stocks from a watchlist or search by symbol. Check at least 3 symbols and review 1Y returns before optimising.',
    },
    {
      id: 'portfolio-parameters',
      anchor: 'portfolio-parameters',
      title: 'Optimisation Controls',
      body: 'Select historical period (1y, 2y, 3y) and objective (Max Sharpe, Min Volatility, Risk Parity). Click Optimize to run.',
    },
    {
      id: 'portfolio-metrics',
      anchor: 'portfolio-metrics',
      title: 'Portfolio Performance',
      body: 'Review expected annual return, volatility, and Sharpe ratio. Higher Sharpe ratios indicate superior return per risk unit.',
    },
    {
      id: 'portfolio-results',
      anchor: 'portfolio-results',
      title: 'Weights and Correlation',
      body: 'Inspect optimal weights, correlation matrix, and individual stock metrics. Replay this tour from DOCS with both panels open.',
    },
  ],
};


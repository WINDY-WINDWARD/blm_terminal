import type { DocField, WidgetDoc } from '../types';

export const portfolioDoc: WidgetDoc = {
  command: 'PORTFOLIO',
  title: 'Portfolio Optimizer',
  summary:
    'Modern Portfolio Theory mean-variance optimizer via PyPortfolioOpt. Select stocks, configure period and objective, and generate optimal asset allocations.',
  kind: 'panel',
  order: 170,
  screenshot: {
    src: '/docs/widgets/PORTFOLIO.png',
    alt: 'Portfolio Optimizer widget screenshot',
    caption: 'Portfolio Optimizer as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'Statistical portfolio optimization powered by PyPortfolioOpt. The widget provides mean-variance optimization and hierarchical risk parity across selected Indian equities. It outputs portfolio-level expected return, annual volatility, Sharpe ratio, optimal symbol weights, pairwise correlation matrix, and individual stock risk statistics.',
    },
    {
      heading: 'Controls',
      items: [
        'New Portfolio button: resets working symbols, selected checkboxes, and loads default state.',
        'Save button: opens modal to save active working symbols into a new or existing watchlist.',
        'Watchlist dropdown: populates the symbol pool from any stored terminal watchlist.',
        'Symbol search input: autocompletes NSE company names and tickers to add symbols manually.',
        'All / None quick toggles: selects or clears all checkboxes in the working stocks list.',
        'Stock checkboxes: toggles inclusion of each individual ticker in the optimization run.',
        'Remove symbol (×): removes a specific stock from the working selection pool.',
        'Period dropdown: sets the lookback window to 1 Year (1y), 2 Years (2y), or 3 Years (3y).',
        'Objective dropdown: selects optimization target among Max Sharpe, Min Volatility, or Risk Parity.',
        'Optimize button: dispatches the optimization request once at least 3 stocks are selected.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'EXPECTED RETURN',
          desc: 'Annualised expected portfolio return calculated from historical daily close prices over the selected period.',
        },
        {
          name: 'VOLATILITY',
          desc: 'Annualised standard deviation of portfolio returns representing total statistical price variance and risk.',
        },
        {
          name: 'SHARPE RATIO',
          desc: 'Expected excess return per unit of volatility relative to the risk-free rate. Higher Sharpe numbers indicate better risk-adjusted return efficiency.',
        },
        {
          name: 'PERIOD',
          desc: 'Historical lookback sample interval utilized by the PyPortfolioOpt engine (1y, 2y, or 3y).',
        },
        {
          name: 'OPTIMAL WEIGHTS',
          desc: 'Target percentage asset allocation for each stock displayed as proportional blue bars. Max Sharpe concentrates in highest risk-adjusted assets; Min Volatility spreads across defensive assets; Risk Parity balances risk contributions.',
        },
        {
          name: 'CORRELATION MATRIX',
          desc: 'Pairwise Pearson correlation coefficients between -1.00 and +1.00. Values near +1.00 indicate strong positive co-movement offering minimal diversification. Values near -1.00 indicate inverse movement providing strong hedging.',
        },
        {
          name: 'PER-SYMBOL STATISTICS',
          desc: 'Asset breakdown table listing annualised return (Ann Return), annualised volatility (Ann Vol), and individual Sharpe ratio for each included asset.',
        },
        {
          name: 'STATES AND NOTICES',
          desc: 'Interactive feedback states: "No symbols — load a watchlist or search to add", "Select at least 3 stocks", "Select stocks and click Optimize", "Optimizing…", and notices identifying failed symbols missing price history.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'Optimization requires a minimum of 3 selected stocks. Historical prices derive from daily warehouse data backfilled from NSE. The optimizer assumes a fixed risk-free rate benchmark. Past historical returns and volatility do not guarantee future performance.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour covers 4 key areas: 1) Universe Selection, 2) Optimisation Controls, 3) Portfolio Performance, and 4) Weights and Correlation. To replay the tour, open DOCS in another panel, keep this PORTFOLIO panel open, then click REPLAY TOUR.',
    },
  ],
};

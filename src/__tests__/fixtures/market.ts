export const gainers = [
  { symbol: 'RELIANCE', lastPrice: 2450.3, change: 10.3, pChange: 0.42, previousClose: 2440 },
  { symbol: 'TCS', lastPrice: 3850.5, change: 25.2, pChange: 0.66, previousClose: 3825.3 },
  { symbol: 'HDFCBANK', lastPrice: 1680.2, change: 12.1, pChange: 0.73, previousClose: 1668.1 },
];

export const losers = [
  { symbol: 'INFY', lastPrice: 1420.3, change: -8.5, pChange: -0.59, previousClose: 1428.8 },
  { symbol: 'WIPRO', lastPrice: 520.1, change: -3.2, pChange: -0.61, previousClose: 523.3 },
  { symbol: 'TECHM', lastPrice: 1180.5, change: -7.8, pChange: -0.66, previousClose: 1188.3 },
];

export const symbolData = (symbol: string) => ({
  equityResponse: [
    {
      orderBook: { lastPrice: 2450.3 },
      tradeInfo: { lastPrice: 2450.3 },
      metaData: { pChange: 0.42 },
      priceInfo: { yearHigh: 2600.0, yearLow: 2200.0 },
    },
  ],
});

export const changeRanges = (symbol: string) => ({
  oneDayPercent: 0.42,
  oneWeekPercent: 2.15,
  oneMonthPercent: 5.3,
  threeMonthPercent: 12.5,
  sixMonthPercent: 18.2,
  oneYearPercent: 25.0,
  twoYearPercent: null,
  threeYearPercent: null,
  fiveYearPercent: null,
});

export const historicalBars = [
  { timestamp: 1713801600, open: 2440, high: 2460, low: 2430, close: 2450, volume: 1000000 },
  { timestamp: 1713715200, open: 2420, high: 2445, low: 2410, close: 2440, volume: 950000 },
  { timestamp: 1713628800, open: 2400, high: 2430, low: 2395, close: 2420, volume: 920000 },
  { timestamp: 1713542400, open: 2380, high: 2410, low: 2375, close: 2400, volume: 880000 },
  { timestamp: 1713456000, open: 2360, high: 2390, low: 2355, close: 2380, volume: 850000 },
];
import type { FundsData, OrderData, PositionData, OrderBookStatistics } from '@/lib/openalgo';

export const fundsData: FundsData = {
  availablecash: '500000',
  collateral: '0',
  m2mrealized: '0',
  m2munrealized: '15000',
  utiliseddebits: '250000',
};

export const orderBook = {
  orders: [
    {
      orderid: 'ORD001',
      symbol: 'RELIANCE',
      exchange: 'NSE',
      action: 'BUY',
      quantity: 10,
      price: 2450,
      pricetype: 'LIMIT',
      product: 'MIS',
      order_status: 'complete',
      timestamp: '2025-04-24T10:00:00Z',
    },
    {
      orderid: 'ORD002',
      symbol: 'TCS',
      exchange: 'NSE',
      action: 'SELL',
      quantity: 5,
      price: 3850,
      pricetype: 'MARKET',
      product: 'MIS',
      order_status: 'open',
      timestamp: '2025-04-24T11:00:00Z',
    },
  ] as OrderData[],
  statistics: {
    total_buy_orders: 10,
    total_sell_orders: 5,
    total_open_orders: 3,
    total_completed_orders: 12,
    total_rejected_orders: 0,
  } as OrderBookStatistics,
};

export const positionBook = [
  {
    symbol: 'RELIANCE',
    exchange: 'NSE',
    product: 'MIS',
    quantity: '10',
    average_price: '2450',
    ltp: '2460',
    pnl: '100',
  },
  {
    symbol: 'TCS',
    exchange: 'NSE',
    product: 'CNC',
    quantity: '5',
    average_price: '3800',
    ltp: '3850',
    pnl: '250',
  },
] as PositionData[];
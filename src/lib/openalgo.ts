// OpenAlgo REST API client
// All endpoints use POST with { apikey, ...params } in the request body.
// The apikey is NOT sent as a Bearer header — this matches the OpenAlgo v1 API spec.

// ─── Response Types ───────────────────────────────────────────────────────────

export interface QuoteData {
  ltp: number;
  open: number;
  high: number;
  low: number;
  close?: number;
  prev_close: number;
  volume: number;
  bid: number;
  ask: number;
  oi?: number;
}

export interface PositionData {
  symbol: string;
  exchange: string;
  product: string;
  quantity: number | string;
  average_price: string;
  ltp?: string;
  pnl?: string;
}

export interface OrderData {
  orderid: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  price: number;
  pricetype: string;
  product: string;
  order_status: string;
  timestamp: string;
  trigger_price?: number;
}

export interface OrderBookStatistics {
  total_buy_orders: number;
  total_sell_orders: number;
  total_open_orders: number;
  total_completed_orders: number;
  total_rejected_orders: number;
}

export interface TradeData {
  orderid: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  average_price: number;
  product: string;
  timestamp: string;
  trade_value: number;
}

export interface HistoricalBar {
  timestamp: number; // Unix epoch seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  oi?: number;
}

export interface FundsData {
  availablecash: string;
  collateral: string;
  m2mrealized: string;
  m2munrealized: string;
  utiliseddebits: string;
}

export interface PlaceOrderParams {
  symbol: string;
  exchange: string;
  action: 'BUY' | 'SELL';
  quantity: string;
  price: string;
  order_type: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
  product: 'MIS' | 'CNC' | 'NRML';
  trigger_price?: string;
  strategy?: string;
}

export interface PlaceOrderResponse {
  status: string;
  orderid: string;
  message: string;
}

// ─── API Client ───────────────────────────────────────────────────────────────

export class OpenAlgoClient {
  private static get baseURL(): string {
    // Call Next.js proxy routes instead of OpenAlgo directly
    return '/api/openalgo';
  }

  private static async request<T>(endpoint: string, body: Record<string, unknown> = {}): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;

    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), // No apikey needed - it's added server-side
    });

    if (!response.ok) {
      const errorData = (await response.json()) as { error?: string };
      throw new Error(errorData.error || `API Error [${response.status}]: ${response.statusText}`);
    }

    const json = (await response.json()) as { status: string; data?: unknown; message?: string };

    if (json.status !== 'success') {
      throw new Error(`API Error: ${json.message ?? 'Unknown error'}`);
    }

    return json as T;
  }

  // ─── Order Management ───────────────────────────────────────────────────────

  static async placeOrder(params: PlaceOrderParams): Promise<PlaceOrderResponse> {
    return this.request<PlaceOrderResponse>('/placeorder', {
      symbol: params.symbol,
      exchange: params.exchange,
      action: params.action,
      quantity: params.quantity,
      price: params.price,
      order_type: params.order_type,
      product: params.product,
      ...(params.trigger_price ? { trigger_price: params.trigger_price } : {}),
      ...(params.strategy ? { strategy: params.strategy } : {}),
    });
  }

  // ─── Account Data ───────────────────────────────────────────────────────────

  static async getPositionBook(): Promise<{ status: string; data: PositionData[] }> {
    return this.request('/positions');
  }

  static async getOrderBook(): Promise<{ status: string; data: { orders: OrderData[]; statistics: OrderBookStatistics } }> {
    return this.request('/orders');
  }

  static async getTradeBook(): Promise<{ status: string; data: TradeData[] }> {
    return this.request('/trades');
  }

  static async getFunds(): Promise<{ status: string; data: FundsData }> {
    return this.request('/funds');
  }

  // ─── Market Data ────────────────────────────────────────────────────────────

  static async getQuote(symbol: string, exchange: string): Promise<{ status: string; data: QuoteData }> {
    return this.request('/quotes', { symbol, exchange });
  }

  static async getHistory(
    symbol: string,
    exchange: string,
    interval: string,
    start_date: string,
    end_date: string
  ): Promise<{ status: string; data: HistoricalBar[] }> {
    return this.request('/history', { symbol, exchange, interval, start_date, end_date });
  }
}

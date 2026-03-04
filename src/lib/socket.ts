// OpenAlgo WebSocket service
// Uses native WebSocket (not socket.io-client) against ws://host:8765
// Protocol: authenticate on connect → subscribe per symbol/mode → receive market_data events
//
// Data Modes:
//   1 = LTP only       { ltp, timestamp }
//   2 = Full quote     { ltp, open, high, low, close, volume, change, change_percent, ... }
//   3 = Market depth   { bids, asks }

export type WsMode = 1 | 2 | 3;

export interface TickData {
  symbol: string;
  exchange: string;
  ltp: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  change?: number;
  change_percent?: number;
  timestamp?: string;
}

type TickHandler = (data: TickData) => void;
type ConnectionHandler = (connected: boolean) => void;

class WebSocketService {
  private static instance: WebSocketService;
  private socket: WebSocket | null = null;
  private authenticated = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  // Event listeners
  private tickListeners: Set<TickHandler> = new Set();
  private connectionListeners: Set<ConnectionHandler> = new Set();

  // Subscriptions to re-apply after reconnect: key = "SYMBOL.EXCHANGE", value = mode
  private subscriptions: Map<string, WsMode> = new Map();

  private get wsURL(): string {
    return process.env.NEXT_PUBLIC_OPENALGO_WS_URL || 'ws://localhost:8765';
  }

  private get apiKey(): string {
    return process.env.NEXT_PUBLIC_OPENALGO_API_KEY || '';
  }

  private constructor() {}

  public static getInstance(): WebSocketService {
    if (!WebSocketService.instance) {
      WebSocketService.instance = new WebSocketService();
    }
    return WebSocketService.instance;
  }

  // ─── Connection ─────────────────────────────────────────────────────────────

  public connect(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return;

    try {
      this.socket = new WebSocket(this.wsURL);

      this.socket.onopen = () => {
        this.reconnectAttempts = 0;
        // Authenticate immediately
        this.send({ action: 'authenticate', api_key: this.apiKey });
      };

      this.socket.onmessage = (event: MessageEvent) => {
        this.handleMessage(event);
      };

      this.socket.onerror = (event) => {
        console.error('[wsService] WebSocket error:', event);
      };

      this.socket.onclose = () => {
        this.authenticated = false;
        this.notifyConnection(false);
        this.scheduleReconnect();
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[wsService] Failed to create WebSocket:', msg);
    }
  }

  public disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.subscriptions.clear();
    if (this.socket) {
      this.socket.onclose = null; // prevent reconnect on intentional close
      this.socket.close();
      this.socket = null;
    }
    this.authenticated = false;
    this.notifyConnection(false);
  }

  // ─── Subscriptions ──────────────────────────────────────────────────────────

  public subscribe(symbol: string, exchange: string, mode: WsMode = 2): void {
    const key = `${symbol}.${exchange}`;
    this.subscriptions.set(key, mode);
    if (this.authenticated) {
      this.send({ action: 'subscribe', symbol, exchange, mode });
    }
  }

  public unsubscribe(symbol: string, exchange: string, mode: WsMode = 2): void {
    const key = `${symbol}.${exchange}`;
    this.subscriptions.delete(key);
    if (this.authenticated) {
      this.send({ action: 'unsubscribe', symbol, exchange, mode });
    }
  }

  // ─── Event Listeners ────────────────────────────────────────────────────────

  public onTick(handler: TickHandler): () => void {
    this.tickListeners.add(handler);
    return () => this.tickListeners.delete(handler);
  }

  public onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionListeners.add(handler);
    return () => this.connectionListeners.delete(handler);
  }

  public get isConnected(): boolean {
    return this.authenticated;
  }

  // ─── Internal ───────────────────────────────────────────────────────────────

  private send(payload: Record<string, unknown>): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }

  private handleMessage(event: MessageEvent): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(event.data as string) as Record<string, unknown>;
    } catch {
      return;
    }

    // Authentication response
    if (msg.type === 'auth' || (msg.action === 'authenticate' && msg.status === 'success')) {
      this.authenticated = true;
      this.notifyConnection(true);
      this.resubscribeAll();
      return;
    }

    // Authentication confirmation (some versions send status:success directly)
    if (msg.status === 'success' && !this.authenticated) {
      this.authenticated = true;
      this.notifyConnection(true);
      this.resubscribeAll();
      return;
    }

    // Market data tick
    if (msg.type === 'market_data') {
      const data = msg.data as TickData | undefined;
      if (data) {
        this.tickListeners.forEach((handler) => handler(data));
      }
    }
  }

  private resubscribeAll(): void {
    for (const [key, mode] of this.subscriptions.entries()) {
      const [symbol, exchange] = key.split('.');
      if (symbol && exchange) {
        this.send({ action: 'subscribe', symbol, exchange, mode });
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn('[wsService] Max reconnect attempts reached.');
      return;
    }
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    this.reconnectAttempts++;
    console.log(`[wsService] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  private notifyConnection(connected: boolean): void {
    this.connectionListeners.forEach((handler) => handler(connected));
  }
}

export const wsService = WebSocketService.getInstance();

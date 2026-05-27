/**
 * MarketWebSocketService — singleton client for /ws/market on the Python backend.
 *
 * Replaces per-symbol HTTP polling for change-ranges and symbol-data with a
 * single persistent WebSocket connection. Multiple React components can
 * register for the same symbol; the service deduplicates and batches requests.
 *
 * Batching strategy (debounced):
 *   Components call requestChangeRanges / requestSymbolData with their symbols.
 *   The service queues those symbols and flushes one WS message after a 50 ms
 *   microtask delay. Rows that mount nearly simultaneously are automatically
 *   grouped into a single round-trip.
 */

export interface ChangeRanges {
  oneDayPercent: number | null;
  oneWeekPercent: number | null;
  oneMonthPercent: number | null;
  threeMonthPercent: number | null;
  sixMonthPercent: number | null;
  oneYearPercent: number | null;
  twoYearPercent: number | null;
  threeYearPercent: number | null;
  fiveYearPercent: number | null;
}

export interface SymbolDataExtract {
  ltp: number;
  pChange: number;
  yearHigh?: number;
  yearLow?: number;
}

type ChangeRangesHandler = (symbol: string, data: ChangeRanges | null) => void;
type SymbolDataHandler = (symbol: string, data: SymbolDataExtract | null) => void;
type ConnectionHandler = (connected: boolean) => void;

// Raw NSE shape returned from the backend for symbol-data
interface RawNseSymbolData {
  equityResponse?: Array<{
    orderBook?: { lastPrice?: number };
    tradeInfo?: { lastPrice?: number };
    metaData?: { pChange?: number };
    priceInfo?: { yearHigh?: number; yearLow?: number };
  }>;
}

function extractSymbolData(raw: RawNseSymbolData | null): SymbolDataExtract | null {
  if (!raw) return null;
  const equity = raw.equityResponse?.[0];
  if (!equity) return null;
  const ltp = equity.orderBook?.lastPrice ?? equity.tradeInfo?.lastPrice ?? 0;
  if (!ltp) return null;
  return {
    ltp,
    pChange: equity.metaData?.pChange ?? 0,
    yearHigh: equity.priceInfo?.yearHigh,
    yearLow: equity.priceInfo?.yearLow,
  };
}

class MarketWebSocketService {
  private static instance: MarketWebSocketService;

  private socket: WebSocket | null = null;
  private wsUrl: string | null = null;
  private wsUrlFetchInitiated = false;
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isAuthenticated = false; // connected & ready

  // ── Listeners ──────────────────────────────────────────────────────────────
  private changeRangesListeners: Set<ChangeRangesHandler> = new Set();
  private symbolDataListeners: Set<SymbolDataHandler> = new Set();
  private connectionListeners: Set<ConnectionHandler> = new Set();

  // ── Debounce queues ────────────────────────────────────────────────────────
  private pendingChangeRanges: Set<string> = new Set();
  private pendingSymbolData: Set<string> = new Set();
  private changeRangesDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  private symbolDataDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly DEBOUNCE_MS = 50;

  // ── In-memory cache (mirrors backend TTLs) ─────────────────────────────────
  private changeRangesCache: Map<string, { data: ChangeRanges; expiresAt: number }> = new Map();
  private symbolDataCache: Map<string, { data: SymbolDataExtract; expiresAt: number }> = new Map();
  private readonly CHANGE_RANGES_TTL_MS = 300_000; // 5 min
  private readonly SYMBOL_DATA_TTL_MS = 60_000;    // 1 min

  private constructor() {}

  public static getInstance(): MarketWebSocketService {
    if (!MarketWebSocketService.instance) {
      MarketWebSocketService.instance = new MarketWebSocketService();
    }
    return MarketWebSocketService.instance;
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Request change-ranges data for a set of symbols.
   * Calls are debounced — multiple calls within 50 ms are merged into one WS message.
   * Symbols already cached (within TTL) are served from cache immediately.
   */
  public requestChangeRanges(symbols: string[]): void {
    this.ensureConnected();

    const now = Date.now();
    const needsFetch: string[] = [];

    for (const sym of symbols) {
      const cached = this.changeRangesCache.get(sym);
      if (cached && cached.expiresAt > now) {
        // Serve from cache immediately
        this.notifyChangeRanges(sym, cached.data);
      } else {
        needsFetch.push(sym);
      }
    }

    if (needsFetch.length === 0) return;

    for (const sym of needsFetch) {
      this.pendingChangeRanges.add(sym);
    }

    if (this.changeRangesDebounceTimer !== null) {
      clearTimeout(this.changeRangesDebounceTimer);
    }
    this.changeRangesDebounceTimer = setTimeout(() => {
      this.flushChangeRanges();
    }, this.DEBOUNCE_MS);
  }

  /**
   * Request symbol-data for a set of symbols.
   * Calls are debounced — multiple calls within 50 ms are merged into one WS message.
   * Symbols already cached (within TTL) are served from cache immediately.
   */
  public requestSymbolData(symbols: string[]): void {
    this.ensureConnected();

    const now = Date.now();
    const needsFetch: string[] = [];

    for (const sym of symbols) {
      const cached = this.symbolDataCache.get(sym);
      if (cached && cached.expiresAt > now) {
        this.notifySymbolData(sym, cached.data);
      } else {
        needsFetch.push(sym);
      }
    }

    if (needsFetch.length === 0) return;

    for (const sym of needsFetch) {
      this.pendingSymbolData.add(sym);
    }

    if (this.symbolDataDebounceTimer !== null) {
      clearTimeout(this.symbolDataDebounceTimer);
    }
    this.symbolDataDebounceTimer = setTimeout(() => {
      this.flushSymbolData();
    }, this.DEBOUNCE_MS);
  }

  /** Subscribe to change-ranges updates for any symbol. */
  public onChangeRanges(handler: ChangeRangesHandler): () => void {
    this.changeRangesListeners.add(handler);
    return () => this.changeRangesListeners.delete(handler);
  }

  /** Subscribe to symbol-data updates for any symbol. */
  public onSymbolData(handler: SymbolDataHandler): () => void {
    this.symbolDataListeners.add(handler);
    return () => this.symbolDataListeners.delete(handler);
  }

  /** Subscribe to connection state changes. */
  public onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionListeners.add(handler);
    return () => this.connectionListeners.delete(handler);
  }

  public get isConnected(): boolean {
    return this.isAuthenticated;
  }

  // ── Connection management ──────────────────────────────────────────────────

  private ensureConnected(): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return;
    if (this.socket && this.socket.readyState === WebSocket.CONNECTING) return;
    this.connect();
  }

  private connect(): void {
    if (!this.wsUrl && !this.wsUrlFetchInitiated) {
      this.wsUrlFetchInitiated = true;
      this.fetchWsUrl().then((url) => {
        if (url) {
          this.wsUrl = url;
          this.openSocket();
        } else {
          console.warn('[marketWs] Failed to fetch WS URL, retrying in 2s');
          setTimeout(() => {
            this.wsUrlFetchInitiated = false;
            this.connect();
          }, 2000);
        }
      });
      return;
    }

    if (!this.wsUrl) return; // still waiting for URL

    this.openSocket();
  }

  private async fetchWsUrl(): Promise<string | null> {
    try {
      const res = await fetch('/api/py/ws-config');
      if (!res.ok) return null;
      const data = (await res.json()) as { marketWsUrl?: string };
      return data.marketWsUrl ?? null;
    } catch {
      return null;
    }
  }

  private openSocket(): void {
    if (!this.wsUrl) return;
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    console.log('[marketWs] Connecting to', this.wsUrl);

    try {
      this.socket = new WebSocket(this.wsUrl);

      this.socket.onopen = () => {
        console.log('[marketWs] Connected');
        this.reconnectAttempts = 0;
      };

      this.socket.onmessage = (event: MessageEvent) => {
        this.handleMessage(event);
      };

      this.socket.onerror = (event) => {
        console.error('[marketWs] WebSocket error', event);
      };

      this.socket.onclose = () => {
        console.log('[marketWs] Disconnected');
        this.isAuthenticated = false;
        this.notifyConnection(false);
        this.scheduleReconnect();
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      console.error('[marketWs] Failed to create WebSocket:', msg);
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn('[marketWs] Max reconnect attempts reached');
      return;
    }
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30_000);
    this.reconnectAttempts++;
    console.log(`[marketWs] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay);
  }

  // ── Message handling ───────────────────────────────────────────────────────

  private handleMessage(event: MessageEvent): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(event.data as string) as Record<string, unknown>;
    } catch {
      return;
    }

    const type = msg.type as string | undefined;

    if (type === 'connected') {
      this.isAuthenticated = true;
      this.notifyConnection(true);
      // Re-flush any pending requests that were queued before connection was ready
      if (this.pendingChangeRanges.size > 0) this.flushChangeRanges();
      if (this.pendingSymbolData.size > 0) this.flushSymbolData();
      return;
    }

    if (type === 'heartbeat') return;
    if (type === 'pong') return;

    if (type === 'change_ranges') {
      const data = msg.data as Record<string, ChangeRanges | null> | undefined;
      if (data) {
        for (const [sym, ranges] of Object.entries(data)) {
          if (ranges) {
            this.changeRangesCache.set(sym, {
              data: ranges,
              expiresAt: Date.now() + this.CHANGE_RANGES_TTL_MS,
            });
          }
          this.notifyChangeRanges(sym, ranges ?? null);
        }
      }
      return;
    }

    if (type === 'symbol_data') {
      const data = msg.data as Record<string, RawNseSymbolData | null> | undefined;
      if (data) {
        for (const [sym, raw] of Object.entries(data)) {
          const extracted = extractSymbolData(raw);
          if (extracted) {
            this.symbolDataCache.set(sym, {
              data: extracted,
              expiresAt: Date.now() + this.SYMBOL_DATA_TTL_MS,
            });
          }
          this.notifySymbolData(sym, extracted);
        }
      }
      return;
    }

    if (type === 'error') {
      console.error('[marketWs] Server error:', msg.message);
    }
  }

  // ── Flush helpers ──────────────────────────────────────────────────────────

  private flushChangeRanges(): void {
    this.changeRangesDebounceTimer = null;
    if (this.pendingChangeRanges.size === 0) return;

    const symbols = Array.from(this.pendingChangeRanges);
    this.pendingChangeRanges.clear();

    if (!this.isAuthenticated || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
      // Re-queue for after reconnect
      for (const s of symbols) this.pendingChangeRanges.add(s);
      return;
    }

    this.send({ action: 'get_change_ranges', symbols });
  }

  private flushSymbolData(): void {
    this.symbolDataDebounceTimer = null;
    if (this.pendingSymbolData.size === 0) return;

    const symbols = Array.from(this.pendingSymbolData);
    this.pendingSymbolData.clear();

    if (!this.isAuthenticated || !this.socket || this.socket.readyState !== WebSocket.OPEN) {
      for (const s of symbols) this.pendingSymbolData.add(s);
      return;
    }

    this.send({ action: 'get_symbol_data', symbols });
  }

  private send(payload: Record<string, unknown>): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(payload));
    }
  }

  // ── Notify helpers ─────────────────────────────────────────────────────────

  private notifyChangeRanges(symbol: string, data: ChangeRanges | null): void {
    this.changeRangesListeners.forEach((h) => h(symbol, data));
  }

  private notifySymbolData(symbol: string, data: SymbolDataExtract | null): void {
    this.symbolDataListeners.forEach((h) => h(symbol, data));
  }

  private notifyConnection(connected: boolean): void {
    this.connectionListeners.forEach((h) => h(connected));
  }
}

export const marketWsService = MarketWebSocketService.getInstance();

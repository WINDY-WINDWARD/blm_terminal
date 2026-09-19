/**
 * MarketWsService — singleton WebSocket client for change-ranges and
 * symbol-data. Replaces the previous HTTP fetch path
 * (`src/lib/nseFetch.ts`) with a persistent WS connection to the
 * backend `/ws/market` endpoint.
 *
 * Why WS:
 *   The previous HTTP path batched N symbols into one Next.js proxy
 *   request, then `Promise.all`'d N throttled NSE calls server-side,
 *   then returned ONE response. The browser waited for the slowest
 *   symbol. The WS path streams per-symbol partials as each NSE call
 *   completes — so a 20-symbol watchlist can paint its first row in
 *   ~200ms (cache hit) and fill in the rest as NSE responds.
 *
 * URL resolution (mirrors `src/lib/newsSocket.ts:fetchWsUrl`):
 *   - `NEXT_PUBLIC_MARKET_WS_URL` env var (dev override, optional)
 *   - Same-origin WS derived from `window.location` (production default)
 *
 * The browser is already at the public origin (e.g. https://blm.example.com),
 * so deriving the WS base from `window.location` is the correct cross-
 * environment pattern. In production the dev-server's `server.js` (or the
 * production reverse proxy) already proxies `/ws/market` to the Python
 * backend, so the browser connecting to the same origin it loaded the
 * page from works. We deliberately do NOT round-trip through
 * `/api/py/ws-config`: that route resolves to PYTHON_BACKEND_URL on the
 * server, which in production is often unreachable from the browser
 * (different host, no public DNS, or no path through the reverse proxy
 * for the WS upgrade).
 *
 * Protocol (server side: `backend/app/routers/market_ws.py`):
 *   Client → Server:
 *     { action: "get_change_ranges", request_id: N, symbols: [...] }
 *     { action: "get_symbol_data",   request_id: N, symbols: [...] }
 *     { action: "ping" }
 *
 *   Server → Client:
 *     { type: "connected" }
 *     { type: "change_ranges_started",  request_id, symbols }
 *     { type: "change_ranges_partial",  request_id, symbol, data | null, error? }
 *     { type: "change_ranges_complete", request_id }
 *     (same three for symbol_data)
 *     { type: "heartbeat" }
 *     { type: "pong" }
 *     { type: "error", request_id?, message }
 *
 * Lifecycle:
 *   - `connect()` is idempotent and safe to call from any number of
 *     components. It opens the socket if not already open/connecting.
 *   - On close, the service schedules a reconnect with exponential
 *     backoff (1s → 2s → 4s … capped at 30s, max 10 attempts),
 *     mirroring `src/lib/newsSocket.ts`.
 *   - On close, all in-flight requests are rejected with `null` data
 *     for each requested symbol — the same shape the HTTP error path
 *     already produces, so consumers (WatchWidget) don't need
 *     special-case handling.
 *   - On reconnect, any requests that were pending at disconnect time
 *     are re-sent on the new socket.
 *
 * Client TTL cache:
 *   Change-ranges cached for 5 min, symbol-data for 1 min — same as
 *   the previous HTTP service. Repeat calls within the TTL are served
 *   from cache without touching the WS.
 */

import type { ChangeRanges, SymbolDataExtract } from './nseTypes';
import { withTicket } from './wsTicket';

type ChangeRangesHandler = (symbol: string, data: ChangeRanges | null) => void;
type SymbolDataHandler = (symbol: string, data: SymbolDataExtract | null) => void;
type ConnectionHandler = (connected: boolean) => void;

interface PendingRequest {
  action: 'get_change_ranges' | 'get_symbol_data';
  symbols: string[];
  // The set of symbols whose partials have arrived. When this equals
  // `symbols.length` we know we could rely on a `*_complete` message,
  // but the explicit `*_complete` is the source of truth.
  seenSymbols: Set<string>;
}

const KEEP_ALIVE_MS = 25_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_MAX_ATTEMPTS = 10;
const DEBOUNCE_MS = 50;
const CHANGE_RANGES_TTL_MS = 5 * 60 * 1000;
const SYMBOL_DATA_TTL_MS = 60 * 1000;

class MarketWsService {
  private static instance: MarketWsService;

  // ── Connection state ────────────────────────────────────────────────────
  private socket: WebSocket | null = null;
  private connected = false;
  private connectInitiated = false;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private keepAliveTimer: ReturnType<typeof setInterval> | null = null;
  private wsUrl: string | null = null;
  private wsUrlFetchInitiated = false;
  private wsUrlFailedOnce = false;

  // ── Request correlation ─────────────────────────────────────────────────
  private nextRequestId = 1;
  private pendingRequests = new Map<number, PendingRequest>();

  // ── Debounce queues ─────────────────────────────────────────────────────
  private pendingChangeRanges = new Set<string>();
  private pendingSymbolData = new Set<string>();
  private changeRangesDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  private symbolDataDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  // ── Client TTL cache ────────────────────────────────────────────────────
  private changeRangesCache = new Map<string, { data: ChangeRanges; expiresAt: number }>();
  private symbolDataCache = new Map<string, { data: SymbolDataExtract; expiresAt: number }>();

  // ── Listeners ───────────────────────────────────────────────────────────
  private changeRangesListeners = new Set<ChangeRangesHandler>();
  private symbolDataListeners = new Set<SymbolDataHandler>();
  private connectionListeners = new Set<ConnectionHandler>();

  private constructor() {}

  public static getInstance(): MarketWsService {
    if (!MarketWsService.instance) {
      MarketWsService.instance = new MarketWsService();
    }
    return MarketWsService.instance;
  }

  // ── Public API ──────────────────────────────────────────────────────────

  /**
   * Open the WebSocket if it isn't already open/connecting. Idempotent
   * and safe to call from many components. The terminal calls this
   * eagerly on mount so the first watchlist render has zero
   * handshake latency.
   */
  public connect(): void {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    if (this.connectInitiated) return;

    this.connectInitiated = true;

    if (!this.wsUrl && !this.wsUrlFetchInitiated) {
      this.wsUrlFetchInitiated = true;
      this.fetchWsUrl().then((url) => {
        if (url) {
          this.wsUrl = url;
          this.openSocket();
        } else {
          console.warn('[marketWs] Failed to resolve WS URL, retrying in 2s');
          this.wsUrlFailedOnce = true;
          this.wsUrlFetchInitiated = false;
          this.connectInitiated = false;
          setTimeout(() => this.connect(), 2000);
        }
      });
      return;
    }

    if (!this.wsUrl) return; // still waiting for URL
    this.openSocket();
  }

  public disconnect(): void {
    this.clearReconnect();
    this.stopKeepAlive();
    if (this.socket) {
      try {
        this.socket.onclose = null;
        this.socket.onerror = null;
        this.socket.onmessage = null;
        this.socket.onopen = null;
        this.socket.close();
      } catch {
        // ignore
      }
      this.socket = null;
    }
    this.connected = false;
    this.connectInitiated = false;
    this.notifyConnection(false);
  }

  /**
   * Request change-ranges for a set of symbols. Calls are debounced —
   * multiple calls within 50ms merge into one WS send. Symbols
   * already cached (within TTL) are served from cache immediately.
   */
  public requestChangeRanges(symbols: string[]): void {
    this.enqueueRequest(symbols, 'get_change_ranges');
  }

  /**
   * Request symbol-data for a set of symbols. Same debounce + cache
   * semantics as `requestChangeRanges`.
   */
  public requestSymbolData(symbols: string[]): void {
    this.enqueueRequest(symbols, 'get_symbol_data');
  }

  public onChangeRanges(handler: ChangeRangesHandler): () => void {
    this.changeRangesListeners.add(handler);
    return () => this.changeRangesListeners.delete(handler);
  }

  public onSymbolData(handler: SymbolDataHandler): () => void {
    this.symbolDataListeners.add(handler);
    return () => this.symbolDataListeners.delete(handler);
  }

  public onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionListeners.add(handler);
    return () => this.connectionListeners.delete(handler);
  }

  public get isConnected(): boolean {
    return this.connected;
  }

  /**
   * Test-only helper. Resets all internal state and tears down any
   * existing connection. NOT for production use.
   */
  public __resetForTests(): void {
    this.disconnect();
    this.changeRangesCache.clear();
    this.symbolDataCache.clear();
    this.pendingChangeRanges.clear();
    this.pendingSymbolData.clear();
    if (this.changeRangesDebounceTimer !== null) {
      clearTimeout(this.changeRangesDebounceTimer);
      this.changeRangesDebounceTimer = null;
    }
    if (this.symbolDataDebounceTimer !== null) {
      clearTimeout(this.symbolDataDebounceTimer);
      this.symbolDataDebounceTimer = null;
    }
    this.pendingRequests.clear();
    this.nextRequestId = 1;
    this.reconnectAttempts = 0;
    this.wsUrl = null;
    this.wsUrlFetchInitiated = false;
    this.wsUrlFailedOnce = false;
    this.changeRangesListeners.clear();
    this.symbolDataListeners.clear();
    this.connectionListeners.clear();
  }

  // ── Internals ───────────────────────────────────────────────────────────

  private enqueueRequest(
    symbols: string[],
    action: 'get_change_ranges' | 'get_symbol_data',
  ): void {
    const cache = action === 'get_change_ranges' ? this.changeRangesCache : this.symbolDataCache;
    const now = Date.now();

    // Cache hits fire listeners synchronously and don't touch the WS.
    const needsFetch: string[] = [];
    for (const sym of symbols) {
      const cached = cache.get(sym);
      if (cached && cached.expiresAt > now) {
        if (action === 'get_change_ranges') {
          this.notifyChangeRanges(sym, cached.data as ChangeRanges);
        } else {
          this.notifySymbolData(sym, cached.data as SymbolDataExtract);
        }
      } else {
        needsFetch.push(sym);
      }
    }

    if (needsFetch.length === 0) return;

    const queue = action === 'get_change_ranges' ? this.pendingChangeRanges : this.pendingSymbolData;
    for (const sym of needsFetch) queue.add(sym);

    // Open the socket on first use — connects once, stays open for
    // the rest of the page lifetime.
    this.connect();

    const timerHolder = action === 'get_change_ranges' ? 'changeRangesDebounceTimer' : 'symbolDataDebounceTimer';
    if (this[timerHolder] !== null) {
      clearTimeout(this[timerHolder]!);
    }
    this[timerHolder] = setTimeout(() => {
      this[timerHolder === 'changeRangesDebounceTimer' ? 'changeRangesDebounceTimer' : 'symbolDataDebounceTimer'] = null;
      if (action === 'get_change_ranges') {
        this.flushChangeRanges();
      } else {
        this.flushSymbolData();
      }
    }, DEBOUNCE_MS);
  }

  private flushChangeRanges(): void {
    if (this.pendingChangeRanges.size === 0) return;
    const symbols = Array.from(this.pendingChangeRanges);
    this.pendingChangeRanges.clear();
    this.send('get_change_ranges', symbols);
  }

  private flushSymbolData(): void {
    if (this.pendingSymbolData.size === 0) return;
    const symbols = Array.from(this.pendingSymbolData);
    this.pendingSymbolData.clear();
    this.send('get_symbol_data', symbols);
  }

  private send(action: 'get_change_ranges' | 'get_symbol_data', symbols: string[]): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      // We're not connected — record the request so we can re-send
      // on reconnect. The consumer's `null` notifications happen
      // when the disconnect actually fires, not here.
      this.recordPending(action, symbols);
      return;
    }
    const requestId = this.allocateRequestId();
    this.recordPending(action, symbols, requestId);
    try {
      this.socket.send(JSON.stringify({ action, request_id: requestId, symbols }));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('[marketWs] send failed:', message);
      // The socket is probably in CLOSING/CLOSED. Treat as a
      // dropped request — listeners will get `null` via the close
      // handler.
    }
  }

  private allocateRequestId(): number {
    const id = this.nextRequestId;
    this.nextRequestId = (this.nextRequestId + 1) | 0;
    if (this.nextRequestId === 0) this.nextRequestId = 1; // never 0
    return id;
  }

  private recordPending(
    action: 'get_change_ranges' | 'get_symbol_data',
    symbols: string[],
    requestId?: number,
  ): void {
    const id = requestId ?? this.allocateRequestId();
    this.pendingRequests.set(id, {
      action,
      symbols: [...symbols],
      seenSymbols: new Set(),
    });
  }

  // ── Socket lifecycle ────────────────────────────────────────────────────

  private async fetchWsUrl(): Promise<string | null> {
    // Resolution mirrors src/lib/newsSocket.ts:env var first, then
    // a same-origin fallback. The browser is already at the public
    // origin (https://blm.example.com), so deriving the WS base from
    // window.location is the correct cross-environment pattern.
    //
    // We deliberately do NOT round-trip through /api/py/ws-config
    // here: that route resolves to PYTHON_BACKEND_URL on the server,
    // which in production is often unreachable from the browser
    // (different host, no public DNS, or no path through the reverse
    // proxy for the WS upgrade). The env-var pattern lets deploys
    // override the URL explicitly when the Python backend is on a
    // different host.
    const envUrl = process.env.NEXT_PUBLIC_MARKET_WS_URL;
    if (envUrl) return envUrl;
    return this.localhostFallback();
  }

  private localhostFallback(): string {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${window.location.host}/ws/market`;
  }

  private async openSocket(): Promise<void> {
    if (!this.wsUrl) return;
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    try {
      const url = await withTicket(this.wsUrl);
      this.socket = new WebSocket(url);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.error('[marketWs] WebSocket constructor failed:', message);
      this.scheduleReconnect();
      return;
    }

    this.socket.onopen = () => {
      this.connected = true;
      this.reconnectAttempts = 0;
      this.connectInitiated = true;
      this.notifyConnection(true);
      this.startKeepAlive();
      this.replayPendingRequests();
    };

    this.socket.onmessage = (event: MessageEvent) => {
      this.handleMessage(event);
    };

    this.socket.onerror = (event) => {
      console.warn('[marketWs] socket error:', event);
    };

    this.socket.onclose = () => {
      this.handleClose();
    };
  }

  private handleClose(): void {
    const wasConnected = this.connected;
    this.connected = false;
    this.stopKeepAlive();
    this.socket = null;

    if (wasConnected) this.notifyConnection(false);

    // Notify listeners for symbols whose partials never arrived.
    // We do NOT clear pendingRequests — the reconnect handler
    // re-sends them on the new socket so consumers can complete
    // their loading state.
    this.failPendingRequests();

    this.scheduleReconnect();
  }

  private failPendingRequests(): void {
    for (const req of this.pendingRequests.values()) {
      for (const sym of req.symbols) {
        if (req.seenSymbols.has(sym)) continue;
        if (req.action === 'get_change_ranges') {
          this.notifyChangeRanges(sym, null);
        } else {
          this.notifySymbolData(sym, null);
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    if (this.reconnectAttempts >= RECONNECT_MAX_ATTEMPTS) {
      console.warn('[marketWs] max reconnect attempts reached; giving up');
      return;
    }
    const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts), RECONNECT_MAX_MS);
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connectInitiated = false;
      this.openSocket();
    }, delay);
  }

  private clearReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startKeepAlive(): void {
    this.stopKeepAlive();
    this.keepAliveTimer = setInterval(() => {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        try {
          this.socket.send(JSON.stringify({ action: 'ping' }));
        } catch {
          // ignore
        }
      }
    }, KEEP_ALIVE_MS);
  }

  private stopKeepAlive(): void {
    if (this.keepAliveTimer !== null) {
      clearInterval(this.keepAliveTimer);
      this.keepAliveTimer = null;
    }
  }

  private replayPendingRequests(): void {
    if (this.pendingRequests.size === 0) return;
    // Re-send every still-pending batch. request_ids are NOT
    // preserved — the new request gets a fresh id, and the old
    // (now-orphaned) request_id in the server's queue is harmless
    // because partials fan out to listeners by symbol, not by
    // request_id, on the client side.
    const toReplay = Array.from(this.pendingRequests.values());
    this.pendingRequests.clear();
    for (const req of toReplay) {
      this.send(req.action, req.symbols);
    }
  }

  // ── Message dispatch ────────────────────────────────────────────────────

  private handleMessage(event: MessageEvent): void {
    let msg: {
      type?: string;
      request_id?: number;
      symbol?: string;
      symbols?: string[];
      data?: unknown;
      error?: string;
      message?: string;
    };
    try {
      msg = JSON.parse(event.data as string) as typeof msg;
    } catch {
      return;
    }

    switch (msg.type) {
      case 'connected':
      case 'heartbeat':
      case 'pong':
        return;

      case 'change_ranges_started':
        this.markPendingSymbols(msg.request_id, msg.symbols ?? []);
        return;

      case 'symbol_data_started':
        this.markPendingSymbols(msg.request_id, msg.symbols ?? []);
        return;

      case 'change_ranges_partial':
        this.handlePartial(msg, 'get_change_ranges');
        return;

      case 'symbol_data_partial':
        this.handlePartial(msg, 'get_symbol_data');
        return;

      case 'change_ranges_complete':
      case 'symbol_data_complete':
        if (typeof msg.request_id === 'number') {
          this.pendingRequests.delete(msg.request_id);
        }
        return;

      case 'error':
        console.warn('[marketWs] server error:', msg.message);
        return;

      default:
        return;
    }
  }

  private markPendingSymbols(requestId: number | undefined, symbols: string[]): void {
    if (typeof requestId !== 'number') return;
    const req = this.pendingRequests.get(requestId);
    if (!req) return;
    // `seenSymbols` stays empty here — it's used to suppress the
    // `null` notification on disconnect, but the explicit
    // `*_complete` is what deletes the pending entry.
    void symbols;
  }

  private handlePartial(
    msg: {
      type?: string;
      request_id?: number;
      symbol?: string;
      data?: unknown;
      error?: string;
    },
    action: 'get_change_ranges' | 'get_symbol_data',
  ): void {
    if (typeof msg.request_id !== 'number' || typeof msg.symbol !== 'string') return;
    const req = this.pendingRequests.get(msg.request_id);
    if (req) req.seenSymbols.add(msg.symbol);

    if (action === 'get_change_ranges') {
      const data = (msg.data ?? null) as ChangeRanges | null;
      if (data) {
        this.changeRangesCache.set(msg.symbol, {
          data,
          expiresAt: Date.now() + CHANGE_RANGES_TTL_MS,
        });
      }
      this.notifyChangeRanges(msg.symbol, data);
    } else {
      // The server's WS handler extracts the {ltp, pChange,
      // yearHigh, yearLow} fields from the raw NSE payload
      // before sending the *_partial. We pass the extracted
      // shape straight to listeners — no client-side extraction
      // is needed.
      const data = (msg.data ?? null) as SymbolDataExtract | null;
      if (data) {
        this.symbolDataCache.set(msg.symbol, {
          data,
          expiresAt: Date.now() + SYMBOL_DATA_TTL_MS,
        });
      }
      this.notifySymbolData(msg.symbol, data);
    }
  }

  // ── Notify helpers ──────────────────────────────────────────────────────

  private notifyChangeRanges(symbol: string, data: ChangeRanges | null): void {
    for (const h of this.changeRangesListeners) h(symbol, data);
  }

  private notifySymbolData(symbol: string, data: SymbolDataExtract | null): void {
    for (const h of this.symbolDataListeners) h(symbol, data);
  }

  private notifyConnection(connected: boolean): void {
    for (const h of this.connectionListeners) h(connected);
  }
}

export const marketWsService = MarketWsService.getInstance();

/**
 * MarketDataService — singleton client for /api/nse/change-ranges and
 * /api/nse/symbol-data (Next.js proxy routes).
 *
 * Replaces the previous WebSocket transport with HTTP. Multiple React
 * components can register for the same symbol; the service deduplicates
 * and batches requests.
 *
 * Batching strategy (debounced):
 *   Components call requestChangeRanges / requestSymbolData with their symbols.
 *   The service queues those symbols and flushes one HTTP request after a
 *   50 ms microtask delay. Rows that mount nearly simultaneously are
 *   automatically grouped into a single round-trip.
 *
 * Client-side TTL caches mirror the server-side TTLs (5 min / 1 min) so
 * that bursts within the same browser tab don't re-hit the proxy.
 */

import type { ChangeRanges, SymbolDataExtract } from './nseTypes';

type ChangeRangesHandler = (symbol: string, data: ChangeRanges | null) => void;
type SymbolDataHandler = (symbol: string, data: SymbolDataExtract | null) => void;
type ConnectionHandler = (connected: boolean) => void;

interface ChangeRangesResponse {
  data: Record<string, ChangeRanges | null>;
}

interface SymbolDataResponse {
  data: Record<string, SymbolDataExtract | null>;
}

class MarketDataService {
  private static instance: MarketDataService;

  // ── Listeners ──────────────────────────────────────────────────────────────
  private changeRangesListeners: Set<ChangeRangesHandler> = new Set();
  private symbolDataListeners: Set<SymbolDataHandler> = new Set();
  private connectionListeners: Set<ConnectionHandler> = new Set();
  private hasEmittedConnected = false;

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

  public static getInstance(): MarketDataService {
    if (!MarketDataService.instance) {
      MarketDataService.instance = new MarketDataService();
    }
    return MarketDataService.instance;
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Request change-ranges data for a set of symbols.
   * Calls are debounced — multiple calls within 50 ms are merged into one HTTP request.
   * Symbols already cached (within TTL) are served from cache immediately.
   */
  public requestChangeRanges(symbols: string[]): void {
    const now = Date.now();
    const needsFetch: string[] = [];

    for (const sym of symbols) {
      const cached = this.changeRangesCache.get(sym);
      if (cached && cached.expiresAt > now) {
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
   * Calls are debounced — multiple calls within 50 ms are merged into one HTTP request.
   * Symbols already cached (within TTL) are served from cache immediately.
   */
  public requestSymbolData(symbols: string[]): void {
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

  /**
   * Subscribe to connection state changes.
   * HTTP transport is always available once the first request succeeds; this is
   * kept for back-compat with consumers that used it to drive a status indicator.
   */
  public onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionListeners.add(handler);
    if (!this.hasEmittedConnected) {
      this.hasEmittedConnected = true;
      queueMicrotask(() => handler(true));
    }
    return () => this.connectionListeners.delete(handler);
  }

  public get isConnected(): boolean {
    return true;
  }

  // ── Flush helpers ──────────────────────────────────────────────────────────

  private flushChangeRanges(): void {
    this.changeRangesDebounceTimer = null;
    if (this.pendingChangeRanges.size === 0) return;

    const symbols = Array.from(this.pendingChangeRanges);
    this.pendingChangeRanges.clear();

    const url = `/api/nse/change-ranges?symbols=${encodeURIComponent(symbols.join(','))}`;

    void fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<ChangeRangesResponse>;
      })
      .then((body) => this.applyChangeRangesResponse(symbols, body))
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[marketData] change-ranges fetch failed:', message);
        for (const sym of symbols) this.notifyChangeRanges(sym, null);
      });
  }

  private flushSymbolData(): void {
    this.symbolDataDebounceTimer = null;
    if (this.pendingSymbolData.size === 0) return;

    const symbols = Array.from(this.pendingSymbolData);
    this.pendingSymbolData.clear();

    const url = `/api/nse/symbol-data?symbols=${encodeURIComponent(symbols.join(','))}`;

    void fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<SymbolDataResponse>;
      })
      .then((body) => this.applySymbolDataResponse(symbols, body))
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error('[marketData] symbol-data fetch failed:', message);
        for (const sym of symbols) this.notifySymbolData(sym, null);
      });
  }

  private applyChangeRangesResponse(requested: string[], body: ChangeRangesResponse): void {
    const now = Date.now();
    for (const sym of requested) {
      const value = body.data?.[sym] ?? null;
      if (value) {
        this.changeRangesCache.set(sym, {
          data: value,
          expiresAt: now + this.CHANGE_RANGES_TTL_MS,
        });
      }
      this.notifyChangeRanges(sym, value);
    }
  }

  private applySymbolDataResponse(requested: string[], body: SymbolDataResponse): void {
    const now = Date.now();
    for (const sym of requested) {
      const value = body.data?.[sym] ?? null;
      if (value) {
        this.symbolDataCache.set(sym, {
          data: value,
          expiresAt: now + this.SYMBOL_DATA_TTL_MS,
        });
      }
      this.notifySymbolData(sym, value);
    }
  }

  // ── Notify helpers ─────────────────────────────────────────────────────────

  private notifyChangeRanges(symbol: string, data: ChangeRanges | null): void {
    this.changeRangesListeners.forEach((h) => h(symbol, data));
  }

  private notifySymbolData(symbol: string, data: SymbolDataExtract | null): void {
    this.symbolDataListeners.forEach((h) => h(symbol, data));
  }
}

export const marketDataService = MarketDataService.getInstance();

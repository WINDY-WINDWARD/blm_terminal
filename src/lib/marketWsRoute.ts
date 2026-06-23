/**
 * WebSocket protocol helpers for the /ws/market endpoint.
 *
 * The route at `src/app/api/ws/market/route.ts` exports a default
 * function that handles incoming WebSocket connections. The
 * helpers in this module are the real protocol — they own the
 * message shape and the per-symbol fallback policy.
 *
 * The streaming functions accept a generic `WsLike` so the same
 * code path can be unit-tested with a fake WebSocket AND wired
 * into the real Next.js WS handler. The Next.js route file is a
 * thin shell that accepts the upgrade, sends `{type: "connected"}`,
 * and dispatches incoming messages to `handleMarketWsMessage`.
 *
 * Wire protocol (browser side: `src/lib/marketWs.ts`):
 *   Server → Browser:
 *     { type: "connected" }
 *     { type: "change_ranges_started",  request_id, symbols }
 *     { type: "change_ranges_partial",  request_id, symbol, data, error? }
 *     { type: "change_ranges_complete", request_id }
 *     { type: "symbol_data_started",    request_id, symbols }
 *     { type: "symbol_data_partial",    request_id, symbol, data, error? }
 *     { type: "symbol_data_complete",   request_id }
 *     { type: "error", request_id?, message }
 *
 * Per-symbol resolution: NSE-direct first, Python backend fallback
 * on NSE failure (3 attempts with backoff). See `marketWsStreamer.ts`
 * for the resolution policy.
 */

import {
  fetchChangeRangesWithFallback,
  fetchSymbolDataWithFallback,
  NSE_MAX_SYMBOLS_PER_REQUEST,
} from './marketWsStreamer';

/** Minimal interface a WebSocket-like object must satisfy. */
export interface WsLike {
  send(data: string): void;
  close?(): void;
  on?(event: string, listener: (...args: unknown[]) => void): void;
}

export interface WsMessage {
  type?: string;
  action?: string;
  request_id?: number;
  symbol?: string;
  symbols?: string[];
  data?: unknown;
  error?: string;
  message?: string;
}

function sendJson(ws: WsLike, msg: WsMessage): void {
  try {
    ws.send(JSON.stringify(msg));
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.warn('[marketWsRoute] send failed:', message);
  }
}

/**
 * Shared per-symbol streaming logic. Runs the per-symbol fetches
 * in parallel and emits one `*_partial` per completion (so the
 * first row paints as soon as its NSE call returns, not after
 * the slowest call).
 */
async function streamBatch(
  ws: WsLike,
  requestId: number,
  symbols: string[],
  startedType: string,
  partialType: string,
  completeType: string,
  fetcher: (symbol: string) => Promise<unknown>,
): Promise<void> {
  if (!symbols || !Array.isArray(symbols) || symbols.length === 0) {
    sendJson(ws, {
      type: 'error',
      request_id: requestId,
      message: 'symbols must be a non-empty list',
    });
    return;
  }

  const capped = symbols.slice(0, NSE_MAX_SYMBOLS_PER_REQUEST);

  sendJson(ws, {
    type: startedType,
    request_id: requestId,
    symbols: capped,
  });

  // Kick off all per-symbol fetches concurrently and emit partials
  // in completion order. The first row paints as soon as its
  // NSE call returns, not after the slowest one completes.
  //
  // We use an array of task objects (each holding its own promise
  // handle) and iterate, awaiting each promise and removing it
  // from the array when it settles. This avoids the
  // `Promise.race(remaining)` pitfall where `Set.delete(value)`
  // doesn't match the original promise handle.
  type Task = {
    sym: string;
    promise: Promise<{ sym: string; value: unknown }>;
  };
  const tasks: Task[] = capped.map((sym) => {
    const promise = fetcher(sym)
      .then((value) => ({ sym, value }))
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.warn(`[marketWsRoute] unhandled error for ${sym}: ${message}`);
        return { sym, value: null as unknown };
      });
    return { sym, promise };
  });

  while (tasks.length > 0) {
    // Promise.race over the current task promises. Whichever
    // settles first, we emit its partial and remove that task
    // from the array.
    const completed = await Promise.race(tasks.map((t) => t.promise));
    const idx = tasks.findIndex((t) => t.sym === completed.sym);
    if (idx >= 0) tasks.splice(idx, 1);
    const partial: WsMessage = {
      type: partialType,
      request_id: requestId,
      symbol: completed.sym,
    };
    if (completed.value === null || completed.value === undefined) {
      partial.data = null;
    } else {
      partial.data = completed.value;
    }
    sendJson(ws, partial);
  }

  sendJson(ws, { type: completeType, request_id: requestId });
}

export async function streamChangeRanges(
  ws: WsLike,
  requestId: number,
  symbols: string[],
): Promise<void> {
  await streamBatch(
    ws,
    requestId,
    symbols,
    'change_ranges_started',
    'change_ranges_partial',
    'change_ranges_complete',
    (sym) => fetchChangeRangesWithFallback(sym),
  );
}

export async function streamSymbolData(
  ws: WsLike,
  requestId: number,
  symbols: string[],
): Promise<void> {
  await streamBatch(
    ws,
    requestId,
    symbols,
    'symbol_data_started',
    'symbol_data_partial',
    'symbol_data_complete',
    (sym) => fetchSymbolDataWithFallback(sym),
  );
}

/**
 * Top-level dispatcher for an incoming client message. Returns
 * the promise from the streaming helpers so the caller can await
 * the full response before processing the next message.
 */
export async function handleMarketWsMessage(
  ws: WsLike,
  raw: string,
): Promise<void> {
  let msg: WsMessage;
  try {
    msg = JSON.parse(raw) as WsMessage;
  } catch {
    return;
  }

  const action = msg.action;
  const requestId = Number(msg.request_id ?? 0) | 0;
  const symbols = Array.isArray(msg.symbols) ? msg.symbols : [];

  if (action === 'get_change_ranges') {
    await streamChangeRanges(ws, requestId, symbols);
  } else if (action === 'get_symbol_data') {
    await streamSymbolData(ws, requestId, symbols);
  } else if (action !== undefined) {
    sendJson(ws, {
      type: 'error',
      request_id: requestId,
      message: `Unknown action: ${action}`,
    });
  }
}

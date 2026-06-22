/**
 * Back-compat shim. The HTTP-based singleton that used to live in
 * this file has been replaced by a persistent WebSocket client in
 * `./marketWs`. The WS path streams per-symbol partials as each
 * NSE call completes, so a 20-symbol watchlist can paint its first
 * row in ~200ms (cache hit) instead of waiting ~15s for the
 * slowest symbol.
 *
 * The public API (`requestChangeRanges`, `requestSymbolData`,
 * `onChangeRanges`, `onSymbolData`, `onConnectionChange`, `isConnected`)
 * is identical to the previous version, so existing call sites in
 * `WatchWidget`, `MoversWidget`, and `TerminalContainer` need no
 * changes. The `isConnected` getter now reflects the real WebSocket
 * state instead of a hardcoded `true`.
 */

export { marketWsService as marketDataService } from './marketWs';

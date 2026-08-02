/**
 * Per-symbol fetch + fallback helpers used by the Next.js WS route
 * at `src/app/api/ws/market/route.ts`. The WS handler delegates
 * per-symbol work to these helpers — they're the place the
 * NSE-direct-with-Python-fallback policy lives.
 *
 * The contract:
 *   1. Try NSE directly via the shared throttledNseCall (concurrency
 *      limit, request coalescing, circuit breaker, 2 retries = 3
 *      total attempts).
 *   2. If NSE returns a value, use it. If NSE returns a soft miss
 *      (e.g. ARROWGREEN's empty payload) or fails after 3 attempts,
 *      fall back to the Python backend's HTTP route for that one
 *      symbol.
 *   3. If Python also fails, return null. The WS route emits a
 *      `*_partial` with `data: null` for that symbol.
 *
 * The shared HTTP route files at `src/app/api/nse/{symbol-data,
 * change-ranges}/route.ts` refactored to call these helpers too,
 * so the WS path and the HTTP path use identical resolution logic.
 */

import { throttledNseCall, NSEServiceUnavailableError } from '@/lib/nseThrottle';
import { cache } from '@/lib/cache';
import {
  extractSymbolData,
  parseChangeRangesRow,
  SYMBOL_DATA_TTL_SECONDS,
  CHANGE_RANGES_TTL_SECONDS,
  NSE_BASE_URL,
  NSE_HEADERS,
  NSE_MAX_SYMBOLS_PER_REQUEST,
  type ChangeRanges,
  type RawNseSymbolData,
  type SymbolDataExtract,
} from '@/lib/nseTypes';

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

const ENDPOINT_SYMBOL_DATA = 'symbol-data';
const ENDPOINT_CHANGE_RANGES = 'change-ranges';

export function isSymbolDataCacheable(value: SymbolDataExtract | null): value is SymbolDataExtract {
  return value !== null && typeof value.ltp === 'number' && value.ltp > 0;
}

export function isChangeRangesCacheable(value: ChangeRanges | null): value is ChangeRanges {
  return value !== null && Object.values(value).some((v) => v !== null);
}

// ── NSE builders (mirror the existing HTTP route) ─────────────────────────

function buildSymbolDataUrl(symbol: string): string {
  const params = new URLSearchParams({
    functionName: 'getSymbolData',
    marketType: 'N',
    series: 'EQ',
    symbol,
  });
  return `${NSE_BASE_URL}/api/NextApi/apiClient/GetQuoteApi?${params.toString()}`;
}

function buildChangeRangesUrl(symbol: string): string {
  const params = new URLSearchParams({
    functionName: 'getYearwiseData',
    symbol: `${symbol}EQN`,
  });
  return `${NSE_BASE_URL}/api/NextApi/apiClient/GetQuoteApi?${params.toString()}`;
}

// ── NSE direct fetches (raw, with parsing) ────────────────────────────────

async function fetchSymbolDataFromNse(symbol: string): Promise<SymbolDataExtract | null> {
  const res = await fetch(buildSymbolDataUrl(symbol), {
    headers: NSE_HEADERS,
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) {
    throw new Error(`NSE returned ${res.status}`);
  }
  const payload = (await res.json()) as unknown;
  if (!payload || typeof payload !== 'object') {
    throw new Error('Unexpected getSymbolData response shape');
  }
  return extractSymbolData(payload as RawNseSymbolData);
}

async function fetchChangeRangesFromNse(symbol: string): Promise<ChangeRanges | null> {
  const res = await fetch(buildChangeRangesUrl(symbol), {
    headers: NSE_HEADERS,
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) {
    throw new Error(`NSE returned ${res.status}`);
  }
  const payload = (await res.json()) as unknown;
  // NSE sometimes returns `{ data: [...] }`, sometimes a bare `[...]`,
  // and sometimes an object/empty payload for unknown symbols (e.g.
  // ARROWGREEN, which is too new for NSE's yearwise endpoint). Treat
  // the latter as a soft miss (null) rather than throwing — throwing
  // would trip the circuit breaker as if NSE were down.
  let row: Record<string, unknown> | undefined;
  if (Array.isArray(payload)) {
    row = payload[0];
  } else if (
    payload &&
    typeof payload === 'object' &&
    Array.isArray((payload as { data?: unknown }).data)
  ) {
    row = ((payload as { data: unknown[] }).data[0] as Record<string, unknown>) ?? undefined;
  }
  if (!row) return null;
  return parseChangeRangesRow(row);
}

// ── Python backend fallbacks ──────────────────────────────────────────────

async function fetchSymbolDataFromPython(symbol: string): Promise<SymbolDataExtract | null> {
  const url = `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) {
    throw new Error(`Python backend returned ${res.status}`);
  }
  // Python streams the raw NSE getSymbolData payload (the same
  // shape NSE returns). We extract it here to keep the same
  // SymbolDataExtract contract as the NSE-direct path.
  const body = (await res.json()) as { data: Record<string, RawNseSymbolData | null> };
  return extractSymbolData(body.data?.[symbol] ?? null);
}

async function fetchChangeRangesFromPython(symbol: string): Promise<ChangeRanges | null> {
  const url = `${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) {
    throw new Error(`Python backend returned ${res.status}`);
  }
  // Python already returns the camelCased ChangeRanges shape (its
  // `get_change_ranges` service does the snake_case → camelCase
  // mapping). Pass it through; if the value is missing/null, the
  // outer `isChangeRangesCacheable` check filters it out.
  const body = (await res.json()) as { data: Record<string, ChangeRanges | null> };
  return body.data?.[symbol] ?? null;
}

// ── Public helpers (used by the WS route + the HTTP routes) ───────────────

const NSE_MAX_ATTEMPTS = 3; // 1 initial + 2 retries

function isNseFailureTransient(err: unknown): boolean {
  // Retriable: transient network errors, aborts, timeouts, NSE
  // 5xx, and any "soft" NSE errors that look transient.
  if (err instanceof TypeError) return true;
  if (err instanceof Error && (err.name === 'AbortError' || err.name === 'TimeoutError')) return true;
  if (err instanceof Error && /^NSE returned 5\d\d/.test(err.message)) return true;
  if (err instanceof Error && /Unexpected getSymbolData response shape/.test(err.message)) return true;
  return false;
}

async function fetchWithRetries<T>(label: string, fn: () => Promise<T>): Promise<T> {
  let lastExc: unknown;
  for (let attempt = 0; attempt < NSE_MAX_ATTEMPTS; attempt++) {
    try {
      return await fn();
    } catch (err: unknown) {
      lastExc = err;
      if (attempt < NSE_MAX_ATTEMPTS - 1 && isNseFailureTransient(err)) {
        const backoffMs = 250 * Math.pow(2, attempt);
        await new Promise<void>((r) => setTimeout(r, backoffMs));
        continue;
      }
      throw err;
    }
  }
  // Unreachable: the loop always either returns or throws. But
  // TypeScript can't infer that, so re-throw for safety.
  throw lastExc;
}

/**
 * Resolve one symbol's data with NSE-direct first, Python fallback.
 * The in-process cache is consulted before any HTTP call, and
 * written on success.
 *
 * NSE is attempted up to 3 times (1 initial + 2 retries) for
 * transient failures (network, aborts, timeouts, NSE 5xx). After
 * the 3rd failure — or on a non-transient error — we fall back
 * to the Python backend's HTTP route for that one symbol.
 */
export async function fetchSymbolDataWithFallback(
  symbol: string,
): Promise<SymbolDataExtract | null> {
  const sym = symbol.toUpperCase();
  const cacheKey = `symbol-data:${sym}`;
  const cached = cache.get<SymbolDataExtract>(cacheKey);
  if (cached) return cached;

  let nseFailed = false;
  try {
    // We do our own retry inside fetchWithRetries (3 total attempts
    // including the initial one) so we pass `retries: 0` to the
    // throttle — otherwise the two retry loops would compose and
    // produce 3 × 3 = 9 attempts on a transient failure.
    const value = await throttledNseCall(
      cacheKey,
      () => fetchWithRetries(`${ENDPOINT_SYMBOL_DATA}:${sym}`, () => fetchSymbolDataFromNse(sym)),
      { coalesceKey: `${ENDPOINT_SYMBOL_DATA}:${sym}`, retries: 0 },
    );
    if (isSymbolDataCacheable(value)) {
      cache.set(cacheKey, value, SYMBOL_DATA_TTL_SECONDS);
      return value;
    }
    nseFailed = true;
  } catch (err: unknown) {
    nseFailed = true;
    if (err instanceof NSEServiceUnavailableError) {
      console.warn(
        `[marketWsStreamer] symbol-data circuit open, falling back to Python for ${sym}`,
      );
    } else {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.warn(
        `[marketWsStreamer] symbol-data NSE fetch failed for ${sym} after 3 attempts: ${message}`,
      );
    }
  }
  void nseFailed;

  try {
    const value = await fetchSymbolDataFromPython(sym);
    if (isSymbolDataCacheable(value)) {
      cache.set(cacheKey, value, SYMBOL_DATA_TTL_SECONDS);
    }
    return value;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(
      `[marketWsStreamer] symbol-data Python fallback failed for ${sym}: ${message}`,
    );
    return null;
  }
}

export async function fetchChangeRangesWithFallback(
  symbol: string,
): Promise<ChangeRanges | null> {
  const sym = symbol.toUpperCase();
  const cacheKey = `change-ranges:${sym}`;
  const cached = cache.get<ChangeRanges>(cacheKey);
  if (cached) return cached;

  let nseFailed = false;
  try {
    const value = await throttledNseCall(
      cacheKey,
      () => fetchWithRetries(`${ENDPOINT_CHANGE_RANGES}:${sym}`, () => fetchChangeRangesFromNse(sym)),
      { coalesceKey: `${ENDPOINT_CHANGE_RANGES}:${sym}`, retries: 0 },
    );
    if (isChangeRangesCacheable(value)) {
      cache.set(cacheKey, value, CHANGE_RANGES_TTL_SECONDS);
      return value;
    }
    nseFailed = true;
  } catch (err: unknown) {
    nseFailed = true;
    if (err instanceof NSEServiceUnavailableError) {
      console.warn(
        `[marketWsStreamer] change-ranges circuit open, falling back to Python for ${sym}`,
      );
    } else {
      const message = err instanceof Error ? err.message : 'Unknown error';
      console.warn(
        `[marketWsStreamer] change-ranges NSE fetch failed for ${sym} after 3 attempts: ${message}`,
      );
    }
  }
  void nseFailed;

  try {
    const value = await fetchChangeRangesFromPython(sym);
    if (isChangeRangesCacheable(value)) {
      cache.set(cacheKey, value, CHANGE_RANGES_TTL_SECONDS);
    }
    return value;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(
      `[marketWsStreamer] change-ranges Python fallback failed for ${sym}: ${message}`,
    );
    return null;
  }
}

// Re-export for any callers that want to constrain the batch size
// the way the HTTP routes do.
export { NSE_MAX_SYMBOLS_PER_REQUEST };

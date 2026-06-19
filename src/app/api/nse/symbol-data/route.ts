import { NextRequest, NextResponse } from 'next/server';
import {
  NSE_BASE_URL,
  NSE_HEADERS,
  NSE_MAX_SYMBOLS_PER_REQUEST,
  SYMBOL_DATA_TTL_SECONDS,
  type RawNseSymbolData,
  type SymbolDataExtract,
  extractSymbolData,
} from '@/lib/nseTypes';
import { cache } from '@/lib/cache';
import { throttledNseCall, NSEServiceUnavailableError } from '@/lib/nseThrottle';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

const ENDPOINT_NAME = 'symbol-data';

function buildUrl(symbol: string): string {
  const params = new URLSearchParams({
    functionName: 'getSymbolData',
    marketType: 'N',
    series: 'EQ',
    symbol,
  });
  return `${NSE_BASE_URL}/api/NextApi/apiClient/GetQuoteApi?${params.toString()}`;
}

async function fetchSymbolDataFromNse(symbol: string): Promise<SymbolDataExtract | null> {
  const res = await fetch(buildUrl(symbol), {
    headers: NSE_HEADERS,
    signal: AbortSignal.timeout(15000),
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

async function fetchSymbolDataFromPython(
  symbol: string,
): Promise<SymbolDataExtract | null> {
  // Backend route defines `symbol: list[str] = Query(...)` — a single
  // `?symbol=X` binds as `["X"]`, repeated `?symbol=A&symbol=B` binds both.
  const url = `${PYTHON_BACKEND_URL}/api/markets/symbol-data?symbol=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    throw new Error(`Python backend returned ${res.status}`);
  }
  const body = (await res.json()) as { data: Record<string, SymbolDataExtract | null> };
  return body.data?.[symbol] ?? null;
}

async function resolveSymbolData(symbol: string): Promise<SymbolDataExtract | null> {
  const cacheKey = `symbol-data:${symbol}`;
  const cached = cache.get<SymbolDataExtract>(cacheKey);
  if (cached) return cached;

  try {
    const value = await throttledNseCall(
      ENDPOINT_NAME,
      () => fetchSymbolDataFromNse(symbol),
      { coalesceKey: `${ENDPOINT_NAME}:${symbol}` },
    );
    if (value) cache.set(cacheKey, value, SYMBOL_DATA_TTL_SECONDS);
    return value;
  } catch (nseErr: unknown) {
    if (nseErr instanceof NSEServiceUnavailableError) {
      console.warn(
        `[nse/symbol-data] circuit open, falling back to Python for ${symbol}`,
      );
    } else {
      const message = nseErr instanceof Error ? nseErr.message : 'Unknown error';
      console.warn(`[nse/symbol-data] NSE fetch failed for ${symbol}: ${message}`);
    }
    try {
      const value = await fetchSymbolDataFromPython(symbol);
      if (value) cache.set(cacheKey, value, SYMBOL_DATA_TTL_SECONDS);
      return value;
    } catch (pyErr: unknown) {
      const message = pyErr instanceof Error ? pyErr.message : 'Unknown error';
      console.error(
        `[nse/symbol-data] Python fallback failed for ${symbol}: ${message}`,
      );
      return null;
    }
  }
}

export async function GET(request: NextRequest): Promise<NextResponse> {
  const raw = request.nextUrl.searchParams.get('symbols') ?? '';
  const symbols = Array.from(
    new Set(
      raw
        .split(',')
        .map((s) => s.trim().toUpperCase())
        .filter(Boolean),
    ),
  ).slice(0, NSE_MAX_SYMBOLS_PER_REQUEST);

  if (symbols.length === 0) {
    return NextResponse.json({ data: {} });
  }

  const results = await Promise.all(
    symbols.map(async (sym) => [sym, await resolveSymbolData(sym)] as const),
  );

  const data: Record<string, SymbolDataExtract | null> = {};
  for (const [sym, value] of results) {
    data[sym] = value;
  }

  return NextResponse.json({ data });
}

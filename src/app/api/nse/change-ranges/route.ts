import { NextRequest, NextResponse } from 'next/server';
import {
  NSE_BASE_URL,
  NSE_HEADERS,
  NSE_MAX_SYMBOLS_PER_REQUEST,
  CHANGE_RANGES_TTL_SECONDS,
  type ChangeRanges,
  parseChangeRangesRow,
} from '@/lib/nseTypes';
import { cache } from '@/lib/cache';
import { throttledNseCall, NSEServiceUnavailableError } from '@/lib/nseThrottle';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

const ENDPOINT_NAME = 'change-ranges';

function buildUrl(symbol: string): string {
  const params = new URLSearchParams({
    functionName: 'getYearwiseData',
    symbol: `${symbol}EQN`,
  });
  return `${NSE_BASE_URL}/api/NextApi/apiClient/GetQuoteApi?${params.toString()}`;
}

async function fetchChangeRangesFromNse(symbol: string): Promise<ChangeRanges | null> {
  const res = await fetch(buildUrl(symbol), {
    headers: NSE_HEADERS,
    signal: AbortSignal.timeout(15000),
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

async function fetchChangeRangesFromPython(
  symbol: string,
): Promise<ChangeRanges | null> {
  const url = `${PYTHON_BACKEND_URL}/api/markets/change-ranges?symbol=${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    throw new Error(`Python backend returned ${res.status}`);
  }
  const body = (await res.json()) as { data: Record<string, ChangeRanges | null> };
  return body.data?.[symbol] ?? null;
}

async function resolveChangeRanges(symbol: string): Promise<ChangeRanges | null> {
  const cacheKey = `change-ranges:${symbol}`;
  const cached = cache.get<ChangeRanges>(cacheKey);
  if (cached) return cached;

  try {
    const value = await throttledNseCall(
      ENDPOINT_NAME,
      () => fetchChangeRangesFromNse(symbol),
      { coalesceKey: `${ENDPOINT_NAME}:${symbol}` },
    );
    if (value) cache.set(cacheKey, value, CHANGE_RANGES_TTL_SECONDS);
    return value;
  } catch (nseErr: unknown) {
    if (nseErr instanceof NSEServiceUnavailableError) {
      console.warn(
        `[nse/change-ranges] circuit open, falling back to Python for ${symbol}`,
      );
    } else {
      const message = nseErr instanceof Error ? nseErr.message : 'Unknown error';
      console.warn(`[nse/change-ranges] NSE fetch failed for ${symbol}: ${message}`);
    }
    try {
      const value = await fetchChangeRangesFromPython(symbol);
      if (value) cache.set(cacheKey, value, CHANGE_RANGES_TTL_SECONDS);
      return value;
    } catch (pyErr: unknown) {
      const message = pyErr instanceof Error ? pyErr.message : 'Unknown error';
      console.error(
        `[nse/change-ranges] Python fallback failed for ${symbol}: ${message}`,
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
    symbols.map(async (sym) => [sym, await resolveChangeRanges(sym)] as const),
  );

  const data: Record<string, ChangeRanges | null> = {};
  for (const [sym, value] of results) {
    data[sym] = value;
  }

  return NextResponse.json({ data });
}

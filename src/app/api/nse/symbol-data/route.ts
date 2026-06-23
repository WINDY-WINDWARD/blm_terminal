import { NextRequest, NextResponse } from 'next/server';
import { NSE_MAX_SYMBOLS_PER_REQUEST } from '@/lib/nseTypes';
import { fetchSymbolDataWithFallback } from '@/lib/marketWsStreamer';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * REST endpoint for the Next.js proxy's symbol-data fetcher.
 *
 * The actual NSE-direct + Python-fallback resolution lives in
 * `src/lib/marketWsStreamer.ts` (shared with the WebSocket route).
 * This file is just the HTTP transport adapter.
 */
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
    symbols.map(async (sym) => [sym, await fetchSymbolDataWithFallback(sym)] as const),
  );

  const data: Record<string, unknown> = {};
  for (const [sym, value] of results) {
    data[sym] = value;
  }

  return NextResponse.json({ data });
}

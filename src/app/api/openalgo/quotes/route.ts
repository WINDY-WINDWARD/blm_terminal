import { NextRequest, NextResponse } from 'next/server';
import { OpenAlgoServerClient } from '@/lib/openalgo-server';
import { cache } from '@/lib/cache';
import { rateLimiter } from '@/lib/rate-limiter';
import { logger } from '@/lib/logger';
import { getCacheTtl } from '@/lib/api-config';

const ENDPOINT_NAME = 'quotes';

export async function POST(req: NextRequest) {
  try {
    // Rate limit check
    if (!rateLimiter.isAllowed(ENDPOINT_NAME)) {
      logger.warn(`Rate limit exceeded for ${ENDPOINT_NAME}`);
      return NextResponse.json({ error: 'Rate limit exceeded' }, { status: 429 });
    }

    // Parse and validate request body
    const body = (await req.json()) as { symbol?: string; exchange?: string };
    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();

    if (!symbol || !exchange) {
      logger.warn('Invalid quote request parameters', { symbol, exchange });
      return NextResponse.json(
        { error: 'symbol and exchange are required' },
        { status: 400 }
      );
    }

    // Check cache using symbol+exchange as key
    const cacheKey = `${ENDPOINT_NAME}:${symbol}:${exchange}`;
    const cached = cache.get(cacheKey);
    if (cached) {
      logger.info(`Cache hit for ${cacheKey}`);
      return NextResponse.json(cached);
    }

    // Call OpenAlgo server client
    const result = await OpenAlgoServerClient.getQuote(symbol, exchange);

    // Cache the result
    const cacheTtl = getCacheTtl('quotes');
    if (cacheTtl > 0) {
      cache.set(cacheKey, result, cacheTtl);
    }

    return NextResponse.json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    logger.error(`Error fetching quote: ${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

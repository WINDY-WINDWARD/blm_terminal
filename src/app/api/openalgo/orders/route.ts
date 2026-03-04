import { NextRequest, NextResponse } from 'next/server';
import { OpenAlgoServerClient } from '@/lib/openalgo-server';
import { cache } from '@/lib/cache';
import { rateLimiter } from '@/lib/rate-limiter';
import { logger } from '@/lib/logger';
import { getCacheTtl } from '@/lib/api-config';

const ENDPOINT_NAME = 'orders';

export async function POST(req: NextRequest) {
  try {
    // Rate limit check
    if (!rateLimiter.isAllowed(ENDPOINT_NAME)) {
      logger.warn(`Rate limit exceeded for ${ENDPOINT_NAME}`);
      return NextResponse.json({ error: 'Rate limit exceeded' }, { status: 429 });
    }

    // Check cache
    const cached = cache.get(ENDPOINT_NAME);
    if (cached) {
      logger.info(`Cache hit for ${ENDPOINT_NAME}`);
      return NextResponse.json(cached);
    }

    // Call OpenAlgo server client
    const result = await OpenAlgoServerClient.getOrderBook();

    // Cache the result
    const cacheTtl = getCacheTtl('orders');
    if (cacheTtl > 0) {
      cache.set(ENDPOINT_NAME, result, cacheTtl);
    }

    return NextResponse.json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    logger.error(`Error fetching orders: ${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

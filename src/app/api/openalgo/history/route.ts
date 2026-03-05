import { NextRequest, NextResponse } from 'next/server';
import { OpenAlgoServerClient } from '@/lib/openalgo-server';
import { cache } from '@/lib/cache';
import { rateLimiter } from '@/lib/rate-limiter';
import { logger } from '@/lib/logger';
import { getCacheTtl } from '@/lib/api-config';

const ENDPOINT_NAME = 'history';

export async function POST(req: NextRequest) {
  try {
    // Rate limit check
    if (!rateLimiter.isAllowed(ENDPOINT_NAME)) {
      logger.warn(`Rate limit exceeded for ${ENDPOINT_NAME}`);
      return NextResponse.json({ error: 'Rate limit exceeded' }, { status: 429 });
    }

    // Parse and validate request body
    const body = (await req.json()) as {
      symbol?: string;
      exchange?: string;
      interval?: string;
      start_date?: string;
      end_date?: string;
    };

    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();
    const interval = body.interval?.trim();
    const startDate = body.start_date?.trim();
    const endDate = body.end_date?.trim();

    if (!symbol || !exchange || !interval || !startDate || !endDate) {
      logger.warn('Invalid history request parameters', {
        symbol,
        exchange,
        interval,
        startDate,
        endDate,
      });
      return NextResponse.json(
        {
          error:
            'symbol, exchange, interval, start_date, and end_date are required',
        },
        { status: 400 }
      );
    }

    // Check cache using symbol+exchange+interval+dates as key
    const cacheKey = `${ENDPOINT_NAME}:${symbol}:${exchange}:${interval}:${startDate}:${endDate}`;
    const cached = cache.get(cacheKey);
    if (cached) {
      logger.info(`Cache hit for ${cacheKey}`);
      return NextResponse.json(cached);
    }

    // Call OpenAlgo server client
    const result = await OpenAlgoServerClient.getHistory(
      symbol,
      exchange,
      interval,
      startDate,
      endDate
    );

    // Cache the result — skip caching empty data arrays to prevent poisoning
    // the cache with results from bad date ranges or transient upstream issues
    const cacheTtl = getCacheTtl('history');
    if (cacheTtl > 0 && Array.isArray(result.data) && result.data.length > 0) {
      cache.set(cacheKey, result, cacheTtl);
    }

    return NextResponse.json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    logger.error(`Error fetching history: ${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

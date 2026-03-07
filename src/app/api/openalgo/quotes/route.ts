import { NextRequest, NextResponse } from 'next/server';
import { OpenAlgoServerClient } from '@/lib/openalgo-server';
import { cache } from '@/lib/cache';
import { rateLimiter } from '@/lib/rate-limiter';
import { logger } from '@/lib/logger';
import { getCacheTtl } from '@/lib/api-config';

const ENDPOINT_NAME = 'quotes';

interface QuoteData {
  ltp: number;
  open: number;
  high: number;
  low: number;
  close?: number;
  prev_close: number;
  volume: number;
  bid: number;
  ask: number;
  oi?: number;
}

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';
const FALLBACK_TIMEOUT_MS = 8000;

async function fetchFromPythonBackend(symbol: string): Promise<QuoteData> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FALLBACK_TIMEOUT_MS);

  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/market/symbol-data/${symbol}`, {
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Python backend returned ${response.status}`);
    }

    const payload = (await response.json()) as Record<string, unknown>;

    // NSE getSymbolData wraps data under equityResponse[0]
    const equity = (payload.equityResponse as Record<string, unknown>[] | undefined)?.[0] ?? payload;
    const meta = (equity.metaData ?? {}) as Record<string, unknown>;
    const trade = (equity.tradeInfo ?? {}) as Record<string, unknown>;
    const book = (equity.orderBook ?? {}) as Record<string, unknown>;

    // lastPrice lives in orderBook and tradeInfo, not metaData
    const ltp = Number(book.lastPrice ?? trade.lastPrice) || 0;

    const quoteData: QuoteData = {
      ltp,
      open: Number(meta.open) || 0,
      high: Number(meta.dayHigh) || 0,
      low: Number(meta.dayLow) || 0,
      prev_close: Number(meta.previousClose ?? meta.basePrice) || 0,
      volume: Number(trade.totalTradedVolume) || 0,
      bid: Number(book.buyPrice1) || 0,
      ask: Number(book.sellPrice1) || 0,
    };

    return quoteData;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function POST(req: NextRequest) {
  let symbol: string | undefined;
  let exchange: string | undefined;
  let cacheKey: string | undefined;

  try {
    // Rate limit check
    if (!rateLimiter.isAllowed(ENDPOINT_NAME)) {
      logger.warn(`Rate limit exceeded for ${ENDPOINT_NAME}`);
      return NextResponse.json({ error: 'Rate limit exceeded' }, { status: 429 });
    }

    // Parse and validate request body
    const body = (await req.json()) as { symbol?: string; exchange?: string };
    symbol = body.symbol?.trim().toUpperCase();
    exchange = body.exchange?.trim().toUpperCase();

    if (!symbol || !exchange) {
      logger.warn('Invalid quote request parameters', { symbol, exchange });
      return NextResponse.json(
        { error: 'symbol and exchange are required' },
        { status: 400 }
      );
    }

    // Check cache using symbol+exchange as key
    cacheKey = `${ENDPOINT_NAME}:${symbol}:${exchange}`;
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
    
    if (!symbol || !cacheKey) {
      logger.error(`Error fetching quote: ${message}`);
      return NextResponse.json({ error: message }, { status: 500 });
    }

    logger.warn(`OpenAlgo unavailable for quote (${symbol}/${exchange}): ${message}. Attempting fallback to Python backend.`);

    try {
      const fallbackData = await fetchFromPythonBackend(symbol);
      const result = { status: 'success', data: fallbackData };

      const cacheTtl = getCacheTtl('quotes');
      if (cacheTtl > 0) {
        cache.set(cacheKey, result, cacheTtl);
      }

      return NextResponse.json(result);
    } catch (fallbackErr: unknown) {
      const fallbackMessage = fallbackErr instanceof Error ? fallbackErr.message : 'Unknown error';
      logger.error(`Fallback also failed for quote (${symbol}/${exchange}): ${fallbackMessage}`);
      return NextResponse.json({ error: message }, { status: 500 });
    }
  }
}

import { NextRequest, NextResponse } from 'next/server';
import { OpenAlgoServerClient, PlaceOrderParams } from '@/lib/openalgo-server';
import { rateLimiter } from '@/lib/rate-limiter';
import { logger } from '@/lib/logger';

const ENDPOINT_NAME = 'placeorder';

export async function POST(req: NextRequest) {
  try {
    // Rate limit check (stricter limit for mutations)
    if (!rateLimiter.isAllowed(ENDPOINT_NAME)) {
      logger.warn(`Rate limit exceeded for ${ENDPOINT_NAME}`);
      return NextResponse.json({ error: 'Rate limit exceeded' }, { status: 429 });
    }

    // Parse and validate request body
    const body = (await req.json()) as PlaceOrderParams;

    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();
    const action = body.action?.toUpperCase();
    const quantity = body.quantity?.trim();
    const price = body.price?.trim();
    const orderType = body.order_type?.toUpperCase();
    const product = body.product?.toUpperCase();

    // Validate required fields
    if (!symbol || !exchange || !action || !quantity || !price || !orderType || !product) {
      logger.warn('Invalid placeorder request parameters', {
        symbol,
        exchange,
        action,
        quantity,
        price,
        orderType,
        product,
      });
      return NextResponse.json(
        {
          error:
            'symbol, exchange, action, quantity, price, order_type, and product are required',
        },
        { status: 400 }
      );
    }

    // Validate enums
    if (!['BUY', 'SELL'].includes(action)) {
      return NextResponse.json({ error: 'action must be BUY or SELL' }, { status: 400 });
    }

    if (!['MARKET', 'LIMIT', 'SL', 'SL-M'].includes(orderType)) {
      return NextResponse.json(
        { error: 'order_type must be MARKET, LIMIT, SL, or SL-M' },
        { status: 400 }
      );
    }

    if (!['MIS', 'CNC', 'NRML'].includes(product)) {
      return NextResponse.json(
        { error: 'product must be MIS, CNC, or NRML' },
        { status: 400 }
      );
    }

    // Validate that LIMIT orders have a price
    if (orderType === 'LIMIT' && (!price || parseFloat(price) <= 0)) {
      return NextResponse.json(
        { error: 'LIMIT orders must have a positive price' },
        { status: 400 }
      );
    }

    // Validate quantities
    const qty = parseInt(quantity, 10);
    if (isNaN(qty) || qty <= 0) {
      return NextResponse.json({ error: 'quantity must be a positive number' }, { status: 400 });
    }

    logger.info('Placing order', {
      symbol,
      exchange,
      action,
      quantity: qty,
      price,
      orderType,
      product,
    });

    // Call OpenAlgo server client
    const result = await OpenAlgoServerClient.placeOrder({
      symbol,
      exchange,
      action: action as 'BUY' | 'SELL',
      quantity,
      price,
      order_type: orderType as 'MARKET' | 'LIMIT' | 'SL' | 'SL-M',
      product: product as 'MIS' | 'CNC' | 'NRML',
      trigger_price: body.trigger_price,
      strategy: body.strategy,
    });

    logger.info('Order placed successfully', {
      orderid: result.orderid,
      message: result.message,
    });

    return NextResponse.json(result);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    logger.error(`Error placing order: ${message}`);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';

// GET /api/watchlist — return all watchlist items
export async function GET() {
  try {
    const items = await prisma.watchlistItem.findMany({
      orderBy: { createdAt: 'asc' },
    });
    return NextResponse.json(items);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// POST /api/watchlist — add a symbol { symbol, exchange }
export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { symbol?: string; exchange?: string };
    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();

    if (!symbol || !exchange) {
      return NextResponse.json({ error: 'symbol and exchange are required' }, { status: 400 });
    }

    const item = await prisma.watchlistItem.upsert({
      where: { symbol_exchange: { symbol, exchange } },
      update: {},
      create: { symbol, exchange },
    });
    return NextResponse.json(item, { status: 201 });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// DELETE /api/watchlist — remove a symbol { symbol, exchange }
export async function DELETE(req: NextRequest) {
  try {
    const body = await req.json() as { symbol?: string; exchange?: string };
    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();

    if (!symbol || !exchange) {
      return NextResponse.json({ error: 'symbol and exchange are required' }, { status: 400 });
    }

    await prisma.watchlistItem.delete({
      where: { symbol_exchange: { symbol, exchange } },
    });
    return NextResponse.json({ ok: true });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

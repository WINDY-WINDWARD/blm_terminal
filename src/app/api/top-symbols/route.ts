import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';

// GET /api/top-symbols — return all configured top mover symbols
export async function GET() {
  try {
    const items = await prisma.topMoverSymbol.findMany({
      orderBy: { id: 'asc' },
    });
    return NextResponse.json(items);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

// POST /api/top-symbols — add a symbol { symbol, exchange }
export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { symbol?: string; exchange?: string };
    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();

    if (!symbol || !exchange) {
      return NextResponse.json({ error: 'symbol and exchange are required' }, { status: 400 });
    }

    const item = await prisma.topMoverSymbol.upsert({
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

// DELETE /api/top-symbols — remove a symbol { symbol, exchange }
export async function DELETE(req: NextRequest) {
  try {
    const body = await req.json() as { symbol?: string; exchange?: string };
    const symbol = body.symbol?.trim().toUpperCase();
    const exchange = body.exchange?.trim().toUpperCase();

    if (!symbol || !exchange) {
      return NextResponse.json({ error: 'symbol and exchange are required' }, { status: 400 });
    }

    await prisma.topMoverSymbol.delete({
      where: { symbol_exchange: { symbol, exchange } },
    });
    return NextResponse.json({ ok: true });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

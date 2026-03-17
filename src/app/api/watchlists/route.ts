import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:8000';

interface WatchlistOut {
  id: number;
  name: string;
  created_at: string;
  item_count?: number;
}

interface WatchlistItemOut {
  id: number;
  watchlist_id: number;
  symbol: string;
  exchange: string;
  created_at: string;
}

// GET /api/watchlists - list all watchlists
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/watchlists`, {
      headers: { accept: 'application/json' },
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

// POST /api/watchlists - create watchlist {name}
export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    const res = await fetch(`${BACKEND_URL}/api/watchlists`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body,
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

// DELETE /api/watchlists/{id} - delete watchlist
export async function DELETE(req: NextRequest) {
  try {
    const idParam = req.nextUrl.pathname.split('/').pop();
    const id = idParam ? parseInt(idParam, 10) : NaN;

    if (isNaN(id)) {
      return NextResponse.json({ error: 'id is required' }, { status: 400 });
    }

    const res = await fetch(`${BACKEND_URL}/api/watchlists/${id}`, {
      method: 'DELETE',
      headers: { accept: 'application/json' },
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

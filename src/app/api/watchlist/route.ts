import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:8000';

// GET /api/watchlist — return all watchlist items from the Python backend
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/watchlist`, {
      headers: { accept: 'application/json' },
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

// POST /api/watchlist — add { symbol, exchange } via the Python backend
export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    const res = await fetch(`${BACKEND_URL}/api/watchlist`, {
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

// DELETE /api/watchlist?id=<id> — remove a watchlist item via the Python backend
export async function DELETE(req: NextRequest) {
  try {
    const idParam = req.nextUrl.searchParams.get('id');
    const id = idParam ? parseInt(idParam, 10) : NaN;

    if (isNaN(id)) {
      return NextResponse.json({ error: 'id query param is required' }, { status: 400 });
    }

    const res = await fetch(`${BACKEND_URL}/api/watchlist/${id}`, {
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

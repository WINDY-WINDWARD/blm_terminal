import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:8000';

export async function GET(req: NextRequest) {
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/notifications?watchlist_id=${watchlistId}`,
      { headers: { accept: 'application/json' } },
    );
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function DELETE(req: NextRequest) {
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';
  try {
    const url = `${BACKEND_URL}/api/notifications?all=true&watchlist_id=${watchlistId}`;
    const res = await fetch(url, { method: 'DELETE' });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

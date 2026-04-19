import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

function getWatchlistIdParam(req: NextRequest): number | null {
  const watchlistIdParam = req.nextUrl.searchParams.get('watchlist_id');
  if (watchlistIdParam === null) return null;
  const watchlistId = parseInt(watchlistIdParam, 10);
  return isNaN(watchlistId) ? null : watchlistId;
}

// GET /api/watchlist — return watchlist items (optionally from specific watchlist)
export async function GET(req: NextRequest) {
  try {
    const watchlistId = getWatchlistIdParam(req);
    let url = `${BACKEND_URL}/api/watchlist`;
    
    // If watchlist_id is specified, use the new endpoint
    if (watchlistId !== null) {
      url = `${BACKEND_URL}/api/watchlists/${watchlistId}/items`;
    }
    
    const res = await fetch(url, {
      headers: { accept: 'application/json' },
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

// POST /api/watchlist — add item (optionally to specific watchlist)
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const watchlistId = getWatchlistIdParam(req);
    let url = `${BACKEND_URL}/api/watchlist`;
    
    // If watchlist_id is specified, use the new endpoint
    if (watchlistId !== null) {
      url = `${BACKEND_URL}/api/watchlists/${watchlistId}/items`;
    }
    
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify(body),
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

// DELETE /api/watchlist?id=<id>&watchlist_id=<id> — remove a watchlist item
export async function DELETE(req: NextRequest) {
  try {
    const idParam = req.nextUrl.searchParams.get('id');
    const id = idParam ? parseInt(idParam, 10) : NaN;
    const watchlistId = getWatchlistIdParam(req);

    if (isNaN(id)) {
      return NextResponse.json({ error: 'id query param is required' }, { status: 400 });
    }

    // Use the legacy endpoint for backward compatibility (defaults to watchlist_id=1)
    let url = `${BACKEND_URL}/api/watchlist/${id}`;
    
    // If watchlist_id is specified, use the new endpoint
    if (watchlistId !== null) {
      url = `${BACKEND_URL}/api/watchlists/${watchlistId}/items/${id}`;
    }
    
    const res = await fetch(url, {
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

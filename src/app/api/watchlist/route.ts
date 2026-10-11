import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export const runtime = 'nodejs';

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
    const backendUrl = getPythonBackendUrl();
    let url = `${backendUrl}/api/watchlist`;
    
    // If watchlist_id is specified, use the new endpoint
    if (watchlistId !== null) {
      url = `${backendUrl}/api/watchlists/${watchlistId}/items`;
    }
    
    const upstream = await fetch(url, {
      headers: getBackendForwardHeaders(req, { accept: 'application/json' }),
    });
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
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
    const backendUrl = getPythonBackendUrl();
    let url = `${backendUrl}/api/watchlist`;
    
    // If watchlist_id is specified, use the new endpoint
    if (watchlistId !== null) {
      url = `${backendUrl}/api/watchlists/${watchlistId}/items`;
    }
    
    const upstream = await fetch(url, {
      method: 'POST',
      headers: getBackendForwardHeaders(req, {
        accept: 'application/json',
        'content-type': 'application/json',
      }),
      body: JSON.stringify(body),
    });
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
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
    const backendUrl = getPythonBackendUrl();
    let url = `${backendUrl}/api/watchlist/${id}`;
    
    // If watchlist_id is specified, use the new endpoint
    if (watchlistId !== null) {
      url = `${backendUrl}/api/watchlists/${watchlistId}/items/${id}`;
    }
    
    const upstream = await fetch(url, {
      method: 'DELETE',
      headers: getBackendForwardHeaders(req, { accept: 'application/json' }),
    });
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

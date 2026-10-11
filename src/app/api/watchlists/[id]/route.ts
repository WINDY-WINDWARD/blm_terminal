import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export const runtime = 'nodejs';

// DELETE /api/watchlists/:id — delete watchlist
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const watchlistId = parseInt(id, 10);

    if (isNaN(watchlistId)) {
      return NextResponse.json({ error: 'Invalid watchlist id' }, { status: 400 });
    }

    const upstream = await fetch(`${getPythonBackendUrl()}/api/watchlists/${watchlistId}`, {
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

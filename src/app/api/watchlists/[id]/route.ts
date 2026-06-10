import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

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

    const headers: Record<string, string> = { accept: 'application/json' };
    const auth = req.headers.get('authorization');
    if (auth) headers['authorization'] = auth;
    const cookie = req.headers.get('cookie');
    if (cookie) headers['cookie'] = cookie;

    const upstream = await fetch(`${BACKEND_URL}/api/watchlists/${watchlistId}`, {
      method: 'DELETE',
      headers,
    });
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    const setCookie = upstream.headers.get('set-cookie');
    if (setCookie) res.headers.set('set-cookie', setCookie);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

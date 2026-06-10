import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

function forwardAuthHeaders(req: NextRequest): Record<string, string> {
  const headers: Record<string, string> = { accept: 'application/json' };
  const auth = req.headers.get('authorization');
  if (auth) headers['authorization'] = auth;
  const cookie = req.headers.get('cookie');
  if (cookie) headers['cookie'] = cookie;
  return headers;
}

function forwardSetCookie(upstream: Response, res: NextResponse): void {
  const setCookie = upstream.headers.get('set-cookie');
  if (setCookie) res.headers.set('set-cookie', setCookie);
}

export async function GET(req: NextRequest) {
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';
  try {
    const upstream = await fetch(
      `${BACKEND_URL}/api/notifications?watchlist_id=${watchlistId}`,
      { headers: forwardAuthHeaders(req) },
    );
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

export async function DELETE(req: NextRequest) {
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';
  try {
    const url = `${BACKEND_URL}/api/notifications?all=true&watchlist_id=${watchlistId}`;
    const upstream = await fetch(url, { method: 'DELETE', headers: forwardAuthHeaders(req) });
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

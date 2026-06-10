import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

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

// GET /api/watchlists - list all watchlists
export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${BACKEND_URL}/api/watchlists`, {
      headers: forwardAuthHeaders(req),
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

// POST /api/watchlists - create watchlist {name}
export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    const upstream = await fetch(`${BACKEND_URL}/api/watchlists`, {
      method: 'POST',
      headers: { ...forwardAuthHeaders(req), 'content-type': 'application/json' },
      body,
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

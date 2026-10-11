import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export const runtime = 'nodejs';

// GET /api/watchlists - list all watchlists
export async function GET(req: NextRequest) {
  try {
    const upstream = await fetch(`${getPythonBackendUrl()}/api/watchlists`, {
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

// POST /api/watchlists - create watchlist {name}
export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    const upstream = await fetch(`${getPythonBackendUrl()}/api/watchlists`, {
      method: 'POST',
      headers: getBackendForwardHeaders(req, {
        accept: 'application/json',
        'content-type': 'application/json',
      }),
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

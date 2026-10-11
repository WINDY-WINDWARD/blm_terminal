import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function GET(req: NextRequest) {
  try {
    const params = new URLSearchParams(req.nextUrl.search);
    const upstreamUrl = `${getPythonBackendUrl()}/api/notifications${params.toString() ? '?' + params.toString() : ''}`;
    const upstream = await fetch(upstreamUrl, {
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

export async function DELETE(req: NextRequest) {
  try {
    const params = new URLSearchParams(req.nextUrl.search);
    if (!params.has('all')) {
      params.set('all', 'true');
    }
    const upstreamUrl = `${getPythonBackendUrl()}/api/notifications${params.toString() ? '?' + params.toString() : ''}`;
    const upstream = await fetch(upstreamUrl, {
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

import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function GET(request: NextRequest) {
  try {
    const upstream = await fetch(`${getPythonBackendUrl()}/api/stockuniverse/errors`, {
      headers: getBackendForwardHeaders(request, { accept: 'application/json' }),
    });
    const data = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
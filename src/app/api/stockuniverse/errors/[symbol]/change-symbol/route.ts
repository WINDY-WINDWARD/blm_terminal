import { NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ symbol: string }> }
) {
  try {
    const { symbol } = await params;
    const body = await req.json();

    const upstream = await fetch(`${getPythonBackendUrl()}/api/stockuniverse/errors/${symbol}/change-symbol`, {
      method: 'PUT',
      headers: getBackendForwardHeaders(req, { 'content-type': 'application/json' }),
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
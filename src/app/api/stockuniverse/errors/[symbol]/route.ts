import { NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function DELETE(
  req: Request,
  { params }: { params: Promise<{ symbol: string }> }
) {
  try {
    const { symbol } = await params;

    const upstream = await fetch(`${getPythonBackendUrl()}/api/stockuniverse/errors/${symbol}`, {
      method: 'DELETE',
      headers: getBackendForwardHeaders(req, { accept: 'application/json' }),
    });
    if (upstream.status === 204) {
      return new NextResponse(null, { status: 204 });
    }
    const data: unknown = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    forwardSetCookie(upstream, res);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
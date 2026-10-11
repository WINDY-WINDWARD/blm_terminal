import { NextRequest, NextResponse } from 'next/server';
import { getPythonBackendUrl, getBackendForwardHeaders, forwardSetCookie } from '@/lib/backendUrl';

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';

  try {
    const upstream = await fetch(
      `${getPythonBackendUrl()}/api/notifications/${id}?watchlist_id=${watchlistId}`,
      {
        method: 'DELETE',
        headers: getBackendForwardHeaders(req, { accept: 'application/json' }),
      },
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

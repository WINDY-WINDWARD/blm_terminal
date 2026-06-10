import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const watchlistId = req.nextUrl.searchParams.get('watchlist_id') ?? '1';
  const headers: Record<string, string> = { accept: 'application/json' };
  const auth = req.headers.get('authorization');
  if (auth) headers['authorization'] = auth;
  const cookie = req.headers.get('cookie');
  if (cookie) headers['cookie'] = cookie;

  try {
    const upstream = await fetch(
      `${BACKEND_URL}/api/notifications/${id}?watchlist_id=${watchlistId}`,
      { method: 'DELETE', headers },
    );
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

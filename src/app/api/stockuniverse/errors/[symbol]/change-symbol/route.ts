import { NextResponse } from 'next/server';

const BACKEND_URL = process.env.PYTHON_BACKEND_URL ?? 'http://localhost:4455';

export async function PUT(
  req: Request,
  { params }: { params: Promise<{ symbol: string }> }
) {
  try {
    const { symbol } = await params;
    const body = await req.json();
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    const cookie = req.headers.get('cookie');
    if (cookie) headers['cookie'] = cookie;

    const upstream = await fetch(`${BACKEND_URL}/api/stockuniverse/errors/${symbol}/change-symbol`, {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
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
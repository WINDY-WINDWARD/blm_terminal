import { NextRequest, NextResponse } from 'next/server';

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  try {
    const headers: Record<string, string> = { accept: 'application/json' };
    const cookie = request.headers.get('cookie');
    if (cookie) headers['cookie'] = cookie;

    const upstream = await fetch(`${PYTHON_BACKEND_URL}/api/stockuniverse/errors`, { headers });
    const data = await upstream.json();
    const res = NextResponse.json(data, { status: upstream.status });
    const setCookie = upstream.headers.get('set-cookie');
    if (setCookie) res.headers.set('set-cookie', setCookie);
    return res;
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}